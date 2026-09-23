from pathlib import Path
from tests.s1x4_test_utils import minimal_dynamic_environment


def _ep(tmp_path,task):
    from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
    idx=load_dynamic_public_environment(minimal_dynamic_environment(tmp_path,length=3))
    return build_episode_definition(idx,'bs_dynamic_demo',task,f'{task}_case_000001',k=3 if task=='S1' else None,pairing_id='pair')


def test_reference_panels_are_complete_and_deterministic(tmp_path):
    from src.s1_x4.reference_algorithms import run_reference_panel
    s=run_reference_panel(_ep(tmp_path,'S1')); x=run_reference_panel(_ep(tmp_path,'X4'))
    assert [r['policy_name'] for r in s['policy_results']]==['KSP-FF','KSP-BF','FF-KSP','BF-KSP','KME-FF','KSP-EFM']
    assert [r['policy_name'] for r in x['policy_results']][-2:]==['SW-SP','SW-EFM']
    assert s==run_reference_panel(_ep(tmp_path,'S1'))
