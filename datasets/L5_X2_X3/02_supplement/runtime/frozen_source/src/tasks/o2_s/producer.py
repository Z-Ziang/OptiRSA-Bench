"""Frozen oracle-contained O2-S production; full-space X2 truth first."""
from src.case_core.task_support import resolve_common_context
from src.case_core.oracle_o2_production import build_from_full_root

def build_o2s_case(env,request_id,*,case_id,candidate_k=3,max_complete_solutions=100000):
    req=env.requests[request_id];state=env.derivations[request_id]['resource_state_id'];common=resolve_common_context(env,state)
    root={k:common[k] for k in ('topology_id','resource_state_id','nodes','directed_links','slot_count','link_spectrum_states','required_slots_probabilities')}
    root.update(case_id=case_id,task_type='X2',request={k:req[k] for k in ('request_id','source_node_id','destination_node_id','required_slots')})
    return build_from_full_root(root,target_task='O2-S',case_id=case_id,source_binding={'source_topology_id':root['topology_id'],'source_resource_state_id':state,'source_request_id':request_id},candidate_k=candidate_k,max_complete_solutions=max_complete_solutions)
