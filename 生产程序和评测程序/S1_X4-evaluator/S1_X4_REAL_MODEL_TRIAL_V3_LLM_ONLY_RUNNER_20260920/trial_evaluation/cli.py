from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from trial_evaluation.checkpoint import atomic_write_json
from trial_evaluation.config import BudgetGuard, PhasePlan, build_phase_plan, load_model_catalog
from trial_evaluation.episodes import load_episode_bundle
from trial_evaluation.offline import run_offline_gate
from trial_evaluation.providers.base import ModelConfig, ProviderError
from trial_evaluation.providers.deepseek import create_deepseek_provider
from trial_evaluation.reports import load_unit_summaries, write_phase_markdown, write_phase_reports
from trial_evaluation.runner import run_unit
from trial_evaluation.security import scan_for_secrets


def _default_model_config_path() -> Path:
    return Path(__file__).resolve().with_name("model_config.example.json")


def _directory_manifest(root: Path) -> dict[str, Any]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
    digest = hashlib.sha256("".join(f"{row['sha256']}  {row['path']}\n" for row in rows).encode()).hexdigest()
    return {"root": str(root.resolve()), "file_count": len(rows), "tree_sha256": digest, "files": rows}


def _provider(config: ModelConfig):
    if config.provider == "deepseek":
        return create_deepseek_provider(config.to_public_dict())
    raise ValueError(f"unsupported provider: {config.provider}")


def _doctor() -> dict[str, Any]:
    tokenizer: dict[str, Any] = {"available": False, "version": None, "encoding": "o200k_base"}
    try:
        import tiktoken

        tokenizer["version"] = str(getattr(tiktoken, "__version__", None))
        tiktoken.get_encoding("o200k_base")
        tokenizer["available"] = tokenizer["version"] == "0.14.0"
    except Exception as exc:
        tokenizer["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    imports = {}
    try:
        from src.s1_x4.evaluator import DynamicEpisodeSession  # noqa: F401

        imports["official_dynamic_session"] = True
    except Exception as exc:
        imports["official_dynamic_session"] = False
        imports["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY"))
    result = {
        "schema_version": "TRIAL_EVALUATION_DOCTOR_V1",
        "python": platform.python_version(),
        "os": platform.platform(),
        "imports": imports,
        "canonical_tokenizer": tokenizer,
        "deepseek": {
            "provider": "deepseek",
            "requested_model": "deepseek-flash",
            "base_url": "https://api.deepseek.com",
            "api_key_present": key_present,
        },
        "deepseek_provider_ready": key_present and imports.get("official_dynamic_session", False),
    }
    result["valid"] = bool(tokenizer["available"] and imports.get("official_dynamic_session", False))
    return result


def _select_model(path: Path | str, requested_model: str) -> ModelConfig:
    configs = load_model_catalog(path)
    for config in configs:
        if config.model == requested_model:
            return config
    raise ValueError(f"model {requested_model!r} is not defined in {path}")


def _budget_limits(plan: PhasePlan, args: argparse.Namespace) -> tuple[int, int, int, float]:
    if plan.name == "PHASE1_SMOKE":
        defaults = (256, 2_000_000, 100_000, 180.0)
    elif plan.name == "PHASE2_REPRESENTATIVE_PILOT":
        defaults = (6000, 20_000_000, 1_000_000, 720.0)
    elif plan.name == "PHASE3_H512_REPRESENTATIVE":
        defaults = (6000, 20_000_000, 1_000_000, 720.0)
    else:
        defaults = (25000, 100_000_000, 5_000_000, 1440.0)
    return (
        args.max_api_calls if args.max_api_calls is not None else defaults[0],
        args.max_input_tokens if args.max_input_tokens is not None else defaults[1],
        args.max_output_tokens if args.max_output_tokens is not None else defaults[2],
        args.max_wall_time_minutes if args.max_wall_time_minutes is not None else defaults[3],
    )


def _budget_for(plan: PhasePlan, args: argparse.Namespace) -> BudgetGuard:
    limits = _budget_limits(plan, args)
    return BudgetGuard(
        max_api_calls=limits[0],
        max_input_tokens=limits[1],
        max_output_tokens=limits[2],
        max_wall_time_minutes=limits[3],
    )


