import pytest

from src.case_core.spectrum_codec import (
    binary_to_occupied_ranges,
    occupied_ranges_to_binary,
    compress_resource_state,
)


def test_binary_ranges_round_trip_and_closed_interval_semantics():
    values = [1, 1, 0, 0, 1, 0, 1, 1]
    ranges = binary_to_occupied_ranges(values)
    assert ranges == [[2, 3], [5, 5]]
    assert occupied_ranges_to_binary(len(values), ranges) == values


def test_codec_handles_all_free_and_all_occupied():
    assert binary_to_occupied_ranges([1, 1, 1]) == []
    assert binary_to_occupied_ranges([0, 0, 0]) == [[0, 2]]
    assert occupied_ranges_to_binary(3, []) == [1, 1, 1]
    assert occupied_ranges_to_binary(3, [[0, 2]]) == [0, 0, 0]


@pytest.mark.parametrize('ranges', [
    [[-1, 1]], [[0, 3]], [[2, 1]], [[0, 1], [1, 2]], [[0, 2], [2, 2]],
])
def test_invalid_ranges_fail_closed(ranges):
    with pytest.raises(ValueError):
        occupied_ranges_to_binary(3, ranges)


def test_compress_resource_state_preserves_link_ids_and_round_trips():
    state = {
        'slot_count': 5,
        'link_spectrum_states': [
            {'link_id': 7, 'slot_availability': [1, 0, 0, 1, 1]},
            {'link_id': 9, 'slot_availability': [1, 1, 1, 1, 1]},
        ],
    }
    compressed = compress_resource_state(state)
    assert compressed == [
        {'link_id': 7, 'occupied_ranges': [[1, 2]]},
        {'link_id': 9, 'occupied_ranges': []},
    ]
    for row, original in zip(compressed, state['link_spectrum_states']):
        assert occupied_ranges_to_binary(5, row['occupied_ranges']) == original['slot_availability']
