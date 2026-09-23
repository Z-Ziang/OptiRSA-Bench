from random import Random

from src.request_generation.core import (
    derive_request,
    generate_dynamic_sequence,
    generate_single_requests,
)


def tiny_objects():
    physical = {"topology_id": "t", "node_records": [{"node_id": i} for i in range(3)],
                "physical_link_records": [
                    {"physical_link_id": 0, "node_u_id": 0, "node_v_id": 1},
                    {"physical_link_id": 1, "node_u_id": 1, "node_v_id": 2}]}
    directed = {"topology_id": "t", "directed_link_records": [
        {"link_id": 0, "source_node_id": 0, "destination_node_id": 1, "physical_link_id": 0},
        {"link_id": 1, "source_node_id": 1, "destination_node_id": 0, "physical_link_id": 0},
        {"link_id": 2, "source_node_id": 1, "destination_node_id": 2, "physical_link_id": 1},
        {"link_id": 3, "source_node_id": 2, "destination_node_id": 1, "physical_link_id": 1}]}
    state = {"resource_state_id": "rs", "slot_count": 4, "link_spectrum_states": [
        {"link_id": i, "slot_availability": [1, 1, 0, 1]} for i in range(4)]}
    return physical, directed, state


def test_all_ordered_pairs_and_derivation_counts():
    reqs = generate_single_requests("t", 3, [2], Random(1), prefix="req")
    assert [(r["source_node_id"], r["destination_node_id"]) for r in reqs] == [
        (0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)]
    p, d, s = tiny_objects()
    derivation = derive_request(reqs[1], p, d, s, 5)
    assert derivation["shortest_path_hops"] == 2
    assert derivation["candidate_paths"][0]["path_link_ids"] == [0, 2]
    assert derivation["candidate_paths"][0]["feasible_slot_starts"] == [0]
    assert derivation["feasible_action_count"] == 1


def test_dynamic_sequence_starts_after_reference_and_has_new_ids():
    seq = generate_dynamic_sequence("seq", "dyn", 3, 20.0, 10.0, 1.0, [2], Random(3))
    events = seq["dynamic_request_events"]
    assert len(events) == 20
    assert len({e["request_id"] for e in events}) == 20
    assert events[0]["arrival_time"] >= 3
    assert all(a["arrival_time"] <= b["arrival_time"] for a, b in zip(events, events[1:]))
    assert "release_time" not in str(seq)
    assert "resource_state_id" not in seq