def _write_run_config(output: Path, *, dataset: Path, config: ModelConfig, plan: PhasePlan, args: argparse.Namespace) -> None:
    config_dir = output / "CONFIG"
    config_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(config_dir / "trial_eval_models.resolved.json", {
        "provider": config.provider,
        "requested_model": config.model,
        "response_model": None,
        "base_url": config.base_url,
        "api_key_env": config.api_key_env,
        "endpoint_style": "OpenAI-compatible Chat Completions",
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_output_tokens": config.max_output_tokens,
        "budget_max_output_tokens": _budget_limits(plan, args)[2],
        "timeout_seconds": config.timeout_seconds,
        "max_transport_retries": config.max_transport_retries,
        "episode_concurrency": 1,
        "response_format": config.response_format,
        "reasoning_effort": config.reasoning_effort,
        "api_key_value_saved": False,
    })
    atomic_write_json(output / "CONFIG" / "trial_plan.json", {
        "phase": plan.name,
        "max_steps": plan.max_steps,
        "topologies": list(plan.topologies),
        "conditions": list(plan.conditions),
        "tasks": list(plan.tasks),
        "modalities": list(plan.modalities),
        "unit_count": plan.unit_count(),
        "dataset_root": str(dataset),
    })
    atomic_write_json(output / "CONFIG" / "input_sha256.json", _directory_manifest(dataset))


def _run_phase(dataset: Path, config: ModelConfig, plan: PhasePlan, output: Path, args: argparse.Namespace) -> dict[str, Any]:
    phase_root = output / plan.name / config.model
    phase_root.mkdir(parents=True, exist_ok=True)
    guard = _budget_for(plan, args)
    secret_values = tuple(value for value in (os.environ.get(config.api_key_env),) if value)
    all_results = []
    stopped_reason = None
    for task in plan.tasks:
        for topology_id in plan.topologies:
            for condition_id in plan.conditions:
                for modality in plan.modalities:
                    bundle = load_episode_bundle(
                        dataset,
                        task=task,
                        modality=modality,
                        topology_id=topology_id,
                        condition_id=condition_id,
                    )
                    current_provider = _provider(config)
                    result = run_unit(
                        bundle,
                        current_provider,
                        phase_root,
                        max_steps=plan.max_steps,
                        resume=bool(args.resume),
                        budget=guard,
                        secrets=secret_values,
                    )
                    all_results.append(result)
                    if result["status"] not in {"PASS", "PREFIX_COMPLETE"}:
                        stopped_reason = result["status"]
                        break
                if stopped_reason:
                    break
            if stopped_reason:
                break
        if stopped_reason:
            break
    report_dir = output / "REPORTS"
    report_stats = write_phase_reports(phase_root, report_dir=report_dir, report_title=plan.name)
    write_phase_markdown(
        report_dir / ("SMOKE_REPORT.md" if plan.name == "PHASE1_SMOKE" else "PILOT_REPORT.md"),
        title=plan.name,
        execution_status="PASS" if stopped_reason is None and len(all_results) == plan.unit_count() else (stopped_reason or "INCOMPLETE"),
        scope="PREFIX_TRIAL" if plan.max_steps < 512 else "FULL_H512",
        max_steps=plan.max_steps,
        summaries=all_results,
    )
    budget_snapshot = guard.snapshot()
    status = "PASS" if stopped_reason is None and len(all_results) == plan.unit_count() and all(row["status"] in {"PASS", "PREFIX_COMPLETE"} for row in all_results) else ("BUDGET_STOP" if stopped_reason == "BUDGET_STOP" else "FAIL")
    result = {
        "status": status,
        "phase": plan.name,
        "evaluation_scope": "PREFIX_TRIAL" if plan.max_steps < 512 else "FULL_H512",
        "max_steps": plan.max_steps,
        "planned_units": plan.unit_count(),
        "completed_units": len(all_results),
        "completed_steps": sum(int(row.get("summary", {}).get("step_count", 0)) for row in all_results),
        "stopped_reason": stopped_reason,
        "budget": budget_snapshot,
        "report_stats": report_stats,
        "unit_results": all_results,
    }
    atomic_write_json(output / "PHASE_RESULT.json", result)
    return result


