from __future__ import annotations

from src.case_core.allocation_validation import is_assignment_feasible
from src.case_core.path_validation import validate_directed_path
from src.case_core.task_support import validate_output_schema
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def _spectrum(root): return {int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}

def _q(root): return {int(k):float(v) for k,v in root['required_slots_probabilities'].items()}


def validate_x2_output(root_case:dict,truth:dict,output:dict)->dict:
    errors=validate_output_schema('X2',output)
    metrics={'feasible_decision_accuracy':0,'hop_gap':None,'wufr_gap':None}
    result={'valid':False,'errors':errors,'metrics':metrics,'submitted_hop_count':None,'submitted_wufr':None}
    if errors: return result
    feasible=bool(truth['feasible'])
    if output['decision']=='REJECT':
        metrics['feasible_decision_accuracy']=int(not feasible); result['valid']=not feasible
        if feasible: errors.append('REJECT is incorrect because a full-space feasible RSA action exists')
        return result
    req=root_case['request']; check=validate_directed_path(output['path_link_ids'],output['path_node_ids'],root_case['directed_links'],int(req['source_node_id']),int(req['destination_node_id']))
    if not check.valid: errors.append(check.error); return result
    sp=_spectrum(root_case)
    if not is_assignment_feasible(output['path_link_ids'],output['slot_start'],int(req['required_slots']),sp):
        errors.append('submitted allocation is not spectrum-feasible'); return result
    if not feasible: errors.append('truth inconsistency: legal ACCEPT found while truth is infeasible'); return result
    hop=len(output['path_link_ids']); result['submitted_hop_count']=hop
    gap=hop-int(truth['optimal_hop_count'])
    if gap<0: errors.append('submitted hop count below stored optimum; truth is inconsistent'); return result
    metrics['feasible_decision_accuracy']=1; metrics['hop_gap']=gap; result['valid']=True
    post=apply_allocations_copy(sp,[{'path_link_ids':output['path_link_ids'],'slot_start':output['slot_start'],'required_slots':int(req['required_slots'])}])
    submitted=network_wufr(root_case['nodes'],root_case['directed_links'],post,_q(root_case)); result['submitted_wufr']=float(submitted)
    if gap==0:
        wgap=submitted-float(truth['optimal_wufr_at_optimal_hop'])
        if abs(wgap)<=WUFR_ABS_TOL: wgap=0.0
        if wgap < -WUFR_ABS_TOL: errors.append('submitted WUFR below stored optimum; truth is inconsistent'); result['valid']=False; return result
        metrics['wufr_gap']=float(wgap)
    return result
