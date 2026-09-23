import pytest
from src.case_core.allocation_validation import (
    assignment_interval,
    is_assignment_feasible,
    joint_allocations_feasible,
)

SPECTRUM = {
    0:[1,1,1,0,1,1,1,1],
    1:[1,1,1,1,1,1,1,1],
    2:[1,1,1,1,1,1,1,1],
    3:[1,1,1,1,1,1,1,1],
}


def test_assignment_interval_is_half_open_in_code_and_bounded():
    assert list(assignment_interval(2,3,8)) == [2,3,4]
    with pytest.raises(ValueError): assignment_interval(-1,2,8)
    with pytest.raises(ValueError): assignment_interval(7,2,8)


def test_single_assignment_checks_every_path_link_against_original_state():
    assert is_assignment_feasible([0,1],0,3,SPECTRUM)
    assert not is_assignment_feasible([0,1],2,3,SPECTRUM)  # link 0 slot 3 occupied


def test_joint_allocation_detects_shared_directed_link_overlap_but_not_shared_node_only():
    requests={
      'a':{'required_slots':2}, 'b':{'required_slots':2}
    }
    path_specs={
      'a':{'path_link_ids':[1,2]}, 'b':{'path_link_ids':[2,3]}
    }
    assert not joint_allocations_feasible(
      [{'request_id':'a','slot_start':1},{'request_id':'b','slot_start':2}],
      requests,path_specs,SPECTRUM
    )
    assert joint_allocations_feasible(
      [{'request_id':'a','slot_start':0},{'request_id':'b','slot_start':3}],
      requests,path_specs,SPECTRUM
    )


def test_opposite_directed_links_are_independent_resources():
    requests={'a':{'required_slots':2},'b':{'required_slots':2}}
    paths={'a':{'path_link_ids':[0]},'b':{'path_link_ids':[1]}}
    assert joint_allocations_feasible(
      [{'request_id':'a','slot_start':0},{'request_id':'b','slot_start':0}],
      requests,paths,SPECTRUM
    )
