"""Exact O2 V2 lexicographic search within the unchanged public candidate sets.

The fragmentation definition and tolerance come from the frozen shared scorer.
Joint stage1 proves the minimum new slots-on-links; stage2 proves fragmentation
optimality conditional on that minimum. Safe integer lower bounds prune only
branches that cannot improve the relevant stage objective. Exceeding the complete
solution budget raises and never returns a partial optimum or infeasibility.
"""
from dataclasses import dataclass
from math import isclose
from src.case_core.search import SearchBudgetExceeded, enumerate_feasible_actions, _ExactWufrScorer
from src.case_core.wufr import WUFR_ABS_TOL, build_reference_paths

O2S_CONTRACT='O2-S_CASE_CONTRACT_V2_0_LEXICOGRAPHIC'
O2C_CONTRACT='O2-C_CASE_CONTRACT_V2_0_LEXICOGRAPHIC'

@dataclass(frozen=True)
class O2SearchResult:
    feasible: bool
    optimal_wufr: float | None
    reference_action: dict | None
    equivalent_optimum_count: int | None
    evaluated_complete_solutions: int
    optimal_primary: int | None
    certification: str
    search_nodes: int
    evaluated_primary_solutions: int = 0
    evaluated_secondary_solutions: int = 0

def _budget(evaluated,maximum,phase):
    if evaluated > maximum:
        e=SearchBudgetExceeded(f'O2 exact search exceeded {maximum} evaluated complete solutions in {phase}')
        e.evaluated_complete_solutions=evaluated;e.phase=phase
        raise e

def _empty(nodes=0,primary_completes=0):
    return O2SearchResult(False,None,None,None,primary_completes,None,'INFEASIBLE_CERTIFIED',nodes,primary_completes,0)

def search_single_optimum(nodes,directed_links,spectrum_by_link,required_slots_probabilities,required_slots,paths,*,max_complete_solutions=100_000):
    if max_complete_solutions<1:raise ValueError('positive complete-solution budget required')
    actions=enumerate_feasible_actions(paths,required_slots,spectrum_by_link)
    if not actions:return _empty()
    # Keep the original conservative single-request action-count budget check.
    _budget(len(actions),max_complete_solutions,'single action enumeration')
    best_hops=min(len(a['path_link_ids']) for a in actions)
    scorer=_ExactWufrScorer(spectrum_by_link,required_slots_probabilities,build_reference_paths(nodes,directed_links))
    best=None;ref=None;equivalent=0;evaluated=0
    for a in actions:
        if len(a['path_link_ids'])!=best_hops:continue
        value=scorer.score([{'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start'],'required_slots':required_slots}]);evaluated+=1
        public={'path_rank':a['path_rank'],'slot_start':a['slot_start']}
        key=(public['path_rank'],public['slot_start']);oldkey=(ref['path_rank'],ref['slot_start']) if ref else None
        if best is None or value<best-WUFR_ABS_TOL:
            best=value;ref=public;equivalent=1
        elif isclose(value,best,rel_tol=0,abs_tol=WUFR_ABS_TOL):
            equivalent+=1
            if oldkey is None or key<oldkey:ref=public
    return O2SearchResult(True,float(best),ref,equivalent,evaluated,best_hops,'EXACT_CERTIFIED',len(actions),0,evaluated)

