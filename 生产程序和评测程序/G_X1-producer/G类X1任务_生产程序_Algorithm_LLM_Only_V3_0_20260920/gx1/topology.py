from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


class TopologyError(ValueError):
    pass


@dataclass(frozen=True)
class PhysicalEdge:
    physical_link_id: int
    u: int
    v: int
    length_km: float | None = None


@dataclass(frozen=True)
class DirectedLink:
    link_id: int
    source_node_id: int
    destination_node_id: int
    physical_link_id: int
    length_km: float | None = None

    def public_dict(self, include_length: bool = True, include_physical: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "link_id": self.link_id,
            "source_node_id": self.source_node_id,
            "destination_node_id": self.destination_node_id,
        }
        if include_physical:
            d["physical_link_id"] = self.physical_link_id
        if include_length and self.length_km is not None:
            d["length_km"] = self.length_km
        return d


@dataclass(frozen=True)
class Topology:
    topology_id: str
    source_type: str
    nodes: tuple[int, ...]
    edges: tuple[PhysicalEdge, ...]

    @property
    def has_complete_lengths(self) -> bool:
        return all(e.length_km is not None and e.length_km > 0 for e in self.edges)


def _check_connected(nodes: tuple[int, ...], edges: tuple[PhysicalEdge, ...]) -> None:
    adj = {n: set() for n in nodes}
    for e in edges:
        adj[e.u].add(e.v)
        adj[e.v].add(e.u)
    seen = {nodes[0]}
    stack = [nodes[0]]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    if len(seen) != len(nodes):
        raise TopologyError("拓扑必须连通")


def _normalize(nodes: Iterable[int], raw_edges: Iterable[tuple[int, int, float | None]], topology_id: str, source_type: str) -> Topology:
    node_tuple = tuple(int(x) for x in nodes)
    if len(node_tuple) < 2:
        raise TopologyError("拓扑至少需要2个节点")
    if node_tuple != tuple(range(len(node_tuple))):
        raise TopologyError("节点编号必须从0开始连续且按升序给出")
    node_set = set(node_tuple)
    normalized: list[tuple[int, int, float | None]] = []
    seen: set[tuple[int, int]] = set()
    for a, b, length in raw_edges:
        a, b = int(a), int(b)
        if a not in node_set or b not in node_set:
            raise TopologyError("物理边端点必须属于节点集合")
        if a == b:
            raise TopologyError("不允许自环")
        u, v = sorted((a, b))
        if (u, v) in seen:
            raise TopologyError("不允许重复无向边")
        if length is not None:
            length = float(length)
            if length <= 0:
                raise TopologyError("length_km 必须为正数")
        seen.add((u, v))
        normalized.append((u, v, length))
    if not normalized:
        raise TopologyError("拓扑至少需要1条物理边")
    normalized.sort(key=lambda x: (x[0], x[1]))
    edges = tuple(PhysicalEdge(i, u, v, length) for i, (u, v, length) in enumerate(normalized))
    _check_connected(node_tuple, edges)
    return Topology(str(topology_id), str(source_type), node_tuple, edges)


def topology_from_dict(data: dict[str, Any]) -> Topology:
    if {"topology_id", "node_records", "physical_link_records"}.issubset(data):
        nodes = tuple(int(x["node_id"]) for x in data["node_records"])
        if nodes != tuple(range(len(nodes))):
            raise TopologyError("节点编号必须从0开始连续且按升序给出")
        records = data["physical_link_records"]
        ids = [int(x["physical_link_id"]) for x in records]
        if ids != list(range(len(ids))):
            raise TopologyError("physical_link_id 必须从0开始连续且按顺序给出")
        node_set = set(nodes)
        seen: set[tuple[int, int]] = set()
        edges: list[PhysicalEdge] = []
        for i, x in enumerate(records):
            u, v = int(x["node_u_id"]), int(x["node_v_id"])
            if u not in node_set or v not in node_set:
                raise TopologyError("物理边端点必须属于节点集合")
            if u == v:
                raise TopologyError("不允许自环")
            if u > v:
                raise TopologyError("canonical 物理边必须满足 node_u_id < node_v_id")
            if (u, v) in seen:
                raise TopologyError("不允许重复无向边")
            length = x.get("length_km")
            if length is not None:
                length = float(length)
                if length <= 0:
                    raise TopologyError("length_km 必须为正数")
            seen.add((u, v))
            edges.append(PhysicalEdge(i, u, v, length))
        if not edges:
            raise TopologyError("拓扑至少需要1条物理边")
        edge_tuple = tuple(edges)
        _check_connected(nodes, edge_tuple)
        return Topology(str(data["topology_id"]), str(data.get("source_type", "SYNTHETIC")), nodes, edge_tuple)
    if {"node_ids", "undirected_edges"}.issubset(data):
        topo_id = data.get("normalization_target_topology_id") or data.get("topology_id") or data.get("raw_topology_name") or "topology"
        raw_edges = [(int(e[0]), int(e[1]), None) for e in data["undirected_edges"]]
        return _normalize(data["node_ids"], raw_edges, topo_id, data.get("source_type", "SYNTHETIC"))
    raise TopologyError("不支持的拓扑输入格式")


def load_topology(path: str | Path) -> Topology:
    p = Path(path)
    return topology_from_dict(json.loads(p.read_text(encoding="utf-8")))


def expand_directed_links(topology: Topology) -> tuple[DirectedLink, ...]:
    out: list[DirectedLink] = []
    for e in topology.edges:
        out.append(DirectedLink(2 * e.physical_link_id, e.u, e.v, e.physical_link_id, e.length_km))
        out.append(DirectedLink(2 * e.physical_link_id + 1, e.v, e.u, e.physical_link_id, e.length_km))
    return tuple(out)


def topology_to_internal_dict(topology: Topology) -> dict[str, Any]:
    return {
        "topology_id": topology.topology_id,
        "source_type": topology.source_type,
        "nodes": list(topology.nodes),
        "physical_edges": [
            {
                "physical_link_id": e.physical_link_id,
                "node_u_id": e.u,
                "node_v_id": e.v,
                **({"length_km": e.length_km} if e.length_km is not None else {}),
            }
            for e in topology.edges
        ],
        "directed_links": [d.public_dict(include_length=True, include_physical=True) for d in expand_directed_links(topology)],
    }
