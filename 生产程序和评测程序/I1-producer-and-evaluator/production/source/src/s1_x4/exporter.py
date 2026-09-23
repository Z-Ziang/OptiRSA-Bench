from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from src.s1_x4.serialization import compute_serialization_metrics
from src.s1_x4.state_machine import DynamicEpisodeState
from src.s1_x4.renderer import render_s1_step, render_x4_step
from src.s1_x4.reference_algorithms import run_reference_panel
from src.s1_x4.efm import network_efm
from src.s1_x4.public_projection import build_static_context

TASKS=('S1','X4')

def _initial_utilization(ep):
    states=ep['initial_link_spectrum_states']
    total=sum(len(x['slot_availability']) for x in states)
    occupied=sum(1-int(v) for x in states for v in x['slot_availability'])
    return occupied/total if total else None

def _difficulty_features(ep, step_ctx):
    spectrum={int(x['link_id']):list(x['slot_availability']) for x in ep['initial_link_spectrum_states']}
    initial_efm=network_efm(spectrum)['network_efm']
    difficulty_ctx=dict(ep.get('difficulty_context') or {})
    reference_time=float(ep.get('initial_reference_time', ep['request_events'][0]['arrival_time']))
    last_time=float(ep['request_events'][-1]['arrival_time'])
    time_span=max(0.0,last_time-reference_time)
    mu=float(ep.get('holding_time_rate_mu',0.0))
    return {
        'initial_load_band':difficulty_ctx.get('initial_load_band'),
        'state_arrival_rate_lambda':difficulty_ctx.get('state_arrival_rate_lambda'),
        'dynamic_arrival_rate_lambda':difficulty_ctx.get('dynamic_arrival_rate_lambda'),
        'arrival_rate_mode':difficulty_ctx.get('arrival_rate_mode'),
        'requested_arrival_rate_multiplier':difficulty_ctx.get('requested_arrival_rate_multiplier'),
        'lambda_ratio':difficulty_ctx.get('lambda_ratio'),
        'initial_network_utilization':_initial_utilization(ep),
        'initial_network_efm':initial_efm,
        'initial_active_connection_count':len(ep['initial_existing_connections']),
        'episode_length':int(ep['episode_length']),
        'episode_time_span':time_span,
        'holding_time_rate_mu':mu,
        'normalized_horizon':time_span*mu,
        'node_count':len(ep['nodes']),
        'directed_link_count':len(ep['directed_links']),
        'k_value':int(ep.get('task_config',{}).get('k', ep.get('task_config',{}).get('reference_k',0))) or None,
        'initial_candidate_action_count':len(step_ctx.get('candidate_actions',[])) if ep['task_type']=='S1' else None,
    }

def _write(path,obj,*,sort=False):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=sort)+'\n',encoding='utf-8')
def _sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def _prompt(ep,ctx,endpoint): return render_s1_step(ep,ctx,endpoint) if ep['task_type']=='S1' else render_x4_step(ep,ctx,endpoint)
def _public_reference(panel):
    return {'type':'POLICY_PANEL','episode_length':panel['episode_length'],'primary_metric':'RBR','secondary_metric':'MEAN_NETWORK_EFM','policy_results':[
        {k:r[k] for k in ('policy_name','episode_length','established_count','blocked_count','rbr','mean_network_efm')} for r in panel['policy_results']
    ]}
def _algorithm_case(ep,ctx):
    req=dict(ctx['request']); net={'nodes':ctx['nodes'],'directed_links':ctx['directed_links'],'slot_count':ctx['slot_count'],
        'link_spectrum_states':[{'link_id':lid,'slot_availability':list(bits)} for lid,bits in sorted(ctx['spectrum_by_link'].items())]}
    action={'kind':'FULL_SPACE_RSA'}
    if ep['task_type']=='S1': action={'kind':'SUPPLIED_FEASIBLE_ACTIONS','candidate_paths':ctx['candidate_paths'],'candidate_actions':ctx['candidate_actions']}
    return {'case_id':ep['case_id'],'task_type':ep['task_type'],'current_request':req,'current_network_state':net,'allowed_action_space':action}

def _algorithm_evaluation_case(ep):
    """Create the public dynamic launcher; observations are built online at runtime."""
    task=ep['task_type']; static=build_static_context(ep).to_public_dict()
    return {
        'schema_version':'S1_X4_ALGORITHM_EVALUATION_CASE_V1_1',
        'case_id':ep['case_id'],
        'task_type':task,
        'interface_type':'DYNAMIC_ONLINE_ALGORITHM_EPISODE',
        'future_requests_visible':False,
        'static_context':static,
        'output_schema_ref':f'contracts/{task}/output_schema.json',
        'runtime_contract_ref':f'contracts/{task}/schemas/algorithm_runtime_contract.json',
        'opaque_case_handle':f'algorithm_episode:{ep["case_id"]}',
    }

