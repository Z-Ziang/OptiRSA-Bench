from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.s1_x4.evaluator import DynamicEpisodeSession
from trial_evaluation.checkpoint import CheckpointStore, atomic_write_json
from trial_evaluation.episodes import EpisodeBundle
from trial_evaluation.providers.base import ModelProvider, ProviderError
from trial_evaluation.reference import load_reference_prefix_summary
from trial_evaluation.security import redact_text
from trial_evaluation.v2.metrics import build_v2_summary
from trial_evaluation.v2.step_result import StepResult
from trial_evaluation.v2.structured_output import StructuredActionParser


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.is_file():
        rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.append(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _provider_error_code(exc: ProviderError) -> str:
    if exc.status_code == 402:
        return "INFRA_BALANCE_402"
    if exc.status_code == 429:
        return "INFRA_HTTP_429"
    if exc.status_code is not None and 500 <= exc.status_code <= 599:
        return "INFRA_HTTP_5XX"
    message = str(exc).lower()
    if "timeout" in message:
        return "INFRA_TIMEOUT"
    if "overload" in message:
        return "INFRA_PROVIDER_OVERLOADED"
    return "INFRA_CONNECTION"


def _response_usage(response: Any) -> dict[str, int | None]:
    usage = response.usage
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached_tokens": usage.cached_tokens,
        "reasoning_tokens": getattr(usage, "reasoning_tokens", None),
        "api_requests": 1 + int(response.retry_count),
    }


def _run_llm_turn(provider: ModelProvider, system_prompt: str, step_prompt: str) -> dict[str, Any]:
    response = provider.complete([{"role": "system", "content": system_prompt}, {"role": "user", "content": step_prompt}])
    return {
        "raw_model_output": response.text or "",
        "finish_reason": response.finish_reason,
        "provider_responses": [response.to_dict()],
        "api_usage": _response_usage(response),
        "latency_ms": response.latency_ms,
        "retry_count": response.retry_count,
        "model_failure_codes": [],
    }


def _scientific_code(validation: Mapping[str, Any]) -> str | None:
    if validation.get("valid") is True:
        return "MODEL_REJECT" if validation.get("decision") == "REJECT" else None
    if validation.get("decision") == "ACCEPT":
        error = str(validation.get("error") or "").lower()
        return "MODEL_INFEASIBLE_ACCEPT" if any(token in error for token in ("feasible", "spectrum", "action", "path")) else "MODEL_ILLEGAL_ACTION"
    return "MODEL_ILLEGAL_ACTION"


def _summary_result(bundle: EpisodeBundle, provider: ModelProvider, status: str, records: list[dict[str, Any]], attempts: list[dict[str, Any]], error: str | None = None) -> dict[str, Any]:
    summary = build_v2_summary(records, attempts)
    response_models = [response.get("response_model") for row in records for response in row.get("provider_responses", []) if response.get("response_model")]
    model = {"provider": getattr(provider.config, "provider", None), "requested_model": getattr(provider.config, "model", None), "response_model": response_models[-1] if response_models else None}
    result = {
        "status": status,
        "evaluation_scope": "PREFIX_TRIAL" if summary["committed_steps"] < bundle.episode_length else "FULL_H512",
        "max_steps": summary["committed_steps"],
        "task_type": bundle.task,
        "modality": bundle.modality,
        "topology_id": bundle.topology_id,
        "condition_id": bundle.condition_id,
        "case_id": bundle.case_id,
        "episode_length": bundle.episode_length,
        "pairing_id": bundle.episode.get("pairing_id"),
        "system_prompt_sha256": bundle.system_prompt_sha256,
        "summary": summary,
        "model": model,
    }
    if error is not None:
        result["error"] = error
    return result


