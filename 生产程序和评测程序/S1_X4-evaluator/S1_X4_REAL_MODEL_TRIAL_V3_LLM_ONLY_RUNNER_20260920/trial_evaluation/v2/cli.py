from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
from pathlib import Path

from trial_evaluation.v2.capability_probe import run_capability_probe
from trial_evaluation.v2.config import build_profile
from trial_evaluation.v2.confirm import run_confirm16
from trial_evaluation.v2.diagnostic import run_protocol_diagnostic
from trial_evaluation.v2.pilot import run_pilot_v2_parallel
from trial_evaluation.security import scan_for_secrets
from trial_evaluation.v2.offline import run_v2_offline_gate


def _doctor() -> dict[str, object]:
    tokenizer: dict[str, object] = {"available": False, "version": None, "encoding": "o200k_base"}
    try:
        import tiktoken

        tokenizer["version"] = str(getattr(tiktoken, "__version__", None))
        tiktoken.get_encoding("o200k_base")
        tokenizer["available"] = tokenizer["version"] == "0.14.0"
    except Exception as exc:
        tokenizer["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    imports = {
        "official_dynamic_session": bool(importlib.util.find_spec("src.s1_x4.evaluator")),
        "siliconflow_provider": bool(importlib.util.find_spec("trial_evaluation.providers.siliconflow")),
    }
    result = {
        "schema_version": "TRIAL_EVALUATION_V2_DOCTOR_V1",
        "python": platform.python_version(),
        "os": platform.platform(),
        "imports": imports,
        "canonical_tokenizer": tokenizer,
        "siliconflow": {
            "provider": "siliconflow",
            "requested_model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "siliconflow_key_present": bool(os.environ.get("SILICONFLOW_API_KEY")),
        },
    }
    result["valid"] = bool(tokenizer["available"] and all(imports.values()))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S1/X4 V2 protocol-hardening trial runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    offline = sub.add_parser("offline")
    offline.add_argument("--dataset", required=True)
    offline.add_argument("--output", required=True)
    offline.add_argument("--max-steps", type=int, default=1)
    probe = sub.add_parser("capability-probe")
    probe.add_argument("--output", required=True)
    probe.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash")
    diagnostic = sub.add_parser("diagnostic")
    diagnostic.add_argument("--dataset", required=True)
    diagnostic.add_argument("--output", required=True)
    diagnostic.add_argument("--capability-probe", required=True)
    diagnostic.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash")
    diagnostic.add_argument("--max-steps", type=int, default=5)
    confirm = sub.add_parser("confirm16")
    confirm.add_argument("--dataset", required=True)
    confirm.add_argument("--output", required=True)
    confirm.add_argument("--diagnostic", required=True)
    confirm.add_argument("--profile", default="B")
    confirm.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash")
    confirm.add_argument("--max-steps", type=int, default=16)
    pilot = sub.add_parser("pilot")
    pilot.add_argument("--dataset", required=True)
    pilot.add_argument("--output", required=True)
    pilot.add_argument("--confirm16", required=True)
    pilot.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash")
    pilot.add_argument("--profile", default="B")
    pilot.add_argument("--max-steps", type=int, default=64)
    pilot.add_argument("--episode-concurrency", type=int, default=3, choices=(1, 2, 3))
    secret_scan = sub.add_parser("secret-scan")
    secret_scan.add_argument("--root", required=True)
    pilot.add_argument("--execute", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        result = _doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 2
    if args.command == "offline":
        result = run_v2_offline_gate(args.dataset, args.output, max_steps=args.max_steps)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "capability-probe":
        config = build_profile("A", "S1")
        config["model"] = args.model
        result = run_capability_probe(config, output_path=args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "diagnostic":
        probe = json.loads(Path(args.capability_probe).read_text(encoding="utf-8"))
        if probe.get("status") != "PASS" or probe.get("exact_model_available") is not True:
            result = {"status": "CAPABILITY_GATE_FAIL", "capability_probe": probe}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "PROTOCOL_DIAGNOSTIC_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        if not os.environ.get("SILICONFLOW_API_KEY"):
            result = {"status": "NOT_RUN_NO_KEY", "real_api_execution": "NOT_RUN_NO_KEY"}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "PROTOCOL_DIAGNOSTIC_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        result = run_protocol_diagnostic(
            args.dataset,
            args.output,
            model=args.model,
            max_steps=args.max_steps,
            secrets=(os.environ["SILICONFLOW_API_KEY"],),
        )
        print(json.dumps({key: value for key, value in result.items() if key != "profiles"}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "confirm16":
        diagnostic = json.loads(Path(args.diagnostic).read_text(encoding="utf-8"))
        selected = next((item for item in diagnostic.get("profiles", []) if item.get("profile") == str(args.profile).upper()), None)
        if not selected or not selected.get("summary", {}).get("protocol_gate_pass") or not selected.get("summary", {}).get("infra_gate_pass"):
            result = {"status": "DIAGNOSTIC_PROFILE_GATE_FAIL", "profile": args.profile}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "CONFIRM16_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        if not os.environ.get("SILICONFLOW_API_KEY"):
            result = {"status": "NOT_RUN_NO_KEY", "real_api_execution": "NOT_RUN_NO_KEY"}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "CONFIRM16_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        result = run_confirm16(
            args.dataset,
            args.output,
            model=args.model,
            profile_name=args.profile,
            max_steps=args.max_steps,
            secrets=(os.environ["SILICONFLOW_API_KEY"],),
        )
        print(json.dumps({key: value for key, value in result.items() if key != "unit_results"}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "pilot":
        confirm = json.loads(Path(args.confirm16).read_text(encoding="utf-8"))
        if confirm.get("status") != "PASS":
            result = {"status": "CONFIRM16_GATE_FAIL", "confirm16_status": confirm.get("status")}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "PILOT_V2_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        if not args.execute:
            result = {"status": "DRY_RUN", "real_api_execution": "NOT_RUN_DRY_RUN", "evaluation_scope": "PILOT_V2_PREFIX_64", "max_steps": args.max_steps}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "DRY_RUN.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not os.environ.get("SILICONFLOW_API_KEY"):
            result = {"status": "NOT_RUN_NO_KEY", "real_api_execution": "NOT_RUN_NO_KEY"}
            Path(args.output).mkdir(parents=True, exist_ok=True)
            Path(args.output, "PILOT_V2_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        result = run_pilot_v2_parallel(
            args.dataset,
            args.output,
            model=args.model,
            profile_name=args.profile,
            max_steps=args.max_steps,
            episode_concurrency=args.episode_concurrency,
            secrets=(os.environ["SILICONFLOW_API_KEY"],),
        )
        print(json.dumps({key: value for key, value in result.items() if key != "unit_results"}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "secret-scan":
        root = Path(args.root).resolve()
        values: list[str] = []
        files: list[str] = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size <= 10_000_000:
                try:
                    values.append(path.read_text(encoding="utf-8"))
                    files.append(str(path.relative_to(root)))
                except (UnicodeDecodeError, OSError):
                    continue
        secrets = tuple(value for value in (os.environ.get("SILICONFLOW_API_KEY"), os.environ.get("DEEPSEEK_API_KEY")) if value)
        # The source legitimately contains the literal word ``Bearer`` while
        # constructing the HTTP header.  For release scanning, fail only when
        # an actual configured secret value is present; report generic auth
        # patterns separately so placeholders/tests are not false positives.
        actual_hits = [index for index, value in enumerate(values) if any(secret in value for secret in secrets)]
        generic = scan_for_secrets(values, secrets=())
        result = {
            "passed": not actual_hits,
            "hit_count": len(actual_hits),
            "hit_indexes": actual_hits,
            "generic_auth_pattern_count": int(generic.get("hit_count", 0)),
            "root": str(root),
            "scanned_file_count": len(files),
            "secret_values_not_printed": True,
        }
        if actual_hits:
            result["hit_files"] = [files[index] for index in actual_hits]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
