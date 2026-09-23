from __future__ import annotations

from random import Random
from typing import Any

from .common import GenerationError
from .graph import shortest_path_info
from .topology import Topology, expand_directed_links


LABELS = ("VALID", "WRONG_DIRECTION", "DISCONNECTED_PATH", "NODE_LINK_MISMATCH", "REPEATED_NODE")


def classify_g2(root: dict[str, Any]) -> str:
    links = {int(x["link_id"]): x for x in root["directed_links"]}
    nodes = list(root["candidate_path"]["path_node_ids"])
    link_ids = list(root["candidate_path"]["path_link_ids"])
    # Production preconditions guarantee known IDs and len(nodes)=len(links)+1.
    selected = [links[int(lid)] for lid in link_ids]
    for i, link in enumerate(selected):
        if link["source_node_id"] == nodes[i + 1] and link["destination_node_id"] == nodes[i]:
            return "WRONG_DIRECTION"
    for i in range(len(selected) - 1):
        if selected[i]["destination_node_id"] != selected[i + 1]["source_node_id"]:
            return "DISCONNECTED_PATH"
    for i, link in enumerate(selected):
        if link["source_node_id"] != nodes[i] or link["destination_node_id"] != nodes[i + 1]:
            return "NODE_LINK_MISMATCH"
    if len(set(nodes)) != len(nodes):
        return "REPEATED_NODE"
    return "VALID"


def _valid_base(topology: Topology, rng: Random, min_hops: int, max_hops: int, need_internal: bool = False, max_sampling_attempts: int = 256) -> tuple[list[int], list[int]]:
    min_required = max(min_hops, 2 if need_internal else min_hops)
    seen: set[tuple[int, int]] = set()
    n = len(topology.nodes)
    attempt_limit = max(1, int(max_sampling_attempts))
    # Bounded randomized sampling keeps production scalable on 100-500 node topologies.
    for _ in range(attempt_limit):
        s = rng.randrange(n)
        d = rng.randrange(n - 1)
        if d >= s:
            d += 1
        pair = (s, d)
        if pair in seen:
            continue
        seen.add(pair)
        info = shortest_path_info(topology, s, d, "HOP_COUNT")
        if min_required <= info.hop_count <= max_hops:
            return list(info.path_node_ids), list(info.path_link_ids)
    # Small-topology deterministic fallback gives strong completeness without harming large-scale cost.
    if n <= 30:
        pairs = [(s, d) for s in topology.nodes for d in topology.nodes if s != d and (s, d) not in seen]
        rng.shuffle(pairs)
        for s, d in pairs:
            info = shortest_path_info(topology, s, d, "HOP_COUNT")
            if min_required <= info.hop_count <= max_hops:
                return list(info.path_node_ids), list(info.path_link_ids)
    raise GenerationError("找不到满足 G2 跳数范围的基础合法路径")


def _root_template(topology: Topology, case_id: str, nodes: list[int], link_ids: list[int]) -> dict[str, Any]:
    return {
        "schema_version": "GX1_ROOT_CASE_V2_0",
        "case_id": case_id,
        "task_type": "G2",
        "topology_id": topology.topology_id,
        "nodes": list(topology.nodes),
        "directed_links": [x.public_dict(include_length=False) for x in expand_directed_links(topology)],
        "source_node_id": nodes[0],
        "destination_node_id": nodes[-1],
        "candidate_path": {"path_node_ids": nodes, "path_link_ids": link_ids},
    }


