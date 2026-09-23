from __future__ import annotations
import hashlib
from pathlib import Path
from src.s1_x4.config import load_s1x4_config
from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
from src.s1_x4.exporter import export_s1x4_dataset

PROJECT_ROOT=Path(__file__).resolve().parents[1]
def _tree_sha(root):
    h=hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob('*') if x.is_file()):
        rel=p.relative_to(root).as_posix().encode(); b=p.read_bytes(); h.update(len(rel).to_bytes(4,'big')); h.update(rel); h.update(len(b).to_bytes(8,'big')); h.update(b)
    return h.hexdigest()

def derive_s1x4_dataset(environment_root,config_path,output_root):
    envroot=Path(environment_root).resolve(); cfg=load_s1x4_config(config_path); env=load_dynamic_public_environment(envroot)
    scenario_ids=sorted(sid for sid,s in env.scenarios.items() if s.get('request_data_type')=='DYNAMIC')
    chosen=scenario_ids[:cfg.case_count]
    if len(chosen)<cfg.case_count and not cfg.allow_shortfall: raise ValueError(f'S1/X4 shortfall {len(chosen)}/{cfg.case_count}')
    episodes={'S1':[],'X4':[]}
    for i,sid in enumerate(chosen,1):
        k=cfg.k_values[(i-1)%len(cfg.k_values)]; pair=f'dynamic_pair_{i:06d}'
        episodes['S1'].append(build_episode_definition(env,sid,'S1',f'S1_case_{i:06d}',k=k,pairing_id=pair))
        episodes['X4'].append(build_episode_definition(env,sid,'X4',f'X4_case_{i:06d}',k=k,pairing_id=pair))
    meta={'profile':cfg.profile,'config_sha256':cfg.config_sha256,'source_environment_sha256':_tree_sha(envroot),'producer_contract_version':'S1X4_DYNAMIC_CASE_PRODUCER_V1_0'}
    return export_s1x4_dataset(output_root,episodes,contracts_root=PROJECT_ROOT/'contracts',production_metadata=meta,run_references=cfg.run_reference_panel)
