from __future__ import annotations
import argparse, hashlib, json, platform, sys
from pathlib import Path


def _parser():
    p=argparse.ArgumentParser(description="OpticalBenchmark shared-environment O-family producer V1.1 (required-slots probability field rename)")
    sp=p.add_subparsers(dest="command",required=True)
    sp.add_parser("doctor",help="check runtime, frozen contracts, and baseline availability")
    d=sp.add_parser("derive-cases",help="derive O1/O2-S/O2-C Cases from an existing public environment")
    d.add_argument("--environment",required=True); d.add_argument("--config",required=True); d.add_argument("--output",required=True); d.add_argument("--case-id-namespace")
    pr=sp.add_parser("produce",help="run inherited public-environment batch production, then derive O-family Cases")
    pr.add_argument("--environment-config",required=True); pr.add_argument("--case-config",required=True); pr.add_argument("--output",required=True)
    v=sp.add_parser("verify-dataset",help="schema/hash/reference-replay verify a produced O-family dataset")
    v.add_argument("--dataset",required=True)
    return p


def main(argv=None):
    a=_parser().parse_args(argv)
    if a.command=="doctor":
        root=Path(__file__).resolve().parent
        expected="e3b72de4b1a5fe259d37a85a7661704d870d14acf7f4f545b0639e5df35bd0e9"
        baseline_name="PUBLIC_ENVIRONMENT_PRODUCTION_RUNNER_V1_0_CLEAN_20260811(5).zip"
        candidates=[root.parent/baseline_name,Path('/mnt/data')/baseline_name]
        baseline_zip=next((p for p in candidates if p.is_file()),None)
        baseline_match=None if baseline_zip is None else hashlib.sha256(baseline_zip.read_bytes()).hexdigest()==expected
        checks={
            "python":platform.python_version(),
            "contracts":all((root/'contracts'/t/'llm_system_prompt.txt').is_file() for t in ('O1','O2-S','O2-C')),
            "algorithm_view_assets":all((root/'contracts'/t/'algorithm_contract.json').is_file() and (root/'contracts'/t/'schemas'/'algorithm_input.schema.json').is_file() for t in ('O1','O2-S','O2-C')),
            "config_schema":(root/'configs/o_family_config.schema.json').is_file(),
                        "baseline_zip_sha256_expected":expected,
            "baseline_zip_sha256_match":baseline_match,
        }
        checks["valid"]=bool(checks["contracts"] and checks["algorithm_view_assets"] and checks["config_schema"] and baseline_match is not False)
        print(json.dumps(checks,ensure_ascii=False,indent=2)); return 0 if checks["valid"] else 2
    if a.command=="verify-dataset":
        from src.case_core.dataset_validator import verify_dataset
        r=verify_dataset(a.dataset); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0 if r['valid'] else 2
    if a.command=="derive-cases":
        from src.o_family_pipeline import derive_o_family_dataset
        r=derive_o_family_dataset(a.environment,a.config,a.output,case_id_namespace=a.case_id_namespace); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    if a.command=="produce":
        from src.o_family_pipeline import produce_environment_and_cases
        r=produce_environment_and_cases(a.environment_config,a.case_config,a.output); print(json.dumps(r,ensure_ascii=False,indent=2)); return 0
    return 2

if __name__=='__main__': raise SystemExit(main())
