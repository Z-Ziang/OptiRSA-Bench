from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.s1_x4.evaluator import DynamicEpisodeSession
from trial_evaluation.checkpoint import atomic_write_json
from trial_evaluation.providers.base import ModelConfig, ProviderResponse, Usage
from trial_evaluation.runner import run_unit


class OfflineFakeProvider:
    """Deterministic legal plumbing adapter; it is never a model-quality result."""

    def __init__(self, task: str) -> None:
        self.task = task
        self.calls: list[dict[str, Any]] = []
        self.config = ModelConfig(
            provider="fake",
            model="offline-fake-legal-policy",
            base_url="offline://fake",
            api_key_env="UNUSED_OFFLINE_KEY",
            max_output_tokens=128,
        )

    def complete(self, messages: Sequence[Mapping[str, Any]]) -> ProviderResponse:
        from trial_evaluation.providers.base import ProviderResponse

        self.calls.append({"messages": [dict(message) for message in messages]})
        if self.task == "S1":
            text = '{"decision":"REJECT","path_rank":null,"slot_start":null}'
        else:
            text = '{"decision":"REJECT","path_node_ids":[],"path_link_ids":[],"slot_start":null}'
        return ProviderResponse(
            requested_model=self.config.model,
            response_model=self.config.model,
            text=text,
            usage=Usage(input_tokens=1, output_tokens=1),
            latency_ms=0.1,
            provider_request_id=None,
            retry_count=0,
        )


def _first_case(dataset_root: Path, task: str) -> tuple[str, str]:
    paths = sorted((dataset_root / "benchmark_case" / task / "episodes").glob("*/*.json"))
    if not paths:
        raise FileNotFoundError(f"no {task} episode under {dataset_root}")
    return paths[0].parent.name, paths[0].stem


def run_offline_gate(dataset_root: Path | str, output_dir: Path | str, *, max_steps: int = 2) -> dict[str, Any]:
    from trial_evaluation.episodes import load_episode_bundle

    dataset = Path(dataset_root).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    def next_run_root(name: str) -> Path:
        candidate = output / name
        index = 1
        while candidate.exists():
            index += 1
            candidate = output / f"{name}_{index}"
        return candidate

    fake_root = next_run_root("FAKE_RUNS")
    resume_output = next_run_root("CHECKPOINT_RESUME_PROBE")
    unit_results = []
    provider_calls = []
    bundles_seen = []
    for task in ("S1", "X4"):
        topology_id, condition_id = _first_case(dataset, task)
        bundle = load_episode_bundle(
            dataset,
            task=task,
            modality="llm",
            topology_id=topology_id,
            condition_id=condition_id,
        )
        bundles_seen.append(bundle)
        fake = OfflineFakeProvider(task)
        result = run_unit(bundle, fake, fake_root, max_steps=min(max_steps, bundle.episode_length))
        unit_results.append(result)
        provider_calls.extend(fake.calls)

    s1_topology, s1_condition = _first_case(dataset, "S1")
    s1_bundle = load_episode_bundle(
        dataset,
        task="S1",
        modality="llm",
        topology_id=s1_topology,
        condition_id=s1_condition,
    )
    probe_session = DynamicEpisodeSession(s1_bundle.episode, endpoint="llm")
    invalid_json = probe_session.submit_response("not-json")
    first_provider = OfflineFakeProvider("S1")
    run_unit(s1_bundle, first_provider, resume_output, max_steps=1)
    second_provider = OfflineFakeProvider("S1")
    resumed = run_unit(s1_bundle, second_provider, resume_output, max_steps=min(2, s1_bundle.episode_length), resume=True)
    forbidden_reference_tokens = ("reference_output", "reference_trajectories", "private_truth", "reference_policy")
    no_reference = all(
        not any(token in json.dumps(call, ensure_ascii=False).lower() for token in forbidden_reference_tokens)
        for call in provider_calls
    ) and all(
        not any(token in json.dumps(bundle.episode, ensure_ascii=False).lower() for token in forbidden_reference_tokens)
        for bundle in bundles_seen
    )
    result = {
        "schema_version": "TRIAL_OFFLINE_GATE_V1",
        "status": "PASS" if all(row["status"] in {"PASS", "PREFIX_COMPLETE"} for row in unit_results) and invalid_json["validation"]["valid"] is False and resumed["status"] in {"PASS", "PREFIX_COMPLETE"} else "FAIL",
        "fake_model_note": "工程 smoke，不是 LLM 能力结论。",
        "fake_llm_steps": sum(row["summary"]["step_count"] for row in unit_results if row["modality"] == "llm"),
        "no_reference_in_decision_loop": no_reference,
        "invalid_json_probe": invalid_json["validation"]["valid"] is False,
        "checkpoint_resume": resumed["status"] in {"PASS", "PREFIX_COMPLETE"} and len(second_provider.calls) == 1,
        "unit_results": unit_results,
    }
    atomic_write_json(output / "OFFLINE_GATE.json", result)
    return result