def _cmd_run(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset).resolve()
    if not dataset.is_dir():
        raise FileNotFoundError(dataset)
    plan = build_phase_plan(args.phase)
    if plan.name == "PHASE4_FULL_MATRIX" and not args.confirm_full:
        raise ValueError("full phase requires --confirm-full in addition to --execute")
    config = _select_model(args.models_config, args.model)
    if args.request_max_output_tokens is not None:
        if args.request_max_output_tokens <= 0:
            raise ValueError("--request-max-output-tokens must be positive")
        config = replace(config, max_output_tokens=args.request_max_output_tokens)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_run_config(output, dataset=dataset, config=config, plan=plan, args=args)
    if not args.execute:
        result = {
            "status": "DRY_RUN",
            "real_api_execution": "NOT_RUN_DRY_RUN",
            "phase": plan.name,
            "model": config.model,
            "unit_count": plan.unit_count(),
            "max_steps": plan.max_steps,
            "output": str(output),
        }
        atomic_write_json(output / "DRY_RUN.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if not os.environ.get(config.api_key_env):
        result = {
            "status": "NOT_RUN_NO_KEY",
            "real_api_execution": "NOT_RUN_NO_KEY",
            "phase": plan.name,
            "model": config.model,
            "unit_count": plan.unit_count(),
            "max_steps": plan.max_steps,
            "api_key_env": config.api_key_env,
            "output": str(output),
        }
        atomic_write_json(output / "NOT_RUN_NO_KEY.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    offline = run_offline_gate(dataset, output / "OFFLINE_VERIFICATION", max_steps=min(2, plan.max_steps))
    atomic_write_json(output / "OFFLINE_VERIFICATION" / "OFFLINE_GATE.json", offline)
    if offline.get("status") != "PASS":
        result = {"status": "OFFLINE_GATE_FAIL", "real_api_execution": "NOT_STARTED", "offline_gate": offline}
        atomic_write_json(output / "PHASE_RESULT.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    result = _run_phase(dataset, config, plan, output, args)
    result["real_api_execution"] = "RUN"
    print(json.dumps({key: value for key, value in result.items() if key != "unit_results"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


def _cmd_offline(args: argparse.Namespace) -> int:
    result = run_offline_gate(args.dataset, args.output, max_steps=args.max_steps)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


def _cmd_summarize(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    result = write_phase_reports(root, report_dir=args.report_dir, report_title=args.title)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_secret_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    values = []
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.stat().st_size <= 10_000_000:
            try:
                values.append(path.read_text(encoding="utf-8"))
                files.append(str(path.relative_to(root)))
            except (UnicodeDecodeError, OSError):
                continue
    result = scan_for_secrets(values, secrets=tuple(value for value in (os.environ.get("DEEPSEEK_API_KEY"),) if value))
    result["root"] = str(root)
    result["scanned_file_count"] = len(files)
    if not result["passed"]:
        result["hit_files"] = [files[index] for index in result["hit_indexes"]]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S1/X4 DeepSeek real-model trial runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    offline = sub.add_parser("offline")
    offline.add_argument("--dataset", required=True)
    offline.add_argument("--output", required=True)
    offline.add_argument("--max-steps", type=int, default=2)
    run = sub.add_parser("run")
    run.add_argument("--phase", choices=("smoke", "pilot", "h512_representative", "full"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--dataset", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--models-config", default=str(_default_model_config_path()))
    run.add_argument("--execute", action="store_true")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--confirm-full", action="store_true")
    run.add_argument("--max-api-calls", type=int)
    run.add_argument("--max-input-tokens", type=int)
    run.add_argument("--max-output-tokens", type=int)
    run.add_argument("--request-max-output-tokens", type=int)
    run.add_argument("--max-wall-time-minutes", type=float)
    summary = sub.add_parser("summarize")
    summary.add_argument("--root", required=True)
    summary.add_argument("--report-dir", required=True)
    summary.add_argument("--title", default="S1/X4 Trial Report")
    scan = sub.add_parser("secret-scan")
    scan.add_argument("--root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = _doctor()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 2
        if args.command == "offline":
            return _cmd_offline(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "summarize":
            return _cmd_summarize(args)
        if args.command == "secret-scan":
            return _cmd_secret_scan(args)
    except Exception as exc:
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
