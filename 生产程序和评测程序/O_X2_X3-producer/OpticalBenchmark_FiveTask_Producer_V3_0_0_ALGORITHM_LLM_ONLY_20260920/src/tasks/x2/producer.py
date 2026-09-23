from __future__ import annotations

import json

from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.spectrum_codec import compress_resource_state
from src.case_core.task_support import resolve_common_context
from src.tasks.x2.oracle import solve_x2_exact
from src.tasks.x2.reference_algorithms import run_x2_reference_algorithms
from src.tasks.x2.validator import validate_x2_output

_PRIVATE=('optimal_hop_count','optimal_wufr_at_optimal_hop','reference_output','private_truth','feasible_slot_starts','oracle_certification')

def _check_public(obj):
    text=json.dumps(obj,ensure_ascii=False,sort_keys=True)
    for token in _PRIVATE:
        if token in text: raise ValueError(f'private field leaked: {token}')

def build_x2_case(env,request_id:str,*,case_id:str,required_slots:int|None=None,max_simple_paths:int=100000,max_optimal_actions:int=100000)->dict:
    req0=env.requests[request_id]; state_id=env.derivations[request_id]['resource_state_id']; common=resolve_common_context(env,state_id)
    req={'request_id':str(req0['request_id']),'source_node_id':int(req0['source_node_id']),'destination_node_id':int(req0['destination_node_id']),'required_slots':int(required_slots if required_slots is not None else req0['required_slots'])}
    if req['required_slots'] not in {2,3,5,9}: raise ValueError('X2 required_slots must be one of 2,3,5,9')
    probs={k:float(v) for k,v in common['required_slots_probabilities'].items()}
    root={'case_id':case_id,'task_type':'X2','topology_id':common['topology_id'],'resource_state_id':state_id,'nodes':common['nodes'],'directed_links':common['directed_links'],'slot_count':common['slot_count'],'link_spectrum_states':common['link_spectrum_states'],'required_slots_probabilities':probs,'request':req}
    sp={int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}
    oracle=solve_x2_exact(root['nodes'],root['directed_links'],sp,{int(k):float(v) for k,v in probs.items()},req,max_simple_paths=max_simple_paths,max_optimal_actions=max_optimal_actions)
    reference=oracle.reference_output
    truth={'case_id':case_id,'task_type':'X2','feasible':oracle.feasible,'oracle_certification':oracle.certification,'optimal_hop_count':oracle.optimal_hop_count,'optimal_wufr_at_optimal_hop':oracle.optimal_wufr,'equivalent_optimum_count':oracle.equivalent_optimum_count,'oracle_evaluated_optimal_actions':oracle.evaluated_optimal_actions}
    public_spectrum=compress_resource_state({'slot_count':root['slot_count'],'link_spectrum_states':root['link_spectrum_states']})
    common_public={'case_id':case_id,'task_type':'X2','topology_id':root['topology_id'],'resource_state_id':state_id,'nodes':root['nodes'],'directed_links':root['directed_links'],'slot_count':root['slot_count'],'link_spectrum_states':public_spectrum,'required_slots_probabilities':probs}
    algorithm={**common_public,'request':req}
    instance=project_algorithm_input('X2', algorithm)
    views=build_benchmark_views(root,reference,strict_frozen_interface=False,instance=instance)
    benchmark=views['benchmark_case']; llm=views['llm_case']
    for obj in (algorithm,llm): _check_public(obj)
    validation=validate_x2_output(root,truth,reference)
    refs=run_x2_reference_algorithms(root)
    features={'node_count':len(root['nodes']),'directed_link_count':len(root['directed_links']),'required_slots':req['required_slots'],'resource_pressure':common['state_metrics'].get('network_spectrum_utilization'),'serialized_char_count_llm':len(llm['prompt']),'oracle_evaluated_optimal_actions':oracle.evaluated_optimal_actions,'reference_algorithms':refs}
    lineage={'source_topology_id':root['topology_id'],'source_resource_state_id':state_id,'source_request_id':request_id,'required_slots_override':required_slots,'derivation_policy':'FULL_TOPOLOGY_X2_NO_K_LIMIT'}
    return {'root_case':root,'algorithm_case':algorithm,'benchmark_case':benchmark,'llm_case':llm,'private_truth':truth,'reference_output':reference,'validation':validation,'features':features,'lineage':lineage}
