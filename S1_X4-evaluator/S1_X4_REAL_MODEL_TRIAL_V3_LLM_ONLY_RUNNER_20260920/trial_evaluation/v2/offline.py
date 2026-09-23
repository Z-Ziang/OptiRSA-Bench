from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from trial_evaluation.episodes import load_episode_bundle
from trial_evaluation.providers.base import ModelConfig, ProviderError, ProviderResponse, Usage
from trial_evaluation.v2.runner import run_v2_unit


class _OfflineProvider:
    def __init__(self, response: ProviderResponse | BaseException):
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.config = ModelConfig(provider="fake", model="v2-offline", base_url="offline://fake", api_key_env="UNUSED")

    def complete(self, messages: Sequence[Mapping[str, Any]]) -> ProviderResponse:
        self.calls.append({"messages": [dict(item) for item in messages]})
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _response(text: str | None, finish_reason: str = "stop") -> ProviderResponse:
    return ProviderResponse("v2-offline", "v2-offline", text, Usage(input_tokens=1, output_tokens=1), 0.1, None, 0, finish_reason)


def _select_offline_target(dataset: Path) -> tuple[str, str]:
    episodes = dataset / "benchmark_case" / "S1" / "episodes"
    preferred = episodes / "topologybench_netrail"
    topology = "topologybench_netrail" if preferred.is_dir() else sorted(path.name for path in episodes.iterdir() if path.is_dir())[0]
    preferred_condition = episodes / topology / "A_MEDIUM_MATCH.json"
    if preferred_condition.is_file():
        return topology, "A_MEDIUM_MATCH"
    first = sorted(path.stem for path in (episodes / topology).glob("*.json"))[0]
    return topology, first


def run_v2_offline_gate(dataset_root: Path | str, output_dir: Path | str, *, max_steps: int = 1) -> dict[str, Any]:
    dataset = Path(dataset_root).resolve()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    topology_id, condition_id = _select_offline_target(dataset)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id=topology_id, condition_id=condition_id)

    balance = run_v2_unit(bundle, _OfflineProvider(ProviderError("balance", status_code=402)), output / "BALANCE", max_steps=max_steps)
    protocol = run_v2_unit(bundle, _OfflineProvider(_response("not-json")), output / "PROTOCOL", max_steps=max_steps)
    truncated = run_v2_unit(bundle, _OfflineProvider(_response("", finish_reason="length")), output / "TRUNCATED", max_steps=max_steps)
    reject = run_v2_unit(bundle, _OfflineProvider(_response('{"decision":"REJECT","path_rank":null,"slot_start":null}')), output / "REJECT", max_steps=max_steps)
    resume_root = output / "RESUME"
    run_v2_unit(bundle, _OfflineProvider(_response("not-json")), resume_root, max_steps=max_steps)
    resumed = run_v2_unit(bundle, _OfflineProvider(_response('{"decision":"REJECT","path_rank":null,"slot_start":null}')), resume_root, max_steps=max_steps, resume=True)
    result = {
        "schema_version": "TRIAL_V2_OFFLINE_GATE_V1",
        "status": "PASS" if balance["status"] == "BALANCE_STOP" and protocol["status"] == "PROTOCOL_STOP" and reject["summary"]["committed_steps"] == max_steps and resumed["summary"]["committed_steps"] == max_steps else "FAIL",
        "infra_failure_probe": balance["summary"]["committed_steps"] == 0 and balance["summary"]["infra_failure_attempts"] == 1,
        "protocol_failure_probe": protocol["summary"]["committed_steps"] == 0 and protocol["summary"]["protocol_failure_attempts"] == 1,
        "truncated_output_probe": truncated["summary"]["committed_steps"] == 0 and truncated["summary"]["protocol_failure_attempts"] == 1,
        "scientific_reject_probe": reject["summary"]["model_failure_counts"].get("MODEL_REJECT") == max_steps,
        "resume_same_step_probe": resumed["summary"]["protocol_failure_attempts"] == 1 and resumed["summary"]["committed_steps"] == max_steps,
        "no_reference_in_fake_messages": all("reference" not in json.dumps(call, ensure_ascii=False).lower() for call in _OfflineProvider(_response("{}")).calls),
        "runs": {"balance": balance, "protocol": protocol, "truncated": truncated, "reject": reject, "resumed": resumed},
    }
    result["status"] = "PASS" if all(result[key] for key in ("infra_failure_probe", "protocol_failure_probe", "truncated_output_probe", "scientific_reject_probe", "resume_same_step_probe", "no_reference_in_fake_messages")) else "FAIL"
    (output / "OFFLINE_GATE_V2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
