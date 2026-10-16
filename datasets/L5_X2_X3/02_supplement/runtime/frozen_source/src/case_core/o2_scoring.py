"""Two-level O2 score; secondary gaps are comparable only at primary optimum."""
from src.case_core.wufr import WUFR_ABS_TOL

def require_new_truth(truth,expected):
    if truth.get('objective_contract_id')!=expected:
        raise ValueError('truth objective version does not match the new O2 contract')
    if truth.get('oracle_certification') not in ('EXACT_CERTIFIED','INFEASIBLE_CERTIFIED'):
        raise ValueError('new O2 scoring requires completed exact truth certification')
    feasible=truth.get('feasible') if expected.startswith('O2-S_') else truth.get('joint_feasible')
    if not isinstance(feasible,bool):
        raise ValueError('truth feasibility must be an explicit boolean')
    expected_certification='EXACT_CERTIFIED' if feasible else 'INFEASIBLE_CERTIFIED'
    if truth['oracle_certification'] != expected_certification:
        raise ValueError('truth certification disagrees with feasibility')
    primary_name='optimal_hop_count' if expected.startswith('O2-S_') else 'optimal_delta_tso'
    primary=truth.get(primary_name);fragmentation=truth.get('optimal_wufr')
    if feasible:
        if isinstance(primary,bool) or not isinstance(primary,int) or primary < 1:
            raise ValueError('feasible exact truth requires a positive integer primary optimum')
        import math
        if isinstance(fragmentation,bool) or not isinstance(fragmentation,(int,float)) or not math.isfinite(fragmentation) or fragmentation < 0:
            raise ValueError('feasible exact truth requires a finite secondary optimum')
    elif primary is not None or fragmentation is not None:
        raise ValueError('infeasible truth cannot contain an optimum')
    if truth.get('reference_output',{}).get('decision') != ('ACCEPT' if feasible else 'REJECT'):
        raise ValueError('truth reference decision disagrees with certification')

def score_lexicographic(result,truth,submitted_primary,submitted_fragmentation,primary_name):
    metrics=result['metrics'];primary_optimum=truth[primary_name]
    if not isinstance(primary_optimum,int) or isinstance(primary_optimum,bool) or primary_optimum<1:
        result['errors'].append('invalid stored primary optimum');return
    gap=int(submitted_primary)-primary_optimum
    if gap<0:
        result['errors'].append('submitted primary objective is below stored optimum; truth is inconsistent');return
    result['submitted_primary']=int(submitted_primary);result['submitted_wufr']=float(submitted_fragmentation)
    metrics['hop_count_gap' if primary_name=='optimal_hop_count' else 'delta_tso_gap']=gap
    result['primary_optimal']=gap==0;result['secondary_comparable']=gap==0
    if gap==0:
        secondary_gap=float(submitted_fragmentation)-float(truth['optimal_wufr'])
        if abs(secondary_gap)<=WUFR_ABS_TOL:secondary_gap=0.0
        if secondary_gap < -WUFR_ABS_TOL:
            result['errors'].append('submitted conditional fragmentation is below stored optimum; truth is inconsistent');return
        metrics['wufr_gap']=secondary_gap;result['lexicographic_optimal']=secondary_gap==0
    else:
        metrics['wufr_gap']=None;result['lexicographic_optimal']=False
    result['valid']=True
