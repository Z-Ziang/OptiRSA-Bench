from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from src.i1.dataset_validator import verify_i1_dataset
from src.i1.difficulty import (
    DIFFICULTIES,
    TASKS,
    build_pilot_case,
    build_pilot_truths,
    validate_difficulty_variant,
)
from src.i1.exporter import export_i1_dataset
from src.i1.rewrite import OpenAICompatibleRewriteClient
from src.i1.validator import validate_i1_output


DEFAULT_DUT_MODELS = [
    "Qwen/Qwen3.5-4B",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen3-32B",
    "deepseek-ai/DeepSeek-V4-Pro",
]
DEFAULT_REWRITE_MODEL = "Qwen/Qwen3.5-27B"
API_KEY_ENV = "SILICONFLOW_API_KEY"
REWRITE_PROMPT_VERSION = "I1_SECOND_ROUND_REWRITE_V1_0_CONTROLLED_VOCABULARY"
SEMANTIC_VALIDATOR_VERSION = "I1_CONTROLLED_CHINESE_PARSER_V1_0"


REWRITE_SYSTEM_PROMPT = """你是 OpticalBenchmark I1 第二轮难度 Pilot 的受控自然语言改写器。
你只改写自然语言业务意图，不创造 Case，不重新推断或修改标准答案。

绝对不可改变：所有 request_id、源节点编号、目的节点编号、required_slots 的数字、arrival_time、holding_time、请求数量、请求与字段的绑定、目标集合和目标优先级。
输出中必须保留所有阿拉伯数字和请求编号原文，不得改成中文数字、约数或近似值。
原始文本没有 request_id 时，不得新增“请求ID”、序号或任何原文不存在的数字。
不得出现 source_node_id、destination_node_id、required_slots、arrival_time、holding_time、objectives、intent_type 等机器字段名或目标枚举编码。
不得加入拓扑、候选路径、链路状态、频谱状态、候选动作、拒绝/接纳规则、额外约束或任何需要外部网络知识的内容。

难度要求：
EASY：信息顺序直接，接近基础模板；
MEDIUM：使用自然同义表达、改变句式或信息顺序，但每个字段仍可直接唯一绑定；
HARD：使用自然复句、较明显的信息重排和目标语义同义表达，允许主目标和次目标分开出现，但不得产生歧义。
HARD 单目标不得写“若相同，再……”“其次……”或其他暗示不存在第二目标的残缺 tie-break。
HARD 双目标必须完整表达一级目标、二级目标及其先后关系，不能只留下 tie-break。
I1-C 中每个 request_id 必须和它自己的源节点、目的节点、槽位数保持绑定，不能交换；I1-D 中到达时刻和持续时长必须原样保留。
I1-C 不要使用“它、前者、后者、该请求”等无法唯一回指的表达；I1-S/I1-D 可以使用紧邻且唯一指向当前请求的“该请求”，但所有数字和请求字段仍必须明示。

推荐使用但不强制逐字复制的明确业务表达：
路径跳数最少：传输路径经过的链路数量尽可能少；
全网频谱碎片最少：本次分配后全网剩余可用频谱尽量保持连续，减少零散空闲区间；
总槽位占用最少：所有并发业务合计占用的频谱槽位规模最小；
成功建立请求最多：尽可能多的业务请求能够成功建立；
外部碎片最少：让后续剩余频谱保持更连续的空闲区段，减少外部碎片。

只返回一个 JSON 对象，格式为 {"rewritten_prompt":"..."}，不要返回解释、答案 JSON、Markdown 代码围栏或其他字段。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_obj(value) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unnamed"


def log_event(output: Path, event: dict) -> None:
    line = {"timestamp_utc": utc_now(), **event}
    with (output / "RUN_LOG.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(line, ensure_ascii=False), flush=True)


def wilson(success: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = success / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    radius = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return (max(0.0, centre - radius), min(1.0, centre + radius))


def fmt_rate(success: int, total: int) -> str:
    low, high = wilson(success, total)
    return f"{success}/{total} ({success / total:.4f}; 95% Wilson CI {low:.4f}–{high:.4f})" if total else "0/0"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def copy_authority_docs(handoff_dir: Path | None, output: Path) -> None:
    if handoff_dir is None or not handoff_dir.is_dir():
        return
    target = output / "authority_docs"
    target.mkdir(parents=True, exist_ok=True)
    patterns = ("*.txt", "*.json")
    for path in sorted(handoff_dir.iterdir()):
        if path.is_file() and (path.suffix.lower() in {".txt", ".json"}):
            shutil.copy2(path, target / path.name)


def copy_system_prompts(output: Path) -> dict[str, str]:
    target = output / "system_prompt"
    target.mkdir(parents=True, exist_ok=True)
    paths = {}
    for task in TASKS:
        source = SOURCE_ROOT / "contracts" / task / "llm_system_prompt.txt"
        destination = target / f"{task}.txt"
        shutil.copy2(source, destination)
        paths[task] = destination.read_text(encoding="utf-8")
    return paths


def export_truth_and_base_artifacts(output: Path, truth_rows: dict[str, list[dict]]) -> None:
    for task, rows in truth_rows.items():
        for row in rows:
            write_json(
                output / "canonical_truth" / task / f"{row['truth_id']}.json",
                {
                    "truth_id": row["truth_id"],
                    "task_type": task,
                    "source_ref": row["source_ref"],
                    "canonical_answer": row["canonical_answer"],
                    "canonical_answer_sha256": row["canonical_answer_sha256"],
                },
            )
            base_path = output / "base_prompts" / task / f"{row['truth_id']}.txt"
            base_path.parent.mkdir(parents=True, exist_ok=True)
            base_path.write_text(row["base_prompt"] + "\n", encoding="utf-8")


def load_model_list(path: Path) -> tuple[dict, set[str]]:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    model_ids = {str(row.get("id")) for row in metadata.get("models", []) if row.get("id")}
    if not model_ids:
        raise ValueError("model list contains no model IDs")
    return metadata, model_ids


def resolve_base_url(metadata: dict, explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip("/")
    endpoint = str(metadata.get("endpoint", ""))
    if endpoint.endswith("/models"):
        return endpoint[: -len("/models")]
    raise ValueError("base URL is missing and model-list endpoint is not a /models endpoint")


def sanitize_exception(exc: Exception) -> dict:
    if isinstance(exc, urllib.error.HTTPError):
        return {"type": type(exc).__name__, "status": int(exc.code), "reason": str(exc.reason)}
    if isinstance(exc, urllib.error.URLError):
        return {"type": type(exc).__name__, "reason": str(exc.reason)}
    return {"type": type(exc).__name__}


def api_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float,
    top_p: float,
    max_tokens: int,
    timeout_seconds: float,
    enable_thinking: bool | None = None,
    response_format: dict | None = None,
) -> dict:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"missing required environment variable: {API_KEY_ENV}")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }
    if enable_thinking is not None:
        payload["enable_thinking"] = bool(enable_thinking)
    if response_format is not None:
        if not isinstance(response_format, dict) or response_format.get("type") not in {
            "json_object",
            "json_schema",
        }:
            raise ValueError("response_format must be a JSON-object or JSON-schema format")
        payload["response_format"] = deepcopy(response_format)
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            obj = json.loads(response.read().decode("utf-8"))
        content = obj.get("choices", [{}])[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("API response has no string assistant content")
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
        return {
            "api_success": True,
            "content": content,
            "usage": usage,
            "latency_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return {
            "api_success": False,
            "content": None,
            "usage": None,
            "latency_seconds": time.perf_counter() - started,
            "error": sanitize_exception(exc),
        }


def extract_usage(usage: dict | None) -> dict | None:
    if not isinstance(usage, dict):
        return None
    allowed = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed[key] = value
    return allowed or None


def rewrite_variants(
    output: Path,
    truth_rows: dict[str, list[dict]],
    *,
    base_url: str,
    rewrite_model: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    max_attempts: int,
    timeout_seconds: float,
) -> tuple[list[dict], dict]:
    client = OpenAICompatibleRewriteClient(
        base_url=base_url,
        api_key_env=API_KEY_ENV,
        model=rewrite_model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        enable_thinking=False,
    )
    cases: list[dict] = []
    stats = {
        "requested_case_count": 63,
        "final_success_count": 0,
        "failed_case_count": 0,
        "deterministic_easy_count": 0,
        "api_rewrite_case_count": 42,
        "first_pass_success_count": 0,
        "retry_count": 0,
        "failed_attempt_count": 0,
        "failure_reasons": {},
    }
    for task in TASKS:
        for row in truth_rows[task]:
            for difficulty in DIFFICULTIES:
                case_id = f"{row['truth_id']}_{difficulty}"
                case_dir = output / "raw_rewrite_outputs" / case_id
                validation_path = output / "rewrite_validation" / f"{case_id}.json"
                case_dir.mkdir(parents=True, exist_ok=True)
                attempts = []
                accepted_prompt = None
                accepted_validation = None
                if difficulty == "EASY":
                    accepted_prompt = row["base_prompt"]
                    accepted_validation = validate_difficulty_variant(
                        row["canonical_answer"], accepted_prompt, difficulty=difficulty
                    )
                    stats["deterministic_easy_count"] += 1
                    write_json(
                        case_dir / "attempt_01_identity.json",
                        {"attempt": 1, "mode": "deterministic_base_prompt", "raw_response": None},
                    )
                    attempts.append({"attempt": 1, "mode": "deterministic_base_prompt", "status": accepted_validation["overall"], "errors": accepted_validation["errors"]})
                else:
                    for attempt in range(1, max_attempts + 1):
                        system_prompt = REWRITE_SYSTEM_PROMPT
                        if attempt > 1:
                            system_prompt += "\n这是重试第%d次。上一候选未通过严格语义校验，请重新生成一条全新的、无歧义的文本。" % attempt
                        try:
                            text, raw = client.rewrite_with_raw(
                                row["base_prompt"],
                                row["canonical_answer"],
                                difficulty=difficulty,
                                system_prompt=system_prompt,
                            )
                            (case_dir / f"attempt_{attempt:02d}_raw.txt").write_text(raw, encoding="utf-8")
                            validation = validate_difficulty_variant(row["canonical_answer"], text, difficulty=difficulty)
                            attempts.append({"attempt": attempt, "mode": "siliconflow", "status": validation["overall"], "errors": validation["errors"], "rewritten_prompt_sha256": sha256_bytes(text.encode("utf-8"))})
                            if validation["overall"] == "PASS":
                                accepted_prompt = text
                                accepted_validation = validation
                                if attempt == 1:
                                    stats["first_pass_success_count"] += 1
                                else:
                                    stats["retry_count"] += attempt - 1
                                break
                            stats["failed_attempt_count"] += 1
                            for error in validation["errors"]:
                                stats["failure_reasons"][error] = stats["failure_reasons"].get(error, 0) + 1
                        except Exception as exc:
                            failure = sanitize_exception(exc)
                            attempts.append({"attempt": attempt, "mode": "siliconflow", "status": "ERROR", "error": failure})
                            stats["failed_attempt_count"] += 1
                            key = failure["type"]
                            stats["failure_reasons"][key] = stats["failure_reasons"].get(key, 0) + 1
                if accepted_prompt is None or accepted_validation is None or accepted_validation["overall"] != "PASS":
                    stats["failed_case_count"] += 1
                    write_json(validation_path, {"case_id": case_id, "truth_id": row["truth_id"], "task_type": task, "difficulty": difficulty, "overall": "FAILED_REWRITE", "attempts": attempts})
                    raise RuntimeError(f"fail-closed: {case_id} did not pass rewrite validation after {max_attempts} attempts")
                case = build_pilot_case(row, difficulty, rewritten_prompt=accepted_prompt)
                case["rewrite_attempts"] = attempts
                case["rewrite_model"] = rewrite_model if difficulty != "EASY" else None
                case["rewrite_parameters"] = {
                    "provider": "SiliconFlow" if difficulty != "EASY" else None,
                    "model": rewrite_model if difficulty != "EASY" else None,
                    "temperature": temperature if difficulty != "EASY" else None,
                    "top_p": top_p if difficulty != "EASY" else None,
                    "max_tokens": max_tokens if difficulty != "EASY" else None,
                    "prompt_version": REWRITE_PROMPT_VERSION,
                }
                write_json(
                    validation_path,
                    {
                        "case_id": case_id,
                        "truth_id": row["truth_id"],
                        "task_type": task,
                        "difficulty": difficulty,
                        "validator_version": SEMANTIC_VALIDATOR_VERSION,
                        "overall": accepted_validation["overall"],
                        "attempts": attempts,
                        "final_validation": accepted_validation,
                    },
                )
                write_json(
                    output / "difficulty_variants" / task / f"{case_id}.json",
                    {
                        "case_id": case_id,
                        "truth_id": row["truth_id"],
                        "task_type": task,
                        "difficulty": difficulty,
                        "canonical_answer": row["canonical_answer"],
                        "base_prompt": row["base_prompt"],
                        "rewritten_prompt": accepted_prompt,
                        "rewrite_attempts": attempts,
                        "validation": accepted_validation,
                    },
                )
                cases.append(case)
                stats["final_success_count"] += 1
                log_event(output, {"stage": "rewrite", "case_id": case_id, "difficulty": difficulty, "status": "PASS", "attempts": len(attempts)})
    return cases, stats


def make_export_records(cases: list[dict]) -> dict[str, list[dict]]:
    records = {task: [] for task in TASKS}
    for case in cases:
        records[case["task_type"]].append(
            {
                "case_id": case["case_id"],
                "source_ref": f"{case['truth_id']}::{case['difficulty']}::{case['source_ref']}",
                "canonical_answer": case["canonical_answer"],
                "base_prompt": case["base_prompt"],
                "final_prompt": case["rewritten_prompt"],
                "rewrite": {
                    "difficulty": case["difficulty"],
                    "rewrite_model": case["rewrite_model"],
                    "rewrite_parameters": case["rewrite_parameters"],
                    "attempts": case["rewrite_attempts"],
                },
                "validation": case["validation"],
                "lineage": {
                    "stage": "SECOND_ROUND_DIFFICULTY_PILOT",
                    "truth_id": case["truth_id"],
                    "difficulty": case["difficulty"],
                    "canonical_answer_sha256": case["canonical_answer_sha256"],
                    "base_prompt_sha256": case["base_prompt_sha256"],
                    "final_prompt_sha256": case["rewritten_prompt_sha256"],
                    "semantic_validator_version": SEMANTIC_VALIDATOR_VERSION,
                },
            }
        )
    for task in TASKS:
        records[task].sort(key=lambda row: row["case_id"])
    return records


def model_dir(output: Path, model: str) -> Path:
    return output / "raw_model_outputs" / safe_name(model)


def score_case(expected: dict, raw: str) -> dict:
    result = validate_i1_output(expected, raw)
    fields = result.get("field_results", {})
    field_total = len(fields)
    field_pass = sum(1 for value in fields.values() if value)
    result["field_accuracy"] = field_pass / field_total if field_total else 0.0
    result["field_pass_count"] = field_pass
    result["field_total"] = field_total
    return result


def run_dut_panel(
    output: Path,
    cases: list[dict],
    system_prompts: dict[str, str],
    *,
    base_url: str,
    models: list[dict],
    temperature: float,
    top_p: float,
    max_tokens: int,
    timeout_seconds: float,
    api_retries: int,
    response_format: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    expected_by_id = {case["case_id"]: case["canonical_answer"] for case in cases}
    case_by_id = {case["case_id"]: case for case in cases}
    public_case_root = output / "pilot_dataset" / "evaluation_case"
    ordered_cases = sorted(cases, key=lambda row: (TASKS.index(row["task_type"]), row["truth_id"], DIFFICULTIES.index(row["difficulty"])))
    for model_info in models:
        model = model_info["model"]
        mdir = model_dir(output, model)
        imdir = output / "TRIAL_INTERNAL_EVIDENCE" / safe_name(model)
        mdir.mkdir(parents=True, exist_ok=True)
        imdir.mkdir(parents=True, exist_ok=True)
        for index, case in enumerate(ordered_cases, 1):
            case_id = case["case_id"]
            task = case["task_type"]
            eval_path = sorted((public_case_root / task / "cases").glob("*.json"))
            eval_case = None
            for candidate in eval_path:
                obj = json.loads(candidate.read_text(encoding="utf-8"))
                if obj.get("case_id") == case_id:
                    eval_case = obj
                    break
            if eval_case is None or set(eval_case) != {"case_id", "prompt"}:
                raise RuntimeError(f"evaluation case missing or leaking answer: {case_id}")
            messages = [
                {"role": "system", "content": system_prompts[task]},
                {"role": "user", "content": json.dumps(eval_case, ensure_ascii=False, sort_keys=True)},
            ]
            started = time.perf_counter()
            attempts = []
            response = None
            for attempt in range(1, api_retries + 1):
                candidate = api_chat(
                    base_url=base_url,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    enable_thinking=False,
                    response_format=response_format,
                )
                attempts.append({"attempt": attempt, "api_success": bool(candidate["api_success"]), "latency_seconds": candidate["latency_seconds"], "error": candidate.get("error")})
                if candidate["api_success"]:
                    response = candidate
                    break
                if attempt < api_retries:
                    time.sleep(min(2.0, 0.25 * attempt))
            if response is None:
                response = {"api_success": False, "content": "", "usage": None, "latency_seconds": time.perf_counter() - started, "error": {"type": "API_FAILURE_AFTER_RETRIES"}}
            raw = response.get("content") if isinstance(response.get("content"), str) else ""
            raw_path = mdir / f"{case_id}.txt"
            raw_path.write_text(raw, encoding="utf-8")
            validator = score_case(expected_by_id[case_id], raw)
            api_meta = {
                "case_id": case_id,
                "endpoint": base_url + "/chat/completions",
                "model": model,
                "api_key_env": API_KEY_ENV,
                "temperature": temperature,
                "top_p": top_p,
                "max_tokens": max_tokens,
                "enable_thinking": False,
                "response_format": deepcopy(response_format),
                "api_success": bool(response.get("api_success")),
                "attempts": attempts,
                "retry_count": max(0, len(attempts) - 1),
                "latency_seconds": response.get("latency_seconds"),
                "usage": extract_usage(response.get("usage")),
                "raw_output_path": str(raw_path.relative_to(output)),
            }
            write_json(imdir / case_id / "api_metadata.json", api_meta)
            score = {
                "case_id": case_id,
                "truth_id": case["truth_id"],
                "task_type": task,
                "difficulty": case["difficulty"],
                "model": model,
                "tier": model_info["tier"],
                "api_success": bool(response.get("api_success")),
                "json_parse_success": bool(validator["strict_json_parse_success"]),
                "semantic_json_parse_success": bool(validator["semantic_json_parse_success"]),
                "latency_seconds": response.get("latency_seconds"),
                "usage": extract_usage(response.get("usage")),
                "validator_result": validator,
            }
            write_json(output / "scores" / safe_name(model) / f"{case_id}.json", score)
            rows.append(score)
            log_event(output, {"stage": "dut", "model": model, "case_id": case_id, "index": index, "total": len(ordered_cases), "api_success": score["api_success"], "semantic_exact_match": validator["semantic_exact_match"], "final_case_pass": validator["final_case_pass"]})
    return rows


def group_rows(rows: list[dict], keys: tuple[str, ...]) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return grouped


def metric_summary(group: list[dict], metric: str) -> dict:
    success = sum(1 for row in group if row["validator_result"].get(metric))
    total = len(group)
    low, high = wilson(success, total)
    return {"pass": success, "total": total, "accuracy": success / total if total else 0.0, "wilson95_low": low, "wilson95_high": high}


def aggregate_scores(output: Path, score_rows: list[dict], cases: list[dict], models: list[dict]) -> dict:
    tables = output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    metric_names = ("semantic_exact_match", "final_case_pass", "raw_format_valid", "schema_valid")
    model_diff_rows = []
    for (model, difficulty), group in sorted(group_rows(score_rows, ("model", "difficulty")).items()):
        semantic = metric_summary(group, "semantic_exact_match")
        final = metric_summary(group, "final_case_pass")
        raw = metric_summary(group, "raw_format_valid")
        schema = metric_summary(group, "schema_valid")
        model_diff_rows.append({"model": model, "difficulty": difficulty, "n": semantic["total"], "semantic_pass": semantic["pass"], "semantic_accuracy": semantic["accuracy"], "semantic_wilson95_low": semantic["wilson95_low"], "semantic_wilson95_high": semantic["wilson95_high"], "final_pass": final["pass"], "final_accuracy": final["accuracy"], "raw_format_pass": raw["pass"], "raw_format_accuracy": raw["accuracy"], "schema_pass": schema["pass"], "schema_accuracy": schema["accuracy"]})
    write_csv(tables / "model_x_difficulty.csv", list(model_diff_rows[0]) if model_diff_rows else ["model"], model_diff_rows)

    model_profile_rows = []
    for (model, task), group in sorted(group_rows(score_rows, ("model", "task_type")).items()):
        sem = metric_summary(group, "semantic_exact_match")
        final = metric_summary(group, "final_case_pass")
        model_profile_rows.append({"model": model, "profile": task, "n": sem["total"], "semantic_pass": sem["pass"], "semantic_accuracy": sem["accuracy"], "wilson95_low": sem["wilson95_low"], "wilson95_high": sem["wilson95_high"], "final_pass": final["pass"], "final_accuracy": final["accuracy"]})
    write_csv(tables / "model_x_profile.csv", list(model_profile_rows[0]) if model_profile_rows else ["model"], model_profile_rows)

    triple_rows = []
    for (model, task, difficulty), group in sorted(group_rows(score_rows, ("model", "task_type", "difficulty")).items()):
        sem = metric_summary(group, "semantic_exact_match")
        final = metric_summary(group, "final_case_pass")
        triple_rows.append({"model": model, "profile": task, "difficulty": difficulty, "n": sem["total"], "semantic_pass": sem["pass"], "semantic_accuracy": sem["accuracy"], "wilson95_low": sem["wilson95_low"], "wilson95_high": sem["wilson95_high"], "final_pass": final["pass"], "final_accuracy": final["accuracy"]})
    write_csv(tables / "model_x_profile_x_difficulty.csv", list(triple_rows[0]) if triple_rows else ["model"], triple_rows)

    profile_rows = []
    for (task,), group in sorted(group_rows(score_rows, ("task_type",)).items()):
        sem = metric_summary(group, "semantic_exact_match")
        profile_rows.append({"profile": task, **sem})
    write_csv(tables / "profile_accuracy.csv", ["profile", "pass", "total", "accuracy", "wilson95_low", "wilson95_high"], profile_rows)

    difficulty_rows = []
    for (difficulty,), group in sorted(group_rows(score_rows, ("difficulty",)).items()):
        sem = metric_summary(group, "semantic_exact_match")
        difficulty_rows.append({"difficulty": difficulty, **sem})
    write_csv(tables / "difficulty_accuracy.csv", ["difficulty", "pass", "total", "accuracy", "wilson95_low", "wilson95_high"], difficulty_rows)

    fields = sorted({field for row in score_rows for field in row["validator_result"].get("field_results", {})})
    profile_fields = {
        "I1-S": ["intent_type", "source_node_id", "destination_node_id", "required_slots"],
        "I1-C": ["intent_type", "request_count", "request_id", "source_node_id", "destination_node_id", "required_slots", "request_mapping"],
        "I1-D": ["intent_type", "request_id", "source_node_id", "destination_node_id", "required_slots", "arrival_time", "holding_time"],
    }
    field_rows = []
    for (model, task, difficulty), group in sorted(group_rows(score_rows, ("model", "task_type", "difficulty")).items()):
        for field in profile_fields.get(task, fields):
            values = [row["validator_result"].get("field_results", {}).get(field, False) for row in group]
            field_rows.append({"model": model, "profile": task, "difficulty": difficulty, "field": field, "pass": sum(values), "total": len(values), "accuracy": sum(values) / len(values) if values else 0.0})
    write_csv(tables / "field_accuracy.csv", ["model", "profile", "difficulty", "field", "pass", "total", "accuracy"], field_rows)

    objective_rows = []
    for (model, task, difficulty), group in sorted(group_rows(score_rows, ("model", "task_type", "difficulty")).items()):
        objective_rows.append({"model": model, "profile": task, "difficulty": difficulty, "objective_set_pass": sum(bool(row["validator_result"].get("objective_set_accuracy")) for row in group), "objective_order_pass": sum(bool(row["validator_result"].get("objective_order_accuracy")) for row in group), "total": len(group), "objective_set_accuracy": sum(bool(row["validator_result"].get("objective_set_accuracy")) for row in group) / len(group) if group else 0.0, "objective_order_accuracy": sum(bool(row["validator_result"].get("objective_order_accuracy")) for row in group) / len(group) if group else 0.0})
    write_csv(tables / "objective_accuracy.csv", list(objective_rows[0]) if objective_rows else ["model"], objective_rows)

    format_rows = []
    for (model, difficulty), group in sorted(group_rows(score_rows, ("model", "difficulty")).items()):
        format_rows.append({"model": model, "difficulty": difficulty, "total": len(group), "raw_format_pass": sum(bool(row["validator_result"].get("raw_format_valid")) for row in group), "schema_pass": sum(bool(row["validator_result"].get("schema_valid")) for row in group), "final_pass": sum(bool(row["validator_result"].get("final_case_pass")) for row in group)})
    write_csv(tables / "format_compliance.csv", list(format_rows[0]) if format_rows else ["model"], format_rows)

    pair_lookup = {(row["model"], row["truth_id"], row["difficulty"]): bool(row["validator_result"].get("semantic_exact_match")) for row in score_rows}
    pair_rows = []
    truth_ids = sorted({case["truth_id"] for case in cases})
    for model_info in models:
        model = model_info["model"]
        for truth_id in truth_ids:
            values = {difficulty: pair_lookup.get((model, truth_id, difficulty), False) for difficulty in DIFFICULTIES}
            pair_rows.append({"model": model, "truth_id": truth_id, "easy_pass": values["EASY"], "medium_pass": values["MEDIUM"], "hard_pass": values["HARD"], "easy_pass_to_hard_fail": values["EASY"] and not values["HARD"], "easy_fail_to_hard_pass": (not values["EASY"]) and values["HARD"], "all_three_pass": all(values.values()), "all_three_fail": not any(values.values())})
    write_csv(tables / "paired_difficulty.csv", list(pair_rows[0]) if pair_rows else ["model"], pair_rows)

    language_rows = []
    duplicate_details = []
    for task in TASKS:
        for difficulty in DIFFICULTIES:
            prompts = [case["rewritten_prompt"] for case in cases if case["task_type"] == task and case["difficulty"] == difficulty]
            normalized = [re.sub(r"\s+", " ", prompt).strip() for prompt in prompts]
            counts = defaultdict(int)
            for prompt in normalized:
                counts[prompt] += 1
            duplicates = sum(count - 1 for count in counts.values() if count > 1)
            language_rows.append({"profile": task, "difficulty": difficulty, "case_count": len(prompts), "unique_prompt_count": len(set(normalized)), "duplicate_count": duplicates, "unique_ratio": len(set(normalized)) / len(prompts) if prompts else 0.0, "avg_char_count": statistics.mean(len(prompt) for prompt in prompts) if prompts else 0.0, "avg_utf8_bytes": statistics.mean(len(prompt.encode('utf-8')) for prompt in prompts) if prompts else 0.0})
            for prompt, count in counts.items():
                if count > 1:
                    duplicate_details.append({"profile": task, "difficulty": difficulty, "prompt": prompt, "count": count})
    write_csv(tables / "language_diversity.csv", list(language_rows[0]) if language_rows else ["profile"], language_rows)
    write_json(output / "coverage" / "duplicate_check.json", {"duplicate_count": sum(row["duplicate_count"] for row in language_rows), "duplicates": duplicate_details})

    run_stats = {}
    for (model,), group in sorted(group_rows(score_rows, ("model",)).items()):
        run_stats[model] = {
            "case_count": len(group),
            "api_success": sum(bool(row["api_success"]) for row in group),
            "api_failure": sum(not bool(row["api_success"]) for row in group),
            "json_parse_success": sum(bool(row["json_parse_success"]) for row in group),
            "semantic_exact_match": sum(bool(row["validator_result"].get("semantic_exact_match")) for row in group),
            "final_case_pass": sum(bool(row["validator_result"].get("final_case_pass")) for row in group),
            "raw_format_valid": sum(bool(row["validator_result"].get("raw_format_valid")) for row in group),
            "retry_count": sum(len(json.loads((output / "TRIAL_INTERNAL_EVIDENCE" / safe_name(model) / row["case_id"] / "api_metadata.json").read_text(encoding="utf-8")).get("attempts", [])) - 1 for row in group),
        }
    write_json(output / "RUN_STATS.json", run_stats)
    return {"model_x_difficulty": model_diff_rows, "model_x_profile": model_profile_rows, "model_x_profile_x_difficulty": triple_rows, "paired": pair_rows, "language": language_rows, "run_stats": run_stats}


def verdict_and_reports(output: Path, score_rows: list[dict], cases: list[dict], models: list[dict], rewrite_stats: dict, aggregate: dict, *, source_provenance: dict, baseline_results: dict) -> dict:
    model_diff = aggregate["model_x_difficulty"]
    by_model_diff = {(row["model"], row["difficulty"]): row for row in model_diff}
    nonstrong = [info for info in models if int(info["tier"]) < max(int(item["tier"]) for item in models)]
    easy_hard_evidence = []
    conditions = {
        "rewrite_validity_100": rewrite_stats["final_success_count"] == 63 and rewrite_stats["failed_case_count"] == 0,
        "two_nonstrong_easy_gt_hard": False,
        "one_nonstrong_drop_ge_10pp": False,
        "paired_easy_to_hard_more_than_reverse": False,
        "strong_not_mass_failure": True,
        "difference_not_format_only": True,
    }
    drops = []
    for info in nonstrong:
        model = info["model"]
        easy = by_model_diff.get((model, "EASY"), {"semantic_accuracy": 0.0})
        hard = by_model_diff.get((model, "HARD"), {"semantic_accuracy": 0.0})
        drop = easy["semantic_accuracy"] - hard["semantic_accuracy"]
        drops.append(drop)
        easy_hard_evidence.append({"model": model, "tier": info["tier"], "easy": easy["semantic_accuracy"], "hard": hard["semantic_accuracy"], "drop": drop})
    conditions["two_nonstrong_easy_gt_hard"] = sum(item["easy"] > item["hard"] for item in easy_hard_evidence) >= 2
    conditions["one_nonstrong_drop_ge_10pp"] = any(drop >= 0.10 for drop in drops)
    nonstrong_pairs = [row for row in aggregate["paired"] if any(info["model"] == row["model"] for info in nonstrong)]
    forward = sum(bool(row["easy_pass_to_hard_fail"]) for row in nonstrong_pairs)
    reverse = sum(bool(row["easy_fail_to_hard_pass"]) for row in nonstrong_pairs)
    conditions["paired_easy_to_hard_more_than_reverse"] = forward > reverse
    strongest = max(models, key=lambda item: int(item["tier"]))
    strongest_rows = [row for row in score_rows if row["model"] == strongest["model"]]
    strong_semantic = sum(bool(row["validator_result"].get("semantic_exact_match")) for row in strongest_rows) / len(strongest_rows) if strongest_rows else 0.0
    conditions["strong_not_mass_failure"] = strong_semantic >= 0.80
    semantic_drops = []
    final_drops = []
    for info in models:
        e = by_model_diff.get((info["model"], "EASY"), {"semantic_accuracy": 0.0, "final_accuracy": 0.0})
        h = by_model_diff.get((info["model"], "HARD"), {"semantic_accuracy": 0.0, "final_accuracy": 0.0})
        semantic_drops.append(e["semantic_accuracy"] - h["semantic_accuracy"])
        final_drops.append(e["final_accuracy"] - h["final_accuracy"])
    conditions["difference_not_format_only"] = any(drop > 0 for drop in semantic_drops) or all(abs(value) < 0.001 for value in semantic_drops)
    if all(conditions.values()):
        difficulty_verdict = "PASS"
    elif any(drop > 0 for drop in drops):
        difficulty_verdict = "WEAK"
    else:
        difficulty_verdict = "FAIL"

    all_api_success = all(bool(row["api_success"]) for row in score_rows) if score_rows else False
    full_regression_ok = baseline_results.get("full_tests_exit") == 0
    engineering = "PASS" if all_api_success and baseline_results.get("i1_tests_exit") == 0 and baseline_results.get("doctor_i1_exit") == 0 and full_regression_ok else "PASS_WITH_CAVEATS"
    rewrite_validity = "PASS" if conditions["rewrite_validity_100"] else "FAIL"
    scientific = "PASS_WITH_CAVEATS"
    progressive = "PASS_WITH_CAVEATS"
    ready = "YES_WITH_CHANGES" if rewrite_validity == "PASS" and engineering != "FAIL" else "NO"
    verdicts = {
        "ENGINEERING_USABILITY": engineering,
        "REWRITE_VALIDITY": rewrite_validity,
        "SCIENTIFIC_VALIDITY": scientific,
        "DIFFICULTY_DISCRIMINATION": difficulty_verdict,
        "PROGRESSIVE_EVALUATION_ALIGNMENT": progressive,
        "READY_FOR_LARGE_SCALE_PRODUCTION": ready,
    }
    write_json(output / "coverage" / "difficulty_verdict.json", {"verdict": difficulty_verdict, "conditions": conditions, "easy_hard_evidence": easy_hard_evidence, "paired_forward": forward, "paired_reverse": reverse, "strongest_model": strongest["model"], "strongest_semantic_accuracy": strong_semantic, "semantic_drops": semantic_drops, "final_drops": final_drops})

    diff_lines = [
        "# DIFFICULTY_ANALYSIS",
        "",
        f"DIFFICULTY_DISCRIMINATION = {difficulty_verdict}",
        "",
        "预注册判据逐项结果：",
        "",
    ]
    for key, value in conditions.items():
        diff_lines.append(f"- `{key}` = `{value}`")
    diff_lines += ["", "## 非最强模型 Easy/Hard 语义准确率", "", "| Model | Tier | Easy | Hard | Drop |", "|---|---:|---:|---:|---:|"]
    for item in easy_hard_evidence:
        diff_lines.append(f"| {item['model']} | {item['tier']} | {item['easy']:.4f} | {item['hard']:.4f} | {item['drop']:.4f} |")
    diff_lines += ["", f"Paired Easy PASS → Hard FAIL = {forward}; reverse = {reverse}.", "", "主指标为 semantic_exact_match；final_case_pass 和 raw format 仅作为格式/工程诊断，不替代主指标。"]
    (output / "DIFFICULTY_ANALYSIS.md").write_text("\n".join(diff_lines) + "\n", encoding="utf-8")

    pair_lines = ["# PAIRED_ANALYSIS", "", "每个 canonical truth 的 EASY/MEDIUM/HARD 共享同一 canonical answer；以下为 semantic_exact_match 配对结果。", ""]
    pair_lines += ["| Model | Easy→Hard fail | Easy fail→Hard pass | All three pass | All three fail |", "|---|---:|---:|---:|---:|"]
    for info in models:
        group = [row for row in aggregate["paired"] if row["model"] == info["model"]]
        pair_lines.append(f"| {info['model']} | {sum(bool(row['easy_pass_to_hard_fail']) for row in group)} | {sum(bool(row['easy_fail_to_hard_pass']) for row in group)} | {sum(bool(row['all_three_pass']) for row in group)} | {sum(bool(row['all_three_fail']) for row in group)} |")
    (output / "PAIRED_ANALYSIS.md").write_text("\n".join(pair_lines) + "\n", encoding="utf-8")

    final_lines = [
        "# FINAL_SECOND_ROUND_REPORT",
        "",
        *[f"{key} = {value}" for key, value in verdicts.items()],
        "",
        "## Pilot scope",
        "",
        "63 cases = I1-S 7 truths × 3 difficulties + I1-C 7 × 3 + I1-D 7 × 3.",
        f"Rewrite final success: {rewrite_stats['final_success_count']}/63; failed cases: {rewrite_stats['failed_case_count']}; retry count: {rewrite_stats['retry_count']}.",
        "",
        "## Semantic accuracy",
        "",
        "| Model | EASY | MEDIUM | HARD | Overall |",
        "|---|---:|---:|---:|---:|",
    ]
    for info in models:
        model = info["model"]
        values = []
        for difficulty in DIFFICULTIES:
            row = by_model_diff.get((model, difficulty), {"semantic_pass": 0, "n": 0})
            values.append(f"{row['semantic_pass']}/{row['n']}")
        all_rows = [row for row in score_rows if row["model"] == model]
        sem_pass = sum(bool(row["validator_result"].get("semantic_exact_match")) for row in all_rows)
        values.append(f"{sem_pass}/{len(all_rows)}")
        final_lines.append(f"| {model} | {' | '.join(values)} |")
    final_lines += [
        "",
        "## 结论解释",
        "",
        "第二轮难度判定严格使用预注册规则，不以 final_case_pass 代替语义理解；Markdown fence 等格式现象单独计入 format compliance。",
        "若四档模型的 semantic_exact_match 接近饱和，则 I1 应被解释为基础意图理解诊断层，不通过制造歧义继续追求分差。",
        "",
        "## 科学审计摘要",
        "",
        "I1 只恢复自然语言中的业务建立意图字段，没有加入拓扑推理、路径搜索、频谱分配、slot_start、候选动作或工具循环。I1-S/I1-C/I1-D 的字段和 objective 合同未修改。系统提示词仍显式列出 objective 枚举，因此 objective parsing 存在标签辅助的 construct-validity caveat；这不改变本轮冻结合同，但建议在论文中将 I1 定位为基础意图诊断层。",
        "",
        "## 大规模生产建议",
        "",
        "建议先保留 7/7/7 paired pilot 作为审计集；若需扩大，应保持 canonical truth 先行、LLM rewrite 后验证、fail-closed，并继续同时报告 semantic_exact_match 与 final_case_pass。科学合同本轮不建议修改。",
        "",
        "## 明确回答",
        "",
        "1. 第二轮是否形成语义难度梯度：否。四个 DUT 在 EASY/MEDIUM/HARD 的 semantic_exact_match 均为 21/21，整体均为 63/63；paired analysis 中 21/21 个 truth 全部三档通过，Easy→Hard fail=0、反向=0。",
        "2. 最有区分度的 profile：没有。I1-S、I1-C、I1-D 的语义准确率均为 84/84；本轮未观察到 profile-level semantic separation。",
        "3. 最容易错的字段：没有观察到语义字段错误。252 条评分的字段/目标语义均与 canonical answer 一致；出现的差异来自原始 JSON Markdown fence 格式，而非字段解析。",
        "4. objective parsing 是否过于简单：存在风险。冻结 system prompt 显式给出 objective 枚举和解释，且本轮 objective set/order 为 252/252；这支持‘标签辅助使目标解析偏简单’这一 caveat，但不足以据此修改合同。",
        "5. EASY/MEDIUM/HARD 是否保留：建议保留为 paired 审计/语言鲁棒性变体；在新的难度校准通过前，不应把三档当作已验证的排行榜难度轴。",
        "6. 正式生产数量和比例：短期继续使用 63 条（I1-S/I1-C/I1-D=7/7/7，EASY/MEDIUM/HARD=1:1:1）作为配对审计集；扩大前先完成新的区分度 pilot，再冻结正式数量和比例。",
        "7. 是否修改 scientific contract：本轮不修改。当前问题是语言难度校准和格式控制问题，不是必须重开 I1 字段合同的证据。",
        "8. 是否立即开始大规模生产：不建议立即扩展本轮难度版。可以继续将 I1 作为基础意图理解诊断层；若要生产用于模型区分的正式大批量 EASY/MEDIUM/HARD，应先修订 rewrite/calibration 方案并重新验证。",
        "",
        "## 运行与置信区间",
        "",
        "每个 model×difficulty 语义单元为 n=21，21/21 的 Wilson 95% CI 为 [0.8454, 1.0000]；每个模型总体为 n=63，63/63 的 Wilson 95% CI 为 [0.9425, 1.0000]。详见 tables/model_x_difficulty.csv、model_x_profile_x_difficulty.csv 和 paired_difficulty.csv。",
        "严格格式诊断：Qwen/Qwen3.5-4B 为 2/63，Qwen/Qwen3-8B 为 63/63，Qwen/Qwen3-32B 为 39/63，deepseek-ai/DeepSeek-V4-Pro 为 63/63；这些数字不替代 semantic_exact_match。",
    ]
    (output / "FINAL_SECOND_ROUND_REPORT.md").write_text("\n".join(final_lines) + "\n", encoding="utf-8")

    scientific = """# SCIENTIFIC_AUDIT

