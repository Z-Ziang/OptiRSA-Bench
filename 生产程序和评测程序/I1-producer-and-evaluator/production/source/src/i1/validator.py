from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_TASK_BY_INTENT = {
    "SINGLE": "I1-S",
    "CONCURRENT": "I1-C",
    "DYNAMIC": "I1-D",
}

_FENCE_RE = re.compile(
    r"\A\s*```(?:json)?\s*\n(?P<body>.*?)\n?```\s*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _load_output_schema(intent_type: str) -> dict:
    task = _TASK_BY_INTENT.get(intent_type)
    if task is None:
        raise ValueError(f"unknown intent_type: {intent_type!r}")
    root = Path(__file__).resolve().parents[2]
    path = root / "contracts" / task / "output_schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_errors(schema: dict, obj: Any) -> list[str]:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(obj),
        key=lambda e: list(e.absolute_path),
    )
    rendered = []
    for error in errors:
        where = ".".join(str(part) for part in error.absolute_path)
        rendered.append(f"{where or '<root>'}: {error.message}")
    return rendered


def _strict_parse(raw_output: str) -> tuple[Any | None, str | None]:
    if not isinstance(raw_output, str) or not raw_output.strip():
        return None, "EMPTY_OUTPUT"
    try:
        return json.loads(raw_output.strip()), None
    except json.JSONDecodeError:
        if _FENCE_RE.fullmatch(raw_output):
            return None, "MARKDOWN_CODE_FENCE"
        return None, "INVALID_JSON_OR_EXTRA_TEXT"


def _semantic_parse(raw_output: str, strict_obj: Any | None) -> tuple[Any | None, str, str | None]:
    if strict_obj is not None:
        return strict_obj, "STRICT_JSON", None
    if not isinstance(raw_output, str):
        return None, "UNPARSED", "EMPTY_OUTPUT"
    match = _FENCE_RE.fullmatch(raw_output)
    if not match:
        return None, "UNPARSED", "INVALID_JSON_OR_EXTRA_TEXT"
    try:
        return json.loads(match.group("body").strip()), "MARKDOWN_FENCE_ONLY", None
    except json.JSONDecodeError:
        return None, "UNPARSED", "INVALID_JSON_INSIDE_MARKDOWN_FENCE"


def _safe_get(mapping: Any, key: str, default=None):
    return mapping.get(key, default) if isinstance(mapping, dict) else default


def _field_results(expected: dict, parsed: Any) -> dict[str, bool]:
    intent = expected.get("intent_type")
    if not isinstance(parsed, dict):
        if intent == "SINGLE":
            names = ["intent_type", "source_node_id", "destination_node_id", "required_slots"]
        elif intent == "CONCURRENT":
            names = [
                "intent_type",
                "request_count",
                "request_id",
                "source_node_id",
                "destination_node_id",
                "required_slots",
                "request_mapping",
            ]
        else:
            names = [
                "intent_type",
                "request_id",
                "source_node_id",
                "destination_node_id",
                "required_slots",
                "arrival_time",
                "holding_time",
            ]
        return {name: False for name in names}

    if intent == "SINGLE":
        return {
            "intent_type": parsed.get("intent_type") == expected.get("intent_type"),
            "source_node_id": parsed.get("source_node_id") == expected.get("source_node_id"),
            "destination_node_id": parsed.get("destination_node_id") == expected.get("destination_node_id"),
            "required_slots": parsed.get("required_slots") == expected.get("required_slots"),
        }

    if intent == "CONCURRENT":
        exp_requests = expected.get("requests", [])
        got_requests = parsed.get("requests", []) if isinstance(parsed.get("requests"), list) else []
        exp_by_id = {row.get("request_id"): row for row in exp_requests if isinstance(row, dict)}
        got_by_id = {row.get("request_id"): row for row in got_requests if isinstance(row, dict)}
        exp_ids = [row.get("request_id") for row in exp_requests if isinstance(row, dict)]
        got_ids = [row.get("request_id") for row in got_requests if isinstance(row, dict)]

        def all_bound(field: str) -> bool:
            return (
                set(got_by_id) == set(exp_by_id)
                and all(got_by_id[rid].get(field) == exp_by_id[rid].get(field) for rid in exp_by_id)
            )

        request_mapping = (
            len(got_requests) == len(exp_requests)
            and got_ids == exp_ids
            and all(
                isinstance(got_requests[i], dict)
                and {
                    key: got_requests[i].get(key)
                    for key in ("request_id", "source_node_id", "destination_node_id", "required_slots")
                }
                == {
                    key: exp_requests[i].get(key)
                    for key in ("request_id", "source_node_id", "destination_node_id", "required_slots")
                }
                for i in range(len(exp_requests))
            )
        )
        return {
            "intent_type": parsed.get("intent_type") == expected.get("intent_type"),
            "request_count": len(got_requests) == len(exp_requests),
            "request_id": got_ids == exp_ids,
            "source_node_id": all_bound("source_node_id"),
            "destination_node_id": all_bound("destination_node_id"),
            "required_slots": all_bound("required_slots"),
            "request_mapping": request_mapping,
        }

    exp_request = expected.get("request", {})
    got_request = parsed.get("request", {}) if isinstance(parsed.get("request"), dict) else {}
    return {
        "intent_type": parsed.get("intent_type") == expected.get("intent_type"),
        "request_id": got_request.get("request_id") == exp_request.get("request_id"),
        "source_node_id": got_request.get("source_node_id") == exp_request.get("source_node_id"),
        "destination_node_id": got_request.get("destination_node_id") == exp_request.get("destination_node_id"),
        "required_slots": got_request.get("required_slots") == exp_request.get("required_slots"),
        "arrival_time": got_request.get("arrival_time") == exp_request.get("arrival_time"),
        "holding_time": got_request.get("holding_time") == exp_request.get("holding_time"),
    }


