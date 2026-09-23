from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from trial_evaluation.checkpoint import atomic_write_json
from trial_evaluation.episodes import EpisodeBundle, load_episode_bundle
from trial_evaluation.providers.base import ModelProvider
from trial_evaluation.providers.siliconflow import create_siliconflow_provider
from trial_evaluation.v2.config import build_profile
from trial_evaluation.v2.runner import run_v2_unit


DEFAULT_TOPOLOGY = "topologybench_netrail"
DEFAULT_CONDITION = "A_MEDIUM_MATCH"
DEFAULT_TASKS = ("S1", "X4")
DEFAULT_MODALITIES = ("llm",)


def _contains_reference(value: object) -> bool:
    return "reference" in json.dumps(value, ensure_ascii=False).lower()


def audit_decision_loop(bundle: EpisodeBundle) -> dict[str, Any]:
    """Audit the public inputs used by a trial unit before any API call."""

    episode = bundle.episode
    first_request_id = str(episode.get("request_events", [{}])[0].get("request_id", ""))
    future_request_ids = [str(row.get("request_id")) for row in episode.get("request_events", [])[1:] if row.get("request_id")]
    forbidden_oracle_terms = (
        "GET_REQUEST_PATHS",
        "GET_BEST_PATH",
        "GET_FEASIBLE_PATHS",
        "GET_RECOMMENDED_ACTION",
        "GET_FEASIBLE_ACTIONS",
    )
    session_prompt = bundle.system_prompt
    prompt = None
    from src.s1_x4.evaluator import DynamicEpisodeSession

    session = DynamicEpisodeSession(episode, endpoint=bundle.modality)
    step = session.current_step()
    prompt = str(step["prompt"])
    future_leaks = [request_id for request_id in future_request_ids if request_id in prompt]
    prompt_leaks = [term for term in forbidden_oracle_terms if term in prompt]
    return {
        "reference_in_system_prompt": _contains_reference(session_prompt),
        "reference_in_step_prompt": _contains_reference(prompt),
        "future_request_ids_in_step_prompt": future_leaks,
        "oracle_terms_in_step_prompt": prompt_leaks,
        "current_request_visible": bool(first_request_id and first_request_id in prompt),
        "pass": not _contains_reference(session_prompt) and not _contains_reference(prompt) and not future_leaks and not prompt_leaks,
    }


def _profile_summary(profile: str, rows: Sequence[Mapping[str, Any]], *, planned_steps: int, max_steps: int, stopped_reason: str | None) -> dict[str, Any]:
    summary_rows = [dict(row.get("summary", {})) for row in rows]
    committed = sum(int(row.get("committed_steps", 0)) for row in summary_rows)
    infra = sum(int(row.get("infra_failure_attempts", 0)) for row in summary_rows)
    protocol = sum(int(row.get("protocol_failure_attempts", 0)) for row in summary_rows)
    api_attempts = sum(int(row.get("all_attempts", 0)) for row in summary_rows)
    model_failures = Counter()
    for item in summary_rows:
        model_failures.update(item.get("model_failure_counts", {}))
    return {
        "profile": profile,
        "evaluation_scope": "PROTOCOL_DIAGNOSTIC_PREFIX_5",
        "max_steps": max_steps,
        "planned_units": len(DEFAULT_TASKS) * len(DEFAULT_MODALITIES),
        "completed_units": len(rows),
        "scheduled_steps": planned_steps,
        "committed_steps": committed,
        "infra_failure_attempts": infra,
        "protocol_failure_attempts": protocol,
        "model_decision_failures": dict(sorted(model_failures.items())),
        "api_attempts": api_attempts,
        "stopped_reason": stopped_reason,
        "protocol_gate_pass": protocol == 0,
        "infra_gate_pass": infra == 0,
    }


def run_protocol_diagnostic(
    dataset_root: Path | str,
    output_root: Path | str,
    *,
    model: str = "deepseek-ai/DeepSeek-V4-Flash",
    topology_id: str = DEFAULT_TOPOLOGY,
    condition_id: str = DEFAULT_CONDITION,
    profiles: Sequence[str] = ("A", "B"),
    max_steps: int = 5,
    provider_factory: Callable[[Mapping[str, Any]], ModelProvider] | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    dataset = Path(dataset_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    factory = provider_factory or create_siliconflow_provider
    all_profile_results: list[dict[str, Any]] = []
    for profile_name in profiles:
        profile = str(profile_name).upper()
        profile_root = output / f"PROFILE_{profile}"
        profile_root.mkdir(parents=True, exist_ok=True)
        unit_results: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        for task in DEFAULT_TASKS:
            for modality in DEFAULT_MODALITIES:
                bundle = load_episode_bundle(dataset, task=task, modality=modality, topology_id=topology_id, condition_id=condition_id)
                audit = audit_decision_loop(bundle)
                audits.append({"task_type": task, "modality": modality, **audit})
                if not audit["pass"]:
                    stopped_reason = "DECISION_LOOP_LEAKAGE_GATE"
                    break
                config = build_profile(profile, task)
                config["model"] = model
                config["topology_id"] = topology_id
                config["condition_id"] = condition_id
                atomic_write_json(profile_root / f"RESOLVED_MODEL_CONFIG_{task}_{modality}.json", {key: value for key, value in config.items() if key != "api_key"})
                provider = factory(config)
                result = run_v2_unit(
                    bundle,
                    provider,
                    profile_root / "RUN",
                    max_steps=max_steps,
                    secrets=secrets,
                )
                unit_results.append(result)
                if result["status"] in {"BALANCE_STOP", "INFRA_STOP", "RUNNER_ERROR"}:
                    stopped_reason = result["status"]
                    break
            if stopped_reason:
                break
        profile_summary = _profile_summary(profile, unit_results, planned_steps=len(DEFAULT_TASKS) * len(DEFAULT_MODALITIES) * max_steps, max_steps=max_steps, stopped_reason=stopped_reason)
        profile_result = {
            "schema_version": "TRIAL_V2_PROTOCOL_DIAGNOSTIC_PROFILE_V1",
            "profile": profile,
            "model": model,
            "topology_id": topology_id,
            "condition_id": condition_id,
            "summary": profile_summary,
            "decision_loop_audit": audits,
            "unit_results": unit_results,
        }
        atomic_write_json(profile_root / "PROFILE_RESULT.json", profile_result)
        all_profile_results.append(profile_result)
    result = {
        "schema_version": "TRIAL_V2_PROTOCOL_DIAGNOSTIC_V1",
        "evaluation_scope": "PROTOCOL_DIAGNOSTIC_PREFIX_5",
        "max_steps": max_steps,
        "model": model,
        "topology_id": topology_id,
        "condition_id": condition_id,
        "profiles": all_profile_results,
        "status": "PASS" if all(item["summary"]["protocol_gate_pass"] and item["summary"]["infra_gate_pass"] for item in all_profile_results) else "GATE_FAIL",
    }
    atomic_write_json(output / "PROTOCOL_DIAGNOSTIC_RESULT.json", result)
    return result
