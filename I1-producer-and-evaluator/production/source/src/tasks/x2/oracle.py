from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from src.case_core.full_rsa import (
    FullRsaBudgetExceeded, allowed_links_for_window, enumerate_exact_hop_paths,
    shortest_hop_distance,
)
from src.case_core.search import _ExactWufrScorer
from src.case_core.wufr import WUFR_ABS_TOL, build_reference_paths


@dataclass(frozen=True)
class X2OracleResult:
    feasible: bool
    certification: str
    optimal_hop_count: int | None
    optimal_wufr: float | None
    reference_output: dict
    equivalent_optimum_count: int | None
    evaluated_optimal_actions: int


def solve_x2_exact(nodes:list[int], directed_links:list[dict], spectrum_by_link:dict[int,list[int]], required_slots_probabilities:dict[int,float], request:dict, *, max_simple_paths:int=100000, max_optimal_actions:int=100000) -> X2OracleResult:
    width=int(request['required_slots']); source=int(request['source_node_id']); dest=int(request['destination_node_id'])
    if not spectrum_by_link: raise ValueError('empty spectrum')
    slot_count=len(next(iter(spectrum_by_link.values())))
    window_links=[]; best_hop=None
    for start in range(slot_count-width+1):
        allowed=allowed_links_for_window(directed_links,spectrum_by_link,start,width)
        d=shortest_hop_distance(source,dest,allowed)
        window_links.append((start,allowed,d))
        if d is not None and (best_hop is None or d<best_hop): best_hop=d
    if best_hop is None:
        return X2OracleResult(False,'INFEASIBLE_CERTIFIED',None,None,{'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None},None,0)
    refs=build_reference_paths(nodes,directed_links)
    scorer=_ExactWufrScorer(spectrum_by_link,required_slots_probabilities,refs)
    evaluated=0; best_value=None; best_ref=None; equivalent=0
    for start,allowed,d in window_links:
        if d!=best_hop: continue
        remaining=max_simple_paths-evaluated
        if remaining<=0: raise FullRsaBudgetExceeded(f'X2 optimal action count exceeds max_simple_paths={max_simple_paths}')
        paths=enumerate_exact_hop_paths(source,dest,allowed,best_hop,max_paths=remaining)
        for path in paths:
            evaluated += 1
            if evaluated>max_optimal_actions: raise FullRsaBudgetExceeded(f'X2 optimal action count exceeds max_optimal_actions={max_optimal_actions}')
            val=scorer.score([{'path_link_ids':path['path_link_ids'],'slot_start':start,'required_slots':width}])
            ref={'decision':'ACCEPT','path_node_ids':path['path_node_ids'],'path_link_ids':path['path_link_ids'],'slot_start':start}
            key=(tuple(ref['path_link_ids']),tuple(ref['path_node_ids']),start)
            best_key=(tuple(best_ref['path_link_ids']),tuple(best_ref['path_node_ids']),best_ref['slot_start']) if best_ref else None
            if best_value is None or val<best_value-WUFR_ABS_TOL:
                best_value=float(val); best_ref=ref; equivalent=1
            elif isclose(val,best_value,rel_tol=0.0,abs_tol=WUFR_ABS_TOL):
                equivalent += 1
                if best_key is None or key<best_key: best_ref=ref
    if best_ref is None: raise RuntimeError('X2 exact search internal inconsistency')
    return X2OracleResult(True,'EXACT_CERTIFIED',int(best_hop),float(best_value),best_ref,equivalent,evaluated)