def run_v2_unit(
    bundle: EpisodeBundle,
    provider: ModelProvider,
    output_root: Path | str,
    *,
    max_steps: int,
    resume: bool = False,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    if max_steps <= 0 or max_steps > bundle.episode_length:
        raise ValueError("max_steps must be in 1..episode_length")
    root = Path(output_root)
    unit_id = bundle.unit_id
    checkpoint = CheckpointStore(root / "CHECKPOINTS" / unit_id)
    attempt_path = root / "ATTEMPTS" / unit_id / "attempts.jsonl"
    raw_path = root / "RAW" / unit_id / "steps.jsonl"
    committed = checkpoint.load()
    attempts = _load_jsonl(attempt_path)
    if (committed or attempts) and not resume:
        raise RuntimeError(f"V2 checkpoint exists; use resume for {unit_id}")
    session = DynamicEpisodeSession(bundle.episode, endpoint=bundle.modality)
    for row in committed:
        if row.get("step_index") != len(session.state.trajectory) + 1:
            raise RuntimeError("V2 checkpoint steps are not contiguous")
        replay = session.submit_response(row["submission_for_replay"])
        if replay["validation"] != row["validation"] or replay["trajectory_record"] != row["trajectory_record"]:
            raise RuntimeError(f"V2 checkpoint replay mismatch at step {row['step_index']}")
    while len(committed) < max_steps:
        current_step_index = len(committed) + 1
        step = session.current_step()
        try:
            turn = _run_llm_turn(provider, bundle.system_prompt, step["prompt"])
        except ProviderError as exc:
            code = _provider_error_code(exc)
            retry_count = int(getattr(exc, "retry_count", 0))
            attempt = StepResult(
                current_step_index,
                "NOT_COMMITTED",
                code,
                "NOT_RUN",
                None,
                code,
                api_usage={"api_requests": retry_count + 1, "transport_retries": retry_count},
                errors=[str(exc)[:500]],
            ).to_dict()
            attempt["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
            _append_jsonl(attempt_path, attempt)
            attempts.append(attempt)
            status = "BALANCE_STOP" if code == "INFRA_BALANCE_402" else "INFRA_STOP"
            result = _summary_result(bundle, provider, status, committed, attempts, f"{type(exc).__name__}: {str(exc)[:500]}")
            atomic_write_json(root / "UNITS" / unit_id / "unit_summary.json", result)
            return result
        except Exception as exc:
            code = "RUNNER_INTERNAL_ERROR"
            attempt = StepResult(current_step_index, "NOT_COMMITTED", code, "NOT_RUN", None, code, errors=[str(exc)[:500]]).to_dict()
            _append_jsonl(attempt_path, attempt)
            attempts.append(attempt)
            result = _summary_result(bundle, provider, "RUNNER_ERROR", committed, attempts, f"{type(exc).__name__}: {str(exc)[:500]}")
            atomic_write_json(root / "UNITS" / unit_id / "unit_summary.json", result)
            return result

        if turn.get("protocol_failure"):
            code = str(turn["protocol_failure"])
            attempt = StepResult(current_step_index, "NOT_COMMITTED", "OK", "PROTOCOL_FAILURE", None, code, raw_model_output=redact_text(turn.get("raw_model_output", ""), secrets=secrets), provider_responses=turn.get("provider_responses", []), api_usage=turn.get("api_usage", {}), errors=[code], model_failure_codes=turn.get("model_failure_codes", [])).to_dict()
            _append_jsonl(attempt_path, attempt)
            attempts.append(attempt)
            result = _summary_result(bundle, provider, "PROTOCOL_STOP", committed, attempts, code)
            atomic_write_json(root / "UNITS" / unit_id / "unit_summary.json", result)
            return result
        parsed = StructuredActionParser(bundle.task).parse(turn.get("raw_model_output"), finish_reason=turn.get("finish_reason"))
        if parsed.protocol_status != "OK":
            attempt = StepResult(current_step_index, "NOT_COMMITTED", "OK", parsed.protocol_status, None, parsed.code, raw_model_output=redact_text(parsed.raw_text, secrets=secrets), provider_responses=turn.get("provider_responses", []), api_usage=turn.get("api_usage", {}), errors=[str(parsed.code)], model_failure_codes=turn.get("model_failure_codes", [])).to_dict()
            _append_jsonl(attempt_path, attempt)
            attempts.append(attempt)
            result = _summary_result(bundle, provider, "PROTOCOL_STOP", committed, attempts, str(parsed.code))
            atomic_write_json(root / "UNITS" / unit_id / "unit_summary.json", result)
            return result
        submission = redact_text(parsed.raw_text, secrets=secrets)
        official = session.submit_response(submission)
        validation = official["validation"]
        scientific = _scientific_code(validation)
        model_codes = list(turn.get("model_failure_codes", []))
        row = StepResult(current_step_index, "COMMITTED", "OK", "OK", scientific, scientific, raw_model_output=submission, validation=validation, trajectory_record=official["trajectory_record"], provider_responses=turn.get("provider_responses", []), api_usage=turn.get("api_usage", {}), errors=[], model_failure_codes=model_codes).to_dict()
        row.update({"submission_for_replay": submission, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "finish_reason": turn.get("finish_reason"), "latency_ms": turn.get("latency_ms", 0.0), "retry_count": turn.get("retry_count", 0)})
        checkpoint.append(row)
        committed.append(row)
        attempts.append(row)
        _append_jsonl(attempt_path, row)
        _append_jsonl(raw_path, row)
        atomic_write_json(root / "UNITS" / unit_id / "progress.json", {"committed_steps": len(committed), "last_step_index": current_step_index})
    result = _summary_result(bundle, provider, "PASS" if len(committed) == bundle.episode_length else "PREFIX_COMPLETE", committed, attempts)
    reference = load_reference_prefix_summary(bundle.dataset_root, task=bundle.task, topology_id=bundle.topology_id, condition_id=bundle.condition_id, step_count=len(committed))
    if reference is not None:
        result["reference_prefix_summary"] = reference
        atomic_write_json(root / "UNITS" / unit_id / "reference_prefix_summary.json", reference)
    atomic_write_json(root / "UNITS" / unit_id / "unit_summary.json", result)
    return result
