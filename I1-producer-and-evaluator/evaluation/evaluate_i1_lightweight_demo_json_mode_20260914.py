from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODELS = [
    "Qwen/Qwen3-8B",
    "THUDM/GLM-4-9B-0414",
]
TASKS = ("I1-S", "I1-C", "I1-D")
MAX_ATTEMPTS = 3
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").replace(":", "_")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def model_response(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system_text: str,
    user_text: str,
    json_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 2048,
    }
    # Qwen3 supports disabling thinking for strict JSON tasks. SiliconFlow accepts
    # this request option for the paired panel; it is kept identical across calls.
    payload["enable_thinking"] = False
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    request_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    last_error = "UNKNOWN_ERROR"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        request = urllib.request.Request(
            endpoint,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                status = int(response.getcode())
                body = response.read()
            if not 200 <= status < 300:
                last_error = f"HTTP_{status}"
                if (status == 429 or 500 <= status <= 599) and attempt < MAX_ATTEMPTS:
                    time.sleep(1.0 * (2 ** (attempt - 1)))
                    continue
                raise RuntimeError(last_error)
            envelope = json.loads(body.decode("utf-8"))
            choice = envelope["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if not isinstance(content, str):
                raise RuntimeError("SUCCESS_RESPONSE_CONTENT_NOT_TEXT")
            usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else None
            public_usage = {}
            if usage is not None:
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = usage.get(key)
                    public_usage[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            metadata = {
                "status": "success",
                "attempts": attempt,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "http_status": status,
                "response_id": envelope.get("id") if isinstance(envelope.get("id"), str) else None,
                "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
                "usage": public_usage or None,
                "endpoint": endpoint,
                "request": {
                    "model": model,
                    "temperature": 0,
                    "top_p": 1,
                    "max_tokens": 2048,
                "enable_thinking": False,
                "response_format": {"type": "json_object"} if json_mode else None,
                },
            }
            return content, metadata
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP_{exc.code}"
            if (exc.code == 429 or 500 <= exc.code <= 599) and attempt < MAX_ATTEMPTS:
                time.sleep(1.0 * (2 ** (attempt - 1)))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            last_error = type(exc).__name__.upper()
            if attempt < MAX_ATTEMPTS:
                time.sleep(1.0 * (2 ** (attempt - 1)))
                continue
            break
        except RuntimeError as exc:
            last_error = str(exc)
            break
    return "", {
        "status": "api_failure",
        "attempts": MAX_ATTEMPTS,
        "error": last_error,
        "endpoint": endpoint,
        "request": {
            "model": model,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 2048,
            "enable_thinking": False,
            "response_format": {"type": "json_object"} if json_mode else None,
        },
    }


def validate_case_layout(demo: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for task in TASKS:
        system_path = demo / task / "llm_system_prompt.txt"
        if not system_path.is_file():
            raise FileNotFoundError(system_path)
        system_text = system_path.read_text(encoding="utf-8")
        case_dir = demo / task / "cases"
        eval_dir = demo / task / "evaluation_cases"
        case_paths = sorted(case_dir.glob("*.json"))
        if len(case_paths) != 9:
            raise ValueError(f"{task} expected 9 cases, got {len(case_paths)}")
        for case_path in case_paths:
            evaluation_path = eval_dir / case_path.name
            benchmark = read_json(case_path)
            evaluation = read_json(evaluation_path)
            if list(benchmark) != ["case_id", "llm_prompt", "answer"]:
                raise ValueError(f"invalid benchmark envelope: {case_path}")
            if list(evaluation) != ["case_id", "prompt"]:
                raise ValueError(f"invalid evaluation envelope: {evaluation_path}")
            if evaluation["case_id"] != benchmark["case_id"] or evaluation["prompt"] != benchmark["llm_prompt"]:
                raise ValueError(f"evaluation mapping mismatch: {case_path}")
            records.append(
                {
                    "task": task,
                    "case_id": benchmark["case_id"],
                    "system_text": system_text,
                    "prompt": evaluation["prompt"],
                    "answer": benchmark["answer"],
                    "prompt_sha256": sha256_text(evaluation["prompt"]),
                    "case_path": case_path.as_posix(),
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-root", type=Path, required=True)
    parser.add_argument("--producer-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-cases-per-model", type=int, default=0)
    parser.add_argument("--json-mode", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("SILICONFLOW_API_KEY is not set")
    base_url = os.environ.get("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url:
        raise SystemExit("SILICONFLOW_BASE_URL is empty")

    sys.path.insert(0, str(args.producer_root))
    from src.i1.validator import validate_i1_output

    records = validate_case_layout(args.demo_root)
    if args.max_cases_per_model > 0:
        selected = []
        for task in TASKS:
            selected.extend([record for record in records if record["task"] == task][: args.max_cases_per_model])
        records = selected

    args.output_root.mkdir(parents=True, exist_ok=True)
    run_config = {
        "provider": "SiliconFlow",
        "base_url": base_url,
        "endpoint": base_url + "/chat/completions",
        "models": MODELS,
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 2048,
        "enable_thinking": False,
        "json_mode": args.json_mode,
        "response_format": {"type": "json_object"} if args.json_mode else None,
        "max_attempts": MAX_ATTEMPTS,
        "case_count_per_model": len(records),
        "case_source": "I1_MENTOR_LIGHTWEIGHT_COMPLETE_DEMO_20260913_REORDERED_20260914",
        "producer_root": "current V2.1.3 producer; absolute path intentionally omitted",
        "started_at_utc": utc_now(),
    }
    write_json(args.output_root / "RUN_CONFIG.json", run_config)
    write_json(
        args.output_root / "MODEL_SELECTION.json",
        {
            "provider": "SiliconFlow",
            "exact_model_ids": MODELS,
            "models_endpoint": base_url + "/models",
            "selection_note": "Paired 8B/9B Chinese-capable model comparison; not a broad capability-tier experiment.",
        },
    )

    all_rows: list[dict[str, Any]] = []
    for model in MODELS:
        model_dir = args.output_root / safe_name(model)
        for record in records:
            task = record["task"]
            case_id = record["case_id"]
            slug = safe_name(case_id)
            raw_path = model_dir / "raw_model_outputs" / task / f"{slug}.txt"
            score_path = model_dir / "scores" / task / f"{slug}.json"
            metadata_path = model_dir / "api_metadata" / task / f"{slug}.json"
            if metadata_path.is_file() and raw_path.is_file() and score_path.is_file():
                print(f"SKIP {model} {task}/{case_id}", flush=True)
                continue
            raw, metadata = model_response(
                api_key=api_key,
                base_url=base_url,
                model=model,
                system_text=record["system_text"],
                user_text=record["prompt"],
                json_mode=args.json_mode,
            )
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(raw, encoding="utf-8")
            metadata.update(
                {
                    "model": model,
                    "task": task,
                    "case_id": case_id,
                    "prompt_sha256": record["prompt_sha256"],
                    "raw_output_sha256": sha256_text(raw) if metadata["status"] == "success" else None,
                    "raw_output_path": raw_path.relative_to(args.output_root).as_posix(),
                    "truth_was_sent_to_api": False,
                    "system_prompt_source": f"{task}/llm_system_prompt.txt",
                    "user_input_source": f"{task}/evaluation_cases/{case_id}.json",
                }
            )
            write_json(metadata_path, metadata)
            if metadata["status"] == "success":
                validation = validate_i1_output(record["answer"], raw)
                score = {
                    "model": model,
                    "task": task,
                    "case_id": case_id,
                    "validator": "src.i1.validator.validate_i1_output",
                    "api_success": True,
                    "json_parse_success": validation["strict_json_parse_success"],
                    "raw_format_valid": validation["raw_format_valid"],
                    "schema_valid": validation["strict_schema_valid"],
                    "semantic_json_parse_success": validation["semantic_json_parse_success"],
                    "semantic_exact_match": validation["semantic_exact_match"],
                    "final_case_pass": validation["final_case_pass"],
                    "objective_set_accuracy": validation["objective_set_accuracy"],
                    "objective_order_accuracy": validation["objective_order_accuracy"],
                    "field_results": validation["field_results"],
                    "semantic_parse_source": validation["semantic_parse_source"],
                    "format_error_type": validation["format_error_type"],
                    "errors": validation["errors"],
                }
            else:
                score = {
            "model": model,
                    "task": task,
                    "case_id": case_id,
                    "validator": "src.i1.validator.validate_i1_output",
                    "api_success": False,
                    "semantic_exact_match": False,
                    "final_case_pass": False,
                    "errors": [metadata.get("error", "API_FAILURE")],
                }
            write_json(score_path, score)
            row = {**metadata, **score}
            row.pop("request", None)
            all_rows.append(row)
            print(
                f"DONE {model} {task}/{case_id} api={metadata['status']} "
                f"semantic={score.get('semantic_exact_match')} strict={score.get('final_case_pass')}",
                flush=True,
            )

    # Rebuild summary from all persisted score files so resume runs are complete.
    summary_rows: list[dict[str, Any]] = []
    for model in MODELS:
        model_dir = args.output_root / safe_name(model)
        for task in TASKS:
            for score_path in sorted((model_dir / "scores" / task).glob("*.json")):
                score = read_json(score_path)
                if "api_success" not in score:
                    metadata_path = model_dir / "api_metadata" / task / score_path.name
                    metadata_path = metadata_path.with_name(metadata_path.name)
                    metadata_path = metadata_path.with_suffix(".json")
                    if metadata_path.is_file():
                        metadata = read_json(metadata_path)
                        score["api_success"] = metadata.get("status") == "success"
                summary_rows.append(score)

    summary: dict[str, Any] = {
        "provider": "SiliconFlow",
        "models": {},
        "case_count_per_model": len(records),
        "total_expected_calls": len(records) * len(MODELS),
        "total_scored_rows": len(summary_rows),
    }
    for model in MODELS:
        model_rows = [row for row in summary_rows if row.get("model") == model]
        model_summary: dict[str, Any] = {}
        for task in TASKS:
            rows = [row for row in model_rows if row.get("task") == task]
            model_summary[task] = {
                "total": len(rows),
                "api_success": sum(row.get("api_success") is True for row in rows),
                "semantic_exact_match": sum(row.get("semantic_exact_match") is True for row in rows),
                "raw_format_valid": sum(row.get("raw_format_valid") is True for row in rows),
                "final_case_pass": sum(row.get("final_case_pass") is True for row in rows),
            }
        model_summary["overall"] = {
            "total": len(model_rows),
            "api_success": sum(row.get("api_success") is True for row in model_rows),
            "semantic_exact_match": sum(row.get("semantic_exact_match") is True for row in model_rows),
            "raw_format_valid": sum(row.get("raw_format_valid") is True for row in model_rows),
            "final_case_pass": sum(row.get("final_case_pass") is True for row in model_rows),
        }
        summary["models"][model] = model_summary
    summary["finished_at_utc"] = utc_now()
    write_json(args.output_root / "SUMMARY.json", summary)

    lines = [
        "# I1 Lightweight Demo SiliconFlow Trial",
        "",
        "本试评使用同一套 I1-S/I1-C/I1-D system prompt 与 27 个 evaluation Case，未向模型发送 answer、拓扑或 provenance。",
        "",
        f"模型：{', '.join(MODELS)}",
        "",
        "| Model | Task | API success | Semantic exact | Raw format valid | Final case pass |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        for task in (*TASKS, "overall"):
            value = summary["models"][model][task]
            lines.append(
                f"| `{model}` | {task} | {value['api_success']}/{value['total']} | "
                f"{value['semantic_exact_match']}/{value['total']} | "
                f"{value['raw_format_valid']}/{value['total']} | "
                f"{value['final_case_pass']}/{value['total']} |"
            )
    (args.output_root / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
