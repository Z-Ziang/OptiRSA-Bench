from __future__ import annotations

from dataclasses import replace

import networkx as nx

from src.multi_topology.simulation import (
    LoadSearchProtocol,
    PathCatalog,
    estimate_arrival_rate,
    run_steady_trial_v1,
    search_snapshot_v1,
)


def _catalog() -> PathCatalog:
    graph = nx.cycle_graph(8)
    return PathCatalog.from_edges(8, list(graph.edges), 5, cache_capacity=128)


def _tiny_protocol() -> LoadSearchProtocol:
    return LoadSearchProtocol(
        warmup_min_requests=80,
        warmup_min_time_factor=0.2,
        observation_min_requests=120,
        observation_min_time_factor=0.2,
        initial_observation_blocks=2,
        max_observation_blocks=4,
        utilization_stability_tolerance=0.20,
        blocking_stability_tolerance=0.20,
        sample_interval_requests=10,
        max_coarse_expansions=4,
        max_fine_rounds=3,
        fine_ratio_stop=1.01,
    )


def test_lambda0_formula_matches_frozen_definition() -> None:
    value = estimate_arrival_rate(0.35, 1 / 15, 100, 320, 4.75, 5.0)
    assert value == 0.35 * (1 / 15) * 100 * 320 / (4.75 * 5.0)


def test_steady_trial_uses_dual_warmup_and_observation_gates() -> None:
    result = run_steady_trial_v1(
        catalog=_catalog(), node_count=8, link_count=16, slot_count=40,
        arrival_rate=8.0, holding_rate=1.0,
        payload_values=[1, 2, 4, 8], payload_probabilities=[0.25] * 4,
        guard_slots=1, policy="BASE_KSP_FF", seed=123,
        target_band=(0.0, 1.0), protocol=_tiny_protocol(),
    )
    assert result.warmup_request_count >= 80
    assert result.warmup_simulated_time >= 0.2
    assert len(result.blocks) >= 2
    assert all(block["request_count"] >= 120 for block in result.blocks)
    assert all(block["simulated_time"] >= 0.2 for block in result.blocks)
    assert result.steady_confirmed is True


def test_search_returns_real_replayed_snapshot_inside_hard_band() -> None:
    result = search_snapshot_v1(
        topology_id="top_tiny", state_id="rs_tiny", connection_set_id="ic_tiny",
        catalog=_catalog(), node_count=8, link_count=16, slot_count=40,
        holding_rate=1.0, payload_values=[1, 2, 4, 8], payload_probabilities=[0.25] * 4,
        guard_slots=1, target_band=(0.0, 1.0), policy="BASE_KSP_FF",
        seed=321, confirmation_seed=654, average_shortest_path_hops=2.0,
        protocol=_tiny_protocol(),
    )
    assert result.status == "TARGET_REACHED"
    assert result.connection_set is not None
    assert result.resource_state is not None
    utilization = result.resource_state["spectrum_state_metrics"]["network_spectrum_utilization"]
    assert 0.0 <= utilization < 1.0
    assert result.snapshot_request_index is not None


def test_same_trial_seed_and_lambda_are_reproducible() -> None:
    kwargs = dict(
        catalog=_catalog(), node_count=8, link_count=16, slot_count=40,
        arrival_rate=7.0, holding_rate=1.0,
        payload_values=[1, 2, 4, 8], payload_probabilities=[0.25] * 4,
        guard_slots=1, policy="KSP_RF_PILOT", seed=111,
        target_band=(0.0, 1.0), protocol=_tiny_protocol(),
    )
    a = run_steady_trial_v1(**kwargs)
    b = run_steady_trial_v1(**kwargs)
    assert a.stable_mean_utilization == b.stable_mean_utilization
    assert a.stable_mean_blocking_probability == b.stable_mean_blocking_probability
    assert a.blocks == b.blocks
