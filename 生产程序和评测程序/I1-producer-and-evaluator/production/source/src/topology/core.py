from __future__ import annotations

from itertools import combinations
from typing import Any

import networkx as nx
import numpy as np


def build_topology(raw: dict[str, Any], topology_id: str, source_type: str) -> tuple[dict, dict, dict]:
    node_ids = raw.get("node_ids")
    if node_ids is None:
        node_ids = list(range(int(raw["node_count"])))
    if node_ids != list(range(len(node_ids))) or len(set(node_ids)) != len(node_ids):
        raise ValueError("node ids must be unique, continuous, and zero-based")
    edges: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for pair in raw["undirected_edges"]:
        if len(pair) != 2:
            raise ValueError("each edge must have two endpoints")
        u, v = sorted(map(int, pair))
        if u == v:
            raise ValueError("self-loop")
        if u not in node_ids or v not in node_ids:
            raise ValueError("unknown endpoint")
        if (u, v) in seen:
            raise ValueError("duplicate undirected edge")
        seen.add((u, v)); edges.append((u, v))
    edges.sort()
    graph = nx.Graph(); graph.add_nodes_from(node_ids); graph.add_edges_from(edges)
    if not nx.is_connected(graph):
        raise ValueError("graph must be connected")
    physical_links = [
        {"physical_link_id": i, "node_u_id": u, "node_v_id": v}
        for i, (u, v) in enumerate(edges)
    ]
    physical = {"topology_id": topology_id, "source_type": source_type,
                "node_records": [{"node_id": n} for n in node_ids],
                "physical_link_records": physical_links}
    directed_links = []
    for edge in physical_links:
        p, u, v = edge["physical_link_id"], edge["node_u_id"], edge["node_v_id"]
        directed_links.extend([
            {"link_id": 2 * p, "source_node_id": u, "destination_node_id": v, "physical_link_id": p},
            {"link_id": 2 * p + 1, "source_node_id": v, "destination_node_id": u, "physical_link_id": p},
        ])
    directed = {"topology_id": topology_id, "directed_link_records": directed_links}
    distances = dict(nx.all_pairs_shortest_path_length(graph))
    pair_distances = [distances[u][v] for u, v in combinations(node_ids, 2)]
    bridges = list(nx.bridges(graph))
    betweenness = nx.edge_betweenness_centrality(graph, normalized=True, weight=None)
    adjacency = nx.to_numpy_array(graph, nodelist=node_ids, dtype=float)
    degrees = adjacency.sum(axis=1)
    invsqrt = np.diag(np.where(degrees > 0, 1 / np.sqrt(degrees), 0))
    laplacian = np.eye(len(node_ids)) - invsqrt @ adjacency @ invsqrt
    eigenvalues = np.linalg.eigvalsh(laplacian)
    metrics = {
        "topology_id": topology_id,
        "node_count": len(node_ids),
        "physical_link_count": len(edges),
        "directed_link_count": len(directed_links),
        "average_node_degree": 2 * len(edges) / len(node_ids),
        "edge_density": 2 * len(edges) / (len(node_ids) * (len(node_ids) - 1)),
        "average_clustering_coefficient": nx.average_clustering(graph),
        "diameter_hops": max(pair_distances),
        "average_shortest_path_hops": sum(pair_distances) / len(pair_distances),
        "global_edge_connectivity": int(nx.edge_connectivity(graph)),
        "bridge_count": len(bridges),
        "bridge_ratio": len(bridges) / len(edges),
        "max_normalized_edge_betweenness": max(betweenness.values()),
        "normalized_algebraic_connectivity": float(eigenvalues[1]),
    }
    return physical, directed, metrics