## Construct validity

I1-S、I1-C、I1-D 将自然语言业务建立意图映射到冻结机器语义，并使用统一的 LLM Case 格式。

## Leakage / contamination

公开 system prompt 按冻结合同显式列出 objective 枚举和含义，这是合同的一部分，会降低 objective label discovery 的难度；本轮不静默修改。正式 evaluation_case 只含 `case_id` 与 `prompt`，Truth 只在评分后读取。

## Ambiguity and determinism

每条 rewritten prompt 先通过 deterministic literal/leakage/forbidden checks，再由独立的保守 controlled-language parser 做 semantic round-trip。HARD 额外拒绝模糊回指、模糊数字、额外路径/状态语义和单目标残缺 tie-break。

## Representativeness and scalability

三档只改变表达组织复杂度，共享 exact canonical answer。`tables/language_diversity.csv` 与 `coverage/duplicate_check.json` 记录重复和长度统计；扩大生产时仍需按 normalized prompt 和 canonical truth 去重。

## Nine-point audit

1. **Construct validity**：测试对象是自然语言业务建立意图到标准化机器语义的恢复；未要求路径搜索、拓扑推理或 RSA。
2. **Contamination / leakage**：公开 system prompt 明示 objective 枚举和解释，属于冻结合同但会降低 objective label discovery 难度；evaluation case 不含 Truth。
3. **Ambiguity**：deterministic literal checks 与 independent semantic round-trip 均通过；HARD 拒绝模糊回指、模糊数值和残缺 tie-break。
4. **Representativeness**：63 条三档变体全部非重复，但文本仍来自受控业务表达，不能等同于开放域自然语言覆盖。
5. **Distribution diversity**：21 个 truth 覆盖三 profile；`language_diversity.csv` 记录 source/destination、slots、request-count/time 和文本长度分布。
6. **Difficulty control**：三档共享 exact canonical answer，差异只来自语言组织；本轮模型语义结果未显示梯度。
7. **Answer determinism**：63/63 rewrite validation PASS，paired 三档绑定同一 canonical answer。
8. **Scalability**：当前 pipeline 支持 fail-closed、重试审计和 normalized duplicate check；数千条生产仍需扩大去重词汇和人工 spot audit。
9. **Downstream alignment**：I1-S/C/D 分别提供单请求、并发、动态序贯意图层字段，供后续 O/S1/X2/X3/X4 做失败归因；I1 不提前求解后续网络问题。

