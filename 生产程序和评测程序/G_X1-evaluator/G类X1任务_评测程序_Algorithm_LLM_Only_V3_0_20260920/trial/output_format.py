"""Provider output-format controls and local structural validation.

This module is deliberately independent of the scientific truth and the
canonical validators.  It derives only the *shape* of a response from public
case metadata (task type, target representation, and metric).  Values such as
the expected path, label, or graph never enter a response-format schema.
"""

from __future__ import annotations

import json
from typing import Any


FORBIDDEN_PAYLOAD_KEYS = {"answer", "truth", "oracle", "reference", "private_truth"}
SUPPORTED_MODES = {"off", "json_object", "json_schema"}


class OutputFormatError(ValueError):
    """Raised when output-format configuration would be ambiguous or unsafe."""


def normalize_output_format_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        raw: dict[str, Any] = {}
    elif isinstance(config, dict):
        raw = dict(config)
    else:
        raise OutputFormatError("output_format must be a JSON object")
    mode = str(raw.get("mode", "off")).strip().lower()
    if mode not in SUPPORTED_MODES:
        raise OutputFormatError(
            f"output_format.mode must be one of {sorted(SUPPORTED_MODES)}, got {mode!r}"
        )
    strict = raw.get("strict", True)
    if not isinstance(strict, bool):
        raise OutputFormatError("output_format.strict must be a boolean")
    preflight = raw.get("preflight", True)
    if not isinstance(preflight, bool):
        raise OutputFormatError("output_format.preflight must be a boolean")
    return {
        "mode": mode,
        "strict": strict,
        "preflight": preflight,
    }


def _int_schema() -> dict[str, Any]:
    return {"type": "integer"}


def _int_array(*, min_items: int | None = None, max_items: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "array", "items": _int_schema()}
    if min_items is not None:
        out["minItems"] = int(min_items)
    if max_items is not None:
        out["maxItems"] = int(max_items)
    return out


def _g1_schema(root: dict[str, Any]) -> dict[str, Any]:
    nodes = list(root.get("nodes") or [])
    target = root.get("target_representation")
    if not target:
        conversion = str(root.get("conversion") or "")
        target = conversion.rsplit("_TO_", 1)[-1] if "_TO_" in conversion else None
    if target not in {"EDGE_LIST", "ADJACENCY_LIST", "ADJACENCY_MATRIX"}:
        raise OutputFormatError(f"cannot determine G1 target representation: {target!r}")

    base: dict[str, Any] = {
        "type": "object",
        "properties": {
            "representation_type": {"type": "string", "enum": [target]},
        },
        "required": ["representation_type"],
        "additionalProperties": False,
    }
    if target == "EDGE_LIST":
        base["properties"]["edge_list"] = {
            "type": "array",
            "items": {"type": "array", "items": _int_schema(), "minItems": 2, "maxItems": 2},
        }
        base["required"].append("edge_list")
    elif target == "ADJACENCY_LIST":
        base["properties"]["adjacency_list"] = {
            "type": "object",
            "properties": {
                str(node): {"type": "array", "items": _int_schema(), "uniqueItems": True}
                for node in nodes
            },
            "required": [str(node) for node in nodes],
            "additionalProperties": False,
        }
        base["required"].append("adjacency_list")
    else:
        base["properties"]["nodes"] = {
            "type": "array",
            "items": _int_schema(),
            "minItems": len(nodes),
            "maxItems": len(nodes),
        }
        base["properties"]["adjacency_matrix"] = {
            "type": "array",
            "minItems": len(nodes),
            "maxItems": len(nodes),
            "items": {
                "type": "array",
                "minItems": len(nodes),
                "maxItems": len(nodes),
                "items": {"type": "integer", "enum": [0, 1]},
            },
        }
        base["required"].extend(["nodes", "adjacency_matrix"])
    return base


def _path_properties(metric: str) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {
        "path_node_ids": _int_array(min_items=2),
        "path_link_ids": _int_array(min_items=1),
        "hop_count": {"type": "integer", "minimum": 1},
    }
    required = ["path_node_ids", "path_link_ids", "hop_count"]
    if metric == "TOTAL_LENGTH_KM":
        properties["total_length_km"] = {"type": "number"}
        required.append("total_length_km")
    return properties, required


def _g2_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "is_valid": {"type": "boolean"},
            "error_type": {
                "enum": [
                    "WRONG_DIRECTION",
                    "DISCONNECTED_PATH",
                    "NODE_LINK_MISMATCH",
                    "REPEATED_NODE",
                    None,
                ]
            },
        },
        "required": ["is_valid", "error_type"],
        "additionalProperties": False,
    }