def export_s1x4_dataset(output_root, episodes_by_task, *, contracts_root: Path, production_metadata: dict, run_references: bool=True):
    root=Path(output_root).resolve(); contracts_root=Path(contracts_root).resolve()
    if root.exists(): shutil.rmtree(root)
    root.mkdir(parents=True); rows=[]; task_counts={}; registry_entries=[]
    for task in TASKS:
        eps=sorted(episodes_by_task.get(task,[]),key=lambda x:x['case_id']); task_counts[task]=len(eps)
        if eps:
            for base in (root/'benchmark_case'/task,root/'evaluation_case'/task):
                base.mkdir(parents=True,exist_ok=True)
                shutil.copy2(contracts_root/task/'llm_system_prompt.txt',base/'llm_system_prompt.txt')
            (root/'evaluation_case'/task/'algorithm').mkdir(parents=True,exist_ok=True)
            shutil.copytree(contracts_root/task,root/'internal/contracts'/task)
        for ordinal,ep in enumerate(eps,1):
            st=DynamicEpisodeState(ep); ctx=st.prepare_current_step(); llm=_prompt(ep,ctx,'llm')
            panel=run_reference_panel(ep) if run_references else {'type':'POLICY_PANEL','episode_length':ep['episode_length'],'primary_metric':'RBR','secondary_metric':'MEAN_NETWORK_EFM','policy_results':[]}
            ref=_public_reference(panel)
            bench={'case_id':ep['case_id'],'llm_prompt':llm,'reference':ref}; llmc={'case_id':ep['case_id'],'prompt':llm}
            alg=_algorithm_case(ep,ctx); algorithm_launcher=_algorithm_evaluation_case(ep); truth={'case_id':ep['case_id'],'evaluation_semantics':'OPERATIONAL_DYNAMIC_RSA','episode_length':ep['episode_length']}
            features={'episode_length':ep['episode_length'],'difficulty':_difficulty_features(ep,ctx),'initial_serialization_metrics':compute_serialization_metrics(llm)}
            lineage={'engineering_parent':'V2.0.1','producer_contract_version':'S1X4_DYNAMIC_CASE_PRODUCER_V1_0','pairing_id':ep['pairing_id'],
                     'topology_id':ep['topology_id'],'resource_state_id':ep['resource_state_id'],'request_sequence_id':ep['request_sequence_id'],
                     'dynamic_generation_context':dict(ep.get('difficulty_context') or {})}
            validation={'valid':True,'metrics':{'episode_length':ep['episode_length']},'errors':[]}
            name=f'case_{ordinal:06d}.json'
            bp=root/'benchmark_case'/task/'cases'/name; lp=root/'evaluation_case'/task/'llm'/name; aep=root/'evaluation_case'/task/'algorithm'/name
            _write(bp,bench); _write(lp,llmc); _write(aep,algorithm_launcher)
            ic=root/'internal/cases'/task/ep['case_id']; ip=root/'internal/private'/task/ep['case_id']
            root_case_path=ic/'root_case.json'
            _write(root_case_path,ep,sort=True); _write(ic/'algorithm_case.json',alg,sort=True)
            registry_entries.append({
                'opaque_case_handle':algorithm_launcher['opaque_case_handle'],
                'case_id':ep['case_id'],
                'task_type':task,
                'root_case_path':root_case_path.relative_to(root).as_posix(),
                'root_case_sha256':_sha(root_case_path),
            })
            _write(ip/'private_truth.json',truth,sort=True); _write(ip/'reference_output.json',ref,sort=True); _write(ip/'features.json',features,sort=True); _write(ip/'lineage.json',lineage,sort=True); _write(ip/'validation.json',validation,sort=True)
            if run_references:
                for pr in panel['policy_results']:
                    traj=pr['trajectory']; trp=ip/'reference_trajectories'/f"{pr['policy_name']}.jsonl"; trp.parent.mkdir(parents=True,exist_ok=True)
                    trp.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in traj),encoding='utf-8')
            rows.append({'case_id':ep['case_id'],'task_type':task,'pairing_id':ep['pairing_id'],'topology_id':ep['topology_id'],'resource_state_id':ep['resource_state_id'],
                         'benchmark_case_path':bp.relative_to(root).as_posix(),'llm_evaluation_path':lp.relative_to(root).as_posix(),'algorithm_evaluation_path':aep.relative_to(root).as_posix(),
                         'internal_case_dir':ic.relative_to(root).as_posix(),'internal_private_dir':ip.relative_to(root).as_posix(),'features':features})
    rows.sort(key=lambda r:(r['task_type'],r['case_id']))
    (root/'case_index.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows),encoding='utf-8')
    _write(root/'internal/algorithm_episode_registry.json',{
        'schema_version':'S1_X4_ALGORITHM_EPISODE_REGISTRY_V1_0',
        'entries':sorted(registry_entries,key=lambda r:r['opaque_case_handle']),
    },sort=True)
    summary={'schema_version':'S1X4_PRODUCTION_SUMMARY_V2_2_0','case_count':len(rows),'task_counts':task_counts,'production_metadata':production_metadata,'benchmark_interface':'DYNAMIC_ALGORITHM_LLM_V1_0'}
    _write(root/'production_summary.json',summary,sort=True)
    files=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name not in {'RUN_MANIFEST.json','SHA256SUMS.txt'}): files.append({'path':p.relative_to(root).as_posix(),'size_bytes':p.stat().st_size,'sha256':_sha(p)})
    _write(root/'RUN_MANIFEST.json',{'schema_version':'S1X4_RUN_MANIFEST_V2_1_0','file_count':len(files),'files':files},sort=True)
    (root/'SHA256SUMS.txt').write_text('\n'.join(f"{_sha(p)}  {p.relative_to(root).as_posix()}" for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='SHA256SUMS.txt'))+'\n',encoding='utf-8')
    return summary
