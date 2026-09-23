from __future__ import annotations

import math
from pathlib import Path
from random import Random

import pytest

from src.multi_topology.audit import (
    audit_source_records,
    build_public_topology,
    length_weighted_normalized_algebraic_connectivity,
)
from src.multi_topology.requests import ordered_request_pairs, stratified_request_pairs
from src.multi_topology.simulation import (
    IncrementalSpectrum,
    PathCatalog,
    choose_action,
    simulate_trial,
)
from src.multi_topology.validation import _replay
from src.multi_topology.xlsx_reader import read_topology_workbook


FIXTURES = Path(__file__).parent / "fixtures"


def test_xlsx_normal_import_preserves_source_fields():
    imported = read_topology_workbook(FIXTURES / "TOP_34_GBLNET.xlsx")
    assert imported.name == "GBLNET"
    assert len(imported.nodes) == 8
    assert len(imported.edges) == 7
    assert all(edge.length_km > 0 for edge in imported.edges)


def test_duplicate_and_ambiguous_length_detected_before_graph_construction():
    imported = read_topology_workbook(FIXTURES / "TOP_13_CERNET.xlsx")
    result = audit_source_records(imported)
    assert result.duplicate_pairs
    assert result.ambiguous_duplicate_pairs
    assert result.clean is False


def test_self_loop_detected_before_graph_construction():
    imported = read_topology_workbook(FIXTURES / "TOP_77_OXFORD.xlsx")
    result = audit_source_records(imported)
    assert result.self_loops
    assert result.clean is False


def test_n100_has_all_9900_ordered_pairs_and_unique_ids():
    pairs = ordered_request_pairs(100)
    assert len(pairs) == 9_900
    assert len(set(pairs)) == 9_900
    assert all(source != destination for source, destination in pairs)


def test_n_greater_than_100_stratified_branch_is_deterministic_and_unique():
    edges = [(i, i + 1) for i in range(110)] + [(i, i + 2) for i in range(109)]
    one = stratified_request_pairs(111, edges, 1000, Random(19))
    two = stratified_request_pairs(111, edges, 1000, Random(19))
    assert one == two
    assert len(one) == 1000
    assert len(set(one)) == 1000


def test_length_weighted_normalized_laplacian_differs_from_unweighted():
    edges = [(0, 1, 1.0), (1, 2, 10.0), (2, 0, 1.0)]
    weighted = length_weighted_normalized_algebraic_connectivity(3, edges)
    unweighted = length_weighted_normalized_algebraic_connectivity(
        3, [(u, v, 1.0) for u, v, _ in edges]
    )
    assert not math.isclose(weighted, unweighted, rel_tol=1e-9, abs_tol=1e-12)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("TOP_61_LAYER42.xlsx", 0.7307256663),
        ("TOP_97_SANET.xlsx", 0.0233089230),
        ("TOP_37_GERMANY50.xlsx", 0.0522231386),
    ],
)
def test_topologybench_length_weighted_anchor_vectors(filename, expected):
    physical, _, _, _ = build_public_topology(read_topology_workbook(FIXTURES / filename), "audit")
    edges = [(item["node_u_id"], item["node_v_id"], item["length_km"])
             for item in physical["physical_link_records"]]
    actual = length_weighted_normalized_algebraic_connectivity(len(physical["node_records"]), edges)
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)


def test_ksp_random_feasible_action_is_seed_reproducible():
    catalog = PathCatalog.from_edges(4, [(0, 1), (1, 3), (0, 2), (2, 3)], k=5)
    spectrum = IncrementalSpectrum(link_count=8, slot_count=16)
    a = choose_action("KSP_RF_PILOT", catalog, spectrum, 0, 3, 2, Random(91))
    b = choose_action("KSP_RF_PILOT", catalog, spectrum, 0, 3, 2, Random(91))
    assert a == b


