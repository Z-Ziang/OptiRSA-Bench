from __future__ import annotations

import json

from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.spectrum_codec import compress_resource_state
from src.case_core.task_support import resolve_common_context, source_resource_state_id
from src.tasks.x3.oracle import solve_x3_exact
from src.tasks.x3.reference_algorithms import run_x3_reference_algorithms
from src.tasks.x3.validator import validate_x3_output

_PRIVATE=('optimal_delta_tso','optimal_wufr_at_optimal_delta_tso','reference_output','private_truth','oracle_certification','feasible_slot_starts')

def _check_public(obj):
    text=json.dumps(obj,ensure_ascii=False,sort_keys=True)
    for token in _PRIVATE:
        if token in text: raise ValueError(f'private field leaked: {token}')

def build_x3_case(env,request_ids:list[str],*,case_id:str,max_simple_paths_per_request:int=5000,max_search_nodes:int=2_000_000,max_complete_optimal_solutions:int=100000)->dict:
    if len(request_ids)<2: raise ValueError('X3 requires at least 2 requests')
    state_id=source_resource_state_id(env,request_ids); common=resolve_common_context(env,state_id); reqs=[]
    for rid in request_ids:
        r=env.requests[rid]; req={'request_id':str(r['request_id']),'source_node_id':int(r['source_node_id']),'destination_node_id':int(r['destination_node_id']),'required_slots':int(r['required_slots'])}
        if req['required_slots'] not in {2,3,5,9}: raise ValueError('X3 required_slots must be one of 2,3,5,9')
        reqs.append(req)
    probs={k:float(v) for k,v in common['required_slots_probabilities'].items()}
    root={'case_id':case_id,'task_type':'X3','topology_id':common['topology_id'],'resource_state_id':state_id,'nodes':common['nodes'],'directed_links':common['directed_links'],'slot_count':common['slot_count'],'link_spectrum_states':common['link_spectrum_states'],'required_slots_probabilities':probs,'requests':reqs}
    sp={int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}
    oracle=solve_x3_exact(root['nodes'],root['directed_links'],sp,{int(k):float(v) for k,v in probs.items()},reqs,max_simple_paths_per_request=max_simple_paths_per_request,max_search_nodes=max_search_nodes,max_complete_optimal_solutions=max_complete_optimal_solutions)
    truth={'case_id':case_id,'task_type':'X3','joint_feasible':oracle.feasible,'oracle_certification':oracle.certification,'optimal_delta_tso':oracle.optimal_delta_tso,'optimal_wufr_at_optimal_delta_tso':oracle.optimal_wufr,'equivalent_optimum_count':oracle.equivalent_optimum_count,'oracle_search_nodes':oracle.search_nodes,'oracle_evaluated_optimal_solutions':oracle.evaluated_optimal_solutions}
    reference=oracle.reference_output; public_spectrum=compress_resource_state({'slot_count':root['slot_count'],'link_spectrum_states':root['link_spectrum_states']})
    common_public={'case_id':case_id,'task_type':'X3','topology_id':root['topology_id'],'resource_state_id':state_id,'nodes':root['nodes'],'directed_links':root['directed_links'],'slot_count':root['slot_count'],'link_spectrum_states':public_spectrum,'required_slots_probabilities':probs}
    algorithm={**common_public,'requests':reqs}
    instance=project_algorithm_input('X3', algorithm)
    views=build_benchmark_views(root,reference,strict_frozen_interface=False,instance=instance)
    benchmark=views['benchmark_case']; llm=views['llm_case']
    for obj in (algorithm,llm): _check_public(obj)
    validation=validate_x3_output(root,truth,reference); refs=run_x3_reference_algorithms(root)
    features={'node_count':len(root['nodes']),'directed_link_count':len(root['directed_links']),'request_count':len(reqs),'total_required_slots':sum(r['required_slots'] for r in reqs),'mean_required_slots':sum(r['required_slots'] for r in reqs)/len(reqs),'max_required_slots':max(r['required_slots'] for r in reqs),'resource_pressure':common['state_metrics'].get('network_spectrum_utilization'),'serialized_char_count_llm':len(llm['prompt']),'oracle_path_counts':oracle.path_counts,'oracle_action_counts':oracle.action_counts,'oracle_search_nodes':oracle.search_nodes,'oracle_evaluated_optimal_solutions':oracle.evaluated_optimal_solutions,'reference_algorithms':refs}
    lineage={'source_topology_id':root['topology_id'],'source_resource_state_id':state_id,'source_request_ids':list(request_ids),'request_order':list(request_ids),'derivation_policy':'FULL_TOPOLOGY_X3_NO_K_LIMIT'}
    return {'root_case':root,'algorithm_case':algorithm,'benchmark_case':benchmark,'llm_case':llm,'private_truth':truth,'reference_output':reference,'validation':validation,'features':features,'lineage':lineage}
