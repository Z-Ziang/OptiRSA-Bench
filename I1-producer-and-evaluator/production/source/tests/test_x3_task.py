from tests.o_family_test_utils import toy_env
from src.tasks.x3.producer import build_x3_case
from src.tasks.x3.validator import validate_x3_output


def test_x3_all_or_nothing_exact_bundle_and_reference_replay():
    bundle=build_x3_case(toy_env(slot_count=5), ['r1','r2'], case_id='X3_TEST', max_simple_paths_per_request=100, max_complete_optimal_solutions=10000)
    assert bundle['private_truth']['oracle_certification'] == 'EXACT_CERTIFIED'
    assert bundle['reference_output']['decision'] == 'ACCEPT'
    assert len(bundle['reference_output']['allocations']) == 2
    assert 'requests' in bundle['algorithm_case']
    assert set(bundle['llm_case']) == {'case_id','prompt'}
    assert '当前网络有向链路及频谱资源状态' in bundle['llm_case']['prompt']
    assert bundle['benchmark_case']['reference'] == bundle['reference_output']
    assert '分配优先选择最小化总槽位数的方案' in bundle['llm_case']['prompt']
    result=validate_x3_output(bundle['root_case'],bundle['private_truth'],bundle['reference_output'])
    assert result['valid']
    assert result['metrics']['joint_feasible_decision_accuracy'] == 1
    assert result['metrics']['delta_tso_gap'] == 0
    assert result['metrics']['wufr_gap'] == 0.0


def test_x3_partial_accept_is_invalid():
    bundle=build_x3_case(toy_env(slot_count=5), ['r1','r2'], case_id='X3_TEST', max_simple_paths_per_request=100, max_complete_optimal_solutions=10000)
    one=bundle['reference_output']['allocations'][:1]
    result=validate_x3_output(bundle['root_case'],bundle['private_truth'],{'decision':'ACCEPT','allocations':one})
    assert not result['valid']

def test_x3_reference_algorithm3_uses_bounded_pilot_search(monkeypatch):
    from src.tasks.x3 import reference_algorithms as ra
    calls={'n':0}
    original=ra._ExactWufrScorer.score
    def counted(self,allocs):
        calls['n']+=1
        return original(self,allocs)
    monkeypatch.setattr(ra._ExactWufrScorer,'score',counted)
    env=toy_env(slot_count=100)
    bundle=build_x3_case(env,['r1','r2'],case_id='X3_REF_BUDGET',max_simple_paths_per_request=100,max_complete_optimal_solutions=20000)
    # Exact Oracle is allowed to evaluate many solutions, but the reference algorithm panel is pilot-only;
    # its K12 joint search is intentionally bounded at 5,000 complete candidates.
    # Producer runs Exact Oracle before references, so subtract exact-oracle scoring from this count by
    # rerunning only the reference panel on the root and resetting the counter.
    calls['n']=0
    ra.run_x3_reference_algorithms(bundle['root_case'])
    assert calls['n'] <= 5005