def test_load_balanced_tie_break_uses_deterministic_ksp_order():
    catalog = PathCatalog.from_edges(4, [(0, 1), (1, 3), (0, 2), (2, 3)], k=5)
    spectrum = IncrementalSpectrum(link_count=8, slot_count=16)
    chosen = choose_action("LOAD_BALANCED_KSP_FF_PILOT", catalog, spectrum, 0, 3, 2, Random(1))
    assert chosen is not None
    assert chosen.path_link_ids == catalog.paths(0, 3)[0]
    assert chosen.slot_start == 0


def test_load_balanced_selects_lowest_utilization_path_before_first_fit():
    catalog = PathCatalog.from_edges(4, [(0, 1), (1, 3), (0, 2), (2, 3)], k=5)
    spectrum = IncrementalSpectrum(link_count=8, slot_count=6)
    first, second = catalog.paths(0, 3)[:2]
    # Fragment the lower-utilization path so it has no two-slot block; load the
    # other path more heavily but leave one two-slot block available.
    for start in (0, 2, 4):
        spectrum.allocate(first, start, 1)
    spectrum.allocate(second, 0, 4)
    chosen = choose_action("LOAD_BALANCED_KSP_FF_PILOT", catalog, spectrum, 0, 3, 2, Random(1))
    assert chosen is None


def test_unreachable_band_returns_closest_snapshot_without_fabrication():
    catalog = PathCatalog.from_edges(2, [(0, 1)], k=1)
    spectrum = IncrementalSpectrum(link_count=2, slot_count=4)
    # Four required slots cannot fit under the frozen {2,3,5,9}; use 5 to
    # force every request to block, leaving utilization at zero.
    assert choose_action("BASE_KSP_FF", catalog, spectrum, 0, 1, 5, Random(0)) is None
    assert spectrum.network_utilization() == 0.0

    trial = simulate_trial(
        catalog, node_count=2, link_count=2, slot_count=1,
        arrival_rate=1.0, holding_rate=1.0,
        payload_values=[1], payload_probabilities=[1.0], guard_slots=1,
        warmup=5, maximum_requests=10, target_band=(0.5, 0.8),
        policy="BASE_KSP_FF", seed=7,
    )
    assert trial.target_reached is False
    assert trial.utilization == 0.0


def test_incremental_cross_topology_state_reconstruction_detects_overlap():
    spectrum = IncrementalSpectrum(link_count=4, slot_count=8)
    spectrum.allocate([0, 2], 1, 3)
    with pytest.raises(ValueError, match="overlap"):
        spectrum.allocate([2], 2, 2)
    spectrum.release([0, 2], 1, 3)
    assert spectrum.network_utilization() == 0.0


def test_cross_topology_dynamic_replay_uses_object_slot_count_and_is_deterministic():
    physical = {
        "topology_id": "top_a",
        "node_records": [{"node_id": 0}, {"node_id": 1}, {"node_id": 2}],
        "physical_link_records": [
            {"physical_link_id": 0, "node_u_id": 0, "node_v_id": 1},
            {"physical_link_id": 1, "node_u_id": 1, "node_v_id": 2},
        ],
    }
    connection_set = {
        "reference_time": 2.0,
        "existing_connections": [{
            "connection_id": "c1", "source_node_id": 0, "destination_node_id": 2,
            "path_link_ids": [0, 2], "slot_start": 0, "required_slots": 2,
            "arrival_time": 0.0, "holding_time": 3.0,
        }],
    }
    sequence = {"dynamic_request_events": [{
        "request_id": "d1", "source_node_id": 0, "destination_node_id": 2,
        "required_slots": 2, "arrival_time": 3.0, "holding_time": 2.0,
    }]}
    one = _replay(sequence, connection_set, physical, slot_count=8)
    two = _replay(sequence, connection_set, physical, slot_count=8)
    assert one == two
    assert all(len(bits) == 8 for bits in one.values())
