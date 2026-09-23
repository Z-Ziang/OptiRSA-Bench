from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from statistics import fmean

import networkx as nx
import numpy as np

from .xlsx_reader import ImportedTopology


@dataclass(frozen=True)
class SourceAudit:
    clean: bool
    self_loops: tuple[dict, ...]
    duplicate_pairs: tuple[dict, ...]
    ambiguous_duplicate_pairs: tuple[dict, ...]
    unknown_endpoint_edges: tuple[dict, ...]
    connected: bool

    def as_dict(self) -> dict:
        return asdict(self)


def audit_source_records(imported: ImportedTopology) -> SourceAudit:
    known = {node.source_node_id for node in imported.nodes}
    self_loops = []
    unknown = []
    grouped: dict[tuple[int, int], list] = {}
    for edge in imported.edges:
        pair = tuple(sorted((edge.source, edge.destination)))
        grouped.setdefault(pair, []).append(edge)
        if edge.source == edge.destination:
            self_loops.append({"edge_id": edge.source_edge_id, "node_id": edge.source, "length_km": edge.length_km})
        if edge.source not in known or edge.destination not in known:
            unknown.append({"edge_id": edge.source_edge_id, "source": edge.source, "destination": edge.destination})
    duplicates = []
    ambiguous = []
    for pair, edges in sorted(grouped.items()):
        if len(edges) <= 1:
            continue
        record = {"source_pair": list(pair), "edge_ids": [e.source_edge_id for e in edges],
                  "lengths_km": [e.length_km for e in edges]}
        duplicates.append(record)
        if len(set(record["lengths_km"])) > 1:
            ambiguous.append(record)
    graph = nx.Graph()
    graph.add_nodes_from(known)
    graph.add_edges_from(pair for pair in grouped if pair[0] != pair[1])
    connected = bool(graph) and nx.is_connected(graph)
    clean = not (self_loops or duplicates or unknown) and connected
    return SourceAudit(clean, tuple(self_loops), tuple(duplicates), tuple(ambiguous), tuple(unknown), connected)


def length_weighted_normalized_algebraic_connectivity(
    node_count: int, edges: list[tuple[int, int, float]]
) -> float:
    adjacency = np.zeros((node_count, node_count), dtype=np.float64)
    for u, v, length in edges:
        adjacency[u, v] += float(length)
        adjacency[v, u] += float(length)
    degrees = adjacency.sum(axis=1)
    if np.any(degrees <= 0):
        raise ValueError("weighted normalized Laplacian requires a connected graph")
    inverse = np.diag(1.0 / np.sqrt(degrees))
    laplacian = np.eye(node_count, dtype=np.float64) - inverse @ adjacency @ inverse
    return float(np.linalg.eigvalsh(laplacian)[1])


def _unweighted_algebraic(graph: nx.Graph, nodes: list[int]) -> float:
    adjacency = nx.to_numpy_array(graph, nodelist=nodes, dtype=np.float64)
    degrees = adjacency.sum(axis=1)
    inverse = np.diag(1.0 / np.sqrt(degrees))
    laplacian = np.eye(len(nodes), dtype=np.float64) - inverse @ adjacency @ inverse
    return float(np.linalg.eigvalsh(laplacian)[1])


def build_public_topology(imported: ImportedTopology, topology_id: str) -> tuple[dict, dict, dict, dict]:
    audit = audit_source_records(imported)
    if not audit.clean:
        raise ValueError(f"source topology {imported.name} is not clean")
    source_ids = sorted(node.source_node_id for node in imported.nodes)
    mapping = {source_id: local for local, source_id in enumerate(source_ids)}
    nodes_by_id = {node.source_node_id: node for node in imported.nodes}
    node_records = []
    for source_id in source_ids:
        source = nodes_by_id[source_id]
        item = {"node_id": mapping[source_id]}
        if source.longitude is not None:
            item["longitude"] = source.longitude
        if source.latitude is not None:
            item["latitude"] = source.latitude
        node_records.append(item)
    converted = []
    edge_map = []
    for edge in imported.edges:
        u, v = sorted((mapping[edge.source], mapping[edge.destination]))
        converted.append((u, v, edge.length_km, edge.source_edge_id))
    converted.sort(key=lambda item: (item[0], item[1]))
    physical_links = []
    for link_id, (u, v, length, source_edge_id) in enumerate(converted):
        physical_links.append({"physical_link_id": link_id, "node_u_id": u, "node_v_id": v, "length_km": length})
        edge_map.append({"source_edge_id": source_edge_id, "physical_link_id": link_id})
    physical = {"topology_id": topology_id, "source_type": "REAL", "node_records": node_records,
                "physical_link_records": physical_links}
    directed_links = []
    for edge in physical_links:
        p, u, v = edge["physical_link_id"], edge["node_u_id"], edge["node_v_id"]
        directed_links.extend([
            {"link_id": 2*p, "source_node_id": u, "destination_node_id": v, "physical_link_id": p},
            {"link_id": 2*p+1, "source_node_id": v, "destination_node_id": u, "physical_link_id": p},
        ])
    directed = {"topology_id": topology_id, "directed_link_records": directed_links}
    graph = nx.Graph()
    graph.add_nodes_from(range(len(source_ids)))
    graph.add_weighted_edges_from(
        ((u, v, length) for u, v, length, _ in converted), weight="length_km"
    )
    hop_dist = dict(nx.all_pairs_shortest_path_length(graph))
    weighted_dist = dict(nx.all_pairs_dijkstra_path_length(graph, weight="length_km"))
    pairs = list(combinations(range(len(source_ids)), 2))
    bridges = list(nx.bridges(graph))
    centrality = nx.edge_betweenness_centrality(graph, normalized=True, weight=None)
    metrics = {
        "topology_id": topology_id,
        "node_count": len(source_ids), "physical_link_count": len(converted), "directed_link_count": 2*len(converted),
        "average_node_degree": 2*len(converted)/len(source_ids),
        "edge_density": 2*len(converted)/(len(source_ids)*(len(source_ids)-1)),
        "average_clustering_coefficient": nx.average_clustering(graph),
        "diameter_hops": max(hop_dist[u][v] for u, v in pairs),
        "average_shortest_path_hops": fmean(hop_dist[u][v] for u, v in pairs),
        "global_edge_connectivity": int(nx.edge_connectivity(graph)),
        "bridge_count": len(bridges), "bridge_ratio": len(bridges)/len(converted),
        "max_normalized_edge_betweenness": max(centrality.values()),
        "normalized_algebraic_connectivity": _unweighted_algebraic(graph, list(range(len(source_ids)))),
        "average_physical_link_length_km": fmean(item[2] for item in converted),
        "diameter_physical_length_km": max(weighted_dist[u][v] for u, v in pairs),
        "average_shortest_path_physical_length_km": fmean(weighted_dist[u][v] for u, v in pairs),
    }
    private_mapping = {
        "topology_id": topology_id, "source_file": imported.source_file, "source_topology_name": imported.name,
        "node_mapping": [{"source_node_id": source_id, "node_id": mapping[source_id]} for source_id in source_ids],
        "edge_mapping": edge_map,
    }
    return physical, directed, metrics, private_mapping
