from __future__ import annotations

from random import Random
from typing import Any

from .topology import Topology


CONVERSIONS = (
    "EDGE_LIST_TO_ADJACENCY_LIST",
    "EDGE_LIST_TO_ADJACENCY_MATRIX",
    "ADJACENCY_LIST_TO_EDGE_LIST",
    "ADJACENCY_LIST_TO_ADJACENCY_MATRIX",
    "ADJACENCY_MATRIX_TO_EDGE_LIST",
    "ADJACENCY_MATRIX_TO_ADJACENCY_LIST",
)


def _edge_list(topology: Topology) -> list[list[int]]:
    return [[e.u, e.v] for e in sorted(topology.edges, key=lambda x: (x.u, x.v))]


def _adjacency_list(topology: Topology) -> dict[str, list[int]]:
    adj = {str(n): [] for n in topology.nodes}
    for e in topology.edges:
        adj[str(e.u)].append(e.v)
        adj[str(e.v)].append(e.u)
    for k in adj:
        adj[k].sort()
    return adj


def _adjacency_matrix(topology: Topology) -> list[list[int]]:
    n = len(topology.nodes)
    m = [[0] * n for _ in range(n)]
    for e in topology.edges:
        m[e.u][e.v] = 1
        m[e.v][e.u] = 1
    return m


def representation(topology: Topology, rep: str) -> Any:
    if rep == "EDGE_LIST":
        return _edge_list(topology)
    if rep == "ADJACENCY_LIST":
        return _adjacency_list(topology)
    if rep == "ADJACENCY_MATRIX":
        return _adjacency_matrix(topology)
    raise ValueError(rep)


def _answer(topology: Topology, target: str) -> dict[str, Any]:
    if target == "EDGE_LIST":
        return {"representation_type": "EDGE_LIST", "edge_list": _edge_list(topology)}
    if target == "ADJACENCY_LIST":
        return {"representation_type": "ADJACENCY_LIST", "adjacency_list": _adjacency_list(topology)}
    return {
        "representation_type": "ADJACENCY_MATRIX",
        "nodes": list(topology.nodes),
        "adjacency_matrix": _adjacency_matrix(topology),
    }


def generate_g1_case(topology: Topology, case_id: str, rng: Random, forced_conversion: str | None = None) -> dict[str, Any]:
    allowed = list(CONVERSIONS if len(topology.nodes) <= 100 else (
        "EDGE_LIST_TO_ADJACENCY_LIST", "ADJACENCY_LIST_TO_EDGE_LIST"
    ))
    conversion = forced_conversion or rng.choice(allowed)
    if conversion not in allowed:
        raise ValueError(f"当前拓扑规模不允许转换方向: {conversion}")
    source, target = conversion.split("_TO_")
    return {
        "schema_version": "GX1_ROOT_CASE_V2_0",
        "case_id": case_id,
        "task_type": "G1",
        "topology_id": topology.topology_id,
        "nodes": list(topology.nodes),
        "undirected_edges": _edge_list(topology),
        "conversion": conversion,
        "source_representation": source,
        "target_representation": target,
        "source_payload": representation(topology, source),
        "answer": _answer(topology, target),
    }
