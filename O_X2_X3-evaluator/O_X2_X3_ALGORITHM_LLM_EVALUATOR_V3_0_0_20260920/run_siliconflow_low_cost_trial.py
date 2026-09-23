from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


TASKS = ["O1", "O2-S", "O2-C", "X2", "X3"]
DEFAULT_MODELS = ["Qwen/Qwen3.8-27B", "deepseek-ai/DeepSeek-V4-Flash"]
EXPECTED_DATASET_SHA256 = (
    "2dbd7aa48fd42fea84f339a31fe5ad6e3024253ce64f936e71e8731dc389bb23"
)


def selected_cases() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for task, prefix in [
        ("O1", "O1"),
        ("O2-S", "O2S"),
        ("O2-C", "O2C"),
        ("X2", "X2"),
        ("X3", "X3"),
    ]:
        rows.append(
            {
                "task": task,
                "topology": "topologybench_netrail",
                "public_case_file": "case_000001.json",
                "evidence_case_file": "case_000001.json",
                "case_id": f"{prefix}_topologybench_netrail_000001",
            }
        )
        rows.append(
            {
                "task": task,
                "topology": "topologybench_elibackbone",
                "public_case_file": "case_000002.json",
                "evidence_case_file": "case_000001.json",
                "case_id": f"{prefix}_topologybench_elibackbone_000001",
            }
        )
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model)


def find_dataset_root(extract_dir: Path) -> Path:
    candidates = []
    for directory in [extract_dir, *extract_dir.rglob("*")]:
        if directory.is_dir() and (directory / "benchmark_case").is_dir() and (
            directory / "evaluation_case"
        ).is_dir():
            candidates.append(directory)
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one extracted dataset root, found {len(candidates)}: "
            + ", ".join(str(p) for p in candidates)
        )
    return candidates[0]


def safe_archive_members(archive: zipfile.ZipFile) -> None:
    for member in archive.namelist():
        path = PurePosixPath(member)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe ZIP member path: {member}")


def extract_dataset(dataset_zip: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    archive_sha = sha256_file(dataset_zip)
    with zipfile.ZipFile(dataset_zip) as archive:
        safe_archive_members(archive)
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"dataset ZIP CRC failure at {bad_member}")
        extract_dir = out / "00_DATASET_INPUT_FRESH_EXTRACTION"
        extract_dir.mkdir(parents=True, exist_ok=False)
        archive.extractall(extract_dir)
        root = find_dataset_root(extract_dir)
        info = {
            "archive": str(dataset_zip),
            "archive_sha256": archive_sha,
            "expected_archive_sha256": EXPECTED_DATASET_SHA256,
            "sha256_matches_expected": archive_sha == EXPECTED_DATASET_SHA256,
            "zip_member_count": len(archive.namelist()),
            "zip_crc": "PASS",
            "fresh_extraction_root": str(root),
        }
    if archive_sha != EXPECTED_DATASET_SHA256:
        raise RuntimeError(
            "current dataset ZIP SHA256 mismatch: " + archive_sha
        )
    return root, info


def tokenizer_info() -> tuple[Any | None, dict[str, Any]]:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_base")
        return encoding, {
            "available": True,
            "version": getattr(tiktoken, "__version__", None),
            "encoding": "o200k_base",
        }
    except Exception as exc:
        return None, {
            "available": False,
            "version": None,
            "encoding": "o200k_base",
            "error": f"{type(exc).__name__}: {exc}",
        }


