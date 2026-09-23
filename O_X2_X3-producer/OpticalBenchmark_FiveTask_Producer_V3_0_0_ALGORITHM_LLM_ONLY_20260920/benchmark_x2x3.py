from __future__ import annotations
import argparse,json,platform
from pathlib import Path

def parser():
    p=argparse.ArgumentParser(description='OpticalBenchmark X2/X3 full-RSA producer V1.0'); s=p.add_subparsers(dest='command',required=True)
    s.add_parser('doctor')
    d=s.add_parser('derive-cases'); d.add_argument('--environment',required=True); d.add_argument('--config',required=True); d.add_argument('--output',required=True); d.add_argument('--case-id-namespace')
    pr=s.add_parser('produce'); pr.add_argument('--environment-config',required=True); pr.add_argument('--case-config',required=True); pr.add_argument('--output',required=True)
    v=s.add_parser('verify-dataset'); v.add_argument('--dataset',required=True)
    return p

def main(argv=None):
    a=parser().parse_args(argv); root=Path(__file__).resolve().parent
    if a.command=='doctor':
        checks={'python':platform.python_version(),'contracts':all((root/'contracts'/t/'llm_system_prompt.txt').is_file() for t in ('X2','X3')),'algorithm_view_assets':all((root/'contracts'/t/'algorithm_contract.json').is_file() and (root/'contracts'/t/'schemas'/'algorithm_input.schema.json').is_file() for t in ('X2','X3')),'config_schema':(root/'configs/x2x3_config.schema.json').is_file(),'representative_config':(root/'configs/x2x3_representative.json').is_file()}
        checks['valid']=all(checks[k] for k in ('contracts','algorithm_view_assets','config_schema','representative_config')); print(json.dumps(checks,ensure_ascii=False,indent=2)); return 0 if checks['valid'] else 2
    if a.command=='derive-cases':
        from src.x2x3_pipeline import derive_x2x3_dataset
        r=derive_x2x3_dataset(a.environment,a.config,a.output,case_id_namespace=a.case_id_namespace); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    if a.command=='produce':
        from src.x2x3_pipeline import produce_environment_and_x2x3
        r=produce_environment_and_x2x3(a.environment_config,a.case_config,a.output); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    if a.command=='verify-dataset':
        from src.x2x3_dataset_validator import verify_x2x3_dataset
        r=verify_x2x3_dataset(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    return 2
if __name__=='__main__': raise SystemExit(main())