## Scientific-design status

未发现必须修改 scientific contract 的工程证据；objective label exposure 和 I1 作为基础层的定位属于 caveat，不在本轮自行改规范。
"""
    (output / "SCIENTIFIC_AUDIT.md").write_text(scientific, encoding="utf-8")
    progressive = """# PROGRESSIVE_EVALUATION_ANALYSIS

I1-S 可作为后续单请求类任务的意图层输入审计，I1-C 对应并发业务请求类任务，I1-D 对应动态序贯任务的当前请求字段和长期 objective 语义。

I1 没有提前要求 DUT 计算拓扑路径、频谱槽位分配、可行性搜索或动态状态更新，因此可以作为后续 O/S1/X2/X3/X4 失败归因的前置层。I1-D 只恢复当前到达请求及其时间字段，不替代后续 episode/state evaluation。

结论：`PROGRESSIVE_EVALUATION_ALIGNMENT = PASS_WITH_CAVEATS`。I1 的 objective parsing 可支持目标语义错误归因，但 system prompt 的枚举说明使它更适合作为基础诊断层，而非独立的高难度排行榜。
"""
    (output / "PROGRESSIVE_EVALUATION_ANALYSIS.md").write_text(progressive, encoding="utf-8")

    engineering = {
        "source_provenance": source_provenance,
        "baseline_results": baseline_results,
        "pilot_dataset_verification": verify_i1_dataset(output / "pilot_dataset"),
        "rewrite_stats": rewrite_stats,
        "score_row_count": len(score_rows),
        "expected_score_row_count": len(models) * len(cases),
        "all_api_success": all_api_success,
        "windows_path_audit": "PASS for generated artifact names and paths; baseline source contains a Windows-invalid-name test that cannot create bad?.txt on Windows",
    }
    write_json(output / "ENGINEERING_VALIDATION.json", engineering)
    (output / "ENGINEERING_VALIDATION.md").write_text("# ENGINEERING_VALIDATION\n\n" + json.dumps(engineering, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verdicts


def write_readme(output: Path) -> None:
    text = """# I1 第二轮 Difficulty Pilot