def parity_preflight(
    public_root: Path, evidence_datasets: Path, rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for row in rows:
        task = row["task"]
        topology = row["topology"]
        public_case = public_root / "benchmark_case" / task / "cases" / row[
            "public_case_file"
        ]
        public_llm = public_root / "evaluation_case" / task / "llm" / row[
            "public_case_file"
        ]
        evidence_root = evidence_datasets / topology
        evidence_case = (
            evidence_root
            / "benchmark_case"
            / task
            / "cases"
            / row["evidence_case_file"]
        )
        evidence_llm = (
            evidence_root
            / "evaluation_case"
            / task
            / "llm"
            / row["evidence_case_file"]
        )
        for path in (public_case, public_llm, evidence_case, evidence_llm):
            if not path.is_file():
                raise FileNotFoundError(path)
        public_case_obj = read_json(public_case)
        evidence_case_obj = read_json(evidence_case)
        public_llm_obj = read_json(public_llm)
        evidence_llm_obj = read_json(evidence_llm)
        check = {
            "task": task,
            "topology": topology,
            "case_id": row["case_id"],
            "public_case_json_equal_to_evidence": public_case_obj
            == evidence_case_obj,
            "public_llm_evaluation_equal_to_evidence": public_llm_obj
            == evidence_llm_obj,
            "public_case_id": public_case_obj.get("case_id"),
            "evidence_case_id": evidence_case_obj.get("case_id"),
            "reference_decision": (public_case_obj.get("reference") or {}).get(
                "decision"
            ),
            "public_benchmark_sha256": sha256_file(public_case),
            "evidence_benchmark_sha256": sha256_file(evidence_case),
            "official_validation_dataset": str(evidence_root),
        }
        if not check["public_case_json_equal_to_evidence"]:
            raise RuntimeError(
                f"public/evidence benchmark mismatch for {task}/{row['case_id']}"
            )
        if not check["public_llm_evaluation_equal_to_evidence"]:
            raise RuntimeError(
                f"public/evidence LLM input mismatch for {task}/{row['case_id']}"
            )
        if check["public_case_id"] != row["case_id"] or check["evidence_case_id"] != row[
            "case_id"
        ]:
            raise RuntimeError(f"case_id mismatch for {task}/{row['case_id']}")
        checks.append(check)
    return checks


def post_json(
    endpoint: str, payload: dict[str, Any], api_key: str, timeout: int
) -> tuple[int | None, str, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-OptiRSA-Client": "OpticalBenchmark-low-cost-trial/20260915",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return int(response.status), response_body, (time.monotonic() - started) * 1000
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), response_body, (time.monotonic() - started) * 1000
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", (time.monotonic() - started) * 1000


def call_model(
    endpoint: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "top_p": 1.0,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
    }
    retryable = {408, 409, 429, 500, 502, 503, 504}
    attempts: list[dict[str, Any]] = []
    last_status: int | None = None
    last_body = ""
    total_started = time.monotonic()
    for attempt_number in range(1, retries + 2):
        status, body, elapsed_ms = post_json(endpoint, payload, api_key, timeout)
        last_status = status
        last_body = body
        attempts.append(
            {
                "attempt": attempt_number,
                "http_status": status,
                "elapsed_ms": round(elapsed_ms, 3),
                "body_bytes": len(body.encode("utf-8")),
            }
        )
        if status is not None and 200 <= status < 300:
            try:
                response = json.loads(body)
                return {
                    "ok": True,
                    "http_status": status,
                    "attempts": attempts,
                    "response": response,
                    "raw_body": body,
                    "total_elapsed_ms": round(
                        (time.monotonic() - total_started) * 1000, 3
                    ),
                }
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "http_status": status,
                    "attempts": attempts,
                    "response": None,
                    "raw_body": body,
                    "error": f"API returned non-JSON body: {exc}",
                    "total_elapsed_ms": round(
                        (time.monotonic() - total_started) * 1000, 3
                    ),
                }
        if status not in retryable or attempt_number > retries:
            break
        time.sleep(min(2 ** (attempt_number - 1), 8))
    return {
        "ok": False,
        "http_status": last_status,
        "attempts": attempts,
        "response": None,
        "raw_body": last_body,
        "error": "request failed after retry policy",
        "total_elapsed_ms": round((time.monotonic() - total_started) * 1000, 3),
    }


def message_content(response: dict[str, Any]) -> tuple[str, str]:
    choices = response.get("choices") or []
    if not choices:
        return "", ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    reasoning = message.get("reasoning_content", "")
    return str(content or ""), str(reasoning or "")


