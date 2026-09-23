from __future__ import annotations

from random import Random
from typing import Any

from .common import GenerationError
from .graph import enumerate_optimal_paths, shortest_path_info
from .topology import Topology, expand_directed_links


def generate_x1_case(topology: Topology, case_id: str, rng: Random, forced_metric: str | None = None, forced_pair: tuple[int, int] | None = None, forced_multiplicity: str | None = None, min_hops: int = 1, max_hops: int = 20, max_sampling_attempts: int = 256) -> dict[str, Any]:
    metric = forced_metric or rng.choice(["HOP_COUNT", "TOTAL_LENGTH_KM"] if topology.has_complete_lengths else ["HOP_COUNT"])
    if metric == "TOTAL_LENGTH_KM" and not topology.has_complete_lengths:
        raise GenerationError("当前拓扑缺少完整 length_km，不能生成 TOTAL_LENGTH_KM X1 Case")
    if forced_multiplicity not in {None, "UNIQUE", "MULTIPLE"}:
        raise GenerationError("forced_multiplicity 只能为 UNIQUE、MULTIPLE 或 None")

    def multiplicity_ok(x) -> bool:
        if forced_multiplicity == "UNIQUE":
            return x.multiplicity == 1
        if forced_multiplicity == "MULTIPLE":
            return x.multiplicity > 1
        return True

    if forced_pair is not None:
        info = shortest_path_info(topology, int(forced_pair[0]), int(forced_pair[1]), metric)
        if not (min_hops <= info.hop_count <= max_hops):
            raise GenerationError("forced_pair 不满足 X1 跳数范围")
        if not multiplicity_ok(info):
            raise GenerationError("forced_pair 不满足 X1 最短路径多重性要求")
    else:
        n = len(topology.nodes)
        seen: set[tuple[int, int]] = set()
        info = None
        for _ in range(max(1, int(max_sampling_attempts))):
            s = rng.randrange(n)
            d = rng.randrange(n - 1)
            if d >= s:
                d += 1
            if (s, d) in seen:
                continue
            seen.add((s, d))
            x = shortest_path_info(topology, s, d, metric)
            if min_hops <= x.hop_count <= max_hops and multiplicity_ok(x):
                info = x
                break
        if info is None and n <= 30:
            pairs = [(s, d) for s in topology.nodes for d in topology.nodes if s != d and (s, d) not in seen]
            rng.shuffle(pairs)
            for s, d in pairs:
                x = shortest_path_info(topology, s, d, metric)
                if min_hops <= x.hop_count <= max_hops and multiplicity_ok(x):
                    info = x
                    break
        if info is None:
            suffix = "" if forced_multiplicity is None else f"且 multiplicity={forced_multiplicity}"
            raise GenerationError(f"找不到满足 X1 跳数范围{suffix}的源宿对")
    answer: dict[str, Any] = {
        "path_node_ids": list(info.path_node_ids),
        "path_link_ids": list(info.path_link_ids),
        "hop_count": info.hop_count,
    }
    if metric == "TOTAL_LENGTH_KM":
        answer["total_length_km"] = float(info.cost)
    root = {
        "schema_version": "GX1_ROOT_CASE_V2_0",
        "case_id": case_id,
        "task_type": "X1",
        "topology_id": topology.topology_id,
        "nodes": list(topology.nodes),
        "directed_links": [x.public_dict(include_length=(metric == "TOTAL_LENGTH_KM")) for x in expand_directed_links(topology)],
        "source_node_id": info.source_node_id,
        "destination_node_id": info.destination_node_id,
        "path_cost_metric": metric,
        "shortest_path_multiplicity": info.multiplicity,
        "optimal_cost": info.cost,
        "answer": answer,
    }
    if info.multiplicity > 1:
        optimal_paths = enumerate_optimal_paths(topology, info.source_node_id, info.destination_node_id, metric, limit=2)
        if len(optimal_paths) < 2:
            raise GenerationError("X1 MULTIPLE Case 未能生成至少两条独立最优路径证据")
        root["oracle_evidence"] = {
            "path_cost_metric": metric,
            "optimal_cost": float(info.cost),
            "shortest_path_multiplicity": int(info.multiplicity),
            "optimal_paths": optimal_paths,
        }
    return root
