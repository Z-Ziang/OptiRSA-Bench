from __future__ import annotations

import heapq
import math
from typing import Any

from .common import public_length_km, strict_json_loads


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    return {"valid": False, "reason": reason, **extra}


def _ok(**extra: Any) -> dict[str, Any]:
    return {"valid": True, "reason": "PASS", **extra}


def _normalize_edge_list(nodes: list[int], edge_list: Any) -> tuple[set[int], set[tuple[int, int]]]:
    if not isinstance(edge_list, list):
        raise ValueError("edge_list")
    edges = set()
    for e in edge_list:
        if not isinstance(e, list) or len(e) != 2 or not all(isinstance(x, int) for x in e):
            raise ValueError("edge_list row")
        a, b = e
        if a == b: raise ValueError("self loop")
        uv = tuple(sorted((a, b)))
        if uv in edges: raise ValueError("duplicate edge")
        edges.add(uv)
    return set(nodes), edges


def _normalize_g1_output(root: dict[str, Any], obj: Any) -> tuple[set[int], set[tuple[int, int]]]:
    if not isinstance(obj, dict) or obj.get("representation_type") != root["target_representation"]:
        raise ValueError("representation_type")
    nodes = list(root["nodes"])
    target = root["target_representation"]
    if target == "EDGE_LIST":
        return _normalize_edge_list(nodes, obj.get("edge_list"))
    if target == "ADJACENCY_LIST":
        adj = obj.get("adjacency_list")
        if not isinstance(adj, dict) or set(adj.keys()) != {str(n) for n in nodes}:
            raise ValueError("adjacency keys")
        edges = set()
        for u in nodes:
            vals = adj[str(u)]
            if not isinstance(vals, list) or len(vals) != len(set(vals)) or u in vals:
                raise ValueError("adjacency values")
            for v in vals:
                if v not in nodes or u not in adj.get(str(v), []):
                    raise ValueError("asymmetric adjacency")
                edges.add(tuple(sorted((u, v))))
        return set(nodes), edges
    out_nodes = obj.get("nodes")
    matrix = obj.get("adjacency_matrix")
    if out_nodes != nodes or not isinstance(matrix, list) or len(matrix) != len(nodes):
        raise ValueError("matrix nodes")
    edges = set()
    n = len(nodes)
    for i, row in enumerate(matrix):
        if not isinstance(row, list) or len(row) != n:
            raise ValueError("matrix shape")
        for j, val in enumerate(row):
            if val not in (0, 1): raise ValueError("matrix value")
            if i == j and val != 0: raise ValueError("matrix diagonal")
            if matrix[j][i] != val: raise ValueError("matrix asymmetric")
            if val and i < j: edges.add((nodes[i], nodes[j]))
    return set(nodes), edges


def _validate_path(root: dict[str, Any], nodes: Any, links: Any, source: int, dest: int, metric: str) -> tuple[bool, str, float]:
    if not isinstance(nodes, list) or not isinstance(links, list) or len(nodes) != len(links) + 1:
        return False, "PATH_SHAPE", 0.0
    if not nodes or nodes[0] != source or nodes[-1] != dest:
        return False, "ENDPOINT_MISMATCH", 0.0
    if len(set(nodes)) != len(nodes):
        return False, "NOT_SIMPLE", 0.0
    link_map = {int(x["link_id"]): x for x in root["directed_links"]}
    total = 0.0
    for i, lid in enumerate(links):
        if lid not in link_map:
            return False, "UNKNOWN_LINK", 0.0
        rec = link_map[lid]
        if rec["source_node_id"] != nodes[i] or rec["destination_node_id"] != nodes[i+1]:
            return False, "ILLEGAL_DIRECTED_STEP", 0.0
        total += 1.0 if metric == "HOP_COUNT" else public_length_km(rec["length_km"])
    return True, "PASS", total


def _shortest_cost_from_public_root(root: dict[str, Any], source: int, dest: int, metric: str) -> float:
    """Compute the optimum from the same directed-link values visible to the DUT."""
    adjacency: dict[int, list[tuple[int, float]]] = {int(node): [] for node in root.get("nodes", [])}
    for rec in root.get("directed_links", []):
        u = int(rec["source_node_id"])
        v = int(rec["destination_node_id"])
        weight = 1.0 if metric == "HOP_COUNT" else public_length_km(rec["length_km"])
        adjacency.setdefault(u, []).append((v, weight))
    dist = {node: float("inf") for node in adjacency}
    dist[int(source)] = 0.0
    queue: list[tuple[float, int]] = [(0.0, int(source))]
    eps = 1e-9
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > dist[node] + eps:
            continue
        if node == int(dest):
            return float(cost)
        for nxt, weight in adjacency.get(node, []):
            candidate = cost + weight
            if candidate < dist.get(nxt, float("inf")) - eps:
                dist[nxt] = candidate
                heapq.heappush(queue, (candidate, nxt))
    return float("inf")


