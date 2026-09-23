from __future__ import annotations
from copy import deepcopy

_ALLOWED_OBJECTIVES = {
    "MIN-HOP-COUNT", "MIN-FRAGMENTATION", "MIN-TOTAL-SLOT-USAGE",
    "MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION",
}


def _validate_objectives(objectives: list[str]) -> list[str]:
    if not isinstance(objectives, list) or not objectives:
        raise ValueError("objectives must be a non-empty ordered list")
    if len(set(objectives)) != len(objectives):
        raise ValueError("objectives must not contain duplicates")
    bad = [x for x in objectives if x not in _ALLOWED_OBJECTIVES]
    if bad:
        raise ValueError(f"unknown objectives: {bad}")
    return list(objectives)


def _base_request(req: dict) -> dict:
    out = {
        "request_id": str(req["request_id"]),
        "source_node_id": int(req["source_node_id"]),
        "destination_node_id": int(req["destination_node_id"]),
        "required_slots": int(req["required_slots"]),
    }
    if out["source_node_id"] == out["destination_node_id"]:
        raise ValueError("source_node_id must differ from destination_node_id")
    if out["required_slots"] <= 0:
        raise ValueError("required_slots must be positive")
    return out


def build_single_answer(request: dict, objectives: list[str]) -> dict:
    r = _base_request(request)
    return {
        "intent_type": "SINGLE",
        "source_node_id": r["source_node_id"],
        "destination_node_id": r["destination_node_id"],
        "required_slots": r["required_slots"],
        "objectives": _validate_objectives(objectives),
    }


def build_concurrent_answer(requests: list[dict], objectives: list[str]) -> dict:
    if not requests:
        raise ValueError("requests must be non-empty")
    rows = [_base_request(x) for x in requests]
    ids = [x["request_id"] for x in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("request_id must be unique within a concurrent case")
    return {"intent_type": "CONCURRENT", "requests": rows, "objectives": _validate_objectives(objectives)}


def build_dynamic_answer(request: dict, objectives: list[str]) -> dict:
    r = _base_request(request)
    r["arrival_time"] = float(request["arrival_time"])
    r["holding_time"] = float(request["holding_time"])
    if r["arrival_time"] < 0 or r["holding_time"] <= 0:
        raise ValueError("dynamic time fields out of range")
    return {"intent_type": "DYNAMIC", "request": r, "objectives": _validate_objectives(objectives)}
