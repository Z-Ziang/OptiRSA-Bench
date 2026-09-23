from __future__ import annotations
import argparse,json,platform
from pathlib import Path


def parser():
    p=argparse.ArgumentParser(description='OpticalBenchmark unified seven-task producer V2.1.0: O1/O2-S/O2-C/X2/X3/S1/X4')
    sp=p.add_subparsers(dest='command',required=True)
    sp.add_parser('doctor',help='check seven-task contracts and canonical tokenizer')
    d=sp.add_parser('derive-cases',help='derive all seven tasks from one existing public environment using three isolated task-family processes')
    d.add_argument('--environment',required=True); d.add_argument('--config'); d.add_argument('--o-config'); d.add_argument('--x-config'); d.add_argument('--s1x4-config'); d.add_argument('--output',required=True)
    pr=sp.add_parser('produce',help='produce shared public environment then derive all seven tasks')
    pr.add_argument('--environment-config',required=True); pr.add_argument('--config'); pr.add_argument('--o-config'); pr.add_argument('--x-config'); pr.add_argument('--s1x4-config'); pr.add_argument('--output',required=True)
    v=sp.add_parser('verify-dataset',help='verify a merged seven-task dataset')
    v.add_argument('--dataset',required=True)
    return p


def _resolve(args):
    if args.config:
        if args.o_config or args.x_config or args.s1x4_config: raise ValueError('use either --config or individual family configs, not both')
        from src.seven_task_profile import load_seven_task_profile
        c=load_seven_task_profile(args.config); return c.o_family_config,c.x2x3_config,c.s1x4_config
    if not (args.o_config and args.x_config and args.s1x4_config): raise ValueError('provide --config, or all of --o-config --x-config --s1x4-config')
    return Path(args.o_config).resolve(),Path(args.x_config).resolve(),Path(args.s1x4_config).resolve()


def _doctor(root):
    tasks=('O1','O2-S','O2-C','X2','X3','S1','X4'); tok={'available':False,'encoding':'o200k_base','version':None}
    try:
        import tiktoken
        version=str(getattr(tiktoken,'__version__',None))
        if version!='0.14.0':
            raise RuntimeError(f'canonical tokenizer requires tiktoken==0.14.0; found {version}')
        tiktoken.get_encoding('o200k_base')
        tok.update(available=True,version=version)
    except Exception as exc: tok['error']=f'{type(exc).__name__}: {exc}'
    checks={'python':platform.python_version(),'tasks':list(tasks),'contracts':all((root/'contracts'/t/'llm_system_prompt.txt').is_file() for t in tasks),'seven_task_profile':(root/'configs/seven_task_profile.json').is_file(),'s1x4_config_schema':(root/'configs/s1_x4_config.schema.json').is_file(),'canonical_tokenizer':tok,'generated_local_output_absent':not (root/'local_output').exists()}
    checks['valid']=bool(checks['contracts'] and checks['seven_task_profile'] and checks['s1x4_config_schema'] and tok['available'] and checks['generated_local_output_absent'])
    return checks


def main(argv=None):
    a=parser().parse_args(argv); root=Path(__file__).resolve().parent
    if a.command=='doctor':
        r=_doctor(root); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.command=='verify-dataset':
        from src.seven_task_orchestrator import verify_seven_task_dataset
        r=verify_seven_task_dataset(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    try:
        o,x,s=_resolve(a)
        if a.command=='derive-cases':
            from src.seven_task_orchestrator import derive_seven_task_dataset
            r=derive_seven_task_dataset(a.environment,o,x,s,a.output)
        else:
            from src.seven_task_orchestrator import produce_environment_and_seven_tasks
            r=produce_environment_and_seven_tasks(a.environment_config,o,x,s,a.output)
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
    print(json.dumps(r,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
