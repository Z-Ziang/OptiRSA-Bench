import math
import pytest

from src.case_core.search import (
    SearchBudgetExceeded,
    enumerate_feasible_actions,
    search_single_optimum,
    search_joint_optimum,
)

LINKS=[
 {'link_id':0,'source_node_id':0,'destination_node_id':1},
 {'link_id':1,'source_node_id':1,'destination_node_id':0},
]
NODES=[0,1]
Q={2:1.0}


def test_enumeration_recomputes_actions_from_root_spectrum_only():
    spectrum={0:[1,1,0,1],1:[1,1,1,1]}
    paths=[{'path_rank':1,'path_link_ids':[0]}]
    actions=enumerate_feasible_actions(paths,2,spectrum)
    assert actions == [{'path_rank':1,'slot_start':0,'path_link_ids':[0]}]


def test_single_search_accepts_equivalent_optima_by_objective_not_reference_json():
    spectrum={0:[1,1,1,1],1:[1,1,1,1]}
    paths=[{'path_rank':1,'path_link_ids':[0]}]
    result=search_single_optimum(NODES,LINKS,spectrum,Q,2,paths,max_complete_solutions=100)
    assert result.feasible
    assert result.reference_action['path_rank']==1
    assert result.equivalent_optimum_count >= 2
    assert math.isfinite(result.optimal_wufr)


def test_joint_search_finds_complete_nonoverlapping_solution_and_counts_ties():
    spectrum={0:[1,1,1,1],1:[1,1,1,1]}
    requests=[
      {'request_id':'a','required_slots':2,'paths':[{'path_rank':1,'path_link_ids':[0]}]},
      {'request_id':'b','required_slots':2,'paths':[{'path_rank':1,'path_link_ids':[0]}]},
    ]
    result=search_joint_optimum(NODES,LINKS,spectrum,Q,requests,max_complete_solutions=100)
    assert result.feasible
    allocs=result.reference_action['allocations']
    assert {x['request_id'] for x in allocs}=={'a','b'}
    assert set(x['slot_start'] for x in allocs)=={0,2}
    assert result.equivalent_optimum_count==2


def test_joint_search_reports_infeasible_and_budget_failure_explicitly():
    spectrum={0:[1,1,1],1:[1,1,1]}
    requests=[
      {'request_id':'a','required_slots':2,'paths':[{'path_rank':1,'path_link_ids':[0]}]},
      {'request_id':'b','required_slots':2,'paths':[{'path_rank':1,'path_link_ids':[0]}]},
    ]
    result=search_joint_optimum(NODES,LINKS,spectrum,Q,requests,max_complete_solutions=100)
    assert not result.feasible
    with pytest.raises(SearchBudgetExceeded):
        search_single_optimum(NODES,LINKS,{0:[1]*8,1:[1]*8},Q,2,[{'path_rank':1,'path_link_ids':[0]}],max_complete_solutions=1)
