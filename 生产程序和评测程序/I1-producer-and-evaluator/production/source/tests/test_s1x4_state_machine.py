from pathlib import Path
from tests.s1x4_test_utils import minimal_dynamic_environment


def _session(tmp_path,task='S1'):
    from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
    from src.s1_x4.state_machine import DynamicEpisodeState
    idx=load_dynamic_public_environment(minimal_dynamic_environment(tmp_path,length=2))
    ep=build_episode_definition(idx,'bs_dynamic_demo',task,f'{task}_case_000001',k=3 if task=='S1' else None,pairing_id='pair')
    return ep,DynamicEpisodeState(ep)


def test_release_happens_before_first_decision(tmp_path):
    ep,st=_session(tmp_path)
    ctx=st.prepare_current_step()
    assert ctx['released_connection_count_before_decision']==1
    assert ctx['spectrum_by_link'][0][0]==1


def test_s1_invalid_action_blocks_without_state_pollution(tmp_path):
    from src.s1_x4.validators import validate_s1_response
    ep,st=_session(tmp_path)
    ctx=st.prepare_current_step(); before={k:list(v) for k,v in st.spectrum_by_link.items()}
    vr=validate_s1_response({'decision':'ACCEPT','path_rank':999,'slot_start':0},ctx)
    result=st.commit_step(vr)
    assert result['blocked'] is True and st.spectrum_by_link==before


def test_s1_valid_action_establishes(tmp_path):
    from src.s1_x4.validators import validate_s1_response
    ep,st=_session(tmp_path); ctx=st.prepare_current_step(); a=ctx['candidate_actions'][0]
    vr=validate_s1_response({'decision':'ACCEPT','path_rank':a['path_rank'],'slot_start':a['slot_start']},ctx)
    result=st.commit_step(vr)
    assert result['established'] and not result['blocked']


def test_x4_validates_full_path_and_reject_is_operational_block(tmp_path):
    from src.s1_x4.validators import validate_x4_response
    ep,st=_session(tmp_path,'X4'); ctx=st.prepare_current_step()
    # deterministic route 0->1->3 after seed connection release
    vr=validate_x4_response({'decision':'ACCEPT','path_node_ids':[0,1,3],'path_link_ids':[0,2],'slot_start':0},ctx)
    assert vr['valid']
    st.commit_step(vr)
    ctx2=st.prepare_current_step(); vr2=validate_x4_response({'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None},ctx2)
    r=st.commit_step(vr2); assert r['blocked'] and not r['established']
