#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import socket
import ssl
import sys
import time
from typing import Any
from urllib import error, request

try:
    from .output_format import (
        OutputFormatError,
        apply_response_format,
        normalize_output_format_config,
        payload_forbidden_key_hits,
        prompt_for_output_format,
        validate_json_output,
        validate_preflight_output,
    )
except ImportError:
    from output_format import (  # type: ignore[no-redef]
        OutputFormatError,
        apply_response_format,
        normalize_output_format_config,
        payload_forbidden_key_hits,
        prompt_for_output_format,
        validate_json_output,
        validate_preflight_output,
    )


RUNNER_VERSION = "3.0.0-algorithm-llm-only"
DEFAULT_RUNNER_CONFIG: dict[str, Any] = {
    "api_base_env": "GX1_API_BASE",
    "api_key_env": "GX1_API_KEY",
    "model_env": "GX1_MODEL",
    "extra_body_env": "GX1_EXTRA_BODY_JSON",
    "temperature": 0.0,
    "max_tokens": 16384,
    "request_timeout_seconds": 180.0,
    "request_hard_timeout_seconds": 210.0,
    "case_timeout_seconds": 720.0,
    "retries": 2,
    "backoff_seconds": 1.0,
    "concurrency": 1,
    "resume": True,
    "output_format": {"mode": "json_schema", "strict": True, "preflight": True},
}
TERMINAL_STATUSES = {
    "SUCCESS", "INFRASTRUCTURE_ERROR", "MODEL_OUTPUT_INVALID", "MODEL_WRONG",
    "LLM_PREFLIGHT_FAILED", "PRODUCER_OR_VALIDATOR_ERROR",
}
RESERVED_EXTRA_BODY_KEYS = {
    "model", "messages", "temperature", "max_tokens", "response_format"
}


class InfrastructureError(RuntimeError):
    def __init__(self, message: str, error_class: str | None = None):
        super().__init__(message)
        self.error_class = error_class


class ModelProtocolError(RuntimeError):
    pass


class PayloadBoundaryError(RuntimeError):
    pass


def _ensure_producer_import(producer_dir: str | Path) -> Path:
    path = Path(producer_dir).resolve()
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    return path


def classify_infrastructure_message(message: str) -> str:
    text = str(message).lower()
    if "ssl" in text or "certificate_verify_failed" in text:
        return "SSL_ERROR"
    if "http " in text or text.startswith("http_") or "http error" in text:
        return "HTTP_ERROR"
    if any(token in text for token in ("connection reset", "remote end closed", "remote closed", "broken pipe", "connection aborted")):
        return "REMOTE_CLOSED"
    if "connect" in text and ("timed out" in text or "timeout" in text):
        return "CONNECT_TIMEOUT"
    if "timed out" in text or "timeout" in text:
        return "READ_TIMEOUT"
    return "INFRASTRUCTURE_ERROR"


def classify_execution_error(exc: BaseException) -> str:
    if isinstance(exc, InfrastructureError):
        return exc.error_class or classify_infrastructure_message(str(exc))
    if isinstance(exc, PayloadBoundaryError):
        return "PRODUCER_OR_VALIDATOR_ERROR"
    return "MODEL_OUTPUT_INVALID"


def load_actual_request(case_dir: str | Path) -> dict[str, Any]:
    obj = json.loads((Path(case_dir) / "actual_llm_request.json").read_text(encoding="utf-8"))
    hits = payload_forbidden_key_hits(obj)
    if hits:
        raise PayloadBoundaryError(f"DUT payload contains forbidden structured keys: {hits}")
    if not isinstance(obj.get("messages"), list):
        raise PayloadBoundaryError("actual_llm_request.json must contain messages array")
    return obj


def _case_dirs(dataset_dir: Path):
    for task in ("G1", "G2", "G3", "X1"):
        task_dir = dataset_dir / "cases" / task
        if task_dir.exists():
            for case_dir in sorted(path for path in task_dir.iterdir() if path.is_dir()):
                yield task, case_dir