def validate_i1_output(expected_answer: dict, raw_output: str, *, output_schema: dict | None = None) -> dict:
    """Score one I1 DUT output while separating format compliance from semantic accuracy.

    Official ``final_case_pass`` is strict: the raw response must itself be a legal JSON
    object, satisfy the frozen output schema, and exactly match the canonical answer.
    For diagnosis only, an output consisting solely of one Markdown JSON code fence is
    unwrapped so semantic intent accuracy can be measured without treating the fence as
    an intent-understanding error. No other repair or extraction is performed.
    """

    if not isinstance(expected_answer, dict):
        raise TypeError("expected_answer must be a dict")
    intent_type = expected_answer.get("intent_type")
    schema = output_schema or _load_output_schema(intent_type)

    strict_obj, format_error = _strict_parse(raw_output)
    semantic_obj, semantic_source, semantic_parse_error = _semantic_parse(raw_output, strict_obj)

    strict_schema_errors = _schema_errors(schema, strict_obj) if strict_obj is not None else []
    semantic_schema_errors = _schema_errors(schema, semantic_obj) if semantic_obj is not None else []
    strict_schema_valid = strict_obj is not None and not strict_schema_errors
    semantic_schema_valid = semantic_obj is not None and not semantic_schema_errors

    expected_objectives = expected_answer.get("objectives", [])
    got_objectives = _safe_get(semantic_obj, "objectives", [])
    got_objectives = got_objectives if isinstance(got_objectives, list) else []
    objective_set_accuracy = set(got_objectives) == set(expected_objectives)
    objective_order_accuracy = got_objectives == expected_objectives
    fields = _field_results(expected_answer, semantic_obj)

    semantic_exact_match = bool(
        semantic_schema_valid and _normalize(semantic_obj) == _normalize(expected_answer)
    )
    raw_format_valid = strict_obj is not None
    final_case_pass = bool(raw_format_valid and strict_schema_valid and semantic_exact_match)

    errors: list[str] = []
    if format_error:
        errors.append(f"format: {format_error}")
    if semantic_parse_error and semantic_obj is None:
        errors.append(f"semantic_parse: {semantic_parse_error}")
    errors.extend(f"strict_schema: {item}" for item in strict_schema_errors)
    errors.extend(f"semantic_schema: {item}" for item in semantic_schema_errors)
    if semantic_obj is not None and not semantic_exact_match:
        errors.append("semantic exact-match mismatch")

    return {
        "intent_type": intent_type,
        "raw_format_valid": raw_format_valid,
        "strict_json_parse_success": strict_obj is not None,
        "semantic_json_parse_success": semantic_obj is not None,
        "semantic_parse_source": semantic_source,
        "format_error_type": format_error,
        "strict_schema_valid": strict_schema_valid,
        "schema_valid": semantic_schema_valid,
        "semantic_exact_match": semantic_exact_match,
        "field_results": fields,
        "objective_set_accuracy": objective_set_accuracy,
        "objective_order_accuracy": objective_order_accuracy,
        "final_case_pass": final_case_pass,
        "errors": errors,
    }