def search_joint_optimum(nodes,directed_links,spectrum_by_link,required_slots_probabilities,requests,*,max_complete_solutions=100_000):
    if max_complete_solutions<1:raise ValueError('positive complete-solution budget required')
    if len(requests)<2 or len({str(r['request_id']) for r in requests})!=len(requests):raise ValueError('at least two distinct requests required')
    order=[str(r['request_id']) for r in requests];per={};widths={}
    for r in requests:
        rid=str(r['request_id']);width=int(r['required_slots']);widths[rid]=width
        actions=enumerate_feasible_actions(list(r['paths']),width,spectrum_by_link)
        if not actions:return _empty()
        packed=[]
        for a in actions:
            mask=((1<<width)-1)<<a['slot_start']
            packed.append((len(a['path_link_ids'])*width,a,{int(link):mask for link in a['path_link_ids']}))
        packed.sort(key=lambda v:(v[0],v[1]['path_rank'],v[1]['slot_start']));per[rid]=packed
    visit=sorted(order,key=lambda rid:(len(per[rid]),rid))
    suffix=[0]*(len(visit)+1)
    for i in range(len(visit)-1,-1,-1):suffix[i]=suffix[i+1]+per[visit[i]][0][0]
    occupied={};chosen={};best_cost=None;search_nodes=0;primary_completes=0;secondary_completes=0
    def enter(masks):
        if any(occupied.get(link,0)&mask for link,mask in masks.items()):return None
        old={link:occupied.get(link,0) for link in masks}
        for link,mask in masks.items():occupied[link]=old[link]|mask
        return old
    def restore(old):
        for link,mask in old.items():
            if mask:occupied[link]=mask
            else:occupied.pop(link,None)
    def stage1(i,cost):
        nonlocal best_cost,search_nodes,primary_completes
        search_nodes+=1
        if best_cost is not None and cost+suffix[i]>=best_cost:return
        if i==len(visit):
            primary_completes+=1;_budget(primary_completes,max_complete_solutions,'primary proof');best_cost=cost;return
        rid=visit[i]
        for added,a,masks in per[rid]:
            ncost=cost+added
            if best_cost is not None and ncost+suffix[i+1]>=best_cost:break
            old=enter(masks)
            if old is None:continue
            stage1(i+1,ncost);restore(old)
    stage1(0,0)
    if best_cost is None:return _empty(search_nodes,primary_completes)
    scorer=_ExactWufrScorer(spectrum_by_link,required_slots_probabilities,build_reference_paths(nodes,directed_links))
    best_frag=None;best_ref=None;equivalent=0
    def stage2(i,cost):
        nonlocal search_nodes,secondary_completes,best_frag,best_ref,equivalent
        search_nodes+=1
        if cost+suffix[i]>best_cost:return
        if i==len(visit):
            if cost!=best_cost:return
            secondary_completes+=1;_budget(primary_completes+secondary_completes,max_complete_solutions,'conditional secondary proof')
            full=[];public=[]
            for rid in order:
                a=chosen[rid];full.append({'path_link_ids':a['path_link_ids'],'slot_start':a['slot_start'],'required_slots':widths[rid]})
                public.append({'request_id':rid,'path_rank':a['path_rank'],'slot_start':a['slot_start']})
            value=scorer.score(full);key=tuple((a['request_id'],a['path_rank'],a['slot_start']) for a in public)
            oldkey=tuple((a['request_id'],a['path_rank'],a['slot_start']) for a in best_ref['allocations']) if best_ref else None
            if best_frag is None or value<best_frag-WUFR_ABS_TOL:best_frag=value;best_ref={'allocations':public};equivalent=1
            elif isclose(value,best_frag,rel_tol=0,abs_tol=WUFR_ABS_TOL):
                equivalent+=1
                if oldkey is None or key<oldkey:best_ref={'allocations':public}
            return
        rid=visit[i]
        for added,a,masks in per[rid]:
            ncost=cost+added
            if ncost+suffix[i+1]>best_cost:break
            old=enter(masks)
            if old is None:continue
            chosen[rid]=a;stage2(i+1,ncost);chosen.pop(rid);restore(old)
    stage2(0,0)
    if best_ref is None:raise AssertionError('proved primary optimum must have a conditional feasible witness')
    return O2SearchResult(True,float(best_frag),best_ref,equivalent,primary_completes+secondary_completes,int(best_cost),'EXACT_CERTIFIED',search_nodes,primary_completes,secondary_completes)
