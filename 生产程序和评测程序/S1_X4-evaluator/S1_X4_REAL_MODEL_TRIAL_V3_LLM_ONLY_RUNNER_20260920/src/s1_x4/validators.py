from __future__ import annotations
from src.case_core.path_validation import validate_directed_path
from src.case_core.allocation_validation import is_assignment_feasible


def _decision_obj(response):
    if not isinstance(response,dict): return None,'response must be a JSON object'
    d=response.get('decision')
    if d not in {'ACCEPT','REJECT'}: return None,'decision must be ACCEPT or REJECT'
    return d,None


def validate_s1_response(response: dict, context: dict) -> dict:
    decision,error=_decision_obj(response)
    if error: return {'valid':False,'decision':None,'error':error}
    expected={'decision','path_rank','slot_start'}
    if set(response)!=expected: return {'valid':False,'decision':decision,'error':'S1 response fields must be exactly decision,path_rank,slot_start'}
    if decision=='REJECT':
        if response['path_rank'] is not None or response['slot_start'] is not None:
            return {'valid':False,'decision':'REJECT','error':'REJECT requires null path_rank and slot_start'}
        return {'valid':True,'decision':'REJECT','path_rank':None,'slot_start':None,'path_node_ids':[],'path_link_ids':[],'error':None}
    rank=response['path_rank']; start=response['slot_start']
    if not isinstance(rank,int) or isinstance(rank,bool) or not isinstance(start,int) or isinstance(start,bool):
        return {'valid':False,'decision':'ACCEPT','error':'path_rank and slot_start must be integers'}
    match=next((a for a in context.get('candidate_actions',[]) if int(a['path_rank'])==rank and int(a['slot_start'])==start),None)
    if match is None: return {'valid':False,'decision':'ACCEPT','path_rank':rank,'slot_start':start,'error':'action is not in the public feasible action set'}
    return {'valid':True,'decision':'ACCEPT','path_rank':rank,'slot_start':start,'path_node_ids':list(match['path_node_ids']),'path_link_ids':list(match['path_link_ids']),'error':None}


def validate_x4_response(response: dict, context: dict) -> dict:
    decision,error=_decision_obj(response)
    if error: return {'valid':False,'decision':None,'error':error}
    expected={'decision','path_node_ids','path_link_ids','slot_start'}
    if set(response)!=expected: return {'valid':False,'decision':decision,'error':'X4 response fields must be exactly decision,path_node_ids,path_link_ids,slot_start'}
    nodes=response['path_node_ids']; links=response['path_link_ids']; start=response['slot_start']
    if decision=='REJECT':
        if nodes!=[] or links!=[] or start is not None: return {'valid':False,'decision':'REJECT','error':'REJECT requires empty path arrays and null slot_start'}
        return {'valid':True,'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None,'error':None}
    if not isinstance(nodes,list) or not isinstance(links,list) or not isinstance(start,int) or isinstance(start,bool):
        return {'valid':False,'decision':'ACCEPT','error':'invalid ACCEPT field types'}
    if not all(isinstance(x,int) and not isinstance(x,bool) for x in nodes+links):
        return {'valid':False,'decision':'ACCEPT','error':'path ids must be integers'}
    req=context['request']
    pv=validate_directed_path(links,nodes,context['directed_links'],int(req['source_node_id']),int(req['destination_node_id']))
    if not pv.valid: return {'valid':False,'decision':'ACCEPT','path_node_ids':nodes,'path_link_ids':links,'slot_start':start,'error':pv.error}
    if not is_assignment_feasible(links,start,int(req['required_slots']),context['spectrum_by_link']):
        return {'valid':False,'decision':'ACCEPT','path_node_ids':nodes,'path_link_ids':links,'slot_start':start,'error':'spectrum allocation is infeasible'}
    return {'valid':True,'decision':'ACCEPT','path_node_ids':nodes,'path_link_ids':links,'slot_start':start,'error':None}
