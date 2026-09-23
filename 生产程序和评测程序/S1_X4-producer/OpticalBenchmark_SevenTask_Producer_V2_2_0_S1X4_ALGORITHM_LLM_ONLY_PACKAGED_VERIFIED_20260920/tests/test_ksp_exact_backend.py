from __future__ import annotations

from itertools import islice
import random

import networkx as nx

from src.multi_topology.ksp_exact import ExactYenKSP
from src.multi_topology.simulation import PathCatalog


def _nx_paths(graph: nx.Graph, s: int, t: int, k: int) -> list[list[int]]:
    return list(islice(nx.shortest_simple_paths(graph, s, t), k))


def test_exact_yen_matches_networkx_on_equal_length_ties() -> None:
    graph = nx.Graph()
    graph.add_nodes_from(range(8))
    graph.add_edges_from(sorted({
        (0, 1), (0, 2), (1, 3), (2, 3), (1, 4), (2, 4),
        (3, 5), (4, 5), (3, 6), (4, 6), (5, 7), (6, 7),
    }))
    engine = ExactYenKSP.from_graph(graph, workspace_capacity=256)
    for source in graph.nodes:
        for destination in graph.nodes:
            if source == destination:
                continue
            assert engine.node_paths(source, destination, 5) == _nx_paths(graph, source, destination, 5)


def test_path_catalog_uses_exact_backend_and_preserves_link_direction() -> None:
    edges = [(0, 1), (1, 2), (0, 2), (2, 3), (1, 3)]
    catalog = PathCatalog.from_edges(4, edges, 5, cache_capacity=16)
    node_paths = catalog.node_paths(0, 3)
    link_paths = catalog.paths(0, 3)
    assert len(node_paths) == len(link_paths)
    for nodes, links in zip(node_paths, link_paths):
        assert len(links) == len(nodes) - 1
        for (u, v), link_id in zip(zip(nodes, nodes[1:]), links):
            assert catalog.lookup[(u, v)] == link_id


def test_path_catalog_fifo_cache_is_bounded() -> None:
    graph = nx.path_graph(12)
    catalog = PathCatalog.from_edges(12, list(graph.edges), 5, cache_capacity=4)
    for target in range(1, 9):
        catalog.paths(0, target)
    assert catalog.cache_size <= 4
    assert catalog.cache_capacity == 4


def test_exact_yen_matches_networkx_on_random_sparse_graph() -> None:
    rng = random.Random(20260809)
    graph = nx.random_labeled_tree(30, seed=7)
    for _ in range(45):
        u, v = rng.sample(range(30), 2)
        graph.add_edge(min(u, v), max(u, v))
    ordered = nx.Graph()
    ordered.add_nodes_from(range(30))
    ordered.add_edges_from(sorted(tuple(sorted(e)) for e in graph.edges))
    engine = ExactYenKSP.from_graph(ordered, workspace_capacity=256)
    for _ in range(100):
        source, destination = rng.sample(range(30), 2)
        assert engine.node_paths(source, destination, 5) == _nx_paths(ordered, source, destination, 5)
