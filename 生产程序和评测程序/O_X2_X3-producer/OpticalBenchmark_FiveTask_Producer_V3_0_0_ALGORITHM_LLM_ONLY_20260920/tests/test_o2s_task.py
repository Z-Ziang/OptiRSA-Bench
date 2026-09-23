from tests.o_family_test_utils import toy_env
from src.tasks.o2_s.producer import build_o2s_case
from src.tasks.o2_s.validator import validate_o2s_output


def test_o2s_candidate_paths_are_topology_legal_and_ranked_from_one():
    package=build_o2s_case(toy_env(slot_count=4),'r1',case_id='O2S_TEST',candidate_k=1,max_complete_solutions=100)
    assert package['root_case']['candidate_paths'][0]['path_rank']==1
    assert package['root_case']['candidate_paths'][0]['path_node_ids']==[0,1]
    assert set(package['llm_case']) == {'case_id','prompt'}
    assert '当前网络有向链路及频谱资源状态' in package['llm_case']['prompt']
    assert package['benchmark_case']['reference'] == package['reference_output']
    assert '请从给定的候选传输路径中选择资源分配方案' in package['llm_case']['prompt']
    assert package['private_truth']['feasible'] is True
    assert package['validation']['valid'] is True


def test_o2s_reject_is_correct_only_when_no_action_exists():
    package=build_o2s_case(toy_env(slot_count=2,occupied0={0,1}),'r1',case_id='O2S_BLOCKED',candidate_k=1,max_complete_solutions=100)
    assert package['private_truth']['feasible'] is False
    result=validate_o2s_output(package['root_case'],package['private_truth'],{'decision':'REJECT','path_rank':None,'slot_start':None})
    assert result['metrics']=={'feasible_decision_accuracy':1,'wufr_gap':None}
