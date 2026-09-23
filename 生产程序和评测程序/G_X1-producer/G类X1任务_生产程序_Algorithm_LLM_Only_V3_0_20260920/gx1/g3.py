from __future__ import annotations

from random import Random
from typing import Any

from .common import GenerationError
from .graph import shortest_path_info
from .topology import Topology, expand_directed_links


def _path_record(pair_id: str, info, metric: str) -> dict[str, Any]:
    d: dict[str, Any] = {
        "pair_id": pair_id,
        "path_node_ids": list(info.path_node_ids),
        "path_link_ids": list(info.path_link_ids),
        "hop_count": info.hop_count,
    }
    if metric == "TOTAL_LENGTH_KM":
        d["total_length_km"] = float(info.cost)
    return d


def generate_g3_case(topology: Topology, case_id: str, rng: Random, forced_metric: str | None = None, forced_shared: bool | None = None, min_hops: int = 1, max_hops: int = 20, max_sampling_attempts: int = 512) -> dict[str, Any]:
    metric = forced_metric or rng.choice(["HOP_COUNT", "TOTAL_LENGTH_KM"] if topology.has_complete_lengths else ["HOP_COUNT"])
    if metric == "TOTAL_LENGTH_KM" and not topology.has_complete_lengths:
        raise GenerationError("当前拓扑缺少完整 length_km，不能生成 TOTAL_LENGTH_KM G3 Case")

    n = len(topology.nodes)
    candidates = []
    seen: set[tuple[int, int]] = set()
    matching_combos = []

    def consider(info):
        nonlocal matching_combos
        for prev in candidates:
            shared = sorted(set(prev.path_link_ids) & set(info.path_link_ids))
            if forced_shared is None or bool(shared) == bool(forced_shared):
                matching_combos.append((prev, info, shared))
        candidates.append(info)

    for _ in range(max(2, int(max_sampling_attempts))):
        s = rng.randrange(n)
        d = rng.randrange(n - 1)
        if d >= s:
            d += 1
        if (s, d) in seen:
            continue
        seen.add((s, d))
        info = shortest_path_info(topology, s, d, metric)
        if info.multiplicity == 1 and min_hops <= info.hop_count <= max_hops:
            consider(info)
            if len(matching_combos) >= 16:
                break

    if not matching_combos and n <= 30:
        pairs = [(s, d) for s in topology.nodes for d in topology.nodes if s != d and (s, d) not in seen]
        rng.shuffle(pairs)
        for s, d in pairs:
            info = shortest_path_info(topology, s, d, metric)
            if info.multiplicity == 1 and min_hops <= info.hop_count <= max_hops:
                consider(info)
                if matching_combos:
                    break

    if not matching_combos:
        raise GenerationError(f"无法生成 shared={forced_shared} 且两对源宿均为唯一最短路径的 G3 Case")
    a, b, shared = rng.choice(matching_combos)
    answer = {
        "shortest_paths": [_path_record("pair_A", a, metric), _path_record("pair_B", b, metric)],
        "has_shared_directed_link": bool(shared),
        "shared_link_ids": shared,
    }
    return {
        "schema_version": "GX1_ROOT_CASE_V2_0",
        "case_id": case_id,
        "task_type": "G3",
        "topology_id": topology.topology_id,
        "nodes": list(topology.nodes),
        "directed_links": [x.public_dict(include_length=(metric == "TOTAL_LENGTH_KM")) for x in expand_directed_links(topology)],
        "path_cost_metric": metric,
        "pairs": [
            {"pair_id": "pair_A", "source_node_id": a.source_node_id, "destination_node_id": a.destination_node_id},
            {"pair_id": "pair_B", "source_node_id": b.source_node_id, "destination_node_id": b.destination_node_id},
        ],
        "oracle_shortest_paths": [
            {**_path_record("pair_A", a, metric), "multiplicity": a.multiplicity, "optimal_cost": a.cost},
            {**_path_record("pair_B", b, metric), "multiplicity": b.multiplicity, "optimal_cost": b.cost},
        ],
        "answer": answer,
    }
