from __future__ import annotations

from typing import Any


_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


def _s1_accept() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["decision", "path_rank", "slot_start"],
        "properties": {
            "decision": {"const": "ACCEPT"},
            "path_rank": {"type": "integer", "minimum": 1},
            "slot_start": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }


def _s1_reject() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["decision", "path_rank", "slot_start"],
        "properties": {
            "decision": {"const": "REJECT"},
            "path_rank": {"type": "null"},
            "slot_start": {"type": "null"},
        },
        "additionalProperties": False,
    }


def _x4_accept() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["decision", "path_node_ids", "path_link_ids", "slot_start"],
        "properties": {
            "decision": {"const": "ACCEPT"},
            "path_node_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "path_link_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "slot_start": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }


def _x4_reject() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["decision", "path_node_ids", "path_link_ids", "slot_start"],
        "properties": {
            "decision": {"const": "REJECT"},
            "path_node_ids": {"const": []},
            "path_link_ids": {"const": []},
            "slot_start": {"type": "null"},
        },
        "additionalProperties": False,
    }


def action_schema(task: str) -> dict[str, Any]:
    if task == "S1":
        branches = [_s1_accept(), _s1_reject()]
    elif task == "X4":
        branches = [_x4_accept(), _x4_reject()]
    else:
        raise ValueError(f"unsupported task: {task}")
    return {"$schema": _SCHEMA_URI, "oneOf": branches}