def parse_model_json(text: str) -> tuple[dict[str, Any] | None, str, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "EMPTY", "model content is empty"
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value, "STRICT_JSON", None
        return None, "NON_OBJECT_JSON", "top-level JSON value is not an object"
    except json.JSONDecodeError:
        pass
    fence = chr(96) * 3
    fenced = re.search(
        re.escape(fence) + r"(?:json)?\s*(\{.*?\})\s*" + re.escape(fence),
        stripped,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        try:
            value = json.loads(fenced.group(1))
            if isinstance(value, dict):
                return value, "FENCED_JSON", None
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for position, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value, "SCANNED_JSON", None
    return None, "INVALID_JSON", "no JSON object could be parsed from model content"


def parse_cli_json(stdout: str) -> dict[str, Any] | None:
    try:
        value = json.loads(stdout.strip())
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def run_official_validator(
    producer_root: Path,
    evidence_dataset: Path,
    task: str,
    case_id: str,
    response_path: Path,
    timeout: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(producer_root / "benchmark_ox.py"),
        "validate-output",
        "--dataset",
        str(evidence_dataset),
        "--task",
        task,
        "--case-id",
        case_id,
        "--response",
        str(response_path),
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=producer_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        result = parse_cli_json(completed.stdout)
        return {
            "command": command,
            "returncode": completed.returncode,
            "valid": bool(result and result.get("valid")),
            "result": result,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except Exception as exc:
        return {
            "command": command,
            "returncode": None,
            "valid": False,
            "result": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }


def file_manifest(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return rows


def write_sha256sums(root: Path) -> None:
    rows = file_manifest(root)
    write_text(
        root / "SHA256SUMS.txt",
        "".join(f"{item['sha256']}  {item['path']}\n" for item in rows),
    )


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    for model in DEFAULT_MODELS:
        model_rows = [row for row in rows if row["model"] == model]
        validation_rows = [
            row["validation"]["result"]
            for row in model_rows
            if row.get("validation", {}).get("result")
        ]
        valid_count = sum(bool(result.get("valid")) for result in validation_rows)
        parse_count = sum(
            row["parse_status"] in {"STRICT_JSON", "FENCED_JSON", "SCANNED_JSON"}
            for row in model_rows
        )
        api_count = sum(bool(row["api_ok"]) for row in model_rows)
        decision_matches = sum(
            row.get("model_decision") is not None
            and row.get("model_decision") == row.get("reference_decision")
            for row in model_rows
        )
        by_model[model] = {
            "requests": len(model_rows),
            "api_success": api_count,
            "json_object_parsed": parse_count,
            "official_validator_pass": valid_count,
            "reference_decision_match": decision_matches,
            "parse_or_api_failure": len(model_rows) - parse_count,
            "validator_not_run": len(model_rows) - len(validation_rows),
        }
    by_task: dict[str, dict[str, Any]] = {}
    for task in TASKS:
        task_rows = [row for row in rows if row["task"] == task]
        for_model = {}
        for model in DEFAULT_MODELS:
            subset = [row for row in task_rows if row["model"] == model]
            results = [
                row["validation"]["result"]
                for row in subset
                if row.get("validation", {}).get("result")
            ]
            gaps = []
            for result in results:
                metrics = result.get("metrics") or {}
                for name in ("wufr_gap", "hop_gap", "delta_tso_gap"):
                    if metrics.get(name) is not None:
                        gaps.append({name: metrics[name]})
            for_model[model] = {
                "cases": len(subset),
                "api_success": sum(bool(row["api_ok"]) for row in subset),
                "json_object_parsed": sum(
                    row["parse_status"]
                    in {"STRICT_JSON", "FENCED_JSON", "SCANNED_JSON"}
                    for row in subset
                ),
                "official_validator_pass": sum(
                    bool(result.get("valid")) for result in results
                ),
                "reference_decision_match": sum(
                    row.get("model_decision") == row.get("reference_decision")
                    for row in subset
                    if row.get("model_decision") is not None
                ),
                "objective_gap_metrics": gaps,
            }
        by_task[task] = for_model
    return {
        "trial_case_count": len({row["case_id"] for row in rows}),
        "model_request_count": len(rows),
        "api_request_count": len(rows),
        "by_model": by_model,
        "by_task": by_task,
        "records": rows,
    }


def summary_markdown(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "# SiliconFlow 低成本 LLM 试评结果",
        "",
        "本次用于检查 O1 / O2-S / O2-C / X2 / X3 数据集的 LLM 输入可用性与模型初步表现，不替代完整 Benchmark 评测。",
        "",
        "## 运行范围",
        "",
        f"- 数据包：{manifest['dataset']['archive']}",
        f"- 数据包 SHA256：{manifest['dataset']['archive_sha256']}",
        "- Case：10 条（每任务 2 条；netrail + elibackbone）",
        f"- 模型请求：{summary['model_request_count']} 次（每模型 10 次）",
        f"- temperature：{manifest['model_parameters']['temperature']}",
        f"- max_tokens：{manifest['model_parameters']['max_tokens']}",
        "",
        "## 按模型汇总",
        "",
        "| 模型 | 请求 | API成功 | JSON解析 | 官方Validator PASS | 参考决策匹配 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, values in summary["by_model"].items():
        lines.append(
            f"| {model} | {values['requests']} | {values['api_success']} | "
            f"{values['json_object_parsed']} | {values['official_validator_pass']} | "
            f"{values['reference_decision_match']} |"
        )
    lines.extend(
        [
            "",
            "## 按任务汇总",
            "",
            "| 任务 | 模型 | API成功 | JSON解析 | Validator PASS | 参考决策匹配 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for task in TASKS:
        for model, values in summary["by_task"][task].items():
            lines.append(
                f"| {task} | {model} | {values['api_success']} | "
                f"{values['json_object_parsed']} | {values['official_validator_pass']} | "
                f"{values['reference_decision_match']} |"
            )
    lines.extend(
        [
            "",
            "## 逐条结果",
            "",
            "| 模型 | 任务 | Case | 参考决策 | 模型决策 | 解析 | Validator | 指标摘要 |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in summary["records"]:
        validation = row.get("validation", {})
        result = validation.get("result") or {}
        metrics = result.get("metrics") or {}
        metric_parts = []
        for name in ("wufr_gap", "hop_gap", "delta_tso_gap"):
            if metrics.get(name) is not None:
                metric_parts.append(f"{name}={metrics[name]}")
        validator = "PASS" if result.get("valid") else (
            "FAIL" if validation.get("result") is not None else "NOT_RUN"
        )
        lines.append(
            f"| {row['model']} | {row['task']} | {row['case_id']} | "
            f"{row.get('reference_decision')} | {row.get('model_decision') or 'NA'} | "
            f"{row['parse_status']} | {validator} | "
            f"{', '.join(metric_parts) if metric_parts else 'NA'} |"
        )
    lines.extend(
        [
            "",
            "## 如何理解",
            "",
            "- 官方Validator PASS 表示模型返回的 JSON 符合输出合同，并被 evaluator-side truth 判定为合法且决策正确；这不等于模型一定达到最优 WUFR、跳数或总槽位目标。",
            "- 参考决策匹配只比较 ACCEPT/REJECT 判断；质量指标仍应看逐条记录中的 gap。",
            "- 本次样本只有 10 条，拓扑和配置覆盖有限，只能判断接口能否跑通、模型是否能完成初步求解，不能据此冻结难度结论或替代 45 条正式试评。",
            "- 完整 API 返回在 results/*/TASK/CASE/raw_api.json，模型原文在 response.txt，解析后的提交和官方 Validator 输出在 parsed_response.json、official_validation.json。",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty trial directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("SILICONFLOW_API_KEY is not available")
    dataset_zip = Path(args.dataset_zip).resolve()
    producer_root = Path(args.producer_root).resolve()
    evidence_datasets = Path(args.evidence_datasets).resolve()
    if not dataset_zip.is_file():
        raise FileNotFoundError(dataset_zip)
    if not (producer_root / "benchmark_ox.py").is_file():
        raise FileNotFoundError(producer_root / "benchmark_ox.py")
    rows = selected_cases()
    public_root, dataset_info = extract_dataset(dataset_zip, output)
    public_root, dataset_info = public_root, dataset_info
    encoding, token_info = tokenizer_info()
    parity = parity_preflight(public_root, evidence_datasets, rows)
    manifest: dict[str, Any] = {
        "status": "RUNNING",
        "started_at": dt.datetime.now().astimezone().isoformat(),
        "dataset": dataset_info,
        "public_dataset_fresh_root": str(public_root),
        "producer_root": str(producer_root),
        "models": DEFAULT_MODELS,
        "model_parameters": {
            "endpoint": args.endpoint,
            "temperature": args.temperature,
            "top_p": 1.0,
            "max_tokens": args.max_tokens,
            "timeout_seconds": args.timeout,
            "retries": args.retries,
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
        },
        "tokenizer": token_info,
        "case_count": len(rows),
        "case_selection": rows,
        "public_evidence_parity": parity,
        "completed_requests": 0,
    }
    write_json(output / "TRIAL_MANIFEST.json", manifest)
    write_json(output / "CASE_SELECTION.json", {"cases": rows, "count": len(rows)})
    write_json(output / "PUBLIC_EVIDENCE_PARITY.json", {"checks": parity})
    write_json(
        output / "MODEL_REQUEST_CONFIG.json",
        {
            "endpoint": args.endpoint,
            "models": DEFAULT_MODELS,
            "temperature": args.temperature,
            "top_p": 1.0,
            "max_tokens": args.max_tokens,
            "timeout_seconds": args.timeout,
            "retries": args.retries,
            "response_format": {"type": "json_object"},
            "enable_thinking": False,
            "api_key_saved": False,
        },
    )
    write_text(
        output / "README.md",
        "\n".join(
            [
                "# O/X2/X3 低成本模型试评",
                "",
                "本目录保存当前公开数据包的 10 条 LLM 小试评，以及两个硅基流动模型的原始返回、解析结果和官方 Validator 结果。",
                "",
                "- 每个任务选择 2 条 Case：topologybench_netrail 和 topologybench_elibackbone。",
                "- 每条 Case 分别提交给两个模型，共 20 次 LLM 请求。",
                "- API 密钥不写入任何文件。",
                "- 公开数据包与 Evidence private truth 的对应 Case 在运行前做 JSON 一致性核对。",
                "",
                "查看顺序：SUMMARY.md → records.jsonl → response.txt、parsed_response.json、official_validation.json。",
                "",
            ]
        ),
    )
    records_path = output / "records.jsonl"
    total = len(DEFAULT_MODELS) * len(rows)
    completed = 0
    for model in DEFAULT_MODELS:
        model_name = model_slug(model)
        for row in rows:
            task = row["task"]
            case_id = row["case_id"]
            public_case_file = public_root / "benchmark_case" / task / "cases" / row[
                "public_case_file"
            ]
            system_path = public_root / "benchmark_case" / task / "llm_system_prompt.txt"
            llm_eval_path = public_root / "evaluation_case" / task / "llm" / row[
                "public_case_file"
            ]
            system_prompt = system_path.read_text(encoding="utf-8")
            user_prompt = read_json(llm_eval_path)["prompt"]
            prompt_tokens = (
                len(encoding.encode(system_prompt + user_prompt)) if encoding else None
            )
            response = call_model(
                args.endpoint,
                api_key,
                model,
                system_prompt,
                user_prompt,
                args.temperature,
                args.max_tokens,
                args.timeout,
                args.retries,
            )
            base = output / "results" / model_name / task / case_id
            raw_api_path = base / "raw_api.json"
            response_text_path = base / "response.txt"
            reasoning_path = base / "reasoning_content.txt"
            parsed_path = base / "parsed_response.json"
            validation_path = base / "official_validation.json"
            if response["response"] is not None:
                write_json(raw_api_path, response["response"])
                content, reasoning = message_content(response["response"])
            else:
                write_json(
                    raw_api_path,
                    {
                        "http_status": response.get("http_status"),
                        "attempts": response.get("attempts"),
                        "error": response.get("error"),
                        "raw_body": response.get("raw_body", ""),
                    },
                )
                content, reasoning = "", ""
            write_text(response_text_path, content)
            write_text(reasoning_path, reasoning)
            parsed, parse_status, parse_error = parse_model_json(content)
            if parsed is not None:
                write_json(parsed_path, parsed)
            validation: dict[str, Any] = {
                "result": None,
                "returncode": None,
                "valid": False,
            }
            if parsed is not None:
                evidence_dataset = evidence_datasets / row["topology"]
                validation = run_official_validator(
                    producer_root,
                    evidence_dataset,
                    task,
                    case_id,
                    parsed_path,
                    args.validator_timeout,
                )
                write_json(validation_path, validation)
            model_decision = parsed.get("decision") if parsed else None
            result_obj = validation.get("result") or {}
            record = {
                "model": model,
                "task": task,
                "topology": row["topology"],
                "case_id": case_id,
                "reference_decision": next(
                    item["reference_decision"]
                    for item in parity
                    if item["case_id"] == case_id
                ),
                "model_decision": model_decision,
                "prompt_tokens_tiktoken": prompt_tokens,
                "api_ok": bool(response["ok"]),
                "api_http_status": response.get("http_status"),
                "api_attempt_count": len(response.get("attempts", [])),
                "api_elapsed_ms": response.get("total_elapsed_ms"),
                "api_usage": (response.get("response") or {}).get("usage"),
                "parse_status": parse_status,
                "parse_error": parse_error,
                "validation": validation,
                "official_validator_valid": bool(result_obj.get("valid")),
                "submitted_metrics": result_obj.get("metrics"),
                "artifact_paths": {
                    "raw_api": raw_api_path.relative_to(output).as_posix(),
                    "response_text": response_text_path.relative_to(output).as_posix(),
                    "reasoning_content": reasoning_path.relative_to(output).as_posix(),
                    "parsed_response": parsed_path.relative_to(output).as_posix()
                    if parsed is not None
                    else None,
                    "official_validation": validation_path.relative_to(output).as_posix()
                    if parsed is not None
                    else None,
                    "public_benchmark_case": str(public_case_file),
                    "public_llm_evaluation": str(llm_eval_path),
                },
            }
            with records_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            completed += 1
            manifest["completed_requests"] = completed
            write_json(output / "TRIAL_MANIFEST.json", manifest)
            status = "PASS" if record["official_validator_valid"] else (
                "NOT_RUN" if parsed is None else "FAIL"
            )
            print(
                f"[{completed}/{total}] {model} | {task} | {case_id} | "
                f"parse={parse_status} validator={status}",
                flush=True,
            )
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = build_summary(records)
    write_json(output / "SUMMARY.json", summary)
    manifest["status"] = "COMPLETE"
    manifest["completed_at"] = dt.datetime.now().astimezone().isoformat()
    manifest["summary_file"] = "SUMMARY.json"
    write_json(output / "TRIAL_MANIFEST.json", manifest)
    write_text(output / "SUMMARY.md", summary_markdown(summary, manifest))
    write_sha256sums(output)
    print(f"TRIAL_OUTPUT={output}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-zip", required=True)
    parser.add_argument("--producer-root", required=True)
    parser.add_argument("--evidence-datasets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--endpoint",
        default="https://api.siliconflow.cn/v1/chat/completions",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--validator-timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
