from __future__ import annotations
import argparse,json,platform
from pathlib import Path
from src.s1_x4_pipeline import derive_s1x4_dataset
from src.s1_x4.dataset_validator import verify_s1x4_dataset


def parser():
    p=argparse.ArgumentParser(description='OpticalBenchmark S1/X4 dynamic task-family producer V1.0')
    sp=p.add_subparsers(dest='cmd',required=True); sp.add_parser('doctor')
    d=sp.add_parser('derive-cases'); d.add_argument('--environment',required=True); d.add_argument('--config',required=True); d.add_argument('--output',required=True)
    v=sp.add_parser('verify-dataset'); v.add_argument('--dataset',required=True)
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
    r={'python':platform.python_version(),'contracts':all((root/'contracts'/t/'llm_system_prompt.txt').is_file() for t in ('S1','X4')),'config_schema':(root/'configs/s1_x4_config.schema.json').is_file(),'canonical_tokenizer':tok}
    r['valid']=bool(r['contracts'] and r['config_schema'] and tok['available']); return r


def main(argv=None):
    a=parser().parse_args(argv); root=Path(__file__).resolve().parent
    if a.cmd=='doctor':
        r=_doctor(root); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.cmd=='verify-dataset':
        r=verify_s1x4_dataset(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    try: r=derive_s1x4_dataset(a.environment,a.config,a.output)
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False,indent=2)); return 2
    print(json.dumps(r,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