def _g3_schema(root: dict[str, Any]) -> dict[str, Any]:
    metric = str(root.get("path_cost_metric") or "HOP_COUNT")
    path_props, path_required = _path_properties(metric)
    pair_props = {
        "pair_id": {"type": "string", "enum": ["pair_A", "pair_B"]},
        **path_props,
    }
    pair_schema = {
        "type": "object",
        "properties": pair_props,
        "required": ["pair_id", *path_required],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "shortest_paths": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": pair_schema,
            },
            "has_shared_directed_link": {"type": "boolean"},
            "shared_link_ids": {"type": "array", "items": _int_schema(), "uniqueItems": True},
        },
        "required": ["shortest_paths", "has_shared_directed_link", "shared_link_ids"],
        "additionalProperties": False,
    }


def _x1_schema(root: dict[str, Any]) -> dict[str, Any]:
    metric = str(root.get("path_cost_metric") or "HOP_COUNT")
    properties, required = _path_properties(metric)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def build_case_response_schema(root: dict[str, Any]) -> dict[str, Any]:
    task = str(root.get("task_type") or "")
    if task == "G1":
        return _g1_schema(root)
    if task == "G2":
        return _g2_schema()
    if task == "G3":
        return _g3_schema(root)
    if task == "X1":
        return _x1_schema(root)
    raise OutputFormatError(f"unsupported task_type for response schema: {task!r}")


def build_preflight_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }


def response_format_for_case(root: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any] | None:
    normalized = normalize_output_format_config(config)
    mode = normalized["mode"]
    if mode == "off":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "gx1_case_output",
            "strict": normalized["strict"],
            "schema": build_case_response_schema(root),
        },
    }


def response_format_for_preflight(config: dict[str, Any] | None) -> dict[str, Any] | None:
    normalized = normalize_output_format_config(config)
    mode = normalized["mode"]
    if mode == "off":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "gx1_preflight_output",
            "strict": normalized["strict"],
            "schema": build_preflight_response_schema(),
        },
    }


def apply_response_format(
    extra_body: dict[str, Any] | None,
    root: dict[str, Any] | None,
    config: dict[str, Any] | None,
    *,
    preflight: bool = False,
) -> dict[str, Any]:
    normalized = normalize_output_format_config(config)
    body = dict(extra_body or {})
    if normalized["mode"] == "off":
        return body
    if "response_format" in body:
        raise OutputFormatError(
            "response_format must be controlled by output_format config; remove it from extra_body"
        )
    response_format = (
        response_format_for_preflight(normalized)
        if preflight or root is None
        else response_format_for_case(root, normalized)
    )
    if response_format is not None:
        body["response_format"] = response_format
    return body


def prompt_for_output_format(config: dict[str, Any] | None, *, preflight: bool = False) -> str:
    mode = normalize_output_format_config(config)["mode"]
    if mode == "off":
        return "Reply with the word OK."
    if preflight:
        return "Return exactly one JSON object with the key ok set to true. Do not use Markdown fences or extra text."
    return "Return exactly one JSON object matching the requested output fields. Do not use Markdown fences or extra text."


def _json_schema_validate(value: Any, schema: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - packaging/environment error
        return [f"jsonschema dependency is required for local strict validation: {exc}"]
    validator = jsonschema.Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(value), key=lambda x: list(x.path))]


def validate_json_output(raw_output: str, root: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_output_format_config(config)
    try:
        value = json.loads(raw_output)
    except Exception as exc:
        return {
            "json_parse_valid": False,
            "schema_valid": False,
            "format_validation_reason": "INVALID_JSON",
            "format_validation_errors": [str(exc)],
        }
    errors = _json_schema_validate(value, build_case_response_schema(root))
    return {
        "json_parse_valid": True,
        "schema_valid": not errors,
        "format_validation_reason": "PASS" if not errors else "OUTPUT_SCHEMA",
        "format_validation_errors": errors,
        "format_mode": normalized["mode"],
    }


def validate_preflight_output(content: Any, config: dict[str, Any] | None) -> bool:
    normalized = normalize_output_format_config(config)
    if normalized["mode"] == "off":
        return bool(str(content or "").strip())
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    try:
        value = json.loads(content)
    except Exception:
        return False
    if _json_schema_validate(value, build_preflight_response_schema()):
        return False
    return value.get("ok") is True


def payload_forbidden_key_hits(payload: Any) -> list[dict[str, str]]:
    """Find forbidden field names in structured payloads and nested JSON content.

    Ordinary prose is not searched: prompts may discuss the evaluation
    protocol, but structured truth/reference fields must never be sent.
    Strings that decode to JSON (a common response-body representation) are
    recursively inspected.
    """

    hits: list[dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                if key_text.lower() in FORBIDDEN_PAYLOAD_KEYS:
                    hits.append({"path": f"{path}.{key_text}", "key": key_text})
                walk(child, f"{path}.{key_text}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    decoded = json.loads(stripped)
                except Exception:
                    return
                if isinstance(decoded, (dict, list)):
                    walk(decoded, f"{path}::<json>")

    walk(payload, "$" )
    return hits
