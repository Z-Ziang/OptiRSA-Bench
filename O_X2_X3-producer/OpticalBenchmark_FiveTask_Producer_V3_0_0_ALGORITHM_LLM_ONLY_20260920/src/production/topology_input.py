"""Topology input adapters and canonical public-topology construction.

The production runner accepts three source forms, but all downstream code sees
one canonical representation.  A source distance is published as ``length_km``
only when the input contract establishes kilometre units.  In particular,
TopoHub/Gabriel's ``dist`` field is retained only in private provenance and is
never relabelled as kilometres.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path
from statistics import fmean
from typing import Any

import networkx as nx
import numpy as np

from src.multi_topology.xlsx_reader import read_topology_workbook
from src.production.config import TopologySpec


class TopologyInputError(ValueError):
    """Raised when a source topology cannot enter the V1.0 production line."""


@dataclass(frozen=True)
class _SourceNode:
    source_id: int
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class _SourceEdge:
    source_edge_id: int | str
    source: int
    destination: int
    length_km: float | None = None
    source_distance: float | None = None


@dataclass(frozen=True)
class _NormalizedSource:
    source_type: str
    nodes: tuple[_SourceNode, ...]
    edges: tuple[_SourceEdge, ...]
    source_distance_field: str | None
    source_distance_unit: str | None
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class TopologyArtifacts:
    physical: dict
    directed: dict
    metrics: dict
    private_mapping: dict


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TopologyInputError(f"cannot read topology JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TopologyInputError("topology JSON root must be an object")
    return value


def _gabriel(path: Path) -> _NormalizedSource:
    value = _read_json(path)
    if value.get("directed") is True:
        raise TopologyInputError("Gabriel source must be undirected")
    if value.get("multigraph") is True:
        raise TopologyInputError("Gabriel source must not be a multigraph")
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges", value.get("links"))
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise TopologyInputError("Gabriel JSON requires nodes and edges arrays")
    nodes: list[_SourceNode] = []
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, dict) or "id" not in item:
            raise TopologyInputError(f"Gabriel node[{index}] lacks id")
        source_id = int(item["id"])
        latitude = item.get("latitude", item.get("lat"))
        longitude = item.get("longitude", item.get("lon"))
        nodes.append(_SourceNode(
            source_id=source_id,
            latitude=None if latitude is None else float(latitude),
            longitude=None if longitude is None else float(longitude),
        ))
    edges: list[_SourceEdge] = []
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict) or "source" not in item or "target" not in item:
            raise TopologyInputError(f"Gabriel edge[{index}] lacks source/target")
        dist = item.get("dist")
        edges.append(_SourceEdge(
            source_edge_id=item.get("id", index),
            source=int(item["source"]),
            destination=int(item["target"]),
            length_km=None,
            source_distance=None if dist is None else float(dist),
        ))
    return _NormalizedSource(
        source_type="SYNTHETIC",
        nodes=tuple(nodes),
        edges=tuple(edges),
        source_distance_field="dist" if any(edge.source_distance is not None for edge in edges) else None,
        source_distance_unit="UNKNOWN" if any(edge.source_distance is not None for edge in edges) else None,
        source_metadata={"format": "TOPOHUB_GABRIEL_NETWORKX_NODE_LINK_JSON"},
    )


def _topologybench(path: Path) -> _NormalizedSource:
    imported = read_topology_workbook(path)
    return _NormalizedSource(
        source_type="REAL",
        nodes=tuple(_SourceNode(n.source_node_id, n.latitude, n.longitude) for n in imported.nodes),
        edges=tuple(_SourceEdge(e.source_edge_id, e.source, e.destination, e.length_km) for e in imported.edges),
        source_distance_field="Computed Length (km)",
        source_distance_unit="km",
        source_metadata={"format": "TOPOLOGYBENCH_XLSX", "source_topology_name": imported.name},
    )


def _canonical(path: Path) -> _NormalizedSource:
    value = _read_json(path)
    nodes_raw = value.get("node_records")
    edges_raw = value.get("physical_link_records")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise TopologyInputError("canonical physical JSON lacks node_records/physical_link_records")
    source_type = value.get("source_type")
    if source_type not in {"REAL", "SYNTHETIC"}:
        raise TopologyInputError("canonical source_type must be REAL or SYNTHETIC")
    nodes = tuple(
        _SourceNode(
            int(item["node_id"]),
            None if item.get("latitude") is None else float(item["latitude"]),
            None if item.get("longitude") is None else float(item["longitude"]),
        )
        for item in nodes_raw
    )
    lengths_present = ["length_km" in item for item in edges_raw]
    if any(lengths_present) and not all(lengths_present):
        raise TopologyInputError("canonical topology must provide length_km for all links or for none")
    edges = tuple(
        _SourceEdge(
            int(item["physical_link_id"]), int(item["node_u_id"]), int(item["node_v_id"]),
            None if "length_km" not in item else float(item["length_km"]),
        )
        for item in edges_raw
    )
    return _NormalizedSource(
        str(source_type), nodes, edges,
        "length_km" if all(lengths_present) and lengths_present else None,
        "km" if all(lengths_present) and lengths_present else None,
        {"format": "CANONICAL_PHYSICAL_JSON", "source_topology_id": value.get("topology_id")},
    )


def _validate_source(source: _NormalizedSource) -> None:
    if len(source.nodes) < 2:
        raise TopologyInputError("topology must contain at least two nodes")
    ids = [node.source_id for node in source.nodes]
    if len(ids) != len(set(ids)):
        raise TopologyInputError("duplicate source node id")
    known = set(ids)
    pairs: set[tuple[int, int]] = set()
    graph = nx.Graph()
    graph.add_nodes_from(known)
    for edge in source.edges:
        if edge.source not in known or edge.destination not in known:
            raise TopologyInputError(f"edge references unknown endpoint: {edge.source}-{edge.destination}")
        if edge.source == edge.destination:
            raise TopologyInputError(f"self-loop is not allowed: {edge.source}")
        pair = tuple(sorted((edge.source, edge.destination)))
        if pair in pairs:
            raise TopologyInputError(f"duplicate undirected edge is not allowed: {pair}")
        pairs.add(pair)
        graph.add_edge(*pair)
        if edge.length_km is not None and edge.length_km <= 0:
            raise TopologyInputError("length_km must be positive")
    if not source.edges:
        raise TopologyInputError("topology must contain at least one edge")
    if not nx.is_connected(graph):
        raise TopologyInputError("physical topology must be connected")


def _normalized_algebraic_connectivity(graph: nx.Graph, nodes: list[int]) -> float:
    adjacency = nx.to_numpy_array(graph, nodelist=nodes, dtype=np.float64)
    degrees = adjacency.sum(axis=1)
    inverse_sqrt = np.diag(1.0 / np.sqrt(degrees))
    normalized_laplacian = np.eye(len(nodes), dtype=np.float64) - inverse_sqrt @ adjacency @ inverse_sqrt
    eigenvalues = np.linalg.eigvalsh(normalized_laplacian)
    return float(max(0.0, eigenvalues[1]))


def _build(spec: TopologySpec, source: _NormalizedSource) -> TopologyArtifacts:
    _validate_source(source)
    source_ids = sorted(node.source_id for node in source.nodes)
    mapping = {source_id: local for local, source_id in enumerate(source_ids)}
    nodes_by_id = {node.source_id: node for node in source.nodes}
    node_records: list[dict[str, Any]] = []
    for source_id in source_ids:
        node = nodes_by_id[source_id]
        record: dict[str, Any] = {"node_id": mapping[source_id]}
        if node.longitude is not None:
            record["longitude"] = node.longitude
        if node.latitude is not None:
            record["latitude"] = node.latitude
        node_records.append(record)

    converted: list[tuple[int, int, _SourceEdge]] = []
    for edge in source.edges:
        u, v = sorted((mapping[edge.source], mapping[edge.destination]))
        converted.append((u, v, edge))
    converted.sort(key=lambda item: (item[0], item[1], str(item[2].source_edge_id)))

    physical_links: list[dict[str, Any]] = []
    edge_mapping: list[dict[str, Any]] = []
    for physical_link_id, (u, v, edge) in enumerate(converted):
        record: dict[str, Any] = {
            "physical_link_id": physical_link_id,
            "node_u_id": u,
            "node_v_id": v,
        }
        if edge.length_km is not None:
            record["length_km"] = float(edge.length_km)
        physical_links.append(record)
        private: dict[str, Any] = {
            "source_edge_id": edge.source_edge_id,
            "physical_link_id": physical_link_id,
        }
        if edge.source_distance is not None:
            private["source_distance_value"] = edge.source_distance
        edge_mapping.append(private)

    physical = {
        "topology_id": spec.topology_id,
        "source_type": source.source_type,
        "node_records": node_records,
        "physical_link_records": physical_links,
    }
    directed_links: list[dict[str, int]] = []
    for edge in physical_links:
        physical_link_id = edge["physical_link_id"]
        u, v = edge["node_u_id"], edge["node_v_id"]
        directed_links.extend([
            {"link_id": 2 * physical_link_id, "source_node_id": u, "destination_node_id": v,
             "physical_link_id": physical_link_id},
            {"link_id": 2 * physical_link_id + 1, "source_node_id": v, "destination_node_id": u,
             "physical_link_id": physical_link_id},
        ])
    directed = {"topology_id": spec.topology_id, "directed_link_records": directed_links}

    graph = nx.Graph()
    graph.add_nodes_from(range(len(source_ids)))
    graph.add_edges_from((u, v) for u, v, _ in converted)
    hop_dist = dict(nx.all_pairs_shortest_path_length(graph))
    node_pairs = list(combinations(range(len(source_ids)), 2))
    bridges = list(nx.bridges(graph))
    centrality = nx.edge_betweenness_centrality(graph, normalized=True, weight=None)
    metrics: dict[str, Any] = {
        "topology_id": spec.topology_id,
        "node_count": len(source_ids),
        "physical_link_count": len(converted),
        "directed_link_count": 2 * len(converted),
        "average_node_degree": 2 * len(converted) / len(source_ids),
        "edge_density": 2 * len(converted) / (len(source_ids) * (len(source_ids) - 1)),
        "average_clustering_coefficient": nx.average_clustering(graph),
        "diameter_hops": max(hop_dist[u][v] for u, v in node_pairs),
        "average_shortest_path_hops": fmean(hop_dist[u][v] for u, v in node_pairs),
        "global_edge_connectivity": int(nx.edge_connectivity(graph)),
        "bridge_count": len(bridges),
        "bridge_ratio": len(bridges) / len(converted),
        "max_normalized_edge_betweenness": max(centrality.values()),
        "normalized_algebraic_connectivity": _normalized_algebraic_connectivity(graph, list(range(len(source_ids)))),
    }
    if converted and all(edge.length_km is not None for _, _, edge in converted):
        weighted = nx.Graph()
        weighted.add_nodes_from(range(len(source_ids)))
        weighted.add_weighted_edges_from(
            (u, v, float(edge.length_km)) for u, v, edge in converted if edge.length_km is not None
        )
        weighted_dist = dict(nx.all_pairs_dijkstra_path_length(weighted, weight="weight"))
        metrics.update({
            "average_physical_link_length_km": fmean(float(edge.length_km) for _, _, edge in converted),
            "diameter_physical_length_km": max(weighted_dist[u][v] for u, v in node_pairs),
            "average_shortest_path_physical_length_km": fmean(weighted_dist[u][v] for u, v in node_pairs),
        })

    private_mapping = {
        "topology_id": spec.topology_id,
        "source_file": str(spec.source_path),
        "source_type": spec.source_type,
        "source_distance_field": source.source_distance_field,
        "source_distance_unit": source.source_distance_unit,
        "source_metadata": source.source_metadata,
        "node_mapping": [
            {"source_node_id": source_id, "node_id": mapping[source_id]} for source_id in source_ids
        ],
        "edge_mapping": edge_mapping,
    }
    return TopologyArtifacts(physical, directed, metrics, private_mapping)


def load_and_build_topology(spec: TopologySpec) -> TopologyArtifacts:
    """Read one registered source topology and produce canonical public objects."""
    if spec.source_type == "GABRIEL_JSON":
        source = _gabriel(spec.source_path)
    elif spec.source_type == "TOPOLOGYBENCH_XLSX":
        source = _topologybench(spec.source_path)
    elif spec.source_type == "CANONICAL_PHYSICAL_JSON":
        source = _canonical(spec.source_path)
    else:  # Config validation should make this unreachable, but keep API safe.
        raise TopologyInputError(f"unsupported source_type: {spec.source_type}")
    return _build(spec, source)
