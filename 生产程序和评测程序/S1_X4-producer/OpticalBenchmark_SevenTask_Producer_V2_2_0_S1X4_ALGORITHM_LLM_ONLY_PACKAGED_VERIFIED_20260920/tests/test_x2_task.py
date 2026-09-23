from tests.o_family_test_utils import toy_env
from src.tasks.x2.producer import build_x2_case
from src.tasks.x2.validator import validate_x2_output


def test_x2_bundle_uses_natural_language_for_llm_and_structured_request_for_algorithm():
    bundle=build_x2_case(toy_env(slot_count=5), 'r1', case_id='X2_TEST', required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    assert bundle['private_truth']['oracle_certification'] == 'EXACT_CERTIFIED'
    assert 'request' in bundle['algorithm_case']
    assert set(bundle['llm_case']) == {'case_id','prompt'}
    assert '当前网络有向链路及频谱资源状态' in bundle['llm_case']['prompt']
    assert bundle['benchmark_case']['reference'] == bundle['reference_output']
    assert '分配优先选择最小化路径跳数的方案' in bundle['llm_case']['prompt']
    result=validate_x2_output(bundle['root_case'],bundle['private_truth'],bundle['reference_output'])
    assert result['valid']
    assert result['metrics']['feasible_decision_accuracy'] == 1
    assert result['metrics']['hop_gap'] == 0
    assert result['metrics']['wufr_gap'] == 0.0


def test_x2_exact_reject_when_no_full_path_allocation_exists():
    env=toy_env(slot_count=2, occupied0={0,1})
    bundle=build_x2_case(env,'r1',case_id='X2_BLOCK',required_slots=2,max_simple_paths=100,max_optimal_actions=100)
    assert bundle['private_truth']['oracle_certification'] == 'INFEASIBLE_CERTIFIED'
    assert bundle['reference_output']['decision'] == 'REJECT'
