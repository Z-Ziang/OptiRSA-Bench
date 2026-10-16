"""Recompute frozen historical O2 inputs without regenerating paths or requests."""
from copy import deepcopy
import hashlib,json
from src.case_core.o2_lexicographic import O2S_CONTRACT,O2C_CONTRACT,search_single_optimum,search_joint_optimum
from src.case_core.path_validation import validate_directed_path
from src.case_core.spectrum_codec import occupied_ranges_to_binary
from src.case_core.task_support import spectrum_by_link,q_numeric
from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.projection import assert_no_private_leak
from src.tasks.o2_s.validator import validate_o2s_output
from src.tasks.o2_c.validator import validate_o2c_output

CONTRACTS={'O2-S':O2S_CONTRACT,'O2-C':O2C_CONTRACT}

def scientific_key(algorithm,source_binding):
    task=algorithm['task_type']
    if task not in CONTRACTS:raise ValueError('migration supports O2-S/O2-C only')
    semantic=deepcopy({k:v for k,v in algorithm.items() if k not in ('case_id','objective_contract_id')})
    # Presentation order is irrelevant to the static optimization problem.
    # IDs, directed attributes, candidate ranks and each path's traversal order remain intact.
    semantic['nodes']=sorted(semantic['nodes'])
    semantic['directed_links']=sorted(semantic['directed_links'],key=lambda row:row['link_id'])
    semantic['spectrum_states']=sorted(semantic['spectrum_states'],key=lambda row:row['link_id'])
    if task=='O2-C':semantic['requests']=sorted(semantic['requests'],key=lambda row:row['request_id'])
    identity={k:source_binding[k] for k in ('source_batch_id','source_id','graph_hash','candidate_k','snapshot_hash','seed_policy') if k in source_binding}
    return hashlib.sha256(json.dumps({'input':semantic,'contract':CONTRACTS[task],'source_identity':identity},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def root_from_algorithm(algorithm):
    task=algorithm['task_type']
    if task not in CONTRACTS:raise ValueError('migration supports O2-S/O2-C only')
    nodes=algorithm['nodes'];links=algorithm['directed_links'];node_set=set(nodes)
    if len(node_set)!=len(nodes):raise ValueError('duplicate node')
    ids=[x['link_id'] for x in links]
    if len(set(ids))!=len(ids):raise ValueError('duplicate directed link')
    if any(x['source_node_id'] not in node_set or x['destination_node_id'] not in node_set for x in links):raise ValueError('link endpoint absent')
    states=algorithm['spectrum_states']
    if len(states)!=len(ids) or {x['link_id'] for x in states}!=set(ids):raise ValueError('spectrum link identity mismatch')
    q_numeric(algorithm['required_slots_probabilities'])
    root={k:deepcopy(algorithm[k]) for k in ('case_id','task_type','topology_id','resource_state_id','nodes','directed_links','slot_count','required_slots_probabilities')}
    root['objective_contract_id']=CONTRACTS[task]
    root['link_spectrum_states']=[{'link_id':x['link_id'],'slot_availability':occupied_ranges_to_binary(root['slot_count'],x['occupied_ranges'])} for x in states]
    if task=='O2-S':root['request']=deepcopy(algorithm['request']);root['candidate_paths']=deepcopy(algorithm['candidate_paths']);requests=[{**root['request'],'candidate_paths':root['candidate_paths']}]
    else:root['requests']=deepcopy(algorithm['requests']);requests=root['requests']
    if task=='O2-C' and (len(requests)<2 or len({r['request_id'] for r in requests})!=len(requests)):raise ValueError('joint requests must be distinct')
    for req in requests:
        if req['required_slots'] not in (2,3,5,9):raise ValueError('invalid required slots')
        if req['source_node_id']==req['destination_node_id']:raise ValueError('identical request endpoints')
        paths=req['candidate_paths']
        if not paths or [p['path_rank'] for p in paths]!=list(range(1,len(paths)+1)):raise ValueError('candidate path ranks not contiguous')
        for p in paths:
            valid=validate_directed_path(p['path_link_ids'],p['path_node_ids'],links,req['source_node_id'],req['destination_node_id'])
            if not valid.valid:raise ValueError('invalid candidate path: '+str(valid.error))
    return root

def recompute_algorithm_case(algorithm,*,case_id,source_binding,max_complete_solutions=100_000):
    original=deepcopy(algorithm);root=root_from_algorithm(original);root['case_id']=str(case_id)
    task=root['task_type'];contract=CONTRACTS[task]
    args=(root['nodes'],root['directed_links'],spectrum_by_link(root),q_numeric(root['required_slots_probabilities']))
    if task=='O2-S':
        result=search_single_optimum(*args,root['request']['required_slots'],root['candidate_paths'],max_complete_solutions=max_complete_solutions)
        reference={'decision':'ACCEPT',**result.reference_action} if result.feasible else {'decision':'REJECT','path_rank':None,'slot_start':None}
        primary='optimal_hop_count';feasible_key='feasible';validator=validate_o2s_output
    else:
        requests=[{'request_id':r['request_id'],'required_slots':r['required_slots'],'paths':r['candidate_paths']} for r in root['requests']]
        result=search_joint_optimum(*args,requests,max_complete_solutions=max_complete_solutions)
        reference={'decision':'ACCEPT',**result.reference_action} if result.feasible else {'decision':'REJECT','allocations':[]}
        primary='optimal_delta_tso';feasible_key='joint_feasible';validator=validate_o2c_output
    truth={'case_id':str(case_id),'task_type':task,'objective_contract_id':contract,feasible_key:result.feasible,primary:result.optimal_primary,'optimal_wufr':result.optimal_wufr,'equivalent_optimum_count':result.equivalent_optimum_count,'oracle_certification':result.certification,'reference_output':reference,'solver_work':{k:getattr(result,k) for k in ('search_nodes','evaluated_complete_solutions','evaluated_primary_solutions','evaluated_secondary_solutions')}}
    updated=deepcopy(original);updated['case_id']=str(case_id);updated['objective_contract_id']=contract
    views=build_benchmark_views(root,reference,strict_frozen_interface=root['slot_count']==320,instance=project_algorithm_input(task,updated),language='en')
    for obj in (updated,views['llm_case']):assert_no_private_leak(obj)
    validation=validator(root,truth,reference)
    if not validation['valid'] or (result.feasible and not validation.get('lexicographic_optimal')):raise ValueError('new exact reference failed Validator')
    return {'root_case':root,'algorithm_case':updated,**views,'private_truth':truth,'reference_output':reference,'validation':validation,'features':{'node_count':len(root['nodes']),'request_count':1 if task=='O2-S' else len(root['requests']),'effective_candidate_k':[len(root['candidate_paths'])] if task=='O2-S' else [len(r['candidate_paths']) for r in root['requests']],'oracle_evaluated_complete_solutions':result.evaluated_complete_solutions},'lineage':{'previous_case_id':original['case_id'],'source_binding':deepcopy(source_binding),'objective_contract_id':contract,'scientific_key':scientific_key(original,source_binding),'migration':'same frozen inputs, independently recomputed V2 exact objectives','default_k_applies_to_future_production_only':True}}