def generate_g2_case(topology: Topology, case_id: str, rng: Random, forced_label: str | None = None, min_hops: int = 2, max_hops: int = 8, max_sampling_attempts: int = 256) -> dict[str, Any]:
    label = forced_label or rng.choice(LABELS)
    if label not in LABELS:
        raise GenerationError(f"未知 G2 标签: {label}")
    need_internal = label == "NODE_LINK_MISMATCH"
    # REPEATED_NODE inserts a two-link out-and-back detour into a valid base path.
    # min_hops/max_hops describe the final candidate path, so compensate the base range.
    if label == "REPEATED_NODE":
        base_min_hops = max(1, min_hops - 2)
        base_max_hops = max_hops - 2
        if base_max_hops < 1:
            raise GenerationError("REPEATED_NODE 候选路径至少需要 3 跳")
    else:
        base_min_hops, base_max_hops = min_hops, max_hops
    base_nodes, base_links = _valid_base(topology, rng, base_min_hops, base_max_hops, need_internal=need_internal, max_sampling_attempts=max_sampling_attempts)
    nodes, link_ids = list(base_nodes), list(base_links)
    all_links = [x.public_dict(include_length=False) for x in expand_directed_links(topology)]

    if label == "WRONG_DIRECTION":
        indexes = list(range(len(link_ids)))
        rng.shuffle(indexes)
        done = False
        for i in indexes:
            rev = link_ids[i] ^ 1
            trial = list(link_ids); trial[i] = rev
            root = _root_template(topology, case_id, list(nodes), trial)
            if classify_g2(root) == label:
                link_ids = trial; done = True; break
        if not done:
            raise GenerationError("无法构造 WRONG_DIRECTION")
    elif label == "DISCONNECTED_PATH":
        possibilities: list[tuple[list[int], list[int]]] = []
        for i in range(len(link_ids)):
            for rec in all_links:
                trial = list(link_ids); trial[i] = rec["link_id"]
                root = _root_template(topology, case_id, list(nodes), trial)
                if classify_g2(root) == label:
                    possibilities.append((list(nodes), trial))
        if not possibilities:
            raise GenerationError("无法构造 DISCONNECTED_PATH")
        nodes, link_ids = rng.choice(possibilities)
    elif label == "NODE_LINK_MISMATCH":
        possibilities = []
        for i in range(1, len(nodes) - 1):
            for replacement in topology.nodes:
                if replacement == nodes[i] or replacement in {nodes[0], nodes[-1]}:
                    continue
                trial_nodes = list(nodes); trial_nodes[i] = replacement
                root = _root_template(topology, case_id, trial_nodes, list(link_ids))
                if classify_g2(root) == label:
                    possibilities.append((trial_nodes, list(link_ids)))
        if not possibilities:
            raise GenerationError("无法构造 NODE_LINK_MISMATCH")
        nodes, link_ids = rng.choice(possibilities)
    elif label == "REPEATED_NODE":
        by_src: dict[int, list[dict[str, int]]] = {}
        for rec in all_links:
            by_src.setdefault(rec["source_node_id"], []).append(rec)
        possibilities = []
        for i, u in enumerate(nodes[:-1]):
            for fwd in by_src.get(u, []):
                v = fwd["destination_node_id"]
                revs = [r for r in by_src.get(v, []) if r["destination_node_id"] == u]
                for rev in revs:
                    trial_nodes = nodes[:i+1] + [v, u] + nodes[i+1:]
                    trial_links = link_ids[:i] + [fwd["link_id"], rev["link_id"]] + link_ids[i:]
                    root = _root_template(topology, case_id, trial_nodes, trial_links)
                    if classify_g2(root) == label:
                        possibilities.append((trial_nodes, trial_links))
        if not possibilities:
            raise GenerationError("无法构造 REPEATED_NODE")
        nodes, link_ids = rng.choice(possibilities)

    root = _root_template(topology, case_id, nodes, link_ids)
    final_hops = len(link_ids)
    if not (min_hops <= final_hops <= max_hops):
        raise GenerationError(f"G2 最终候选路径跳数 {final_hops} 不在配置范围 [{min_hops},{max_hops}]")
    oracle = classify_g2(root)
    if oracle != label:
        raise GenerationError(f"G2 独立 FIRST_MATCH 复核失败: intended={label}, oracle={oracle}")
    root["oracle_label"] = oracle
    root["answer"] = {"is_valid": oracle == "VALID", "error_type": None if oracle == "VALID" else oracle}
    return root
