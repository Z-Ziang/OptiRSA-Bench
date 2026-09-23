from __future__ import annotations
import argparse,json,platform
from pathlib import Path
from src.s1_x4_pipeline import derive_s1x4_dataset
from src.s1_x4.dataset_validator import verify_s1x4_dataset
from src.s1_x4.difficulty_calibration import write_difficulty_report


def parser():
    p=argparse.ArgumentParser(description='OpticalBenchmark S1/X4 dynamic task-family producer V1.0')
    sp=p.add_subparsers(dest='cmd',required=True); sp.add_parser('doctor')
    d=sp.add_parser('derive-cases'); d.add_argument('--environment',required=True); d.add_argument('--config',required=True); d.add_argument('--output',required=True)
    v=sp.add_parser('verify-dataset'); v.add_argument('--dataset',required=True)
    pv=sp.add_parser('verify-public-dataset'); pv.add_argument('--dataset',required=True)
    gs=sp.add_parser('validate-generation-spec'); gs.add_argument('--spec',required=True); gs.add_argument('--strict-matrix',action='store_true')
    re=sp.add_parser('regenerate-episode'); re.add_argument('--spec',required=True); re.add_argument('--environment',required=True); re.add_argument('--task',choices=('S1','X4'),required=True); re.add_argument('--output',required=True)
    ra=sp.add_parser('run-algorithm'); ra.add_argument('--run-config',required=True); ra.add_argument('--dataset-root'); ra.add_argument('--task',choices=('S1','X4'),required=True); ra.add_argument('--output',required=True); ra.add_argument('--policy',choices=('first-feasible','reject'),default='first-feasible')
    rr=sp.add_parser('run-reference'); rr.add_argument('--run-config',required=True); rr.add_argument('--dataset-root'); rr.add_argument('--output')
    rp=sp.add_parser('run-reference-panel'); rp.add_argument('--run-config',required=True); rp.add_argument('--dataset-root'); rp.add_argument('--output')
    c=sp.add_parser('calibrate-difficulty'); c.add_argument('--dataset',required=True); c.add_argument('--output',required=True); c.add_argument('--prefixes',default='32,128,512')
    return p


def _doctor(root: Path):
    tok={'available':False,'encoding':'o200k_base','version':None}
    try:
        import tiktoken
        version=str(getattr(tiktoken,'__version__',None))
        if version!='0.14.0':
            raise RuntimeError(f'canonical tokenizer requires tiktoken==0.14.0; found {version}')
        tiktoken.get_encoding('o200k_base')
        tok.update(available=True,version=version)
    except Exception as exc: tok['error']=f'{type(exc).__name__}: {exc}'
    r={'python':platform.python_version(),'contracts':all((root/'contracts'/t/'llm_system_prompt.txt').is_file() and (root/'contracts'/t/'output_schema.json').is_file() for t in ('S1','X4')),'config_schema':(root/'configs/s1_x4_config.schema.json').is_file(),'algorithm_schemas':all((root/'contracts'/t/'schemas'/name).is_file() for t in ('S1','X4') for name in ('algorithm_evaluation_case.schema.json','algorithm_observation.schema.json','algorithm_runtime_contract.json')),'canonical_tokenizer':tok}
    r['valid']=bool(r['contracts'] and r['config_schema'] and r['algorithm_schemas'] and tok['available']); return r


def main(argv=None):
    a=parser().parse_args(argv); root=Path(__file__).resolve().parent
    if a.cmd=='doctor':
        r=_doctor(root); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='verify-dataset':
        r=verify_s1x4_dataset(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='verify-public-dataset':
        from src.s1_x4.public_dataset_v2 import verify_public_dataset_v2
        r=verify_public_dataset_v2(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='validate-generation-spec':
        from src.s1_x4.generation_spec import validate_generation_spec
        try:
            spec=json.loads(Path(a.spec).read_text(encoding='utf-8'))
            errors=validate_generation_spec(spec,strict_matrix=bool(a.strict_matrix))
            r={'valid':not errors,'spec':str(Path(a.spec).resolve()),'errors':errors}
        except Exception as exc:
            r={'valid':False,'spec':str(Path(a.spec).resolve()),'errors':[f'{type(exc).__name__}: {exc}']}
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='regenerate-episode':
        from src.s1_x4.generation_spec import regenerate_episode_from_spec
        try:
            spec=json.loads(Path(a.spec).read_text(encoding='utf-8'))
            episode=regenerate_episode_from_spec(spec,environment_root=a.environment,task_type=a.task)
            Path(a.output).parent.mkdir(parents=True,exist_ok=True)
            Path(a.output).write_text(json.dumps(episode,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
            r={'valid':True,'task_type':a.task,'case_id':episode['case_id'],'output':str(Path(a.output).resolve())}
        except Exception as exc:
            r={'valid':False,'errors':[f'{type(exc).__name__}: {exc}']}
        print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='run-algorithm':
        from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark
        def algorithm(_static, observation):
            if a.policy=='reject':
                return {'decision':'REJECT','path_rank':None,'slot_start':None} if a.task=='S1' else {'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None}
            if a.task=='S1' and observation.feasible_actions is not None and observation.feasible_actions.size:
                row=observation.feasible_actions[0]
                return {'decision':'ACCEPT','path_rank':int(row[0]),'slot_start':int(row[1])}
            return {'decision':'REJECT','path_rank':None,'slot_start':None} if a.task=='S1' else {'decision':'REJECT','path_node_ids':[],'path_link_ids':[],'slot_start':None}
        try:
            r=run_algorithm_benchmark(a.run_config,algorithm,task_type=a.task,dataset_root=a.dataset_root,output_dir=a.output)
        except Exception as exc:
            print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
        print(json.dumps({'status':'PASS','summary':r['summary'],'timing':r['timing']},ensure_ascii=False,indent=2)); return 0
    if a.cmd in ('run-reference','run-reference-panel'):
        from src.s1_x4.reference_algorithms import run_reference_panel_from_run_config
        try:
            r=run_reference_panel_from_run_config(a.run_config,dataset_root=a.dataset_root,output_dir=a.output)
        except Exception as exc:
            print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
        print(json.dumps({'status':'PASS','episode_length':r['episode_length'],'policy_count':len(r['policy_results'])},ensure_ascii=False,indent=2)); return 0
    if a.cmd=='calibrate-difficulty':
        try:
            prefixes=tuple(int(x.strip()) for x in a.prefixes.split(',') if x.strip())
            r=write_difficulty_report(a.dataset,a.output,prefixes=prefixes)
        except Exception as exc:
            print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
        print(json.dumps({'status':'PASS','case_count':r['case_count'],'prefix_row_count':len(r['prefixes']),'output':str(Path(a.output).resolve())},ensure_ascii=False,indent=2)); return 0
    try: r=derive_s1x4_dataset(a.environment,a.config,a.output)
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
    print(json.dumps(r,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
