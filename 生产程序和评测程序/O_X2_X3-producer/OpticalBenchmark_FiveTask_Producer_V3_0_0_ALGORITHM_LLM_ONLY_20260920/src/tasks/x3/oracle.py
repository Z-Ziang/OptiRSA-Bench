from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from src.case_core.full_rsa import FullRsaBudgetExceeded, add_masks, enumerate_feasible_actions_for_request, masks_conflict, restore_masks
from src.case_core.search import _ExactWufrScorer
from src.case_core.wufr import WUFR_ABS_TOL, build_reference_paths


@dataclass(frozen=True)
class X3OracleResult:
    feasible: bool
    certification: str
    optimal_delta_tso: int | None
    optimal_wufr: float | None
    reference_output: dict
    equivalent_optimum_count: int | None
    search_nodes: int
    evaluated_optimal_solutions: int
    path_counts: dict[str,int]
    action_counts: dict[str,int]


def _public_item(rid:str, action:dict)->dict:
    return {'request_id':rid,'path_node_ids':list(action['path_node_ids']),'path_link_ids':list(action['path_link_ids']),'slot_start':int(action['slot_start'])}


def solve_x3_exact(nodes:list[int],directed_links:list[dict],spectrum_by_link:dict[int,list[int]],required_slots_probabilities:dict[int,float],requests:list[dict],*,max_simple_paths_per_request:int=5000,max_search_nodes:int=2_000_000,max_complete_optimal_solutions:int=100000)->X3OracleResult:
    if len(requests)<2: raise ValueError('X3 requires at least 2 requests')
    per={}; path_counts={}; action_counts={}; input_order=[]
    for req in requests:
        rid=str(req['request_id']); input_order.append(rid)
        actions,pcount=enumerate_feasible_actions_for_request(req,directed_links,spectrum_by_link,max_paths=max_simple_paths_per_request)
        path_counts[rid]=pcount; action_counts[rid]=len(actions)
        if not actions:
            return X3OracleResult(False,'INFEASIBLE_CERTIFIED',None,None,{'decision':'REJECT','allocations':[]},None,0,0,path_counts,action_counts)
        per[rid]=actions
    visit=sorted(input_order,key=lambda r:(len(per[r]),r))
    min_cost={rid:min(a['delta_tso_contribution'] for a in per[rid]) for rid in visit}
    suffix=[0]*(len(visit)+1)
    for i in range(len(visit)-1,-1,-1): suffix[i]=suffix[i+1]+min_cost[visit[i]]
    occupied={}; chosen={}; best_cost=None; search_nodes=0

    def stage1(i:int,cost:int):
        nonlocal best_cost,search_nodes
        search_nodes += 1
        if search_nodes>max_search_nodes: raise FullRsaBudgetExceeded(f'X3 joint search exceeds max_search_nodes={max_search_nodes}')
        if best_cost is not None and cost+suffix[i]>best_cost: return
        if i==len(visit):
            if best_cost is None or cost<best_cost: best_cost=cost
            return
        rid=visit[i]
        for action in per[rid]:
            ncost=cost+int(action['delta_tso_contribution'])
            if best_cost is not None and ncost+suffix[i+1]>best_cost: break
            if masks_conflict(occupied,action): continue
            changed=add_masks(occupied,action); chosen[rid]=action
            stage1(i+1,ncost)
            chosen.pop(rid,None); restore_masks(occupied,changed)
    stage1(0,0)
    if best_cost is None:
        return X3OracleResult(False,'INFEASIBLE_CERTIFIED',None,None,{'decision':'REJECT','allocations':[]},None,search_nodes,0,path_counts,action_counts)

    refs=build_reference_paths(nodes,directed_links); scorer=_ExactWufrScorer(spectrum_by_link,required_slots_probabilities,refs)
    occupied.clear(); chosen.clear(); evaluated=0; best_w=None; best_ref=None; equivalent=0
    # exact lower bound remains valid; second pass only explores cost exactly best_cost
    def stage2(i:int,cost:int):
        nonlocal evaluated,best_w,best_ref,equivalent,search_nodes
        search_nodes += 1
        if search_nodes>max_search_nodes: raise FullRsaBudgetExceeded(f'X3 joint search exceeds max_search_nodes={max_search_nodes}')
        if cost+suffix[i]>best_cost: return
        if i==len(visit):
            if cost!=best_cost: return
            evaluated += 1
            if evaluated>max_complete_optimal_solutions: raise FullRsaBudgetExceeded(f'X3 optimal complete solutions exceed max_complete_optimal_solutions={max_complete_optimal_solutions}')
            full=[]; pubs=[]
            for rid in input_order:
                a=chosen[rid]
                full.append({'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start'],'required_slots':a['required_slots']})
                pubs.append(_public_item(rid,a))
            w=float(scorer.score(full)); ref={'decision':'ACCEPT','allocations':pubs}
            key=tuple((x['request_id'],tuple(x['path_link_ids']),tuple(x['path_node_ids']),x['slot_start']) for x in pubs)
            best_key=tuple((x['request_id'],tuple(x['path_link_ids']),tuple(x['path_node_ids']),x['slot_start']) for x in best_ref['allocations']) if best_ref else None
            if best_w is None or w<best_w-WUFR_ABS_TOL:
                best_w=w; best_ref=ref; equivalent=1
            elif isclose(w,best_w,rel_tol=0.0,abs_tol=WUFR_ABS_TOL):
                equivalent += 1
                if best_key is None or key<best_key: best_ref=ref
            return
        rid=visit[i]
        for action in per[rid]:
            ncost=cost+int(action['delta_tso_contribution'])
            if ncost+suffix[i+1]>best_cost: break
            if masks_conflict(occupied,action): continue
            changed=add_masks(occupied,action); chosen[rid]=action
            stage2(i+1,ncost)
            chosen.pop(rid,None); restore_masks(occupied,changed)
    stage2(0,0)
    if best_ref is None: raise RuntimeError('X3 exact second-level search internal inconsistency')
    return X3OracleResult(True,'EXACT_CERTIFIED',int(best_cost),float(best_w),best_ref,equivalent,search_nodes,evaluated,path_counts,action_counts)
