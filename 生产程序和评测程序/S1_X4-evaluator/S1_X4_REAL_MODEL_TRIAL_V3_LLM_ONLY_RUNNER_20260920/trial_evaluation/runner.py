from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.s1_x4.evaluator import DynamicEpisodeSession
from trial_evaluation.checkpoint import CheckpointStore, atomic_write_json
from trial_evaluation.config import BudgetGuard, BudgetStop
from trial_evaluation.episodes import EpisodeBundle
from trial_evaluation.llm_loop import run_llm_step
from trial_evaluation.metrics import build_prefix_summary
from trial_evaluation.providers.base import ModelProvider, ProviderError
from trial_evaluation.reference import load_reference_prefix_summary
from trial_evaluation.security import redact_text


class TrialExecutionError(RuntimeError):
    pass


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _try_parse_json(text: str) -> object | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _provider_identity(provider: ModelProvider) -> dict[str, Any]:
    config = getattr(provider, "config", None)
    if config is None:
        return {"provider": "fake", "requested_model": "fake-model", "response_model": None}
    return {
        "provider": getattr(config, "provider", None),
        "requested_model": getattr(config, "model", None),
        "response_model": None,
    }


def _write_jsonl_atomic(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _api_usage(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    def total(key: str) -> int | None:
        values = [row.get("api_usage", {}).get(key) for row in rows]
        numeric = [int(value) for value in values if value is not None]
        return sum(numeric) if numeric else None

    latencies = [float(row.get("latency_ms", 0.0)) for row in rows]
    return {
        "api_requests": total("api_requests"),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "cached_tokens": total("cached_tokens"),
        "transport_retries": sum(int(row.get("retry_count", 0)) for row in rows),
        "latency_mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "latency_total_ms": sum(latencies),
    }


def _replay_checkpointed_steps(session: DynamicEpisodeSession, rows: list[Mapping[str, Any]]) -> None:
    for row in rows:
        if row.get("step_index") != len(session.state.trajectory) + 1:
            raise TrialExecutionError("checkpoint steps are not contiguous with the dynamic session")
        result = session.submit_response(row["submission_for_replay"])
        if row.get("validation") != result["validation"] or row.get("trajectory_record") != result["trajectory_record"]:
            raise TrialExecutionError(f"checkpoint replay mismatch at step {row['step_index']}")


def _save_unit_state(
    *,
    unit_dir: Path,
    bundle: EpisodeBundle,
    provider: ModelProvider,
    status: str,
    rows: list[Mapping[str, Any]],
    summary: Mapping[str, Any],
    api_usage: Mapping[str, Any],
    error: str | None = None,
) -> dict[str, Any]:
    identity = _provider_identity(provider)
    response_models = [
        response.get("response_model")
        for row in rows
        for response in row.get("provider_responses", [])
        if response.get("response_model")
    ]
    if response_models:
        identity["response_model"] = response_models[-1]
    result = {
        "status": status,
        "evaluation_scope": "PREFIX_TRIAL" if len(rows) < bundle.episode_length else "FULL_H512",
        "max_steps": len(rows),
        "task_type": bundle.task,
        "modality": bundle.modality,
        "topology_id": bundle.topology_id,
        "condition_id": bundle.condition_id,
        "case_id": bundle.case_id,
        "episode_length": bundle.episode_length,
        "pairing_id": bundle.episode.get("pairing_id"),
        "system_prompt_sha256": bundle.system_prompt_sha256,
        "summary": dict(summary),
        "api_usage": dict(api_usage),
        "model": identity,
    }
    if error is not None:
        result["error"] = error
    atomic_write_json(unit_dir / "unit_summary.json", result)
    return result


def run_unit(
    bundle: EpisodeBundle,
    provider: ModelProvider,
    output_root: Path | str,
    *,
    max_steps: int,
    resume: bool = False,
    budget: BudgetGuard | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_steps <= 0 or max_steps > bundle.episode_length:
        raise ValueError("max_steps must be in 1..episode_length")
    root = Path(output_root)
    unit_dir = root / "UNITS" / bundle.unit_id
    checkpoint = CheckpointStore(root / "CHECKPOINTS" / bundle.unit_id)
    raw_path = root / "RAW" / bundle.unit_id / "steps.jsonl"
    unit_dir.mkdir(parents=True, exist_ok=True)
    existing = checkpoint.load()
    if existing and not resume:
        raise TrialExecutionError(f"checkpoint exists; use resume for {bundle.unit_id}")
    session = DynamicEpisodeSession(bundle.episode, endpoint=bundle.modality)
    _replay_checkpointed_steps(session, existing)
    rows = list(existing)
    guard = budget or BudgetGuard()
    if len(rows) > max_steps:
        raise TrialExecutionError("checkpoint already exceeds requested max_steps")
    try:
        while len(rows) < max_steps:
            step = session.current_step()
            outcome = run_llm_step(
                provider=provider,
                budget=guard,
                system_prompt=bundle.system_prompt,
                step_prompt=step["prompt"],
            )
            submission = redact_text(outcome["submission"], secrets=secrets)
            official = session.submit_response(submission)
            row = {
                "model": _provider_identity(provider)["requested_model"],
                "provider": _provider_identity(provider)["provider"],
                "task_type": bundle.task,
                "modality": bundle.modality,
                "topology_id": bundle.topology_id,
                "condition_id": bundle.condition_id,
                "case_id": bundle.case_id,
                "step_index": int(official["trajectory_record"]["step_index"]),
                "prompt_sha256": _sha256_text(step["prompt"]),
                "system_prompt_sha256": bundle.system_prompt_sha256,
                "raw_model_output": submission,
                "submission_for_replay": submission,
                "parsed_action": _try_parse_json(submission),
                "provider_responses": outcome.get("provider_responses", []),
                "validation": official["validation"],
                "trajectory_record": official["trajectory_record"],
                "api_usage": outcome.get("api_usage", {}),
                "latency_ms": outcome.get("latency_ms", 0.0),
                "retry_count": outcome.get("retry_count", 0),
                "errors": outcome.get("errors", []),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
            checkpoint.append(row)
            rows.append(row)
            _write_jsonl_atomic(raw_path, rows)
            atomic_write_json(unit_dir / "progress.json", {"completed_steps": len(rows), "last_step_index": len(rows)})
    except BudgetStop as exc:
        summary = build_prefix_summary([row["trajectory_record"] for row in rows])
        return _save_unit_state(
            unit_dir=unit_dir,
            bundle=bundle,
            provider=provider,
            status="BUDGET_STOP",
            rows=rows,
            summary=summary,
            api_usage=_api_usage(rows),
            error=str(exc),
        )
    except ProviderError as exc:
        summary = build_prefix_summary([row["trajectory_record"] for row in rows])
        return _save_unit_state(
            unit_dir=unit_dir,
            bundle=bundle,
            provider=provider,
            status="API_ERROR",
            rows=rows,
            summary=summary,
            api_usage=_api_usage(rows),
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
    except Exception as exc:
        summary = build_prefix_summary([row["trajectory_record"] for row in rows])
        return _save_unit_state(
            unit_dir=unit_dir,
            bundle=bundle,
            provider=provider,
            status="RUNNER_ERROR",
            rows=rows,
            summary=summary,
            api_usage=_api_usage(rows),
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
    summary = build_prefix_summary([row["trajectory_record"] for row in rows])
    reference = load_reference_prefix_summary(
        bundle.dataset_root,
        task=bundle.task,
        topology_id=bundle.topology_id,
        condition_id=bundle.condition_id,
        step_count=len(rows),
    )
    result = _save_unit_state(
        unit_dir=unit_dir,
        bundle=bundle,
        provider=provider,
        status="PASS" if len(rows) == bundle.episode_length else "PREFIX_COMPLETE",
        rows=rows,
        summary=summary,
        api_usage=_api_usage(rows),
    )
    if reference is not None:
        result["reference_prefix_summary"] = reference
        atomic_write_json(unit_dir / "reference_prefix_summary.json", reference)
        atomic_write_json(unit_dir / "unit_summary.json", result)
    atomic_write_json(unit_dir / "budget_snapshot.json", guard.snapshot())
    return result
