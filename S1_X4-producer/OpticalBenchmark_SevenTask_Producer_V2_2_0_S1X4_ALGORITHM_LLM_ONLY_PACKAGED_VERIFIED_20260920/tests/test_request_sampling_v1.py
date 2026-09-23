from __future__ import annotations

from collections import Counter
from random import Random

import networkx as nx
import pytest

from src.multi_topology.requests import (
    nearest_rank_cutpoints,
    stratified_request_pairs_v1,
)


def test_nearest_rank_cutpoints_use_ceil_without_interpolation() -> None:
    values = [1, 1, 2, 2, 3, 3, 4, 9, 10, 11]
    assert nearest_rank_cutpoints(values) == (2, 4)


def test_v1_sampler_preserves_largest_remainder_quotas_and_node_coverage() -> None:
    # A cycle with two attached bridge leaves creates both local-connectivity strata.
    graph = nx.cycle_graph(12)
    graph.add_edge(0, 12)
    graph.add_edge(6, 13)
    edges = list(graph.edges)
    pairs, audit = stratified_request_pairs_v1(14, edges, 100, Random(20260809))
    assert len(pairs) == 100
    assert len(set(pairs)) == 100
    assert sum(audit["quotas"].values()) == 100
    assert audit["coverage_after"]["all_sources_covered"] is True
    assert audit["coverage_after"]["all_destinations_covered"] is True
    assert set(s for s, _ in pairs) == set(range(14))
    assert set(t for _, t in pairs) == set(range(14))
    selected_counts = Counter(audit["pair_to_stratum"][f"{s}->{t}"] for s, t in pairs)
    assert dict(selected_counts) == audit["quotas"]


def test_v1_sampler_is_deterministic_for_same_seed() -> None:
    graph = nx.barabasi_albert_graph(30, 2, seed=3)
    edges = list(graph.edges)
    a, audit_a = stratified_request_pairs_v1(30, edges, 200, Random(1234))
    b, audit_b = stratified_request_pairs_v1(30, edges, 200, Random(1234))
    assert a == b
    assert audit_a["repair_count"] == audit_b["repair_count"]


def test_v1_sampler_rejects_sample_too_small_for_source_destination_coverage() -> None:
    graph = nx.path_graph(10)
    with pytest.raises(ValueError, match="node coverage"):
        stratified_request_pairs_v1(10, list(graph.edges), 5, Random(1))
