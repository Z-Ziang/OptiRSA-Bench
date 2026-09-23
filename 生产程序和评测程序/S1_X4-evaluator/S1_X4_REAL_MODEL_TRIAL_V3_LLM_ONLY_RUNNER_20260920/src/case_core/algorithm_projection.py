"""Pure projection from an internal five-task algorithm case to public input.

The internal algorithm case is intentionally not the public Algorithm API.  It
contains provenance-oriented fields (and, for some tasks, a legacy shape).  A
projection is therefore built from an explicit allow-list instead of copying
the internal dictionary wholesale.  This module does not compute paths,
allocations, objectives, or reference results.
"""

from __future__ import annotations

from typing import Any


_TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
_REQUIRED_SLOTS = (2, 3, 5, 9)


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return int(value)


def _path(raw: dict[str, Any], *, candidate: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("path must be an object")
    required = ("path_node_ids", "path_link_ids")
    if any(key not in raw for key in required):
        raise ValueError("path must contain path_node_ids and path_link_ids")
    result: dict[str, Any] = {
        "path_node_ids": [_integer(x, "path_node_ids item") for x in raw["path_node_ids"]],
        "path_link_ids": [_integer(x, "path_link_ids item") for x in raw["path_link_ids"]],
    }
    if candidate:
        if "path_rank" not in raw:
            raise ValueError("candidate path must contain path_rank")
        result = {"path_rank": _integer(raw["path_rank"], "path_rank"), **result}
    return result


def _request_common(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("request must be an object")
    required = ("request_id", "source_node_id", "destination_node_id", "required_slots")
    if any(key not in raw for key in required):
        raise ValueError("request is missing a required public field")
    slots = _integer(raw["required_slots"], "required_slots")
    if slots not in _REQUIRED_SLOTS:
        raise ValueError("required_slots must be one of 2, 3, 5, 9")
    request_id = raw["request_id"]
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be a non-empty string")
    return {
        "request_id": request_id,
        "source_node_id": _integer(raw["source_node_id"], "source_node_id"),
        "destination_node_id": _integer(raw["destination_node_id"], "destination_node_id"),
        "required_slots": slots,
    }


def _requests(task_type: str, internal: dict[str, Any]) -> list[dict[str, Any]]:
    if task_type == "O1":
        raw_requests = internal.get("requests")
        if not isinstance(raw_requests, list):
            raise ValueError("O1 internal algorithm case must contain requests")
        result = []
        for raw in raw_requests:
            item = _request_common(raw)
            if "fixed_path" not in raw:
                raise ValueError("O1 request must contain fixed_path")
            item["fixed_path"] = _path(raw["fixed_path"], candidate=False)
            result.append(item)
        return result

    if task_type == "O2-S":
        raw_request = internal.get("request")
        raw_paths = internal.get("candidate_paths")
        if not isinstance(raw_request, dict) or not isinstance(raw_paths, list):
            raise ValueError("O2-S internal algorithm case must contain request and candidate_paths")
        item = _request_common(raw_request)
        item["candidate_paths"] = [_path(path, candidate=True) for path in raw_paths]
        return [item]

    if task_type == "X2":
        raw_request = internal.get("request")
        if not isinstance(raw_request, dict):
            raise ValueError("X2 internal algorithm case must contain request")
        return [_request_common(raw_request)]

    raw_requests = internal.get("requests")
    if not isinstance(raw_requests, list):
        raise ValueError(f"{task_type} internal algorithm case must contain requests")
    result = []
    for raw in raw_requests:
        item = _request_common(raw)
        if task_type == "O2-C":
            paths = raw.get("candidate_paths")
            if not isinstance(paths, list):
                raise ValueError("O2-C request must contain candidate_paths")
            item["candidate_paths"] = [_path(path, candidate=True) for path in paths]
        result.append(item)
    return result


def _spectrum_rows(internal: dict[str, Any]) -> list[dict[str, Any]]:
    rows = internal.get("link_spectrum_states")
    if rows is None:
        rows = internal.get("spectrum_states")
    if not isinstance(rows, list):
        raise ValueError("internal algorithm case must contain a spectrum state list")
    result = []
    for raw in rows:
        if not isinstance(raw, dict) or "link_id" not in raw or "occupied_ranges" not in raw:
            raise ValueError("spectrum state must contain link_id and occupied_ranges")
        ranges = []
        for value in raw["occupied_ranges"]:
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                raise ValueError("occupied range must be [start, end]")
            ranges.append([_integer(value[0], "occupied range start"), _integer(value[1], "occupied range end")])
        result.append({"link_id": _integer(raw["link_id"], "link_id"), "occupied_ranges": ranges})
    return result


def project_algorithm_input(task_type: str, internal_algorithm_case: dict[str, Any]) -> dict[str, Any]:
    """Return the deterministic, public Algorithm input for one five-task Case."""

    task = str(task_type)
    if task not in _TASKS:
        raise ValueError(f"Algorithm projection is only defined for {_TASKS}")
    if not isinstance(internal_algorithm_case, dict):
        raise ValueError("internal_algorithm_case must be an object")

    raw_nodes = internal_algorithm_case.get("nodes")
    raw_links = internal_algorithm_case.get("directed_links")
    if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
        raise ValueError("internal algorithm case must contain nodes and directed_links")
    nodes = [_integer(node, "node") for node in raw_nodes]
    links = []
    for raw in raw_links:
        if not isinstance(raw, dict):
            raise ValueError("directed link must be an object")
        links.append({
            "link_id": _integer(raw["link_id"], "link_id"),
            "source_node_id": _integer(raw["source_node_id"], "source_node_id"),
            "destination_node_id": _integer(raw["destination_node_id"], "destination_node_id"),
        })

    return {
        "task_type": task,
        "slot_count": _integer(internal_algorithm_case["slot_count"], "slot_count"),
        "nodes": nodes,
        "directed_links": links,
        "link_spectrum_states": _spectrum_rows(internal_algorithm_case),
        "requests": _requests(task, internal_algorithm_case),
    }
