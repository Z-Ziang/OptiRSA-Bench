from tests.o_family_test_utils import toy_env
from src.tasks.o2_c.producer import build_o2c_case
from src.tasks.o2_c.validator import validate_o2c_output


def test_o2c_detects_individually_feasible_but_jointly_infeasible_batch():
    package=build_o2c_case(toy_env(slot_count=3),['r1','r2'],case_id='O2C_TEST',candidate_k=1,max_complete_solutions=100)
    assert set(package['llm_case']) == {'case_id','prompt'}
    assert '当前网络有向链路及频谱资源状态' in package['llm_case']['prompt']
    assert package['benchmark_case']['reference'] == package['reference_output']
    assert '请你优先选择资源分配后全网碎片化程度最低的方案' in package['llm_case']['prompt']
    assert package['private_truth']['joint_feasible'] is False
    assert package['reference_output']=={'decision':'REJECT','allocations':[]}
    result=validate_o2c_output(package['root_case'],package['private_truth'],package['reference_output'])
    assert result['metrics']=={'joint_feasible_decision_accuracy':1,'wufr_gap':None}


def test_o2c_partial_accept_is_never_correct():
    package=build_o2c_case(toy_env(slot_count=4),['r1','r2'],case_id='O2C_TEST',candidate_k=1,max_complete_solutions=100)
    bad={'decision':'ACCEPT','allocations':[{'request_id':'r1','path_rank':1,'slot_start':0}]}
    result=validate_o2c_output(package['root_case'],package['private_truth'],bad)
    assert result['metrics']['joint_feasible_decision_accuracy']==0
