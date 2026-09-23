from __future__ import annotations
import hashlib
import re
from itertools import combinations
from pathlib import Path
from src.case_core.full_rsa import FullRsaBudgetExceeded
from src.case_core.scenario_loader import load_public_environment
from src.tasks.x2.producer import build_x2_case
from src.tasks.x3.producer import build_x3_case
from src.x2x3_config import load_x2x3_config
from src.x2x3_exporter import export_x2x3_dataset

PROJECT_ROOT=Path(__file__).resolve().parents[1]


def _case_id(task: str, ordinal: int, namespace: str | None) -> str:
    if namespace is None:
        return f'{task}_{ordinal:06d}'
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(namespace)).strip('_')
    if not safe:
        raise ValueError('case_id_namespace must contain an identifier character')
    return f'{task}_{safe}_{ordinal:06d}'
def _tree_sha(root):
    h=hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob('*') if x.is_file()):
        r=p.relative_to(root).as_posix().encode(); b=p.read_bytes(); h.update(len(r).to_bytes(4,'big')); h.update(r); h.update(len(b).to_bytes(8,'big')); h.update(b)
    return h.hexdigest()
def _source_complexity(env,rid): return int(env.derivations[rid].get('feasible_action_count',10**9))
def _rank1_links(env,rid):
    ps=sorted(env.derivations[rid].get('candidate_paths',[]),key=lambda x:int(x['rank']))
    return set(int(x) for x in ps[0]['path_link_ids']) if ps else set()
def _high_conflict(ids,env,r):
    score={rid:0 for rid in ids}
    for a,b in combinations(ids,2):
        w=len(_rank1_links(env,a)&_rank1_links(env,b)); score[a]+=w; score[b]+=w
    return sorted(ids,key=lambda x:(-score[x],x))[:r]

def _x2(env,cfg,allow,case_id_namespace=None):
    if not cfg.enabled or cfg.case_count==0: return []
    ids=sorted(env.requests)
    if cfg.selection=='LOW_ORACLE_COMPLEXITY': ids.sort(key=lambda rid:(_source_complexity(env,rid),rid))
    specs=[]
    for w in cfg.required_slots_values:
        for rid in ids: specs.append((rid,w))
    # interleave widths rather than exhaust one width first
    specs=[]
    for i,rid in enumerate(ids):
        for w in cfg.required_slots_values: specs.append((rid,w))
    out=[]
    for rid,w in specs:
        if len(out)>=cfg.case_count: break
        try: b=build_x2_case(env,rid,case_id=_case_id('X2',len(out)+1,case_id_namespace),required_slots=w,max_simple_paths=cfg.max_simple_paths,max_optimal_actions=cfg.max_optimal_actions)
        except FullRsaBudgetExceeded: continue
        out.append(b)
    if len(out)<cfg.case_count and not allow: raise ValueError(f'X2 shortfall {len(out)}/{cfg.case_count}')
    return out

def _x3(env,cfg,allow,case_id_namespace=None):
    if not cfg.enabled or cfg.case_count==0: return []
    specs=[]
    for mode in cfg.selection_values:
        for sid,item in sorted(env.concurrent_sets.items()):
            ids=[str(x) for x in item.get('request_ids',[])]
            for r in cfg.request_count_values:
                if len(ids)<r: continue
                chosen=ids[:r] if mode=='PREFIX' else _high_conflict(ids,env,r)
                complexity=1
                for rid in chosen: complexity*=max(1,_source_complexity(env,rid))
                specs.append((complexity,mode,sid,chosen,r))
    specs.sort(key=lambda x:(x[0],x[1],x[2],tuple(x[3])))
    out=[]
    for _,mode,sid,ids,r in specs:
        if len(out)>=cfg.case_count: break
        try: b=build_x3_case(env,ids,case_id=_case_id('X3',len(out)+1,case_id_namespace),max_simple_paths_per_request=cfg.max_simple_paths_per_request,max_search_nodes=cfg.max_search_nodes,max_complete_optimal_solutions=cfg.max_complete_optimal_solutions)
        except FullRsaBudgetExceeded: continue
        b['lineage']['source_concurrent_request_set_id']=sid; b['lineage']['construction_mode']=mode; out.append(b)
    if len(out)<cfg.case_count and not allow: raise ValueError(f'X3 shortfall {len(out)}/{cfg.case_count}')
    return out

def derive_x2x3_dataset(environment_root,config_path,output_root,*,case_id_namespace=None):
    envroot=Path(environment_root).resolve(); cfg=load_x2x3_config(config_path); env=load_public_environment(envroot)
    namespace = case_id_namespace or cfg.case_id_namespace
    bundles={'X2':_x2(env,cfg.x2,cfg.allow_shortfall,namespace),'X3':_x3(env,cfg.x3,cfg.allow_shortfall,namespace)}
    meta={'profile':cfg.profile,'seed':cfg.seed,'config_sha256':cfg.config_sha256,'source_environment_sha256':_tree_sha(envroot),'producer_contract_version':'X2X3_CASE_PRODUCER_V1_1_ALGORITHM_VIEW','case_id_namespace':namespace}
    return export_x2x3_dataset(output_root,bundles,contracts_root=PROJECT_ROOT/'contracts',production_metadata=meta)

def produce_environment_and_x2x3(environment_config,case_config,output_root):
    from src.production.batch import run_batch
    from src.production.config import load_production_config
    out=Path(output_root).resolve(); batch=out/'public_environment_batch'; r=run_batch(load_production_config(Path(environment_config)),batch)
    if r.get('status')!='PASS': raise RuntimeError(f"public-environment batch did not PASS: {r.get('status')}")
    datasets={}
    for unit in sorted((batch/'units').iterdir()):
        if unit.is_dir(): datasets[unit.name]=derive_x2x3_dataset(unit/'public_environment',case_config,out/'datasets'/unit.name,case_id_namespace=unit.name)
    return {'status':'PASS','public_environment_batch_id':r.get('batch_id'),'topology_count':len(datasets),'datasets':datasets}