def validate_dut_output(root: dict[str, Any], raw_output: str) -> dict[str, Any]:
    try:
        obj = strict_json_loads(raw_output)
    except Exception as e:
        return _fail("INVALID_JSON", detail=str(e))
    task = root["task_type"]
    try:
        if task == "G1":
            actual = _normalize_g1_output(root, obj)
            expected = _normalize_g1_output(root, root["answer"])
            return _ok() if actual == expected else _fail("WRONG_GRAPH")
        if task == "G2":
            if not isinstance(obj, dict) or set(obj.keys()) != {"is_valid", "error_type"}:
                return _fail("OUTPUT_SCHEMA")
            expected = root["answer"]
            return _ok() if obj == expected else _fail("WRONG_G2_LABEL", expected=expected)
        if task == "X1":
            return _validate_x1(root, obj)
        if task == "G3":
            return _validate_g3(root, obj)
        return _fail("UNKNOWN_TASK")
    except Exception as e:
        return _fail("OUTPUT_SCHEMA", detail=str(e))


def _validate_x1(root: dict[str, Any], obj: Any) -> dict[str, Any]:
    metric = root["path_cost_metric"]
    required = {"path_node_ids", "path_link_ids", "hop_count"} | ({"total_length_km"} if metric == "TOTAL_LENGTH_KM" else set())
    if not isinstance(obj, dict) or set(obj.keys()) != required:
        return _fail("OUTPUT_SCHEMA")
    ok, reason, cost = _validate_path(root, obj["path_node_ids"], obj["path_link_ids"], root["source_node_id"], root["destination_node_id"], metric)
    if not ok: return _fail(reason)
    if obj["hop_count"] != len(obj["path_link_ids"]): return _fail("WRONG_HOP_COUNT")
    if metric == "TOTAL_LENGTH_KM" and not math.isclose(float(obj["total_length_km"]), cost, abs_tol=1e-9):
        return _fail("WRONG_TOTAL_LENGTH")
    public_optimal_cost = _shortest_cost_from_public_root(
        root, root["source_node_id"], root["destination_node_id"], metric
    )
    if not math.isclose(public_optimal_cost, cost, rel_tol=0.0, abs_tol=1e-9):
        return _fail("NOT_GLOBAL_OPTIMUM", optimal_cost=public_optimal_cost, submitted_cost=cost)
    return _ok(submitted_cost=cost)


def _validate_g3(root: dict[str, Any], obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj.keys()) != {"shortest_paths", "has_shared_directed_link", "shared_link_ids"}:
        return _fail("OUTPUT_SCHEMA")
    paths = obj["shortest_paths"]
    if not isinstance(paths, list) or len(paths) != 2:
        return _fail("OUTPUT_SCHEMA")
    by_id = {p.get("pair_id"): p for p in paths if isinstance(p, dict)}
    if set(by_id) != {"pair_A", "pair_B"}:
        return _fail("PAIR_IDS")
    pairs = {x["pair_id"]: x for x in root["pairs"]}
    metric = root["path_cost_metric"]
    actual_link_sets = []
    for pid in ["pair_A", "pair_B"]:
        p = by_id[pid]
        required = {"pair_id", "path_node_ids", "path_link_ids", "hop_count"} | ({"total_length_km"} if metric == "TOTAL_LENGTH_KM" else set())
        if set(p.keys()) != required:
            return _fail("OUTPUT_SCHEMA")
        pair = pairs[pid]
        ok, reason, cost = _validate_path(root, p["path_node_ids"], p["path_link_ids"], pair["source_node_id"], pair["destination_node_id"], metric)
        if not ok: return _fail(reason, pair_id=pid)
        if p["hop_count"] != len(p["path_link_ids"]): return _fail("WRONG_HOP_COUNT", pair_id=pid)
        if metric == "TOTAL_LENGTH_KM" and not math.isclose(float(p["total_length_km"]), cost, abs_tol=1e-9):
            return _fail("WRONG_TOTAL_LENGTH", pair_id=pid)
        public_optimal_cost = _shortest_cost_from_public_root(
            root, pair["source_node_id"], pair["destination_node_id"], metric
        )
        if not math.isclose(public_optimal_cost, cost, rel_tol=0.0, abs_tol=1e-9):
            return _fail("NOT_SHORTEST", pair_id=pid, optimal_cost=public_optimal_cost, submitted_cost=cost)
        actual_link_sets.append(set(p["path_link_ids"]))
    inter = actual_link_sets[0] & actual_link_sets[1]
    shared_ids = obj["shared_link_ids"]
    if not isinstance(shared_ids, list) or len(shared_ids) != len(set(shared_ids)) or set(shared_ids) != inter:
        return _fail("WRONG_SHARED_LINK_IDS", expected=sorted(inter))
    if obj["has_shared_directed_link"] is not bool(inter):
        return _fail("WRONG_SHARED_BOOLEAN")
    return _ok()
