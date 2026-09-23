from tests.o_family_test_utils import toy_env
from src.tasks.o1.producer import build_o1_case
from src.tasks.o1.validator import validate_o1_output


def test_o1_producer_freezes_precomputed_path_and_builds_algorithm_llm_endpoints():
    package=build_o1_case(toy_env(slot_count=4),['r1','r2'],case_id='O1_TEST',max_complete_solutions=100)
    assert package['root_case']['requests'][0]['fixed_path']['path_link_ids']==[0]
    assert 'link_spectrum_states' in package['root_case']
    assert 'spectrum_states' in package['algorithm_case']
    assert set(package['llm_case']) == {'case_id','prompt'}
    assert '当前网络有向链路及频谱资源状态' in package['llm_case']['prompt']
    assert package['benchmark_case']['reference'] == package['reference_output']
    assert '固定传输路径' in package['llm_case']['prompt']
    assert package['private_truth']['joint_feasible'] is True
    assert package['validation']['valid'] is True


def test_o1_validator_rejects_partial_accept_and_accepts_reference():
    package=build_o1_case(toy_env(slot_count=4),['r1','r2'],case_id='O1_TEST',max_complete_solutions=100)
    bad={'decision':'ACCEPT','allocations':[{'request_id':'r1','slot_start':0}]}
    result=validate_o1_output(package['root_case'],package['private_truth'],bad)
    assert result['metrics']['joint_feasible_decision_accuracy']==0
    assert result['metrics']['wufr_gap'] is None
    good=validate_o1_output(package['root_case'],package['private_truth'],package['reference_output'])
    assert good['valid']
    assert good['metrics']['joint_feasible_decision_accuracy']==1
    assert good['metrics']['wufr_gap']==0.0
