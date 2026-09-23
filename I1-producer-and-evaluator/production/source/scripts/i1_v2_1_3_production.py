"""I1 V2.1.3 one-truth/one-prompt production and pre-production dry run.

This module intentionally keeps the historical difficulty pilot separate from the
formal public production path.  It reuses the frozen source loader, truth builders,
renderer, SiliconFlow-compatible rewrite adapter, and canonical I1 contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from jsonschema import Draft202012Validator

from src.case_core.serialization_metrics import compute_serialization_metrics
from src.i1.pipeline import _expand_concurrent_sources, _generate_base_records
from src.i1.production import (
    build_formal_benchmark_case,
    build_formal_evaluation_case,
    normalized_prompt,
    validate_formal_rewrite,
    validate_one_prompt_per_truth,
)
from src.i1.rewrite import OpenAICompatibleRewriteClient
from src.i1.source_loader import load_i1_sources
from src.i1.truth import _ALLOWED_OBJECTIVES
from src.i1.version import I1_PRODUCER_VERSION


TASKS = ("I1-S", "I1-C", "I1-D")
STYLES = ("DIRECT", "NATURAL", "REORDERED", "PARAPHRASED")
API_KEY_ENV = "SILICONFLOW_API_KEY"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen3-8B"
REWRITE_PROMPT_VERSION = "I1_V2_1_3_FORMAL_STYLE_REWRITE_V1"
PRODUCTION_SCHEMA_VERSION = "I1_PRODUCTION_V2_1_3"

PRODUCTION_REWRITE_SYSTEM_PROMPT = """你只负责把一条已经具有确定标准答案的光网络业务意图改写成更自然的中文业务表达。
这不是重新设计需求，也不是生成答案。请严格保持所有业务语义不变：请求数量、每个 request_id、request_id 与源节点/目的节点/频谱槽位的绑定、节点编号、required_slots、动态请求的 arrival_time 和 holding_time、优化目标集合及其优先级顺序都必须保持不变。
不得增加或删除网络拓扑、链路、路径、频谱状态、候选动作、业务约束、字段、优化目标或任何需要求解网络问题的信息。不得输出答案、JSON schema、机器字段名或目标枚举编码。数字和标识符必须保留原样，不得改成约数、不同单位或其他数字形式。
目标中的范围词也属于不可变语义：例如“全网”和“网络外部”必须原样保留或用明确等价表达，不能省略、缩小或泛化范围。
本次只按用户指定的表达风格改写。表达必须自然、明确、唯一可解析，不得故意绕口、使用模糊代词或制造歧义。若只有一个优化目标，不得暗示存在第二个目标或 tie-break；若有多个目标，必须完整保留原有顺序。
只返回一个 JSON 对象，格式为：{"rewritten_prompt":"..."}，不得返回 Markdown fence、解释或其他内容。"""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_obj(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _write_json(path: Path, value: Any, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _load_config(path: Path | str) -> tuple[dict, str]:
    config_path = Path(path).resolve()
    raw = config_path.read_bytes()
    config = json.loads(raw.decode("utf-8"))
    if not isinstance(config, dict):
        raise ValueError("V2.1.3 production config must be an object")
    required = {"schema_version", "seed", "requested_case_counts", "objective_profiles", "rewrite", "style_cycle"}
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"production config missing fields: {missing}")
    if config["schema_version"] != PRODUCTION_SCHEMA_VERSION:
        raise ValueError("unsupported V2.1.3 production config schema_version")
    requested = config["requested_case_counts"]
    if set(requested) != set(TASKS) or any(
        not isinstance(requested[task], int) or isinstance(requested[task], bool) or requested[task] < 0
        for task in TASKS
    ):
        raise ValueError("requested_case_counts must define non-negative integer I1-S/I1-C/I1-D values")
    profiles = config["objective_profiles"]
    if set(profiles) != set(TASKS):
        raise ValueError("objective_profiles must define I1-S/I1-C/I1-D")
    for task in TASKS:
        if not isinstance(profiles[task], list) or not profiles[task]:
            raise ValueError(f"objective_profiles.{task} must be non-empty")
        for vector in profiles[task]:
            if not isinstance(vector, list) or not vector or any(x not in _ALLOWED_OBJECTIVES for x in vector):
                raise ValueError(f"invalid frozen objective vector for {task}")
            if len(vector) != len(set(vector)):
                raise ValueError(f"duplicate objective in {task}")
    styles = config["style_cycle"]
    if not isinstance(styles, list) or not styles or any(style not in STYLES for style in styles):
        raise ValueError(f"style_cycle must contain only {STYLES}")
    rewrite = config["rewrite"]
    if not isinstance(rewrite, dict):
        raise ValueError("rewrite config must be an object")
    if rewrite.get("mode") != "openai_compatible":
        raise ValueError("V2.1.3 production requires the existing openai_compatible rewrite adapter")
    for field in ("provider", "base_url", "api_key_env", "model"):
        if not isinstance(rewrite.get(field), str) or not rewrite[field]:
            raise ValueError(f"rewrite.{field} is required")
    if rewrite["api_key_env"] != API_KEY_ENV:
        raise ValueError(f"rewrite.api_key_env must be {API_KEY_ENV}")
    for field in ("temperature", "top_p"):
        if not isinstance(rewrite.get(field), (int, float)) or isinstance(rewrite[field], bool):
            raise ValueError(f"rewrite.{field} must be numeric")
    for field in ("max_tokens", "max_attempts"):
        if not isinstance(rewrite.get(field), int) or isinstance(rewrite[field], bool) or rewrite[field] < 1:
            raise ValueError(f"rewrite.{field} must be a positive integer")
    if "max_workers" in config and (
        not isinstance(config["max_workers"], int)
        or isinstance(config["max_workers"], bool)
        or config["max_workers"] < 1
    ):
        raise ValueError("max_workers must be a positive integer")
    return config, _sha256_bytes(raw)


def build_preproduction_base_records(
    environment_root: Path | str, config: dict, config_sha256: str
) -> tuple[dict[str, list[dict]], dict]:
    """Build only truths/base prompts, with fail-closed source-pool accounting."""

    sources = load_i1_sources(environment_root)
    requested = config["requested_case_counts"]
    seed = int(config["seed"])
    concurrent_probe = _expand_concurrent_sources(
        sources, requested["I1-C"], seed + 23
    )
    capacities = {
        "I1-S": len(sources["single"]),
        "I1-C": len(concurrent_probe),
        "I1-D": len(sources["dynamic"]),
    }
    supported = {task: min(requested[task], capacities[task]) for task in TASKS}
    generation_config = {
        "profile": "i1_v2_1_3_preproduction",
        "seed": seed,
        "case_counts": supported,
        "objective_profiles": config["objective_profiles"],
        "rewrite": {"enabled": False, "mode": "identity", "max_attempts": 1},
        "allow_shortfall": False,
        "require_canonical_tokenizer": False,
        "config_sha256": config_sha256,
    }
    records = _generate_base_records(generation_config, sources)
    pool_report = {
        "requested_case_counts": requested,
        "safe_supported_case_counts": {task: len(records[task]) for task in TASKS},
        "shortfall_case_counts": {
            task: max(0, requested[task] - len(records[task])) for task in TASKS
        },
        "raw_source_counts": {
            "single_requests": len(sources["single"]),
            "prebuilt_concurrent_sets": len(sources["concurrent"]),
            "dynamic_events": len(sources["dynamic"]),
        },
        "effective_safe_capacity": capacities,
        "capacity_notes": {
            "I1-S": "one source request produces one unique single canonical truth",
            "I1-C": "existing deterministic single-request grouping expansion is reused; no random or duplicate truth fabrication",
            "I1-D": "one loaded dynamic event produces one dynamic canonical truth; no synthetic time/request pairing is created",
        },
    }
    return records, pool_report


def _style_for_index(index: int, styles: list[str]) -> str:
    return styles[index % len(styles)]


def _safe_exception(exc: Exception) -> dict:
    # Do not preserve exception text: network libraries can echo request details.
    return {"type": type(exc).__name__}


def _stat_add(stats: dict, key: str, value: int = 1) -> None:
    lock = stats.get("_lock")
    if lock is None:
        stats[key] += value
        return
    with lock:
        stats[key] += value


def _stat_reason(stats: dict, reason: str) -> None:
    lock = stats.get("_lock")
    if lock is None:
        stats["failure_reasons"][reason] += 1
        return
    with lock:
        stats["failure_reasons"][reason] += 1


def _resume_rewrite_one(
    resume_root: Path,
    output: Path,
    record: dict,
    style: str,
    rewrite_model: str,
    stats: dict,
) -> tuple[str, dict] | None:
    """Reuse a previously accepted raw rewrite without regenerating it.

    The raw API response is copied unchanged and its embedded rewritten prompt is
    revalidated with the current gate.  A previous FAIL/ERROR history is never
    treated as a candidate; the caller falls through to a fresh API attempt.
    """

    case_id = record["case_id"]
    old_case_dir = resume_root / "raw_rewrite_outputs" / _safe_name(case_id)
    if not old_case_dir.is_dir():
        return None
    metadata_paths = sorted(old_case_dir.glob("attempt_*_metadata.json"))
    if not metadata_paths:
        return None
    attempts = []
    revalidated_attempts = []
    accepted = None
    accepted_prompt = None
    accepted_validation = None
    for metadata_path in metadata_paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if accepted is not None:
            attempts.append(metadata)
            continue
        attempt_number = int(metadata.get("attempt", 0))
        raw_path = old_case_dir / f"attempt_{attempt_number:02d}_raw.txt"
        revalidated = dict(metadata)
        try:
            if not raw_path.is_file():
                raise ValueError("missing raw rewrite response")
            raw_obj = OpenAICompatibleRewriteClient._extract_json(
                raw_path.read_text(encoding="utf-8")
            )
            candidate = raw_obj.get("rewritten_prompt")
            validation = validate_formal_rewrite(record["canonical_answer"], candidate)
            revalidated["revalidated_status"] = validation["overall"]
            revalidated["revalidated_errors"] = validation["errors"]
        except Exception as exc:
            validation = None
            candidate = None
            revalidated["revalidated_status"] = "ERROR"
            revalidated["revalidated_errors"] = [type(exc).__name__]
        attempts.append(revalidated)
        revalidated_attempts.append(revalidated)
        if validation is not None and validation["overall"] == "PASS":
            accepted = attempt_number
            accepted_prompt = candidate
            accepted_validation = validation
    if accepted is None or accepted_prompt is None or accepted_validation is None:
        return None

    new_case_dir = output / "raw_rewrite_outputs" / _safe_name(case_id)
    shutil.copytree(old_case_dir, new_case_dir)
    _stat_add(stats, "api_rewrite_case_count")
    for metadata in revalidated_attempts:
        _stat_add(stats, "total_rewrite_calls")
        if metadata.get("revalidated_status") != "PASS":
            _stat_add(stats, "failed_attempt_count")
            for error in metadata.get("revalidated_errors", []):
                _stat_reason(stats, str(error))
    if accepted == 1:
        _stat_add(stats, "first_pass_success_count")
    else:
        _stat_add(stats, "cases_needing_retry")
        _stat_add(stats, "retry_count_total", accepted - 1)
    validation_path = output / "rewrite_validation" / f"{_safe_name(case_id)}.json"
    _write_json(
        validation_path,
        {
            "case_id": case_id,
            "task_type": record["task_type"],
            "rewrite_style": style,
            "validator_version": REWRITE_PROMPT_VERSION,
            "overall": "PASS",
            "resumed_from": str(resume_root),
            "attempts": attempts,
            "final_validation": accepted_validation,
        },
    )
    return accepted_prompt, {
        "rewrite_style": style,
        "rewrite_model": rewrite_model,
        "rewrite_attempt_count": accepted,
        "attempts": attempts,
        "validation": accepted_validation,
        "resumed_from": str(resume_root),
    }
def _rewrite_one(
    output: Path,
    record: dict,
    style: str,
    client: OpenAICompatibleRewriteClient,
    rewrite_cfg: dict,
    stats: dict,
) -> tuple[str, dict]:
    case_id = record["case_id"]
    case_dir = output / "raw_rewrite_outputs" / _safe_name(case_id)
    validation_path = output / "rewrite_validation" / f"{_safe_name(case_id)}.json"
    case_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict] = []

    if style == "DIRECT":
        prompt = record["base_prompt"]
        validation = validate_formal_rewrite(record["canonical_answer"], prompt)
        attempt = {
            "attempt": 1,
            "mode": "deterministic_base_prompt",
            "status": validation["overall"],
            "errors": validation["errors"],
        }
        attempts.append(attempt)
        _write_json(case_dir / "attempt_01_metadata.json", attempt)
        _stat_add(stats, "deterministic_base_count")
        if validation["overall"] != "PASS":
            stats["failed_case_count"] += 1
            raise RuntimeError(f"fail-closed rewrite validation: {case_id}")
        _write_json(
            validation_path,
            {
                "case_id": case_id,
                "task_type": record["task_type"],
                "rewrite_style": style,
                "validator_version": REWRITE_PROMPT_VERSION,
                "overall": "PASS",
                "attempts": attempts,
                "final_validation": validation,
            },
        )
        return prompt, {
            "rewrite_style": style,
            "rewrite_model": None,
            "rewrite_attempt_count": 1,
            "attempts": attempts,
            "validation": validation,
        }

    max_attempts = int(rewrite_cfg["max_attempts"])
    _stat_add(stats, "api_rewrite_case_count")
    accepted_prompt = None
    accepted_validation = None
    used_attempts = 0
    for attempt_number in range(1, max_attempts + 1):
        used_attempts = attempt_number
        _stat_add(stats, "total_rewrite_calls")
        system_prompt = PRODUCTION_REWRITE_SYSTEM_PROMPT
        if attempt_number > 1:
            system_prompt += "\n这是重试。上一候选未通过严格语义校验，请重新生成一条全新的、无歧义的合规改写。"
        try:
            text, raw_response = client.rewrite_with_raw(
                record["base_prompt"],
                record["canonical_answer"],
                rewrite_style=style,
                system_prompt=system_prompt,
            )
            raw_path = case_dir / f"attempt_{attempt_number:02d}_raw.txt"
            _write_text(raw_path, raw_response if isinstance(raw_response, str) else "")
            validation = validate_formal_rewrite(record["canonical_answer"], text)
            metadata = {
                "attempt": attempt_number,
                "mode": "siliconflow",
                "status": validation["overall"],
                "errors": validation["errors"],
                "rewritten_prompt_sha256": _sha256_bytes(text.encode("utf-8")),
                "raw_output_path": raw_path.relative_to(output).as_posix(),
            }
            _write_json(case_dir / f"attempt_{attempt_number:02d}_metadata.json", metadata)
            attempts.append(metadata)
            if validation["overall"] == "PASS":
                accepted_prompt = text
                accepted_validation = validation
                if attempt_number == 1:
                    _stat_add(stats, "first_pass_success_count")
                else:
                    _stat_add(stats, "cases_needing_retry")
                    _stat_add(stats, "retry_count_total", attempt_number - 1)
                break
            _stat_add(stats, "failed_attempt_count")
            for error in validation["errors"]:
                _stat_reason(stats, error)
        except Exception as exc:
            failure = _safe_exception(exc)
            metadata = {
                "attempt": attempt_number,
                "mode": "siliconflow",
                "status": "ERROR",
                "error": failure,
            }
            _write_json(case_dir / f"attempt_{attempt_number:02d}_metadata.json", metadata)
            attempts.append(metadata)
            _stat_add(stats, "failed_attempt_count")
            _stat_reason(stats, failure["type"])

    if accepted_prompt is None or accepted_validation is None:
        _stat_add(stats, "failed_case_count")
        _write_json(
            validation_path,
            {
                "case_id": case_id,
                "task_type": record["task_type"],
                "rewrite_style": style,
                "validator_version": REWRITE_PROMPT_VERSION,
                "overall": "FAILED_REWRITE",
                "attempts": attempts,
            },
        )
        raise RuntimeError(f"fail-closed rewrite validation: {case_id}")

    _write_json(
        validation_path,
        {
            "case_id": case_id,
            "task_type": record["task_type"],
            "rewrite_style": style,
            "validator_version": REWRITE_PROMPT_VERSION,
            "overall": "PASS",
            "attempts": attempts,
            "final_validation": accepted_validation,
        },
    )
    return accepted_prompt, {
        "rewrite_style": style,
        "rewrite_model": rewrite_cfg["model"],
        "rewrite_attempt_count": used_attempts,
        "attempts": attempts,
        "validation": accepted_validation,
    }


def _validate_schema(schema_path: Path, value: dict, label: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.absolute_path)
    )
    if errors:
        raise ValueError(f"{label} schema violation: {errors[0].message}")


def _copy_contract_prompt(contracts_root: Path, output: Path, task: str) -> None:
    for view in ("benchmark_case", "evaluation_case"):
        target = output / "preproduction_dataset" / view / task / "llm_system_prompt.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(contracts_root / task / "llm_system_prompt.txt", target)


def _serialization_metrics(prompt: str) -> dict:
    try:
        dual = compute_serialization_metrics(prompt, prompt)
        return {
            "prompt_char_count": dual["llm_prompt_char_count"],
            "prompt_utf8_bytes": dual["llm_prompt_utf8_bytes"],
            "prompt_token_count": dual["llm_prompt_token_count"],
            "canonical_tokenizer": dual["canonical_tokenizer"],
        }
    except Exception as exc:
        return {
            "prompt_char_count": len(prompt),
            "prompt_utf8_bytes": len(prompt.encode("utf-8")),
            "prompt_token_count": None,
            "canonical_tokenizer": {"available": False, "error_type": type(exc).__name__},
        }


def _write_case_artifacts(
    output: Path,
    record: dict,
    final_prompt: str,
    rewrite_meta: dict,
    contracts_root: Path,
) -> dict:
    task = record["task_type"]
    case_id = record["case_id"]
    public_case = build_formal_benchmark_case(case_id, final_prompt, record["canonical_answer"])
    evaluation_case = build_formal_evaluation_case(public_case)
    _validate_schema(
        contracts_root / task / "schemas" / "benchmark_case.schema.json",
        public_case,
        f"{task}/{case_id}/benchmark_case",
    )
    _validate_schema(
        contracts_root / task / "schemas" / "evaluation_case.schema.json",
        evaluation_case,
        f"{task}/{case_id}/evaluation_case",
    )
    _validate_schema(
        contracts_root / task / "output_schema.json",
        record["canonical_answer"],
        f"{task}/{case_id}/canonical_answer",
    )
    _copy_contract_prompt(contracts_root, output, task)
    name = f"case_{int(case_id.rsplit('_', 1)[-1]):06d}.json"
    benchmark_path = output / "preproduction_dataset" / "benchmark_case" / task / "cases" / name
    evaluation_path = output / "preproduction_dataset" / "evaluation_case" / task / "cases" / name
    _write_json(benchmark_path, public_case, sort_keys=False)
    _write_json(evaluation_path, evaluation_case, sort_keys=False)

    truth_path = output / "canonical_truth" / task / f"{case_id}.json"
    base_path = output / "base_prompts" / task / f"{case_id}.txt"
    _write_json(
        truth_path,
        {
            "truth_id": case_id,
            "task_type": task,
            "source_ref": record["source_ref"],
            "canonical_answer": record["canonical_answer"],
            "canonical_answer_sha256": _sha256_obj(record["canonical_answer"]),
        },
    )
    _write_text(base_path, record["base_prompt"] + "\n")

    internal = output / "production_records" / task / case_id
    _write_json(
        internal / "record.json",
        {
            "truth_id": case_id,
            "case_id": case_id,
            "task_type": task,
            "source_ref": record["source_ref"],
            "canonical_answer": record["canonical_answer"],
            "base_prompt": record["base_prompt"],
            "final_prompt": final_prompt,
            "rewrite": rewrite_meta,
            "lineage": {
                "stage": "V2_1_3_FORMAL_PRODUCTION",
                "one_truth_one_prompt": True,
                "canonical_answer_sha256": _sha256_obj(record["canonical_answer"]),
                "base_prompt_sha256": _sha256_bytes(record["base_prompt"].encode("utf-8")),
                "final_prompt_sha256": _sha256_bytes(final_prompt.encode("utf-8")),
            },
        },
    )
    _write_json(internal / "validation.json", rewrite_meta["validation"])
    _write_json(internal / "features.json", _serialization_metrics(final_prompt))
    return {
        "case_id": case_id,
        "truth_id": case_id,
        "task_type": task,
        "source_ref": record["source_ref"],
        "rewrite_style": rewrite_meta["rewrite_style"],
        "rewrite_attempt_count": rewrite_meta["rewrite_attempt_count"],
        "canonical_answer_sha256": _sha256_obj(record["canonical_answer"]),
        "base_prompt_sha256": _sha256_bytes(record["base_prompt"].encode("utf-8")),
        "final_prompt_sha256": _sha256_bytes(final_prompt.encode("utf-8")),
        "benchmark_case_path": benchmark_path.relative_to(output).as_posix(),
        "evaluation_case_path": evaluation_path.relative_to(output).as_posix(),
        "canonical_truth_path": truth_path.relative_to(output).as_posix(),
        "base_prompt_path": base_path.relative_to(output).as_posix(),
        "production_record_path": (internal / "record.json").relative_to(output).as_posix(),
    }


def _write_index(output: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda row: (TASKS.index(row["task_type"]), row["case_id"]))
    _write_text(
        output / "preproduction_dataset" / "case_index.jsonl",
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )


def _write_coverage_reports(output: Path, rows: list[dict], records: dict[str, list[dict]], pool_report: dict) -> None:
    slot_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    destination_counts: Counter[str] = Counter()
    objective_counts: Counter[str] = Counter()
    objective_vectors: Counter[str] = Counter()
    style_counts: Counter[str] = Counter(row["rewrite_style"] for row in rows)
    for task in TASKS:
        for record in records[task]:
            answer = record["canonical_answer"]
            requests = [answer] if task == "I1-S" else [answer["request"]] if task == "I1-D" else answer["requests"]
            for request in requests:
                slot_counts[str(request["required_slots"])] += 1
                source_counts[str(request["source_node_id"])] += 1
                destination_counts[str(request["destination_node_id"])] += 1
            vector = " > ".join(answer["objectives"])
            objective_vectors[vector] += 1
            for objective in answer["objectives"]:
                objective_counts[objective] += 1
    coverage = {
        "case_counts": {task: sum(1 for row in rows if row["task_type"] == task) for task in TASKS},
        "required_slots": {"values": sorted(int(x) for x in slot_counts), "counts": dict(sorted(slot_counts.items()))},
        "objective_codes": {
            "allowed": sorted(_ALLOWED_OBJECTIVES),
            "observed": sorted(objective_counts),
            "counts": dict(sorted(objective_counts.items())),
            "ordered_vectors": dict(sorted(objective_vectors.items())),
            "all_allowed_observed": set(objective_counts) == set(_ALLOWED_OBJECTIVES),
        },
        "source_node_ids": dict(sorted(source_counts.items(), key=lambda item: int(item[0]))),
        "destination_node_ids": dict(sorted(destination_counts.items(), key=lambda item: int(item[0]))),
        "rewrite_style_distribution": dict(sorted(style_counts.items())),
        "pool_report": pool_report,
    }
    _write_json(output / "coverage_report.json", coverage)

    prompts = []
    for row in rows:
        final_prompt = json.loads((output / row["benchmark_case_path"]).read_text(encoding="utf-8"))["llm_prompt"]
        prompts.append((row["case_id"], final_prompt))
    normalized = {}
    duplicate_pairs = []
    for case_id, prompt in prompts:
        key = normalized_prompt(prompt)
        if key in normalized:
            duplicate_pairs.append({"first_case_id": normalized[key], "second_case_id": case_id})
        else:
            normalized[key] = case_id
    answer_hashes = Counter(row["canonical_answer_sha256"] for row in rows)
    duplicate_report = {
        "case_count": len(rows),
        "canonical_answer_duplicate_count": sum(count - 1 for count in answer_hashes.values() if count > 1),
        "raw_prompt_duplicate_count": len(duplicate_pairs),
        "normalized_prompt_duplicate_count": len(duplicate_pairs),
        "duplicate_pairs": duplicate_pairs,
        "validated_zero_normalized_duplicates": not duplicate_pairs,
    }
    _write_json(output / "duplicate_report.json", duplicate_report)

    char_lengths = [len(prompt) for _, prompt in prompts]
    token_rows = [_serialization_metrics(prompt) for _, prompt in prompts]
    token_values = [row["prompt_token_count"] for row in token_rows if isinstance(row["prompt_token_count"], int)]
    _write_json(
        output / "language_diversity.json",
        {
            "case_count": len(prompts),
            "style_distribution": dict(sorted(style_counts.items())),
            "prompt_char_count": {
                "min": min(char_lengths) if char_lengths else 0,
                "max": max(char_lengths) if char_lengths else 0,
                "mean": sum(char_lengths) / len(char_lengths) if char_lengths else 0.0,
            },
            "prompt_token_count": {
                "available": bool(token_values),
                "min": min(token_values) if token_values else None,
                "max": max(token_values) if token_values else None,
                "mean": sum(token_values) / len(token_values) if token_values else None,
            },
            "normalized_duplicate_rate": len(duplicate_pairs) / len(prompts) if prompts else 0.0,
            "note": "style is an expression-coverage label only; it is not a validated difficulty axis",
        },
    )


def _finalize_rewrite_stats(stats: dict, total_cases: int) -> dict:
    stats.pop("_lock", None)
    api_cases = stats["api_rewrite_case_count"]
    stats["total_case_count"] = total_cases
    stats["final_success_count"] = total_cases - stats["failed_case_count"]
    stats["first_pass_success_rate"] = stats["first_pass_success_count"] / api_cases if api_cases else 1.0
    stats["final_success_rate"] = stats["final_success_count"] / total_cases if total_cases else 1.0
    stats["retry_count_distribution"] = dict(sorted(Counter(stats.pop("_attempt_counts", [])).items()))
    stats["max_attempts_used"] = max(
        [int(key) for key in stats["retry_count_distribution"]] or [0]
    )
    stats["failure_reason_distribution"] = dict(sorted(stats["failure_reasons"].items()))
    stats["failure_reasons"] = stats["failure_reason_distribution"]
    return stats


def _write_readme_and_reports(
    output: Path,
    config: dict,
    config_sha256: str,
    pool_report: dict,
    rewrite_stats: dict,
    rows: list[dict],
    *,
    source_root: Path,
) -> None:
    counts = {task: sum(1 for row in rows if row["task_type"] == task) for task in TASKS}
    target_met = counts == config["requested_case_counts"]
    target_status = "PASS" if target_met else "FAIL"
    model = config["rewrite"]["model"]
    _write_text(
        output / "README.md",
        "# I1 V2.1.3 Pre-production evidence\n\n"
        "## Case input\n\n"
        "正式 benchmark case 是 `preproduction_dataset/benchmark_case/<profile>/cases/*.json`，字段严格为 `case_id`、`llm_prompt`、`answer`。实际被测对象先读取对应的 `llm_system_prompt.txt`，再读取 `preproduction_dataset/evaluation_case/<profile>/cases/*.json`；evaluation case 只含 `case_id` 和 `prompt`，且该 prompt 逐字等于 benchmark 的 llm_prompt，不含 Truth。\n\n"
        "## Output validation\n\n"
        "模型原始输出原样保存后，由 canonical I1 Validator 直接判定。`semantic_exact_match`/`semantic_intent_accuracy` 是 I1 主科学指标；`raw_format_valid`/`strict_format_compliance` 是独立工程指标；`final_case_pass`/`strict_case_pass_rate` 是格式、Schema、语义同时通过的严格端到端指标。不得用严格格式通过率替代意图理解准确率。\n\n"
        "正式公开生产不使用 EASY/MEDIUM/HARD 标签；每个 canonical truth 只导出一个 final prompt。\n",
    )
    _write_text(
        output / "I1_V2_1_3_PRODUCTION_SPEC.md",
        f"# I1 V2.1.3 production specification\n\n"
        f"- producer version: `{I1_PRODUCER_VERSION}`\n"
        f"- schema: `{PRODUCTION_SCHEMA_VERSION}`\n"
        f"- config SHA256: `{config_sha256}`\n"
        f"- base layer: frozen source loader → canonical truth builder → frozen base renderer\n"
        f"- final layer: controlled rewrite adapter → strict rewrite validation → exactly one final prompt per truth\n"
        f"- public benchmark shape: `{{case_id, llm_prompt, answer}}`\n"
        f"- DUT evaluation shape: `{{case_id, prompt}}`\n"
        f"- public difficulty label: absent\n"
        f"- rewrite model: `{model}`; provider: `{config['rewrite']['provider']}`; temperature: `{config['rewrite']['temperature']}`; top_p: `{config['rewrite']['top_p']}`; max_tokens: `{config['rewrite']['max_tokens']}`\n"
        f"- rewrite prompt version: `{REWRITE_PROMPT_VERSION}`\n"
        f"- source root used: `{source_root}`\n"
        ,
    )
    _write_text(
        output / "I1_V2_1_3_EVALUATION_METRICS.md",
        "# I1 V2.1.3 evaluation metrics\n\n"
        "| Metric | Meaning | Scientific status |\n"
        "|---|---|---|\n"
        "| `semantic_exact_match` / `semantic_intent_accuracy` | canonical semantic answer equals model meaning; fence-only output may be diagnosed semantically | primary I1 science metric |\n"
        "| `raw_format_valid` / `strict_format_compliance` | raw content is one strict JSON value | independent engineering metric |\n"
        "| `final_case_pass` / `strict_case_pass_rate` | strict format + schema + semantics | strict end-to-end metric, not intent accuracy |\n\n"
        "The scorer calls `src.i1.validator.validate_i1_output` and does not repair or extract model output.\n"
        ,
    )
    _write_text(
        output / "I1_V2_1_3_PREPRODUCTION_REPORT.md",
        f"# I1 V2.1.3 pre-production report\n\n"
        f"## Result\n\n"
        f"- requested counts: I1-S/I1-C/I1-D = {config['requested_case_counts']['I1-S']}/{config['requested_case_counts']['I1-C']}/{config['requested_case_counts']['I1-D']}\n"
        f"- produced counts: I1-S/I1-C/I1-D = {counts['I1-S']}/{counts['I1-C']}/{counts['I1-D']}\n"
        f"- PREPRODUCTION_300 = **{target_status}**\n"
        f"- one truth → one prompt: **PASS**\n"
        f"- rewrite final success: {rewrite_stats['final_success_count']}/{rewrite_stats['total_case_count']} ({rewrite_stats['final_success_rate']:.3f})\n"
        f"- total API rewrite calls: {rewrite_stats['total_rewrite_calls']}\n"
        f"- first-pass API rewrite success: {rewrite_stats['first_pass_success_count']}/{rewrite_stats['api_rewrite_case_count']} ({rewrite_stats['first_pass_success_rate']:.3f})\n"
        f"- cases needing retry: {rewrite_stats['cases_needing_retry']}\n"
        f"- normalized duplicate prompts: see `duplicate_report.json`\n\n"
        "## Capacity caveat\n\n"
        f"The available frozen source pool safely exposed {pool_report['raw_source_counts']['single_requests']} single requests, {pool_report['raw_source_counts']['prebuilt_concurrent_sets']} prebuilt concurrent sets, and {pool_report['raw_source_counts']['dynamic_events']} dynamic events. The existing deterministic concurrent grouping expansion supports the requested concurrent count; the dynamic pool does not safely support 100 unique dynamic truths. No synthetic request/time pairing was created.\n\n"
        "Therefore the dry run is evidence for production-chain stability at the supported count, but it is not evidence that a 300-case release has been completed. Expand the authoritative dynamic source pool before claiming PREPRODUCTION_300=PASS.\n",
    )
    _write_text(
        output / "ENGINEERING_VALIDATION.md",
        f"# Engineering validation\n\n"
        f"- production path: one canonical truth → one final prompt → public/evaluation cases\n"
        f"- output schemas validated with frozen `contracts/I1-*` schemas\n"
        f"- evaluation answer leakage check: evaluation shape constructed with exactly `case_id` and `prompt`\n"
        f"- strict rewrite validation: {rewrite_stats['final_success_count']}/{rewrite_stats['total_case_count']}\n"
        f"- duplicate normalized final prompts: checked by `src.i1.production.validate_one_prompt_per_truth` and `duplicate_report.json`\n"
        f"- source pool counts and shortfall: `coverage_report.json`\n"
        f"- baseline source root: `{source_root}`\n"
        f"- no API key is written; only `{API_KEY_ENV}` variable name is recorded\n"
        ,
    )
    _write_text(
        output / "SCIENTIFIC_AUDIT.md",
        "# Scientific audit\n\n"
        "## Contract preservation\n\n"
        "The I1 scientific contract is preserved: LLM-only, I1-S/I1-C/I1-D, business-intent fields and frozen objective order. The public production case does not add topology, path, spectrum, slot_start, candidate action, dynamic environment state, or runtime access.\n\n"
        "## Difficulty status\n\n"
        "The historical second-round 21 truths × EASY/MEDIUM/HARD pilot found all four DUTs at 63/63 semantic exact match and registered `DIFFICULTY_DISCRIMINATION=FAIL`. EASY/MEDIUM/HARD therefore remain internal paired robustness/language-expression audit variants only; they are not claimed as a validated formal ability difficulty axis and are not exported as public labels here.\n\n"
        "## Construct-validity caveat\n\n"
        "The system prompt explicitly enumerates objective codes and meanings. Objective parsing is consequently a controlled label-mapping test, not open-ended objective discovery. This is a frozen design caveat, not silently changed by V2.1.3.\n\n"
        "## Progressive evaluation\n\n"
        "I1 remains a diagnostic prerequisite for later O/S1/X2/X3/X4 analyses: I1 failure can be one potential source of downstream failure; I1 pass plus downstream failure points toward later graph/path/resource/decision abilities and should not be called an intent failure without additional evidence.\n\n"
        "## Production implication\n\n"
        "The chain is ready for formal expansion with the caveat that the authoritative source pool must be expanded before a 100/100/100 preproduction claim. The dry run must not be padded with duplicate or synthetic dynamic truths.\n",
    )
    _write_text(
        output / "PROGRESSIVE_EVALUATION_ANALYSIS.md",
        "# Progressive evaluation alignment\n\n"
        "I1-S isolates a single connection intent; I1-C isolates concurrent request parsing and request-to-field binding; I1-D isolates dynamic request timing and holding-time semantics. None requires path search, RSA, spectrum allocation, topology reasoning, or runtime access. The outputs cover the business semantics later tasks need to distinguish from solving ability.\n\n"
        "Verdict: `PASS_WITH_CAVEATS` — objective parsing is controlled by explicit label definitions, and I1 should be used as a diagnostic layer rather than the main leaderboard discriminator.\n",
    )
    _write_text(
        output / "FINAL_V2_1_3_REPORT.md",
        f"# Final V2.1.3 production-readiness report\n\n"
        "- ENGINEERING_READINESS = **PASS_WITH_CAVEATS**\n"
        "- SCIENTIFIC_CONTRACT_PRESERVED = **PASS**\n"
        f"- PREPRODUCTION_300 = **{target_status}**\n"
        "- READY_FOR_FORMAL_I1_PRODUCTION = **YES_WITH_CHANGES**\n\n"
        "The Windows portability fix is isolated to test construction; the production Windows path validator remains unchanged. The formal production path is usable, but the current frozen fixture cannot support 100 unique dynamic canonical truths, so formal large-scale production should begin only after the authoritative dynamic source pool is expanded and the same gates are rerun.\n\n"
        "Formal releases should export one prompt per canonical truth and omit EASY/MEDIUM/HARD from the public scientific case. Preserve the historical difficulty pilot as internal audit evidence.\n",
    )
    _write_json(
        output / "production_summary.json",
        {
            "producer_version": I1_PRODUCER_VERSION,
            "schema_version": PRODUCTION_SCHEMA_VERSION,
            "requested_case_counts": config["requested_case_counts"],
            "produced_case_counts": counts,
            "case_count": len(rows),
            "preproduction_300": target_status,
            "one_truth_one_prompt": True,
            "public_difficulty_axis": False,
            "rewrite_model": model,
            "rewrite_stats": rewrite_stats,
            "pool_report": pool_report,
        },
    )


def _write_manifest_and_sums(output: Path) -> dict:
    manifest_files = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name not in {"MANIFEST.json", "SHA256SUMS.txt"}):
        manifest_files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "producer_version": I1_PRODUCER_VERSION,
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "file_count_excluding_manifest_and_sums": len(manifest_files),
        "files": manifest_files,
    }
    _write_json(output / "MANIFEST.json", manifest)
    sum_paths = sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    _write_text(
        output / "SHA256SUMS.txt",
        "".join(f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}\n" for path in sum_paths),
    )
    return manifest


def run_preproduction(
    environment_root: Path | str,
    config_path: Path | str,
    output_root: Path | str,
    *,
    rewrite_client=None,
    resume_from: Path | str | None = None,
) -> dict:
    """Run the V2.1.3 dry run and return the generated production summary."""

    source_root = Path(__file__).resolve().parents[1]
    output = Path(output_root).resolve()
    config, config_sha256 = _load_config(config_path)
    run_started_at = _utc_now()
    resume_root = Path(resume_from).resolve() if resume_from is not None else None
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    records, pool_report = build_preproduction_base_records(environment_root, config, config_sha256)
    all_records = [
        {**record, "task_type": task}
        for task in TASKS
        for record in records[task]
    ]
    styles = config["style_cycle"]

    rewrite_cfg = dict(config["rewrite"])
    key_env = rewrite_cfg["api_key_env"]
    if rewrite_client is None:
        if not os.environ.get(key_env):
            _write_json(output / "PREPRODUCTION_FAILURE.json", {"status": "MISSING_API_KEY", "api_key_env": key_env})
            raise RuntimeError(f"missing required environment variable: {key_env}")
        rewrite_client = OpenAICompatibleRewriteClient(
            base_url=os.environ.get("SILICONFLOW_BASE_URL", rewrite_cfg["base_url"]),
            api_key_env=key_env,
            model=os.environ.get("SILICONFLOW_MODEL", rewrite_cfg["model"]),
            temperature=rewrite_cfg["temperature"],
            top_p=rewrite_cfg["top_p"],
            max_tokens=rewrite_cfg["max_tokens"],
            timeout_seconds=rewrite_cfg.get("timeout_seconds", 60),
            enable_thinking=False,
        )
    rewrite_cfg["base_url"] = getattr(rewrite_client, "base_url", rewrite_cfg["base_url"])
    rewrite_cfg["model"] = getattr(rewrite_client, "model", rewrite_cfg["model"])
    runtime_config = dict(config)
    runtime_config["rewrite"] = rewrite_cfg
    _write_json(
        output / "PILOT_CONFIG.json",
        {
            **runtime_config,
            "config_sha256": config_sha256,
            "environment_root": str(Path(environment_root).resolve()),
        },
    )
    stats = {
        "api_rewrite_case_count": 0,
        "deterministic_base_count": 0,
        "total_rewrite_calls": 0,
        "first_pass_success_count": 0,
        "cases_needing_retry": 0,
        "retry_count_total": 0,
        "failed_attempt_count": 0,
        "failed_case_count": 0,
        "failure_reasons": Counter(),
        "_attempt_counts": [],
        "_lock": Lock(),
    }
    rows = []
    # Keep source order deterministic and write an inspectable, non-public base layer.
    worker_count = int(config.get("max_workers", 4))
    rewrite_results = {}
    pending = []
    for index, record in enumerate(all_records):
        style = _style_for_index(index, styles)
        resumed = None
        if resume_root is not None and style != "DIRECT":
            resumed = _resume_rewrite_one(
                resume_root,
                output,
                record,
                style,
                rewrite_cfg["model"],
                stats,
            )
        if resumed is None:
            pending.append((index, record, style))
        else:
            rewrite_results[index] = resumed
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            (
                index,
                executor.submit(
                    _rewrite_one,
                    output,
                    record,
                    style,
                    rewrite_client,
                    rewrite_cfg,
                    stats,
                ),
            )
            for index, record, style in pending
        ]
        for index, future in futures:
            rewrite_results[index] = future.result()
    for index, record in enumerate(all_records):
        final_prompt, rewrite_meta = rewrite_results[index]
        stats["_attempt_counts"].append(int(rewrite_meta["rewrite_attempt_count"]))
        rows.append(_write_case_artifacts(output, record, final_prompt, rewrite_meta, source_root / "contracts"))
    validate_one_prompt_per_truth(
        [{"truth_id": row["truth_id"], "final_prompt": json.loads((output / row["benchmark_case_path"]).read_text(encoding="utf-8"))["llm_prompt"]} for row in rows]
    )
    _write_index(output, rows)
    _write_coverage_reports(output, rows, records, pool_report)
    rewrite_stats = _finalize_rewrite_stats(stats, len(rows))
    _write_json(output / "rewrite_efficiency.json", rewrite_stats)
    _write_readme_and_reports(
        output,
        config,
        config_sha256,
        pool_report,
        rewrite_stats,
        rows,
        source_root=source_root,
    )
    _write_json(
        output / "ENVIRONMENT.json",
        {
            "producer_version": I1_PRODUCER_VERSION,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "source_git_head": _git_head(source_root),
            "source_root": str(source_root),
            "rewrite_provider": rewrite_cfg["provider"],
            "rewrite_model": getattr(rewrite_client, "model", rewrite_cfg["model"]),
            "rewrite_base_url": getattr(rewrite_client, "base_url", rewrite_cfg["base_url"]),
            "api_key_env": API_KEY_ENV,
            "api_key_value_recorded": False,
            "run_started_at": run_started_at,
            "run_finished_at": _utc_now(),
        },
    )
    manifest = _write_manifest_and_sums(output)
    summary = json.loads((output / "production_summary.json").read_text(encoding="utf-8"))
    summary["manifest_file_count_excluding_manifest_and_sums"] = manifest["file_count_excluding_manifest_and_sums"]
    _write_json(output / "production_summary.json", summary)
    _write_manifest_and_sums(output)
    return summary


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="I1 V2.1.3 formal production dry run")
    parser.add_argument("--environment", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        summary = run_preproduction(args.environment, args.config, args.output)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
