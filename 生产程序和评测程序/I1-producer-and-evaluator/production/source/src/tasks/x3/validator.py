from __future__ import annotations

from src.case_core.allocation_validation import is_assignment_feasible
from src.case_core.path_validation import validate_directed_path
from src.case_core.task_support import validate_output_schema
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def _spectrum(root): return {int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}

def _q(root): return {int(k):float(v) for k,v in root['required_slots_probabilities'].items()}


def validate_x3_output(root_case:dict,truth:dict,output:dict)->dict:
    errors=validate_output_schema('X3',output)
    metrics={'joint_feasible_decision_accuracy':0,'delta_tso_gap':None,'wufr_gap':None}
    result={'valid':False,'errors':errors,'metrics':metrics,'submitted_delta_tso':None,'submitted_wufr':None}
    if errors: return result
    feasible=bool(truth['joint_feasible'])
    if output['decision']=='REJECT':
        metrics['joint_feasible_decision_accuracy']=int(not feasible); result['valid']=not feasible
        if feasible: errors.append('REJECT is incorrect because a full-space joint feasible solution exists')
        return result
    reqs={str(r['request_id']):r for r in root_case['requests']}
    allocs=output['allocations']; ids=[str(a['request_id']) for a in allocs]
    if len(ids)!=len(set(ids)) or set(ids)!=set(reqs):
        errors.append('ACCEPT must contain exactly one allocation for every request_id'); return result
    sp=_spectrum(root_case); occupied=set(); delta=0; full=[]
    for a in allocs:
        rid=str(a['request_id']); req=reqs[rid]
        check=validate_directed_path(a['path_link_ids'],a['path_node_ids'],root_case['directed_links'],int(req['source_node_id']),int(req['destination_node_id']))
        if not check.valid: errors.append(f'{rid}: {check.error}'); return result
        width=int(req['required_slots']); start=a['slot_start']
        if not is_assignment_feasible(a['path_link_ids'],start,width,sp): errors.append(f'{rid}: allocation is not spectrum-feasible'); return result
        cells={(int(lid),slot) for lid in a['path_link_ids'] for slot in range(start,start+width)}
        if not occupied.isdisjoint(cells): errors.append(f'{rid}: allocation conflicts with another new request'); return result
        occupied.update(cells); delta += width*len(a['path_link_ids']); full.append({'path_link_ids':a['path_link_ids'],'slot_start':start,'required_slots':width})
    if not feasible: errors.append('truth inconsistency: legal ACCEPT found while truth is infeasible'); return result
    result['submitted_delta_tso']=delta; gap=delta-int(truth['optimal_delta_tso'])
    if gap<0: errors.append('submitted delta_tso below stored optimum; truth is inconsistent'); return result
    metrics['joint_feasible_decision_accuracy']=1; metrics['delta_tso_gap']=gap; result['valid']=True
    post=apply_allocations_copy(sp,full); w=network_wufr(root_case['nodes'],root_case['directed_links'],post,_q(root_case)); result['submitted_wufr']=float(w)
    if gap==0:
        wg=w-float(truth['optimal_wufr_at_optimal_delta_tso'])
        if abs(wg)<=WUFR_ABS_TOL: wg=0.0
        if wg<-WUFR_ABS_TOL: errors.append('submitted WUFR below stored optimum; truth is inconsistent'); result['valid']=False; return result
        metrics['wufr_gap']=float(wg)
    return result
