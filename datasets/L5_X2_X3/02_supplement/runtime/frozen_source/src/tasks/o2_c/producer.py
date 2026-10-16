"""Frozen oracle-contained O2-C production; full-space joint X3 truth first."""
from src.case_core.task_support import resolve_common_context,source_resource_state_id
from src.case_core.oracle_o2_production import build_from_full_root

def build_o2c_case(env,request_ids,*,case_id,candidate_k=3,max_complete_solutions=100000):
    if len(request_ids)<2 or len(set(request_ids))!=len(request_ids):raise ValueError('distinct concurrent request group required')
    state=source_resource_state_id(env,request_ids);common=resolve_common_context(env,state)
    root={k:common[k] for k in ('topology_id','resource_state_id','nodes','directed_links','slot_count','link_spectrum_states','required_slots_probabilities')}
    root.update(case_id=case_id,task_type='X3',requests=[{k:env.requests[rid][k] for k in ('request_id','source_node_id','destination_node_id','required_slots')} for rid in request_ids])
    return build_from_full_root(root,target_task='O2-C',case_id=case_id,source_binding={'source_topology_id':root['topology_id'],'source_resource_state_id':state,'source_request_ids':list(request_ids)},candidate_k=candidate_k,max_complete_solutions=max_complete_solutions)
