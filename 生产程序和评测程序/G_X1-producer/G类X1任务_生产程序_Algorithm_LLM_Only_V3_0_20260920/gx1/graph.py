from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Any

from .topology import Topology, expand_directed_links


class GraphError(ValueError):
    pass


@dataclass(frozen=True)
class ShortestPathInfo:
    source_node_id: int
    destination_node_id: int
    metric: str
    path_node_ids: tuple[int, ...]
    path_link_ids: tuple[int, ...]
    hop_count: int
    cost: float
    multiplicity: int


def shortest_path_info(topology: Topology, source: int, destination: int, metric: str) -> ShortestPathInfo:
    if source == destination:
        raise GraphError("源节点和目的节点必须不同")
    if source not in topology.nodes or destination not in topology.nodes:
        raise GraphError("源宿节点必须属于拓扑")
    if metric not in {"HOP_COUNT", "TOTAL_LENGTH_KM"}:
        raise GraphError("不支持的最短路径指标")
    if metric == "TOTAL_LENGTH_KM" and not topology.has_complete_lengths:
        raise GraphError("TOTAL_LENGTH_KM 需要完整正 length_km")

    adj: dict[int, list[Any]] = {n: [] for n in topology.nodes}
    for link in expand_directed_links(topology):
        adj[link.source_node_id].append(link)
    for links in adj.values():
        links.sort(key=lambda x: x.link_id)

    inf = float("inf")
    dist = {n: inf for n in topology.nodes}
    count = {n: 0 for n in topology.nodes}
    best_link_path: dict[int, tuple[int, ...] | None] = {n: None for n in topology.nodes}
    best_node_path: dict[int, tuple[int, ...] | None] = {n: None for n in topology.nodes}
    dist[source] = 0.0
    count[source] = 1
    best_link_path[source] = ()
    best_node_path[source] = (source,)
    pq: list[tuple[float, int]] = [(0.0, source)]
    eps = 1e-9

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u] + eps:
            continue
        for link in adj[u]:
            w = 1.0 if metric == "HOP_COUNT" else float(link.length_km)
            v = link.destination_node_id
            nd = d + w
            cand_links = best_link_path[u] + (link.link_id,)  # type: ignore[operator]
            cand_nodes = best_node_path[u] + (v,)  # type: ignore[operator]
            if nd < dist[v] - eps:
                dist[v] = nd
                count[v] = count[u]
                best_link_path[v] = cand_links
                best_node_path[v] = cand_nodes
                heapq.heappush(pq, (nd, v))
            elif math.isclose(nd, dist[v], rel_tol=0.0, abs_tol=eps):
                count[v] += count[u]
                if best_link_path[v] is None or cand_links < best_link_path[v]:
                    best_link_path[v] = cand_links
                    best_node_path[v] = cand_nodes

    if not math.isfinite(dist[destination]) or best_link_path[destination] is None:
        raise GraphError("源宿节点之间不存在有向路径")
    links = best_link_path[destination]
    nodes = best_node_path[destination]
    assert nodes is not None
    cost = float(len(links)) if metric == "HOP_COUNT" else float(dist[destination])
    return ShortestPathInfo(
        source, destination, metric, nodes, links, len(links), cost, int(count[destination])
    )


def enumerate_optimal_paths(
    topology: Topology,
    source: int,
    destination: int,
    metric: str,
    *,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Enumerate a deterministic, bounded prefix of globally optimal paths.

    This is private production evidence for X1 MULTIPLE cases.  It deliberately
    leaves ``shortest_path_info`` and the canonical answer untouched.  Positive
    edge weights make shortest paths simple, while reverse distance pruning
    prevents exploring non-optimal branches on the larger Pilot topologies.
    """
    if int(limit) < 1:
        return []
    info = shortest_path_info(topology, source, destination, metric)
    links = list(expand_directed_links(topology))
    adjacency: dict[int, list[Any]] = {n: [] for n in topology.nodes}
    reverse: dict[int, list[tuple[int, float]]] = {n: [] for n in topology.nodes}
    for link in links:
        weight = 1.0 if metric == "HOP_COUNT" else float(link.length_km)
        adjacency[link.source_node_id].append(link)
        reverse[link.destination_node_id].append((link.source_node_id, weight))
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda x: x.link_id)

    inf = float("inf")
    distance_to_destination = {n: inf for n in topology.nodes}
    distance_to_destination[destination] = 0.0
    pq: list[tuple[float, int]] = [(0.0, destination)]
    while pq:
        distance, node = heapq.heappop(pq)
        if distance > distance_to_destination[node] + 1e-9:
            continue
        for predecessor, weight in reverse[node]:
            candidate = distance + weight
            if candidate < distance_to_destination[predecessor] - 1e-9:
                distance_to_destination[predecessor] = candidate
                heapq.heappush(pq, (candidate, predecessor))

    target_cost = float(info.cost)
    paths: list[dict[str, Any]] = []
    eps = 1e-9

    def visit(node: int, path_nodes: list[int], path_links: list[int], cost: float) -> None:
        if len(paths) >= int(limit):
            return
        if node == destination:
            if math.isclose(cost, target_cost, rel_tol=0.0, abs_tol=eps):
                paths.append({
                    "path_node_ids": list(path_nodes),
                    "path_link_ids": list(path_links),
                    "hop_count": len(path_links),
                    "cost": float(cost),
                })
            return
        for link in adjacency[node]:
            next_node = link.destination_node_id
            if next_node in path_nodes:
                continue
            weight = 1.0 if metric == "HOP_COUNT" else float(link.length_km)
            next_cost = cost + weight
            tail_cost = distance_to_destination[next_node]
            if not math.isfinite(tail_cost):
                continue
            if next_cost > target_cost + eps:
                continue
            if not math.isclose(next_cost + tail_cost, target_cost, rel_tol=0.0, abs_tol=eps):
                continue
            visit(next_node, path_nodes + [next_node], path_links + [link.link_id], next_cost)

    visit(source, [source], [], 0.0)
    return paths