def _http_worker(api_base: str, api_key: str, payload: dict[str, Any], timeout: float, out_queue) -> None:
    url = api_base.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    })
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        out_queue.put({"ok": True, "value": json.loads(raw)})
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        out_queue.put({"ok": False, "error_class": "HTTP_ERROR", "error": f"HTTP {exc.code}: {detail[:1000]}"})
    except error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            category = "SSL_ERROR"
        elif isinstance(reason, socket.timeout):
            category = "CONNECT_TIMEOUT"
        elif isinstance(reason, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            category = "REMOTE_CLOSED"
        else:
            category = classify_infrastructure_message(str(exc))
        out_queue.put({"ok": False, "error_class": category, "error": f"{type(exc).__name__}: {exc}"})
    except ssl.SSLError as exc:
        out_queue.put({"ok": False, "error_class": "SSL_ERROR", "error": f"{type(exc).__name__}: {exc}"})
    except (socket.timeout, TimeoutError) as exc:
        out_queue.put({"ok": False, "error_class": "READ_TIMEOUT", "error": f"{type(exc).__name__}: {exc}"})
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as exc:
        out_queue.put({"ok": False, "error_class": "REMOTE_CLOSED", "error": f"{type(exc).__name__}: {exc}"})
    except Exception as exc:
        out_queue.put({"ok": False, "error_class": classify_infrastructure_message(str(exc)), "error": f"{type(exc).__name__}: {exc}"})


def _post_chat_hard_timeout(
    api_base: str, api_key: str, payload: dict[str, Any], *, retries: int = 2,
    request_timeout_seconds: float = 180, hard_timeout_seconds: float = 210,
    backoff_seconds: float = 1.0, deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    attempts = min(3, max(1, int(retries)))
    last_error = "unknown infrastructure error"
    last_class = "INFRASTRUCTURE_ERROR"
    context = mp.get_context("spawn")
    for attempt in range(attempts):
        if deadline_monotonic is not None:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise InfrastructureError("case hard timeout exhausted before API call", "CASE_WALLCLOCK_TIMEOUT")
            attempt_timeout = min(float(hard_timeout_seconds), remaining)
        else:
            attempt_timeout = float(hard_timeout_seconds)
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_http_worker,
            args=(api_base, api_key, payload, float(request_timeout_seconds), result_queue),
            daemon=True,
        )
        try:
            process.start()
            process.join(attempt_timeout)
            if process.is_alive():
                process.terminate()
                process.join(2.0)
                last_class = "CASE_WALLCLOCK_TIMEOUT" if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic - 1e-6 else "REQUEST_HARD_TIMEOUT"
                last_error = f"hard timeout after {attempt_timeout:.3f}s"
            else:
                try:
                    result = result_queue.get(timeout=0.5)
                except queue.Empty:
                    result = {"ok": False, "error_class": "INFRASTRUCTURE_ERROR", "error": f"HTTP worker exited with code {process.exitcode} without result"}
                if result.get("ok"):
                    return result["value"]
                last_class = str(result.get("error_class") or classify_infrastructure_message(result.get("error", "")))
                last_error = str(result.get("error") or "unknown infrastructure error")
        finally:
            try:
                result_queue.close()
            except Exception:
                pass
        if attempt + 1 < attempts:
            delay = min(60.0, float(backoff_seconds) * (2 ** attempt))
            if deadline_monotonic is not None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise InfrastructureError("case hard timeout exhausted during retry backoff", "CASE_WALLCLOCK_TIMEOUT")
                delay = min(delay, max(0.0, remaining))
            if delay > 0:
                time.sleep(delay)
    raise InfrastructureError(f"API request failed after {attempts} attempts: {last_error}", last_class)


def _load_extra_body(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("GX1_EXTRA_BODY_JSON must decode to a JSON object")
    overlap = RESERVED_EXTRA_BODY_KEYS & set(obj)
    if overlap:
        raise ValueError(f"reserved request keys cannot be overridden: {sorted(overlap)}")
    return obj


def _extract_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
        if not isinstance(message, dict):
            raise TypeError("message is not an object")
        return message
    except Exception as exc:
        raise ModelProtocolError(f"API response missing choices[0].message: {exc}") from exc


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _load_resume_record(target: str | Path, resume: bool) -> dict[str, Any] | None:
    if not resume:
        return None
    path = Path(target) / "trial_record.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return record if record.get("execution_status") in TERMINAL_STATUSES else None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _copy_config(base: dict[str, Any]) -> dict[str, Any]:
    config = dict(DEFAULT_RUNNER_CONFIG)
    config["output_format"] = dict(DEFAULT_RUNNER_CONFIG["output_format"])
    for key, value in base.items():
        if key == "output_format" and isinstance(value, dict):
            config["output_format"].update(value)
        else:
            config[key] = value
    config["output_format"] = normalize_output_format_config(config.get("output_format"))
    return config


def load_runner_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        return _copy_config({})
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runner config must be a JSON object")
    return _copy_config(value)


def _build_payload(model: str, messages: list[dict[str, Any]], config: dict[str, Any], extra_body: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(config.get("temperature", 0.0)),
    }
    if config.get("max_tokens") is not None:
        payload["max_tokens"] = int(config["max_tokens"])
    return {**payload, **extra_body}


def _case_extra_body(extra_body: dict[str, Any], root: dict[str, Any] | None, config: dict[str, Any], *, preflight: bool = False) -> dict[str, Any]:
    try:
        return apply_response_format(extra_body, root, config.get("output_format"), preflight=preflight)
    except OutputFormatError as exc:
        raise PayloadBoundaryError(str(exc)) from exc


def _persist_model_request(target: Path | None, payload: dict[str, Any]) -> None:
    if target is None:
        return
    hits = payload_forbidden_key_hits(payload)
    _write_json(target / "actual_model_request.json", payload)
    _write_json(target / "request_boundary_audit.json", {"forbidden_key_hits": hits, "passed": not hits})
    if hits:
        raise PayloadBoundaryError(f"DUT request contains forbidden structured keys: {hits}")


def _post_for_case(api_base: str, api_key: str, payload: dict[str, Any], deadline: float, options: dict[str, Any]):
    return _post_chat_hard_timeout(
        api_base, api_key, payload,
        retries=options["retries"],
        request_timeout_seconds=options["request_timeout_seconds"],
        hard_timeout_seconds=options["request_hard_timeout_seconds"],
        backoff_seconds=options["backoff_seconds"],
        deadline_monotonic=deadline,
    )


def run_llm_preflight(
    api_base: str, api_key: str, model: str, *, request_timeout_seconds: float,
    request_hard_timeout_seconds: float, retries: int, backoff_seconds: float,
    case_timeout_seconds: float, extra_body: dict[str, Any],
    output_format_config: dict[str, Any] | None = None,
    temperature: float = 0.0, max_tokens: int | None = 1024,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + float(case_timeout_seconds)
    format_config = normalize_output_format_config(output_format_config)
    try:
        body = apply_response_format(extra_body, None, format_config, preflight=True)
        prompt = prompt_for_output_format(format_config, preflight=True)
        payload = _build_payload(model, [{"role": "user", "content": prompt}], {"temperature": temperature, "max_tokens": max_tokens}, body)
        response = _post_chat_hard_timeout(
            api_base, api_key, payload, retries=retries,
            request_timeout_seconds=request_timeout_seconds,
            hard_timeout_seconds=request_hard_timeout_seconds,
            backoff_seconds=backoff_seconds, deadline_monotonic=deadline,
        )
        message = _extract_message(response)
        valid = validate_preflight_output(message.get("content"), format_config)
        return {
            "supported": valid,
            "status": "PASS" if valid else "LLM_PREFLIGHT_FAILED",
            "level": 1,
            "error_class": None if valid else "MODEL_OUTPUT_INVALID",
            "error": None if valid else "preflight response did not satisfy configured output format",
            "raw_api_responses": [response],
            "latency_seconds": round(time.monotonic() - started, 3),
            "output_format_valid": valid,
        }
    except Exception as exc:
        return {
            "supported": False, "status": "LLM_PREFLIGHT_FAILED", "level": 1,
            "error_class": classify_execution_error(exc), "error": str(exc),
            "raw_api_responses": [], "latency_seconds": round(time.monotonic() - started, 3),
        }


def run_one_llm_case(
    case_dir: Path, model: str, api_base: str, api_key: str,
    options: dict[str, Any], extra_body: dict[str, Any], *,
    output_dir: Path | None = None,
    output_format_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = json.loads((case_dir / "root_case.json").read_text(encoding="utf-8"))
    actual_request = load_actual_request(case_dir)
    format_config = output_format_config if output_format_config is not None else options.get("output_format")
    body = _case_extra_body(extra_body, root, {"output_format": format_config})
    payload = _build_payload(model, actual_request["messages"], options, body)
    target = Path(output_dir) if output_dir is not None else None
    _persist_model_request(target, payload)
    response = _post_for_case(api_base, api_key, payload, time.monotonic() + float(options["case_timeout_seconds"]), options)
    if target is not None:
        _write_json(target / "raw_api_responses.json", [response])
    return {
        "model_output": _content_text(_extract_message(response).get("content")),
        "api_responses": [response], "termination_reason": "FINAL_RESPONSE",
    }


def run_dry_run(producer_dir: str | Path, dataset_dir: str | Path, *, runner_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    _ensure_producer_import(producer_dir)
    from gx1.validators import validate_dut_output
    config = _copy_config(runner_config or {})
    rows: list[dict[str, Any]] = []
    for task, case_dir in _case_dirs(Path(dataset_dir)):
        root = json.loads((case_dir / "root_case.json").read_text(encoding="utf-8"))
        actual_request = load_actual_request(case_dir)
        body = _case_extra_body({}, root, config)
        payload = _build_payload("dry-run-model", actual_request["messages"], config, body)
        validation = validate_dut_output(root, json.dumps(root["answer"], ensure_ascii=False))
        hits = payload_forbidden_key_hits(payload)
        rows.append({
            "task": task, "case_id": root["case_id"], "track": "llm",
            "payload_ok": not hits, "boundary_hits": hits,
            "validator_valid": bool(validation.get("valid")),
            "output_format_mode": config["output_format"]["mode"],
            "response_format": payload.get("response_format"),
        })
    return rows


def _classify_validation(validation: dict[str, Any]) -> str:
    if validation.get("valid"):
        return "SUCCESS"
    return "MODEL_OUTPUT_INVALID" if validation.get("reason") in {"INVALID_JSON", "OUTPUT_SCHEMA", "PAIR_IDS"} else "MODEL_WRONG"


def _legacy_json_parse_valid(validation: dict[str, Any]) -> bool:
    return validation.get("reason") != "INVALID_JSON"


def _legacy_schema_valid(validation: dict[str, Any]) -> bool:
    return validation.get("reason") not in {"INVALID_JSON", "OUTPUT_SCHEMA", "PAIR_IDS"}


def _usage_totals(responses: list[dict[str, Any]]) -> dict[str, int | None]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    seen = False
    for response in responses:
        usage = response.get("usage") if isinstance(response, dict) else None
        if not isinstance(usage, dict):
            continue
        seen = True
        for target, candidates in {
            "input_tokens": ("prompt_tokens", "input_tokens"),
            "output_tokens": ("completion_tokens", "output_tokens"),
            "total_tokens": ("total_tokens",),
        }.items():
            value = next((usage.get(name) for name in candidates if isinstance(usage.get(name), (int, float))), None)
            if value is not None:
                totals[target] += int(value)
    return totals if seen else {name: None for name in totals}


def _case_dimensions(root: dict[str, Any]) -> dict[str, Any]:
    metadata = root.get("generation_metadata") or {}
    return {
        "difficulty": metadata.get("requested_difficulty"),
        "node_count": len(root.get("nodes", [])),
        "path_cost_metric": root.get("path_cost_metric"),
        "g1_conversion": root.get("conversion"),
        "g2_oracle_label": root.get("oracle_label"),
        "g3_shared": root.get("answer", {}).get("has_shared_directed_link") if root.get("task_type") == "G3" else None,
        "x1_multiplicity": ("MULTIPLE" if int(root.get("shortest_path_multiplicity", 1)) > 1 else "UNIQUE") if root.get("task_type") == "X1" else None,
    }


def _g2_predicted_label(output: str) -> str | None:
    try:
        value = json.loads(output)
    except Exception:
        return None
    if not isinstance(value, dict) or set(value) != {"is_valid", "error_type"}:
        return None
    return "VALID" if value.get("is_valid") is True and value.get("error_type") is None else value.get("error_type")


def _write_failure_artifacts(target: Path, validation: dict[str, Any], error_text: str | None = None) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "model_output.txt").write_text("", encoding="utf-8")
    if not (target / "raw_api_responses.json").exists():
        _write_json(target / "raw_api_responses.json", [])
    _write_json(target / "validation_result.json", validation)
    if error_text is not None:
        (target / "execution_error.txt").write_text(error_text, encoding="utf-8")


def _summary(rows: list[dict[str, Any]], model: str, config: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    attempted = sum(bool(row.get("api_attempted")) for row in rows)
    api_success = sum(bool(row.get("api_success")) for row in rows)
    model_completed = sum(bool(row.get("model_completed")) for row in rows)
    validator_pass = sum(bool(row.get("validator_valid")) for row in rows)
    by_task: dict[str, Any] = {}
    for task in ("G1", "G2", "G3", "X1"):
        subset = [row for row in rows if row.get("task") == task]
        completed = sum(bool(row.get("model_completed")) for row in subset)
        passed = sum(bool(row.get("validator_valid")) for row in subset)
        by_task[task] = {"case_count": len(subset), "model_completed": completed, "validator_pass": passed, "accuracy": passed / completed if completed else None}
    return {
        "runner_version": RUNNER_VERSION,
        "model": model,
        "track": "llm",
        "api_attempted": attempted,
        "api_success": api_success,
        "infrastructure_failure": sum(row.get("execution_status") == "INFRASTRUCTURE_ERROR" for row in rows),
        "model_completed": model_completed,
        "json_parse_success": sum(row.get("json_parse_valid") is True for row in rows),
        "schema_valid": sum(row.get("schema_valid") is True for row in rows),
        "validator_pass": validator_pass,
        "validator_fail": model_completed - validator_pass,
        "accuracy": validator_pass / model_completed if model_completed else None,
        "total_input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
        "total_output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in rows),
        "total_latency_seconds": round(sum(float(row.get("latency_seconds") or 0) for row in rows), 3),
        "by_task": by_task,
        "llm_preflight": preflight,
        "config": {key: value for key, value in config.items() if key not in {"api_key", "extra_body"}},
    }


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# GX1 Algorithm+LLM Evaluator — LLM Trial Summary", "",
        f"- Model: `{summary['model']}`",
        f"- API attempted: {summary['api_attempted']}",
        f"- API success: {summary['api_success']}",
        f"- Model completed: {summary['model_completed']}",
        f"- Validator pass: {summary['validator_pass']}",
        f"- Accuracy: {summary['accuracy']}", "",
        "| Task | Cases | Completed | Pass | Accuracy |", "|---|---:|---:|---:|---:|",
    ]
    for task, row in summary["by_task"].items():
        lines.append(f"| {task} | {row['case_count']} | {row['model_completed']} | {row['validator_pass']} | {row['accuracy']} |")
    return "\n".join(lines) + "\n"


def _resolved_runtime_config(config: dict[str, Any], extra_body: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, str, str, dict[str, Any]]:
    cfg = _copy_config(config)
    for key in ("request_timeout_seconds", "request_hard_timeout_seconds", "case_timeout_seconds", "backoff_seconds", "temperature"):
        cfg[key] = float(cfg[key])
    cfg["retries"] = min(3, max(1, int(cfg["retries"])))
    cfg["max_tokens"] = None if cfg.get("max_tokens") is None else int(cfg["max_tokens"])
    body = dict(extra_body) if extra_body is not None else (
        dict(cfg["extra_body"]) if isinstance(cfg.get("extra_body"), dict)
        else _load_extra_body(os.environ.get(str(cfg.get("extra_body_env", "GX1_EXTRA_BODY_JSON")), "").strip())
    )
    overlap = RESERVED_EXTRA_BODY_KEYS & set(body)
    if overlap:
        raise ValueError(f"reserved request keys cannot be overridden: {sorted(overlap)}")
    api_base = str(cfg.get("api_base") or os.environ.get(str(cfg["api_base_env"]), "")).strip()
    api_key = os.environ.get(str(cfg["api_key_env"]), "").strip()
    model = str(cfg.get("model") or os.environ.get(str(cfg["model_env"]), "")).strip()
    if not api_base or not api_key or not model:
        raise RuntimeError(f"Set API base/model and API key in environment variable {cfg['api_key_env']}; API keys must not be written into files.")
    return cfg, api_base, api_key, model, body


def run_trial(
    producer_dir: str | Path, dataset_dir: str | Path, results_dir: str | Path, *,
    runner_config: dict[str, Any] | None = None, resume: bool = False,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_producer_import(producer_dir)
    from gx1.validators import validate_dut_output
    cfg, api_base, api_key, model, body = _resolved_runtime_config(runner_config or {}, extra_body)
    results = Path(results_dir)
    results.mkdir(parents=True, exist_ok=True)
    preflight = run_llm_preflight(
        api_base, api_key, model,
        request_timeout_seconds=cfg["request_timeout_seconds"],
        request_hard_timeout_seconds=cfg["request_hard_timeout_seconds"],
        retries=cfg["retries"], backoff_seconds=cfg["backoff_seconds"],
        case_timeout_seconds=cfg["case_timeout_seconds"], extra_body=body,
        output_format_config=cfg["output_format"], temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
    )
    _write_json(results / "llm_preflight.json", preflight)
    rows: list[dict[str, Any]] = []
    for task, case_dir in _case_dirs(Path(dataset_dir)):
        root = json.loads((case_dir / "root_case.json").read_text(encoding="utf-8"))
        target = results / "llm" / task / root["case_id"]
        target.mkdir(parents=True, exist_ok=True)
        old = _load_resume_record(target, resume or bool(cfg.get("resume")))
        if old is not None:
            rows.append({**old, "resumed": True})
            continue
        started = time.monotonic()
        record: dict[str, Any] = {
            "track": "llm", "task": task, "case_id": root["case_id"],
            "execution_status": None, "api_attempted": False, "api_success": False, "model_completed": False,
            "json_parse_valid": None, "schema_valid": None, "validator_valid": False,
            "output_format_mode": cfg["output_format"]["mode"],
            "response_format_applied": cfg["output_format"]["mode"] != "off",
            "latency_seconds": None, "input_tokens": None, "output_tokens": None,
            "total_tokens": None, "error_class": None, "error": None,
            "termination_reason": None, "resumed": False, **_case_dimensions(root),
        }
        if not preflight.get("supported"):
            record.update({"execution_status": "LLM_PREFLIGHT_FAILED", "error_class": "LLM_PREFLIGHT_FAILED", "error": "LLM preflight failed; formal cases were not attempted.", "termination_reason": "LLM_PREFLIGHT_FAILED"})
            _write_failure_artifacts(target, {"valid": False, "reason": "LLM_PREFLIGHT_FAILED", "preflight": preflight}, record["error"])
        else:
            try:
                record["api_attempted"] = True
                run = run_one_llm_case(case_dir, model, api_base, api_key, cfg, body, output_dir=target, output_format_config=cfg["output_format"])
                record["api_success"] = True
                record["model_completed"] = True
                model_output = run["model_output"]
                scientific = validate_dut_output(root, model_output)
                if cfg["output_format"]["mode"] == "off":
                    format_result = {"json_parse_valid": _legacy_json_parse_valid(scientific), "schema_valid": _legacy_schema_valid(scientific), "format_validation_reason": "LEGACY_VALIDATOR_ONLY", "format_validation_errors": [], "format_mode": "off"}
                else:
                    format_result = validate_json_output(model_output, root, cfg["output_format"])
                record["json_parse_valid"] = format_result["json_parse_valid"]
                record["schema_valid"] = format_result["schema_valid"]
                record["validator_valid"] = bool(scientific.get("valid")) and bool(format_result["schema_valid"])
                record["execution_status"] = "MODEL_OUTPUT_INVALID" if not format_result["schema_valid"] else _classify_validation(scientific)
                record["error_class"] = None if record["validator_valid"] else record["execution_status"]
                record["termination_reason"] = run["termination_reason"]
                record["validation_reason"] = scientific.get("reason")
                record["predicted_g2_label"] = _g2_predicted_label(model_output) if task == "G2" else None
                (target / "model_output.txt").write_text(model_output, encoding="utf-8")
                _write_json(target / "validation_result.json", {**scientific, "output_format_validation": format_result})
                record.update(_usage_totals(run["api_responses"]))
            except InfrastructureError as exc:
                category = exc.error_class or classify_infrastructure_message(str(exc))
                record.update({"execution_status": "INFRASTRUCTURE_ERROR", "error_class": category, "error": str(exc), "termination_reason": category})
                _write_failure_artifacts(target, {"valid": False, "reason": "EXECUTION_ERROR", "error_class": category}, str(exc))
            except PayloadBoundaryError as exc:
                record.update({"execution_status": "PRODUCER_OR_VALIDATOR_ERROR", "error_class": "PRODUCER_OR_VALIDATOR_ERROR", "error": str(exc), "termination_reason": "PRODUCER_OR_VALIDATOR_ERROR"})
                _write_failure_artifacts(target, {"valid": False, "reason": "PAYLOAD_BOUNDARY_ERROR"}, str(exc))
            except Exception as exc:
                record.update({"execution_status": "MODEL_OUTPUT_INVALID", "error_class": "MODEL_OUTPUT_INVALID", "error": str(exc), "termination_reason": "MODEL_OUTPUT_INVALID"})
                _write_failure_artifacts(target, {"valid": False, "reason": "EXECUTION_ERROR", "error_class": "MODEL_OUTPUT_INVALID"}, str(exc))
        record["latency_seconds"] = round(time.monotonic() - started, 3)
        _write_json(target / "trial_record.json", record)
        rows.append(record)

    summary = _summary(rows, model, cfg, preflight)
    _write_json(results / "summary.json", summary)
    (results / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    fieldnames = sorted({key for row in rows for key in row})
    with (results / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAI-compatible resilient LLM trial runner for G1/G2/G3/X1")
    parser.add_argument("--producer-dir", required=True)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--results-dir", default="trial_results")
    parser.add_argument("--runner-config")
    parser.add_argument("--api-base-env")
    parser.add_argument("--api-key-env")
    parser.add_argument("--model-env")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--extra-body-json")
    parser.add_argument("--output-format-mode", choices=["off", "json_object", "json_schema"])
    parser.add_argument("--output-format-strict", action="store_true", default=None)
    parser.add_argument("--no-output-format-strict", dest="output_format_strict", action="store_false")
    parser.add_argument("--request-timeout-seconds", type=float)
    parser.add_argument("--request-hard-timeout-seconds", type=float)
    parser.add_argument("--case-timeout-seconds", type=float)
    parser.add_argument("--retries", type=int)
    parser.add_argument("--backoff-seconds", type=float)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = load_runner_config(args.runner_config)
    for key in ("api_base_env", "api_key_env", "model_env", "temperature", "max_tokens", "request_timeout_seconds", "request_hard_timeout_seconds", "case_timeout_seconds", "retries", "backoff_seconds"):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    output_format = dict(config.get("output_format") or {})
    if args.output_format_mode is not None:
        output_format["mode"] = args.output_format_mode
    if args.output_format_strict is not None:
        output_format["strict"] = args.output_format_strict
    config["output_format"] = output_format
    if args.extra_body_json is not None:
        config["extra_body"] = _load_extra_body(args.extra_body_json)
    if args.dry_run:
        rows = run_dry_run(args.producer_dir, args.dataset_dir, runner_config=config)
        print(json.dumps({"dry_run": True, "rows": rows}, ensure_ascii=False, indent=2))
        return 0 if rows and all(row["validator_valid"] and row["payload_ok"] for row in rows) else 1
    summary = run_trial(
        args.producer_dir, args.dataset_dir, args.results_dir,
        runner_config=config, resume=args.resume,
        extra_body=config.get("extra_body"),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
