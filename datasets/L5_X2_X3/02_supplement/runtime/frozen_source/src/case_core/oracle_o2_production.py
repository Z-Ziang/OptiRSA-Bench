"""Full-space oracle first, jointly for X3; witness-containing K=3 O2 second."""
from copy import deepcopy
import hashlib,json
from src.case_core.oracle_contained_o2 import derive_o2_from_exact_case
from src.case_core.task_support import spectrum_by_link,q_numeric
from src.tasks.x2.oracle import solve_x2_exact
from src.tasks.x3.oracle import solve_x3_exact

POLICY='O2_ORACLE_CONTAINED_V3_20261013'
class GlobalInfeasibleReview(ValueError):
    def __init__(self,truth,reference):
        super().__init__('full-space exact result is infeasible: no optimal witness path exists')
        self.truth=truth;self.reference=reference

def full_root_from_o2(root):
    x=deepcopy(root);x.pop('objective_contract_id',None);x.pop('candidate_paths',None)
    x['task_type']='X2' if root['task_type']=='O2-S' else 'X3'
    if x['task_type']=='X3':
        for r in x['requests']:r.pop('candidate_paths',None)
    return x

def base_key(root):
    x=deepcopy({k:root[k] for k in ('task_type','topology_id','resource_state_id','nodes','directed_links','slot_count','link_spectrum_states','required_slots_probabilities')})
    x['nodes']=sorted(x['nodes']);x['directed_links']=sorted(x['directed_links'],key=lambda r:r['link_id']);x['link_spectrum_states']=sorted(x['link_spectrum_states'],key=lambda r:r['link_id'])
    if root['task_type']=='X2':x['request']=root['request']
    else:x['requests']=sorted(root['requests'],key=lambda r:r['request_id'])
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def solve_global(root):
    args=(root['nodes'],root['directed_links'],spectrum_by_link(root),q_numeric(root['required_slots_probabilities']))
    if root['task_type']=='X2':
        z=solve_x2_exact(*args,root['request'],max_simple_paths=100000,max_optimal_actions=100000)
        truth={'case_id':root['case_id'],'task_type':'X2','feasible':z.feasible,'oracle_certification':z.certification,'optimal_hop_count':z.optimal_hop_count,'optimal_wufr_at_optimal_hop':z.optimal_wufr,'equivalent_optimum_count':z.equivalent_optimum_count,'oracle_evaluated_optimal_actions':z.evaluated_optimal_actions}
    else:
        z=solve_x3_exact(*args,root['requests'],max_simple_paths_per_request=5000,max_search_nodes=2000000,max_complete_optimal_solutions=100000)
        truth={'case_id':root['case_id'],'task_type':'X3','joint_feasible':z.feasible,'oracle_certification':z.certification,'optimal_delta_tso':z.optimal_delta_tso,'optimal_wufr_at_optimal_delta_tso':z.optimal_wufr,'equivalent_optimum_count':z.equivalent_optimum_count,'oracle_search_nodes':z.search_nodes,'oracle_evaluated_optimal_solutions':z.evaluated_optimal_solutions}
    return truth,z.reference_output

def build_from_full_root(root,*,target_task,case_id,source_binding,candidate_k=3,max_complete_solutions=100000,reused=None):
    if candidate_k!=3:raise ValueError('frozen rule requires optimal witness plus two distinct alternatives, K=3')
    if reused:
        src,truth,reference=reused
        if base_key(src)!=base_key(root):raise ValueError('reused full-space Case does not match the frozen graph/state/request group')
        root=src
    else:truth,reference=solve_global(root)
    if reference['decision']!='ACCEPT':raise GlobalInfeasibleReview(truth,reference)
    b=derive_o2_from_exact_case(root,truth,reference,target_task=target_task,case_id=case_id,source_binding={**source_binding,'candidate_policy_version':POLICY},candidate_k=3,max_complete_solutions=max_complete_solutions)
    b['global_oracle']={'root_case':root,'private_truth':truth,'reference_output':reference,'reused':bool(reused)}
    b['lineage']['candidate_policy_version']=POLICY
    b['features']['global_solver_work']={k:v for k,v in truth.items() if k.startswith('oracle_')}
    return b
