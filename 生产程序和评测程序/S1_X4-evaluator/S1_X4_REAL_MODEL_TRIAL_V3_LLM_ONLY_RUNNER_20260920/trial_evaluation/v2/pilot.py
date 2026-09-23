from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from trial_evaluation.checkpoint import atomic_write_json
from trial_evaluation.episodes import load_episode_bundle
from trial_evaluation.providers.base import ModelProvider
from trial_evaluation.providers.siliconflow import create_siliconflow_provider
from trial_evaluation.v2.config import build_profile
from trial_evaluation.v2.diagnostic import audit_decision_loop
from trial_evaluation.v2.runner import run_v2_unit


PILOT_TOPOLOGIES = (
    "topologybench_netrail",
    "topologybench_conus75",
    "topohub_gabriel_450_9",
)
PILOT_CONDITIONS = ("A_MEDIUM_MATCH", "B_HIGH_MATCH", "C_HIGH_X1P2")
PILOT_TASKS = ("S1", "X4")
PILOT_MODALITIES = ("llm",)


def run_pilot_v2(
    dataset_root: Path | str,
    output_root: Path | str,
    *,
    model: str = "deepseek-ai/DeepSeek-V4-Flash",
    profile_name: str = "B",
    max_steps: int = 64,
    topologies: Sequence[str] = PILOT_TOPOLOGIES,
    conditions: Sequence[str] = PILOT_CONDITIONS,
    provider_factory: Callable[[Mapping[str, Any]], ModelProvider] | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_steps <= 0 or max_steps > 512:
        raise ValueError("pilot max_steps must be in 1..512")
    dataset = Path(dataset_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    factory = provider_factory or create_siliconflow_provider
    profile = str(profile_name).upper()
    planned_units = len(topologies) * len(conditions) * len(PILOT_TASKS) * len(PILOT_MODALITIES)
    planned_steps = planned_units * max_steps
    unit_results: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    stopped_reason: str | None = None

    for topology_id in topologies:
        for condition_id in conditions:
            for task in PILOT_TASKS:
                for modality in PILOT_MODALITIES:
                    bundle = load_episode_bundle(dataset, task=task, modality=modality, topology_id=topology_id, condition_id=condition_id)
                    audit = audit_decision_loop(bundle)
                    audits.append({"task_type": task, "modality": modality, "topology_id": topology_id, "condition_id": condition_id, **audit})
                    if not audit["pass"]:
                        stopped_reason = "DECISION_LOOP_LEAKAGE_GATE"
                        break
                    config = build_profile(profile, task)
                    config["model"] = model
                    config["topology_id"] = topology_id
                    config["condition_id"] = condition_id
                    config["evaluation_scope"] = "PILOT_V2_PREFIX_64"
                    atomic_write_json(output / "CONFIG" / f"RESOLVED_MODEL_CONFIG_{task}_{modality}.json", {key: value for key, value in config.items() if key != "api_key"})
                    provider = factory(config)
                    result = run_v2_unit(
                        bundle,
                        provider,
                        output / "RUN",
                        max_steps=max_steps,
                        secrets=secrets,
                    )
                    unit_results.append({"topology_id": topology_id, "condition_id": condition_id, "task_type": task, "modality": modality, "result": result})
                    atomic_write_json(
                        output / "CHECKPOINTS" / "pilot_progress.json",
                        {
                            "completed_units": len(unit_results),
                            "completed_steps": sum(int(item["result"].get("summary", {}).get("committed_steps", 0)) for item in unit_results),
                            "planned_units": planned_units,
                            "planned_steps": planned_steps,
                            "last_unit": unit_results[-1],
                        },
                    )
                    if result["status"] in {"BALANCE_STOP", "INFRA_STOP", "PROTOCOL_STOP", "RUNNER_ERROR"}:
                        stopped_reason = result["status"]
                        break
                if stopped_reason:
                    break
            if stopped_reason:
                break
        if stopped_reason:
            break

    committed = sum(int(item["result"].get("summary", {}).get("committed_steps", 0)) for item in unit_results)
    infra = sum(int(item["result"].get("summary", {}).get("infra_failure_attempts", 0)) for item in unit_results)
    protocol = sum(int(item["result"].get("summary", {}).get("protocol_failure_attempts", 0)) for item in unit_results)
    model_failure_counts = Counter()
    for item in unit_results:
        model_failure_counts.update(item["result"].get("summary", {}).get("model_failure_counts", {}))
    result = {
        "schema_version": "TRIAL_V2_PILOT_V2_V1",
        "evaluation_scope": "PILOT_V2_PREFIX_64",
        "profile": profile,
        "model": model,
        "topologies": list(topologies),
        "conditions": list(conditions),
        "scheduled_units": planned_units,
        "completed_units": len(unit_results),
        "scheduled_steps": planned_steps,
        "committed_steps": committed,
        "infra_failure_attempts": infra,
        "protocol_failure_attempts": protocol,
        "model_failure_counts": dict(sorted(model_failure_counts.items())),
        "decision_loop_audit": audits,
        "stopped_reason": stopped_reason,
        "status": "PASS" if len(unit_results) == planned_units and committed == planned_steps and infra == 0 and protocol == 0 and stopped_reason is None else "INCOMPLETE_OR_GATE_FAIL",
        "unit_results": unit_results,
    }
    atomic_write_json(output / "PILOT_V2_RESULT.json", result)
    return result


def run_pilot_v2_parallel(
    dataset_root: Path | str,
    output_root: Path | str,
    *,
    model: str = "deepseek-ai/DeepSeek-V4-Flash",
    profile_name: str = "B",
    max_steps: int = 64,
    topologies: Sequence[str] = PILOT_TOPOLOGIES,
    conditions: Sequence[str] = PILOT_CONDITIONS,
    episode_concurrency: int = 3,
    provider_factory: Callable[[Mapping[str, Any]], ModelProvider] | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run independent Episodes in bounded waves; each Episode remains serial."""

    if episode_concurrency < 1 or episode_concurrency > 3:
        raise ValueError("episode_concurrency must be in 1..3")
    if max_steps <= 0 or max_steps > 512:
        raise ValueError("pilot max_steps must be in 1..512")
    dataset = Path(dataset_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    factory = provider_factory or create_siliconflow_provider
    profile = str(profile_name).upper()
    units = [(topology_id, condition_id, task, modality) for topology_id in topologies for condition_id in conditions for task in PILOT_TASKS for modality in PILOT_MODALITIES]
    planned_units = len(units)
    planned_steps = planned_units * max_steps

    def run_one(spec: tuple[str, str, str, str]) -> dict[str, Any]:
        topology_id, condition_id, task, modality = spec
        bundle = load_episode_bundle(dataset, task=task, modality=modality, topology_id=topology_id, condition_id=condition_id)
        audit = audit_decision_loop(bundle)
        if not audit["pass"]:
            return {"topology_id": topology_id, "condition_id": condition_id, "task_type": task, "modality": modality, "audit": audit, "result": {"status": "DECISION_LOOP_LEAKAGE_GATE", "summary": {"committed_steps": 0, "infra_failure_attempts": 0, "protocol_failure_attempts": 0}}}
        config = build_profile(profile, task)
        config.update({"model": model, "topology_id": topology_id, "condition_id": condition_id, "evaluation_scope": "PILOT_V2_PREFIX_64"})
        config_path = output / "CONFIG" / f"RESOLVED_MODEL_CONFIG_{topology_id}_{condition_id}_{task}_{modality}.json"
        atomic_write_json(config_path, {key: value for key, value in config.items() if key != "api_key"})
        unit_id = bundle.unit_id
        checkpoint_exists = (output / "RUN" / "CHECKPOINTS" / unit_id / "steps.jsonl").is_file() or (output / "RUN" / "ATTEMPTS" / unit_id / "attempts.jsonl").is_file()
        provider = factory(config)
        trial = run_v2_unit(bundle, provider, output / "RUN", max_steps=max_steps, resume=checkpoint_exists, secrets=secrets)
        return {"topology_id": topology_id, "condition_id": condition_id, "task_type": task, "modality": modality, "audit": audit, "result": trial}

    completed: list[dict[str, Any]] = []
    stopped_reason: str | None = None
    for offset in range(0, planned_units, episode_concurrency):
        wave = units[offset : offset + episode_concurrency]
        with ThreadPoolExecutor(max_workers=episode_concurrency, thread_name_prefix="s1x4-episode") as executor:
            futures = {executor.submit(run_one, spec): spec for spec in wave}
            wave_results = []
            for future in as_completed(futures):
                wave_results.append(future.result())
        wave_results.sort(key=lambda item: (item["topology_id"], item["condition_id"], item["task_type"], item["modality"]))
        completed.extend(wave_results)
        atomic_write_json(
            output / "CHECKPOINTS" / "pilot_progress.json",
            {
                "completed_units": len(completed),
                "completed_steps": sum(int(item["result"].get("summary", {}).get("committed_steps", 0)) for item in completed),
                "planned_units": planned_units,
                "planned_steps": planned_steps,
                "episode_concurrency": episode_concurrency,
                "last_wave": wave_results,
            },
        )
        failures = [item["result"].get("status") for item in wave_results if item["result"].get("status") in {"BALANCE_STOP", "INFRA_STOP", "PROTOCOL_STOP", "RUNNER_ERROR", "DECISION_LOOP_LEAKAGE_GATE"}]
        if failures:
            stopped_reason = str(failures[0])
            break

    committed = sum(int(item["result"].get("summary", {}).get("committed_steps", 0)) for item in completed)
    infra = sum(int(item["result"].get("summary", {}).get("infra_failure_attempts", 0)) for item in completed)
    protocol = sum(int(item["result"].get("summary", {}).get("protocol_failure_attempts", 0)) for item in completed)
    model_failure_counts = Counter()
    for item in completed:
        model_failure_counts.update(item["result"].get("summary", {}).get("model_failure_counts", {}))
    result = {
        "schema_version": "TRIAL_V2_PILOT_V2_V1",
        "evaluation_scope": "PILOT_V2_PREFIX_64",
        "profile": profile,
        "model": model,
        "topologies": list(topologies),
        "conditions": list(conditions),
        "episode_concurrency": episode_concurrency,
        "scheduled_units": planned_units,
        "completed_units": len(completed),
        "scheduled_steps": planned_steps,
        "committed_steps": committed,
        "infra_failure_attempts": infra,
        "protocol_failure_attempts": protocol,
        "model_failure_counts": dict(sorted(model_failure_counts.items())),
        "stopped_reason": stopped_reason,
        "status": "PASS" if len(completed) == planned_units and committed == planned_steps and infra == 0 and protocol == 0 and stopped_reason is None else "INCOMPLETE_OR_GATE_FAIL",
        "unit_results": completed,
    }
    atomic_write_json(output / "PILOT_V2_RESULT.json", result)
    return result
