from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trial_evaluation.providers.base import ProviderError, ProviderResponse
from trial_evaluation.providers.siliconflow import create_siliconflow_provider
from trial_evaluation.v2.action_schemas import action_schema


def parse_chat_model_ids(payload: Mapping[str, Any]) -> list[str]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("model list response does not contain data list")
    return [str(row["id"]) for row in rows if isinstance(row, Mapping) and isinstance(row.get("id"), str)]


def require_exact_model(model_ids: list[str], requested_model: str) -> bool:
    if requested_model not in model_ids:
        raise ValueError(f"model {requested_model!r} is not available; AVAILABLE_MODEL_IDS={model_ids}")
    return True


def _default_get_json(url: str, headers: Mapping[str, str], timeout_seconds: float) -> dict[str, Any]:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - explicit configured endpoint
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"model list HTTP {exc.code}: {body}", status_code=int(exc.code), retryable=False) from exc
    except (TimeoutError, OSError, URLError) as exc:
        raise ProviderError(f"model list transport error: {type(exc).__name__}: {str(exc)[:300]}", retryable=False) from exc
    if not isinstance(payload, dict):
        raise ProviderError("model list response must be a JSON object", retryable=False)
    return payload


def _safe_error(exc: BaseException, secret: str | None) -> str:
    message = f"{type(exc).__name__}: {str(exc)[:500]}"
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return message.replace("Authorization", "[AUTHORIZATION]")


def _probe_summary(response: ProviderResponse) -> dict[str, Any]:
    return {
        "ok": True,
        "response_model": response.response_model,
        "finish_reason": response.finish_reason,
        "usage": response.usage.to_dict(),
        "latency_ms": response.latency_ms,
        "retry_count": response.retry_count,
        "text_present": response.text is not None,
    }


def _probe_config(raw: Mapping[str, Any], *, response_format: dict[str, Any] | None, thinking: bool | None = None, budget: int | None = None, reasoning_effort: str | None = None) -> dict[str, Any]:
    config = dict(raw)
    config.setdefault("temperature", 0.0)
    config.setdefault("top_p", 1.0)
    config.setdefault("max_output_tokens", 512)
    config["response_format"] = response_format
    config["structured_output_mode"] = "JSON_SCHEMA" if response_format and response_format.get("type") == "json_schema" else ("JSON_OBJECT" if response_format else "NONE")
    config["enable_thinking"] = thinking
    config["thinking_budget"] = budget
    config["reasoning_effort"] = reasoning_effort
    return config


def _schema_response(task: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"{task.lower()}_capability_probe_action",
            "strict": True,
            "schema": action_schema(task),
        },
    }


def _probe_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "This is an API capability probe. Return only the requested structured response."},
        {"role": "user", "content": "Return a valid protocol probe response. Do not discuss the probe."},
    ]


def run_capability_probe(
    raw_config: Mapping[str, Any],
    *,
    api_key: str | None = None,
    get_json: Callable[[str, Mapping[str, str], float], dict[str, Any]] | None = None,
    provider_factory: Callable[[Mapping[str, Any]], Any] | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Probe the configured OpenAI-compatible endpoint without entering a science Episode.

    The endpoint is checked for the exact requested model before any POST
    capability request is made.  Only redacted request metadata and response
    usage/envelope facts are persisted.
    """

    config = dict(raw_config)
    secret = api_key or os.environ.get(str(config.get("api_key_env", "")))
    result: dict[str, Any] = {
        "schema_version": "TRIAL_V2_PROVIDER_CAPABILITY_PROBE_V1",
        "provider": config.get("provider"),
        "requested_model": config.get("model"),
        "base_url": config.get("base_url"),
        "api_key_present": bool(secret),
        "available_model_ids": [],
        "exact_model_available": False,
        "probes": {},
        "capabilities": {},
    }
    if not secret:
        result["status"] = "NO_API_KEY"
        if output_path is not None:
            Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    fetch = get_json or _default_get_json
    factory = provider_factory or create_siliconflow_provider
    timeout = float(config.get("timeout_seconds", 60.0))
    model_url = f"{str(config['base_url']).rstrip('/')}/models?sub_type=chat"
    try:
        model_payload = fetch(model_url, {"Authorization": f"Bearer {secret}", "Accept": "application/json"}, timeout)
        model_ids = parse_chat_model_ids(model_payload)
    except Exception as exc:
        result["status"] = "MODEL_LIST_ERROR"
        result["model_list_error"] = _safe_error(exc, secret)
        if output_path is not None:
            Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    result["available_model_ids"] = model_ids
    if config.get("model") not in model_ids:
        result["status"] = "MODEL_UNAVAILABLE"
        if output_path is not None:
            Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    result["exact_model_available"] = True

    base_messages = _probe_messages()

    probe_specs: list[tuple[str, dict[str, Any]]] = [
        ("chat_completions", _probe_config(config, response_format=None, thinking=False)),
        ("json_schema_s1", _probe_config(config, response_format=_schema_response("S1"), thinking=False)),
        ("json_schema_x4", _probe_config(config, response_format=_schema_response("X4"), thinking=False)),
        ("json_object", _probe_config(config, response_format={"type": "json_object"}, thinking=False)),
        ("enable_thinking", _probe_config(config, response_format=_schema_response("S1"), thinking=True, budget=1024)),
        ("thinking_budget", _probe_config(config, response_format=_schema_response("S1"), thinking=True, budget=1024)),
        ("reasoning_effort", _probe_config(config, response_format=_schema_response("S1"), thinking=None, reasoning_effort="low")),
    ]
    for name, probe_config in probe_specs:
        try:
            provider = factory(probe_config)
            response = provider.complete(base_messages)
            result["probes"][name] = _probe_summary(response)
        except Exception as exc:
            result["probes"][name] = {"ok": False, "error": _safe_error(exc, secret), "error_type": type(exc).__name__}

    probes = result["probes"]
    ok = lambda name: bool(isinstance(probes.get(name), Mapping) and probes[name].get("ok"))
    successful = [value for value in probes.values() if isinstance(value, Mapping) and value.get("ok")]
    result["capabilities"] = {
        "chat_completions": ok("chat_completions"),
        "json_schema": ok("json_schema_s1") and ok("json_schema_x4"),
        "json_object": ok("json_object"),
        "enable_thinking": ok("enable_thinking"),
        "thinking_budget": ok("thinking_budget"),
        "reasoning_effort": ok("reasoning_effort"),
        "finish_reason": any(item.get("finish_reason") is not None for item in successful),
        "usage_prompt_tokens": any(item.get("usage", {}).get("input_tokens") is not None for item in successful),
        "usage_output_tokens": any(item.get("usage", {}).get("output_tokens") is not None for item in successful),
        "usage_reasoning_tokens": any(item.get("usage", {}).get("reasoning_tokens") is not None for item in successful),
        "usage_cached_tokens": any(item.get("usage", {}).get("cached_tokens") is not None for item in successful),
    }
    result["status"] = "PASS" if result["capabilities"]["chat_completions"] else "PARTIAL"
    if output_path is not None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