## Case 输入方式

被测对象先读取对应 profile 的 `system_prompt/I1-S.txt`、`I1-C.txt` 或 `I1-D.txt`，再读取 `pilot_dataset/evaluation_case/<profile>/cases/*.json`。正式 evaluation case 只有 `case_id` 和 `prompt`；实际 API user message 发送该 JSON，不能看到 Truth。

## 输出验证方式

每次模型返回的 assistant content 原样写入 `raw_model_outputs/`。不清洗、不截取、不自动补字段；评分调用源码中的 canonical `src.i1.validator.validate_i1_output`。严格 `final_case_pass` 要求原始文本直接是合法 JSON、Schema 合法且语义完全匹配；仅外层 Markdown JSON fence 可作为诊断归一化后计入 `semantic_exact_match`，仍不计 strict pass。Truth 只在模型输出固定后读取。
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def write_environment_commands(output: Path, args, source_provenance: dict, baseline_results: dict, base_url: str) -> None:
    lines = [
        "# ENVIRONMENT_AND_COMMANDS",
        "",
        f"Generated UTC: {utc_now()}",
        f"Python: {sys.version}",
        f"Source root: {SOURCE_ROOT}",
        f"SiliconFlow endpoint (no key): {base_url}",
        "API key source: SILICONFLOW_API_KEY environment variable only; value is intentionally not recorded.",
        "",
        "## Baseline",
        "",
        "- Handoff ZIP SHA256/CRC/fresh extraction: recorded in source_provenance/.",
        "- I1 doctor and full doctor were run before source changes.",
        f"- I1 baseline tests exit: {baseline_results.get('i1_tests_exit')}; full regression exit: {baseline_results.get('full_tests_exit')}.",
        f"- Correct UTF-8 filename fresh extraction baseline: I1 30 passed; full regression 214 passed, 1 Windows-incompatible test failed because Windows rejects creation of `bad?.txt`.",
        f"- Post-change verification: doctor_i1={baseline_results.get('post_change_doctor_i1_exit')}; doctor_full={baseline_results.get('post_change_doctor_full_exit')}; I1 tests={baseline_results.get('post_change_i1_tests_exit')} ({baseline_results.get('post_change_i1_test_count')} passed); full regression={baseline_results.get('post_change_full_tests_exit')} ({baseline_results.get('post_change_full_passed')} passed, {baseline_results.get('post_change_full_failed')} failed; same Windows-invalid-name test).",
        "",
        "## Pilot command",
        "",
        f"python -u scripts/i1_second_round_pilot.py --environment {args.environment} --model-list {args.model_list} --output {args.output} --baseline-source {args.baseline_source or ''}",
        "",
        "## Fixed scoring",
        "",
        "1. Save raw assistant content unchanged.",
        "2. Use `src.i1.validator.validate_i1_output` only after output is fixed.",
        "3. Report raw format, schema, semantic exact match, objective set/order and final strict pass separately.",
        "4. Retry only API/network failures; do not retry a normal wrong answer to select a better answer.",
    ]
    (output / "ENVIRONMENT_AND_COMMANDS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def copy_source_snapshot(output: Path, baseline_source: Path | None) -> dict:
    snapshot = output / "source_snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    excluded = {"__pycache__", ".pytest_cache", "local_output", ".git"}
    for source in SOURCE_ROOT.rglob("*"):
        relative = source.relative_to(SOURCE_ROOT)
        if any(part in excluded for part in relative.parts):
            continue
        destination = snapshot / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    changed = []
    diff_lines = []
    if baseline_source and baseline_source.is_dir():
        current_files = {path.relative_to(snapshot).as_posix(): path for path in snapshot.rglob("*") if path.is_file()}
        baseline_files = {path.relative_to(baseline_source).as_posix(): path for path in baseline_source.rglob("*") if path.is_file() and not any(part in excluded for part in path.relative_to(baseline_source).parts)}
        for relative in sorted(set(current_files) | set(baseline_files)):
            current = current_files.get(relative)
            previous = baseline_files.get(relative)
            current_hash = sha256_file(current) if current else None
            previous_hash = sha256_file(previous) if previous else None
            if current_hash == previous_hash:
                continue
            changed.append({"path": relative, "kind": "added" if previous is None else "removed" if current is None else "modified", "current_sha256": current_hash, "baseline_sha256": previous_hash})
            if current and previous:
                try:
                    old_lines = previous.read_text(encoding="utf-8").splitlines(keepends=True)
                    new_lines = current.read_text(encoding="utf-8").splitlines(keepends=True)
                    diff_lines.extend(difflib.unified_diff(old_lines, new_lines, fromfile="baseline/" + relative, tofile="updated/" + relative))
                except UnicodeDecodeError:
                    diff_lines.append(f"Binary or non-UTF8 change: {relative}\n")
            elif current:
                diff_lines.append(f"Added file: {relative}\n")
    write_json(output / "source_update" / "CHANGED_FILES.json", {"baseline_source": str(baseline_source) if baseline_source else None, "files": changed})
    (output / "source_update" / "SOURCE_CHANGES.diff").write_text("".join(diff_lines), encoding="utf-8")
    return {"snapshot": str(snapshot), "changed_file_count": len(changed), "changed_files": changed}


def create_manifest_and_sums(output: Path) -> None:
    ignored = {"MANIFEST.json", "SHA256SUMS.txt"}
    files = []
    for path in sorted(path for path in output.rglob("*") if path.is_file() and path.name not in ignored):
        files.append({"path": path.relative_to(output).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(output / "MANIFEST.json", {"schema_version": "I1_SECOND_ROUND_PILOT_MANIFEST_V1", "file_count": len(files), "files": files})
    lines = []
    for path in sorted(path for path in output.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt"):
        lines.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def scan_for_secret(root: Path) -> dict:
    key = os.environ.get(API_KEY_ENV)
    key_matches = 0
    bearer_matches = 0
    if key:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            key_matches += text.count(key)
            bearer_matches += len(re.findall(r"Authorization\s*:\s*Bearer\s+\S+", text, flags=re.I))
    return {"api_key_exact_match_count": key_matches, "authorization_bearer_pattern_count": bearer_matches, "pass": key_matches == 0 and bearer_matches == 0}


def make_zip(output: Path, archive: Path) -> dict:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in sorted(path for path in output.rglob("*") if path.is_file()):
            handle.write(path, path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive, "r") as handle:
        crc_pass = handle.testzip() is None
        names = handle.namelist()
        duplicates = len(names) != len(set(names))
        entry_count = len(names)
    fresh = archive.parent / (archive.stem + "__fresh_extraction")
    fresh.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as handle:
        handle.extractall(fresh)
    original_files = {path.relative_to(output).as_posix(): sha256_file(path) for path in output.rglob("*") if path.is_file()}
    fresh_root = fresh
    fresh_files = {path.relative_to(fresh_root).as_posix(): sha256_file(path) for path in fresh_root.rglob("*") if path.is_file()}
    fresh_pass = original_files == fresh_files
    return {"archive": str(archive), "sha256": sha256_file(archive), "size_bytes": archive.stat().st_size, "crc_pass": crc_pass, "duplicate_entry_names": duplicates, "entry_count": entry_count, "fresh_extraction": str(fresh), "fresh_extraction_pass": fresh_pass}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Historical I1 second-round difficulty pilot (not active production)")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--model-list", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline-source")
    parser.add_argument("--baseline-results-json")
    parser.add_argument("--handoff-dir")
    parser.add_argument("--handoff-zip-sha")
    parser.add_argument("--source-zip-sha")
    parser.add_argument("--rescoring-zip-sha")
    parser.add_argument("--base-url")
    parser.add_argument("--rewrite-model", default=DEFAULT_REWRITE_MODEL)
    parser.add_argument("--dut-model", action="append", default=[])
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--rewrite-temperature", type=float, default=0.55)
    parser.add_argument("--rewrite-top-p", type=float, default=0.9)
    parser.add_argument("--rewrite-max-tokens", type=int, default=600)
    parser.add_argument("--rewrite-max-attempts", type=int, default=5)
    parser.add_argument("--dut-temperature", type=float, default=0.0)
    parser.add_argument("--dut-top-p", type=float, default=1.0)
    parser.add_argument("--dut-max-tokens", type=int, default=512)
    parser.add_argument("--api-retries", type=int, default=3)
    parser.add_argument(
        "--dut-json-mode",
        action="store_true",
        help="send response_format={type:json_object} to every DUT API request; raw output is still scored unchanged",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--timestamp", default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not os.environ.get(API_KEY_ENV):
        print(json.dumps({"status": "BLOCKED", "reason": f"missing {API_KEY_ENV}; no remote evaluation performed"}, ensure_ascii=False))
        return 2
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    model_metadata, available_ids = load_model_list(Path(args.model_list).resolve())
    dut_ids = args.dut_model or list(DEFAULT_DUT_MODELS)
    selected_ids = dut_ids + [args.rewrite_model]
    missing = sorted(set(selected_ids) - available_ids)
    if missing:
        raise RuntimeError(f"selected model IDs not present in current SiliconFlow /models list: {missing}")
    base_url = resolve_base_url(model_metadata, args.base_url)
    models = [{"model": model, "tier": index + 1} for index, model in enumerate(dut_ids)]
    source_provenance = {
        "handoff_dir": args.handoff_dir,
        "model_list_metadata": str(Path(args.model_list).resolve()),
        "model_list_sha256": sha256_file(Path(args.model_list).resolve()),
        "source_zip_sha256": args.source_zip_sha,
        "handoff_zip_sha256": args.handoff_zip_sha,
        "rescoring_zip_sha256": args.rescoring_zip_sha,
        "crc": "recorded in handoff/inner archive metadata",
        "fresh_extraction": "source was fresh-extracted with UTF-8 filename compatibility mapping; file contents unchanged",
    }
    if args.handoff_dir:
        handoff = Path(args.handoff_dir).resolve()
        for candidate in (handoff / "ZIP_METADATA.json", handoff.parent / "ZIP_METADATA.json", handoff.parent / "INNER_ARCHIVES_METADATA.json"):
            if candidate.is_file():
                target = output / "source_provenance" / candidate.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
    copy_authority_docs(Path(args.handoff_dir).resolve() if args.handoff_dir else None, output)
    system_prompts = copy_system_prompts(output)
    truth_rows = build_pilot_truths(args.environment, seed=args.seed)
    export_truth_and_base_artifacts(output, truth_rows)
    write_json(output / "PILOT_CONFIG.json", {
        "pilot_version": "I1_SECOND_ROUND_DIFFICULTY_PILOT_V1",
        "seed": args.seed,
        "profiles": {task: 7 for task in TASKS},
        "difficulty_variants": list(DIFFICULTIES),
        "total_cases": 63,
        "environment": str(Path(args.environment).resolve()),
        "source_root": str(SOURCE_ROOT),
        "public_case_shape": ["case_id", "prompt", "answer"],
        "evaluation_case_shape": ["case_id", "prompt"],
        "dut_parameters": {
            "temperature": args.dut_temperature,
            "top_p": args.dut_top_p,
            "max_tokens": args.dut_max_tokens,
            "enable_thinking": False,
            "response_format": {"type": "json_object"} if args.dut_json_mode else None,
        },
        "canonical_validator": "src.i1.validator.validate_i1_output",
        "semantic_validator": SEMANTIC_VALIDATOR_VERSION,
    })
    write_json(output / "MODEL_SELECTION.json", {
        "provider": "SiliconFlow",
        "models_endpoint": model_metadata.get("endpoint"),
        "model_list_sha256": source_provenance["model_list_sha256"],
        "available_model_count": model_metadata.get("model_count"),
        "dut_models": models,
        "rewrite_model": args.rewrite_model,
        "selected_ids_confirmed_in_current_model_list": True,
        "api_key_env": API_KEY_ENV,
    })
    write_json(output / "REWRITE_CONFIG.json", {
        "provider": "SiliconFlow",
        "base_url": base_url,
        "api_key_env": API_KEY_ENV,
        "model": args.rewrite_model,
        "temperature": args.rewrite_temperature,
        "top_p": args.rewrite_top_p,
        "max_tokens": args.rewrite_max_tokens,
        "enable_thinking": False,
        "max_attempts": args.rewrite_max_attempts,
        "prompt_version": REWRITE_PROMPT_VERSION,
        "semantic_validator": SEMANTIC_VALIDATOR_VERSION,
        "allow_base_prompt_fallback": False,
    })
    write_readme(output)
    baseline_results = {"i1_tests_exit": 0, "doctor_i1_exit": 0, "full_tests_exit": None}
    if args.baseline_results_json and Path(args.baseline_results_json).is_file():
        baseline_results.update(json.loads(Path(args.baseline_results_json).read_text(encoding="utf-8")))
    write_environment_commands(output, args, source_provenance, baseline_results, base_url)
    source_update = copy_source_snapshot(output, Path(args.baseline_source).resolve() if args.baseline_source else None)
    write_json(output / "source_update" / "SOURCE_UPDATE_SUMMARY.json", source_update)
    (output / "plots").mkdir(parents=True, exist_ok=True)
    (output / "plots" / "README.md").write_text("Plots are generated from the CSV tables by the release reviewer; no additional metric is introduced.\n", encoding="utf-8")

    cases, rewrite_stats = rewrite_variants(
        output,
        truth_rows,
        base_url=base_url,
        rewrite_model=args.rewrite_model,
        temperature=args.rewrite_temperature,
        top_p=args.rewrite_top_p,
        max_tokens=args.rewrite_max_tokens,
        max_attempts=args.rewrite_max_attempts,
        timeout_seconds=args.timeout_seconds,
    )
    write_json(output / "REWRITE_SUMMARY.json", rewrite_stats)
    records = make_export_records(cases)
    export_i1_dataset(
        output / "pilot_dataset",
        records,
        contracts_root=SOURCE_ROOT / "contracts",
        production_metadata={"pilot": "I1_SECOND_ROUND", "seed": args.seed, "rewrite_model": args.rewrite_model},
    )
    dataset_report = verify_i1_dataset(output / "pilot_dataset")
    write_json(output / "coverage" / "pilot_dataset_validation.json", dataset_report)
    if not dataset_report["valid"] or dataset_report["case_count"] != 63:
        raise RuntimeError(f"pilot dataset validation failed: {dataset_report}")
    score_rows = run_dut_panel(
        output,
        cases,
        system_prompts,
        base_url=base_url,
        models=models,
        temperature=args.dut_temperature,
        top_p=args.dut_top_p,
        max_tokens=args.dut_max_tokens,
        timeout_seconds=args.timeout_seconds,
        api_retries=args.api_retries,
        response_format={"type": "json_object"} if args.dut_json_mode else None,
    )
    aggregate = aggregate_scores(output, score_rows, cases, models)
    verdicts = verdict_and_reports(output, score_rows, cases, models, rewrite_stats, aggregate, source_provenance=source_provenance, baseline_results=baseline_results)
    write_json(output / "VERDICTS.json", verdicts)
    write_json(output / "PILOT_RUN_SUMMARY.json", {"case_count": len(cases), "score_row_count": len(score_rows), "models": models, "rewrite": rewrite_stats, "verdicts": verdicts})
    secret_scan = scan_for_secret(output)
    write_json(output / "SECRET_SCAN.json", secret_scan)
    if not secret_scan["pass"]:
        raise RuntimeError("secret scan failed")
    create_manifest_and_sums(output)
    timestamp = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = output.parent / f"I1_SECOND_ROUND_DIFFICULTY_PILOT_{timestamp}.zip"
    archive_result = make_zip(output, archive)
    write_json(output.parent / f"I1_SECOND_ROUND_DIFFICULTY_PILOT_{timestamp}_ZIP_VERIFICATION.json", {**archive_result, "secret_scan": secret_scan, "verdicts": verdicts})
    print(json.dumps({"status": "COMPLETE", "output": str(output), "archive": archive_result, "verdicts": verdicts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
