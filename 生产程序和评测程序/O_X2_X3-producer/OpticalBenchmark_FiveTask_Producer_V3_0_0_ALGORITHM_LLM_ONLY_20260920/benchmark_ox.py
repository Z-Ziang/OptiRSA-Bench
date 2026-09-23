from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpticalBenchmark unified five-task producer: O1/O2-S/O2-C/X2/X3")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check runtime dependencies, contracts, configs and source completeness")

    d = sub.add_parser("derive-cases", help="derive all five task families from one existing public environment using isolated child processes")
    d.add_argument("--environment", required=True)
    d.add_argument("--config", help="Five-task profile JSON; preferred")
    d.add_argument("--o-config")
    d.add_argument("--x-config")
    d.add_argument("--output", required=True)

    pr = sub.add_parser("produce", help="produce shared public environment, then all five task families")
    pr.add_argument("--environment-config", required=True)
    pr.add_argument("--config", help="Five-task profile JSON; preferred")
    pr.add_argument("--o-config")
    pr.add_argument("--x-config")
    pr.add_argument("--output", required=True)

    v = sub.add_parser("verify-dataset", help="verify merged five-task dataset")
    v.add_argument("--dataset", required=True)

    e = sub.add_parser("validate-output", help="validate one DUT response against evaluator-side scientific evidence")
    e.add_argument("--dataset", required=True)
    e.add_argument("--task", required=True, choices=["O1", "O2-S", "O2-C", "X2", "X3"])
    e.add_argument("--case-id", required=True)
    e.add_argument("--response", required=True)
    return p


def _resolve_task_configs(args) -> tuple[Path, Path]:
    if args.config:
        if args.o_config or args.x_config:
            raise ValueError("use either --config or --o-config/--x-config, not both")
        from src.five_task_profile import load_five_task_profile
        profile = load_five_task_profile(args.config)
        return profile.o_family_config, profile.x2x3_config
    if not args.o_config or not args.x_config:
        raise ValueError("provide --config, or provide both --o-config and --x-config")
    return Path(args.o_config).resolve(), Path(args.x_config).resolve()


def _doctor(root: Path) -> dict:
    tasks = ["O1", "O2-S", "O2-C", "X2", "X3"]
    tokenizer = {"available": False, "version": None, "encoding": "o200k_base"}
    try:
        import tiktoken
        tokenizer["available"] = True
        tokenizer["version"] = getattr(tiktoken, "__version__", None)
        # Force loading of the canonical encoding; this is deliberately fail-closed.
        tiktoken.get_encoding("o200k_base")
    except Exception as exc:
        tokenizer["error"] = f"{type(exc).__name__}: {exc}"
    checks = {
        "python": platform.python_version(),
        "tasks": tasks,
        "contracts": all(
            (root / "contracts" / task / "llm_system_prompt.txt").is_file()
            and not (root / "contracts" / task / "system_prompt.txt").exists()
            for task in tasks
        ),
        "benchmark_schemas": all((root / "contracts" / task / "schemas" / "benchmark_case.schema.json").is_file() for task in tasks),
        "algorithm_view_assets": all(
            (root / "contracts" / task / "algorithm_contract.json").is_file()
            and (root / "contracts" / task / "schemas" / "algorithm_input.schema.json").is_file()
            and (root / "contracts" / task / "schemas" / "algorithm_evaluation_case.schema.json").is_file()
            for task in tasks
        ),
        "algorithm_api": (root / "src" / "algorithm_api" / "loader.py").is_file(),
        "frozen_format": (root / "docs" / "格式规范_冻结版.txt").is_file(),
        "five_task_profile": (root / "configs" / "five_task_profile.json").is_file(),
        "canonical_tokenizer": tokenizer,
        "generated_local_output_absent": not (root / "local_output").exists(),
    }
    checks["valid"] = bool(
        checks["contracts"]
        and checks["benchmark_schemas"]
        and checks["algorithm_view_assets"]
        and checks["algorithm_api"]
        and checks["frozen_format"]
        and checks["five_task_profile"]
        and tokenizer["available"]
        and checks["generated_local_output_absent"]
    )
    return checks


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    root = Path(__file__).resolve().parent

    if args.command == "doctor":
        checks = _doctor(root)
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if checks["valid"] else 2

    if args.command == "derive-cases":
        from src.five_task_orchestrator import derive_five_task_dataset
        try:
            o_cfg, x_cfg = _resolve_task_configs(args)
            result = derive_five_task_dataset(args.environment, o_cfg, x_cfg, args.output)
        except Exception as exc:
            print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "produce":
        from src.five_task_orchestrator import produce_environment_and_five_tasks
        try:
            o_cfg, x_cfg = _resolve_task_configs(args)
            result = produce_environment_and_five_tasks(args.environment_config, o_cfg, x_cfg, args.output)
        except Exception as exc:
            print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "verify-dataset":
        from src.five_task_orchestrator import verify_five_task_dataset
        result = verify_five_task_dataset(args.dataset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 2

    if args.command == "validate-output":
        from src.case_core.dut_evaluation import validate_dut_response
        try:
            result = validate_dut_response(args.dataset, args.task, args.case_id, args.response)
        except Exception as exc:
            print(json.dumps({"valid": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("valid") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
