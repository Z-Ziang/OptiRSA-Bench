from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from src.i1.base_dataset import verify_i1_base_dataset
from src.i1.dataset_validator import verify_i1_dataset
from src.i1.pipeline import derive_i1_base_dataset, derive_i1_dataset, rewrite_i1_base_dataset
from src.i1.version import I1_PRODUCER_VERSION

TASKS = ("I1-S", "I1-C", "I1-D")


def parser():
    p = argparse.ArgumentParser(
        description=f"OpticalBenchmark I1 intent-understanding producer {I1_PRODUCER_VERSION} (LLM-only)",
        epilog="I1-S, I1-C and I1-D remain independent LLM-only tasks.",
    )
    p.add_argument("--version", action="version", version=I1_PRODUCER_VERSION)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor")

    base = sp.add_parser("derive-base-cases")
    base.add_argument("--environment", required=True)
    base.add_argument("--config", required=True)
    base.add_argument("--output", required=True)

    base_verify = sp.add_parser("verify-base-dataset")
    base_verify.add_argument("--dataset", required=True)

    rewrite = sp.add_parser("rewrite-base-cases")
    rewrite.add_argument("--base-dataset", required=True)
    rewrite.add_argument("--config", required=True)
    rewrite.add_argument("--output", required=True)

    derive = sp.add_parser("derive-cases")
    derive.add_argument("--environment", required=True)
    derive.add_argument("--config", required=True)
    derive.add_argument("--output", required=True)

    verify = sp.add_parser("verify-dataset")
    verify.add_argument("--dataset", required=True)

    preproduction = sp.add_parser(
        "preproduction-dry-run",
        help="run V2.1.3 one-truth/one-prompt production readiness dry run",
    )
    preproduction.add_argument("--environment", required=True)
    preproduction.add_argument("--config", required=True)
    preproduction.add_argument("--output", required=True)
    return p


def _doctor(root: Path):
    contracts = True
    for task in TASKS:
        base = root / "contracts" / task
        required = [
            base / "llm_system_prompt.txt",
            base / "output_schema.json",
            base / "schemas" / "benchmark_case.schema.json",
            base / "schemas" / "evaluation_case.schema.json",
        ]
        contracts = contracts and all(path.is_file() for path in required)
    config_schema = (root / "configs" / "i1_config.schema.json").is_file()
    representative = (root / "configs" / "i1_representative.json").is_file()
    rewrite_contract = (root / "contracts" / "I1" / "rewrite_system_prompt.txt").is_file()
    try:
        import tiktoken
        tokenizer = {
            "available": True,
            "package_version": getattr(tiktoken, "__version__", None),
            "required_version": "0.14.0",
        }
    except ImportError:
        tokenizer = {"available": False, "package_version": None, "required_version": "0.14.0"}
    valid = bool(contracts and config_schema and representative and rewrite_contract and tokenizer["available"] and tokenizer["package_version"] == tokenizer["required_version"])
    return {
        "python": platform.python_version(),
        "contracts": contracts,
        "config_schema": config_schema,
        "representative_config": representative,
        "rewrite_contract": rewrite_contract,
        "canonical_tokenizer": tokenizer,
        "valid": valid,
    }


def main(argv=None):
    args = parser().parse_args(argv)
    root = Path(__file__).resolve().parent
    if args.cmd == "doctor":
        report = _doctor(root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2
    if args.cmd == "verify-base-dataset":
        report = verify_i1_base_dataset(args.dataset)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2
    if args.cmd == "verify-dataset":
        report = verify_i1_dataset(args.dataset)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2

    try:
        if args.cmd == "derive-base-cases":
            result = derive_i1_base_dataset(args.environment, args.config, args.output)
        elif args.cmd == "rewrite-base-cases":
            result = rewrite_i1_base_dataset(
                args.base_dataset, args.config, args.output
            )
        elif args.cmd == "preproduction-dry-run":
            from scripts.i1_v2_1_3_production import run_preproduction

            result = run_preproduction(
                args.environment,
                args.config,
                args.output,
            )
        else:
            result = derive_i1_dataset(args.environment, args.config, args.output)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
