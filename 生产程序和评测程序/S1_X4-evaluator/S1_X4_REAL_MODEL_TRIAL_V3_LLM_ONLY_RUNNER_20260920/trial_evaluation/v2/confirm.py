from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from trial_evaluation.checkpoint import atomic_write_json
from trial_evaluation.episodes import load_episode_bundle
from trial_evaluation.providers.base import ModelProvider
from trial_evaluation.providers.siliconflow import create_siliconflow_provider
from trial_evaluation.v2.config import build_profile
from trial_evaluation.v2.diagnostic import DEFAULT_CONDITION, DEFAULT_MODALITIES, DEFAULT_TASKS, DEFAULT_TOPOLOGY, audit_decision_loop
from trial_evaluation.v2.runner import run_v2_unit


def run_confirm16(
    dataset_root: Path | str,
    output_root: Path | str,
    *,
    model: str = "deepseek-ai/DeepSeek-V4-Flash",
    topology_id: str = DEFAULT_TOPOLOGY,
    condition_id: str = DEFAULT_CONDITION,
    profile_name: str = "B",
    max_steps: int = 16,
    provider_factory: Callable[[Mapping[str, Any]], ModelProvider] | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    dataset = Path(dataset_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    factory = provider_factory or create_siliconflow_provider
    profile = str(profile_name).upper()
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
            atomic_write_json(output / f"RESOLVED_MODEL_CONFIG_{task}_{modality}.json", {key: value for key, value in config.items() if key != "api_key"})
            provider = factory(config)
            result = run_v2_unit(
                bundle,
                provider,
                output / "RUN",
                max_steps=max_steps,
                secrets=secrets,
            )
            unit_results.append(result)
            if result["status"] in {"BALANCE_STOP", "INFRA_STOP", "RUNNER_ERROR"}:
                stopped_reason = result["status"]
                break
        if stopped_reason:
            break
    committed = sum(int(item.get("summary", {}).get("committed_steps", 0)) for item in unit_results)
    infra = sum(int(item.get("summary", {}).get("infra_failure_attempts", 0)) for item in unit_results)
    protocol = sum(int(item.get("summary", {}).get("protocol_failure_attempts", 0)) for item in unit_results)
    expected_units = len(DEFAULT_TASKS) * len(DEFAULT_MODALITIES)
    expected_steps = expected_units * max_steps
    result = {
        "schema_version": "TRIAL_V2_CONFIRM16_V1",
        "evaluation_scope": "PROTOCOL_CONFIRM_PREFIX_16",
        "profile": profile,
        "model": model,
        "topology_id": topology_id,
        "condition_id": condition_id,
        "scheduled_steps": expected_steps,
        "completed_units": len(unit_results),
        "committed_steps": committed,
        "infra_failure_attempts": infra,
        "protocol_failure_attempts": protocol,
        "decision_loop_audit": audits,
        "unit_results": unit_results,
        "stopped_reason": stopped_reason,
        "status": "PASS" if len(unit_results) == expected_units and committed == expected_steps and infra == 0 and protocol == 0 and stopped_reason is None else "GATE_FAIL",
    }
    atomic_write_json(output / "CONFIRM16_RESULT.json", result)
    return result
