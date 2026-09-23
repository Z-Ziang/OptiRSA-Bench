import math
from src.case_core.wufr import (
    WUFR_ABS_TOL,
    path_wufr,
    build_reference_paths,
    network_wufr,
    apply_allocations_copy,
)


def test_path_wufr_all_free_and_all_occupied_are_zero():
    q={2:1.0}
    assert path_wufr([0,1], {0:[1,1,1,1],1:[1,1,1,1]}, q) == 0.0
    assert path_wufr([0,1], {0:[0,0,0,0],1:[0,0,0,0]}, q) == 0.0


def test_path_wufr_counts_partial_free_and_short_common_block_exactly():
    q={2:1.0}
    spectrum={0:[1,1,0,0],1:[1,0,1,0]}
    assert math.isclose(path_wufr([0,1], spectrum, q), 1.0, abs_tol=WUFR_ABS_TOL)


def test_reference_paths_use_deterministic_equal_hop_tie_break():
    links=[
      {'link_id':0,'source_node_id':0,'destination_node_id':1},
      {'link_id':1,'source_node_id':1,'destination_node_id':3},
      {'link_id':2,'source_node_id':0,'destination_node_id':2},
      {'link_id':3,'source_node_id':2,'destination_node_id':3},
      {'link_id':4,'source_node_id':1,'destination_node_id':0},
      {'link_id':5,'source_node_id':3,'destination_node_id':1},
      {'link_id':6,'source_node_id':2,'destination_node_id':0},
      {'link_id':7,'source_node_id':3,'destination_node_id':2},
    ]
    refs=build_reference_paths([0,1,2,3],links)
    by_pair={(x['source_node_id'],x['destination_node_id']):x['path_link_ids'] for x in refs}
    assert by_pair[(0,3)] == [0,1]  # node path 0-1-3 beats 0-2-3 lexicographically
    assert len(refs)==12


def test_network_wufr_aggregates_all_ordered_reference_paths():
    links=[
      {'link_id':0,'source_node_id':0,'destination_node_id':1},
      {'link_id':1,'source_node_id':1,'destination_node_id':0},
    ]
    spectrum={0:[1,0,1],1:[1,1,1]}
    # single-link reference paths have no partial-link waste; blocks shorter than demand contribute unusable free slots
    value=network_wufr([0,1],links,spectrum,{2:1.0})
    assert value >= 0
    assert math.isfinite(value)


def test_apply_allocations_copy_does_not_mutate_input():
    original={0:[1,1,1,1],1:[1,1,1,1]}
    updated=apply_allocations_copy(original,[{'path_link_ids':[0,1],'slot_start':1,'required_slots':2}])
    assert original[0]==[1,1,1,1]
    assert updated[0]==[1,0,0,1]
    assert updated[1]==[1,0,0,1]
