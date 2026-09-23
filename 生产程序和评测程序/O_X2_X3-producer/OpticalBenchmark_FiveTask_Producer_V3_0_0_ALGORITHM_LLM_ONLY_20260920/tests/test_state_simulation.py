import pytest

from src.state_simulation.core import (
    first_fit,
    reconstruct_availability,
    spectrum_metrics,
    validate_connections,
)


def test_first_fit_uses_common_contiguous_slots():
    availability = {0: [1, 0, 1, 1, 1], 2: [1, 1, 1, 1, 0]}
    assert first_fit([0, 2], availability, 2) == 2
    assert first_fit([0, 2], availability, 4) is None


def test_reconstruction_and_metrics_are_independent_of_saved_state():
    directed = {"directed_link_records": [{"link_id": i} for i in range(2)]}
    conns = [{"connection_id": "c", "path_link_ids": [0], "slot_start": 1,
              "required_slots": 2, "arrival_time": 0.0, "holding_time": 10.0,
              "source_node_id": 0, "destination_node_id": 1}]
    state = reconstruct_availability(conns, directed, 4)
    assert state == {0: [1, 0, 0, 1], 1: [1, 1, 1, 1]}
    metrics = spectrum_metrics(state, 4)
    assert metrics["network_spectrum_utilization"] == 0.25
    assert metrics["link_spectrum_metrics"][0]["external_fragmentation"] == 0.5


def test_connection_validation_rejects_slot_overflow_overlap_and_bad_width():
    directed = {"directed_link_records": [{"link_id": 0, "source_node_id": 0,
        "destination_node_id": 1, "physical_link_id": 0}]}
    base = {"connection_id": "c1", "path_link_ids": [0], "slot_start": 3,
            "required_slots": 2, "arrival_time": 0.0, "holding_time": 10.0,
            "source_node_id": 0, "destination_node_id": 1}
    with pytest.raises(ValueError, match="boundary"):
        validate_connections([base], directed, 4, 1.0)
    bad = dict(base, slot_start=0, required_slots=4)
    with pytest.raises(ValueError, match="required_slots"):
        validate_connections([bad], directed, 4, 1.0)
    a = dict(base, slot_start=0)
    b = dict(base, connection_id="c2", slot_start=1)
    with pytest.raises(ValueError, match="overlap"):
        validate_connections([a, b], directed, 4, 1.0)
