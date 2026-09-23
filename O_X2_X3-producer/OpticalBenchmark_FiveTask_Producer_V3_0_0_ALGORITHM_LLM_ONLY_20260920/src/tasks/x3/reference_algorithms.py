from __future__ import annotations

import networkx as nx

from src.case_core.full_rsa import add_masks, feasible_slot_starts, masks_conflict, path_from_nodes, restore_masks
from src.case_core.search import _ExactWufrScorer
from src.case_core.wufr import apply_allocations_copy, build_reference_paths


def _graph(nodes,links):
    g=nx.DiGraph(); g.add_nodes_from(sorted(int(x) for x in nodes))
    for r in sorted(links,key=lambda x:int(x['link_id'])): g.add_edge(int(r['source_node_id']),int(r['destination_node_id']))
    return g

def _kpaths(req,root,k):
    g=_graph(root['nodes'],root['directed_links'])
    try: gen=nx.shortest_simple_paths(g,int(req['source_node_id']),int(req['destination_node_id']))
    except nx.NetworkXNoPath: return []
    out=[]
    try:
        for _ in range(k): out.append(path_from_nodes(next(gen),root['directed_links']))
    except (StopIteration,nx.NetworkXNoPath): pass
    out.sort(key=lambda p:(p['hop_count'],tuple(p['path_link_ids']),tuple(p['path_node_ids'])))
    return out[:k]

def _spectrum(root): return {int(x['link_id']):list(x['slot_availability']) for x in root['link_spectrum_states']}

def _allocate_in_state(state,path,width):
    starts=feasible_slot_starts(path['path_link_ids'],width,state)
    if not starts: return None
    return starts[0]

def _apply(state,path,start,width):
    return apply_allocations_copy(state,[{'path_link_ids':path['path_link_ids'],'slot_start':start,'required_slots':width}])

def _sequential(root,k):
    state=_spectrum(root); out=[]
    for req in root['requests']:
        found=None
        for p in _kpaths(req,root,k):
            s=_allocate_in_state(state,p,int(req['required_slots']))
            if s is not None:
                found=(p,s); break
        if found is None: return None
        p,s=found; out.append({'request_id':req['request_id'],'path_node_ids':p['path_node_ids'],'path_link_ids':p['path_link_ids'],'slot_start':s}); state=_apply(state,p,s,int(req['required_slots']))
    return {'decision':'ACCEPT','allocations':out}

def _score(root,output):
    if output is None: return None
    reqs={r['request_id']:r for r in root['requests']}; delta=0; full=[]
    for a in output['allocations']:
        r=reqs[a['request_id']]; w=int(r['required_slots']); delta+=w*len(a['path_link_ids']); full.append({'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start'],'required_slots':w})
    refs=build_reference_paths(root['nodes'],root['directed_links']); scorer=_ExactWufrScorer(_spectrum(root),{int(k):float(v) for k,v in root['required_slots_probabilities'].items()},refs)
    return {'output':output,'delta_tso':delta,'post_wufr':float(scorer.score(full))}

def _joint_k12(root, incumbent=None, max_complete=5000):
    reqs=root['requests']; base=_spectrum(root); per={}
    for r in reqs:
        actions=[]
        for p in _kpaths(r,root,12):
            for s in feasible_slot_starts(p['path_link_ids'],int(r['required_slots']),base): actions.append({**p,'slot_start':s,'required_slots':int(r['required_slots'])})
        if not actions: return None
        actions.sort(key=lambda a:(a['required_slots']*a['hop_count'],tuple(a['path_link_ids']),a['slot_start'])); per[r['request_id']]=actions
    visit=sorted([r['request_id'] for r in reqs],key=lambda rid:(len(per[rid]),rid)); input_order=[r['request_id'] for r in reqs]; occupied={}; chosen={}; best=None; complete=0
    refs=build_reference_paths(root['nodes'],root['directed_links']); scorer=_ExactWufrScorer(base,{int(k):float(v) for k,v in root['required_slots_probabilities'].items()},refs)
    if incumbent is not None:
        scored=_score(root,incumbent)
        ikey=(scored['delta_tso'],scored['post_wufr'],tuple((x['request_id'],tuple(x['path_link_ids']),x['slot_start']) for x in incumbent['allocations']))
        best=(scored['delta_tso'],scored['post_wufr'],ikey,incumbent)
    def rec(i,cost):
        nonlocal best,complete
        if complete>=max_complete: return
        if best is not None and cost>best[0]: return
        if i==len(visit):
            complete+=1; full=[]; pubs=[]
            for rid in input_order:
                a=chosen[rid]; full.append({'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start'],'required_slots':a['required_slots']}); pubs.append({'request_id':rid,'path_node_ids':a['path_node_ids'],'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start']})
            w=float(scorer.score(full)); key=(cost,w,tuple((x['request_id'],tuple(x['path_link_ids']),x['slot_start']) for x in pubs))
            if best is None or key<best[2]: best=(cost,w,key,{'decision':'ACCEPT','allocations':pubs})
            return
        rid=visit[i]
        for a in per[rid]:
            ncost=cost+a['required_slots']*a['hop_count']
            if best is not None and ncost>best[0]: break
            if masks_conflict(occupied,a): continue
            ch=add_masks(occupied,a); chosen[rid]=a; rec(i+1,ncost); chosen.pop(rid,None); restore_masks(occupied,ch)
    rec(0,0)
    return None if best is None else best[3]

def run_x3_reference_algorithms(root:dict)->dict:
    a1=_sequential(root,1); a2=_sequential(root,5); a3=_joint_k12(root,incumbent=a2,max_complete=5000)
    return {'algorithm_1_sp_ff':_score(root,a1),'algorithm_2_ksp5_ff':_score(root,a2),'algorithm_3_joint_backtrack_k12':_score(root,a3)}
