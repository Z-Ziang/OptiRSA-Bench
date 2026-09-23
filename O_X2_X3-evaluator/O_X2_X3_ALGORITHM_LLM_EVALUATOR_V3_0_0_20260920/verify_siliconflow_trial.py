from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import zipfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


TASKS = ["O1", "O2-S", "O2-C", "X2", "X3"]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(walk_keys(child))
    return keys


def run(args: argparse.Namespace) -> dict[str, Any]:
    trial = Path(args.trial).resolve()
    dataset = Path(args.dataset).resolve()
    producer = Path(args.producer).resolve()
    records = [
        json.loads(line)
        for line in (trial / "records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    config = read_json(trial / "MODEL_REQUEST_CONFIG.json")
    manifest = read_json(trial / "TRIAL_MANIFEST.json")
    schema_valid = 0
    raw_json_valid = 0
    usage_present = 0
    public_case_count = 0
    parity_pass = 0
    public_llm_shape_pass = 0
    public_llm_prompt_parity_pass = 0
    public_case_seen: set[str] = set()
    official_valid = 0
    format_failures: list[dict[str, Any]] = []
    official_failures: list[dict[str, Any]] = []
    latencies: list[float] = []
    api_statuses: list[int | None] = []
    key_leak_hits: list[dict[str, Any]] = []
    for record in records:
        task = record["task"]
        case_id = record["case_id"]
        base = (
            trial
            / "results"
            / record["model"].replace("/", "_")
            / task
            / case_id
        )
        raw_path = base / "raw_api.json"
        parsed_path = base / "parsed_response.json"
        validation_path = base / "official_validation.json"
        raw = read_json(raw_path)
        parsed = read_json(parsed_path)
        schema = read_json(
            producer / "contracts" / task / "output_schema.json"
        )
        errors = sorted(Draft202012Validator(schema).iter_errors(parsed), key=str)
        if not errors:
            schema_valid += 1
        else:
            format_failures.append(
                {
                    "model": record["model"],
                    "task": task,
                    "case_id": case_id,
                    "errors": [error.message for error in errors],
                }
            )
        if isinstance(raw, dict):
            raw_json_valid += 1
        usage = record.get("api_usage")
        if isinstance(usage, dict) and all(
            usage.get(key) is not None
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        ):
            usage_present += 1
        if record.get("api_http_status") is not None:
            api_statuses.append(int(record["api_http_status"]))
        if record.get("api_elapsed_ms") is not None:
            latencies.append(float(record["api_elapsed_ms"]))
        validation = read_json(validation_path)
        if bool(validation.get("valid")):
            official_valid += 1
        else:
            official_failures.append(
                {
                    "model": record["model"],
                    "task": task,
                    "case_id": case_id,
                    "errors": (validation.get("result") or {}).get("errors", []),
                }
            )
        if record.get("parse_status") != "STRICT_JSON":
            format_failures.append(
                {
                    "model": record["model"],
                    "task": task,
                    "case_id": case_id,
                    "errors": [f"parse_status={record.get('parse_status')}"],
                }
            )
        public_case = read_json(
            dataset / "benchmark_case" / task / "cases" / (
                "case_000001.json"
                if "netrail" in case_id
                else "case_000002.json"
            )
        )
        public_llm = read_json(
            dataset / "evaluation_case" / task / "llm" / (
                "case_000001.json"
                if "netrail" in case_id
                else "case_000002.json"
            )
        )
        public_case_count += 1
        public_case_seen.add(case_id)
        if record["reference_decision"] == public_case["reference"]["decision"]:
            parity_pass += 1
        if set(public_llm) == {"case_id", "prompt"} and "reference" not in walk_keys(
            public_llm
        ):
            public_llm_shape_pass += 1
        if (
            public_llm.get("case_id") == public_case.get("case_id")
            and public_llm.get("prompt") == public_case.get("llm_prompt")
        ):
            public_llm_prompt_parity_pass += 1
        if "reference" in walk_keys(parsed) or "truth" in walk_keys(parsed):
            key_leak_hits.append(
                {
                    "model": record["model"],
                    "task": task,
                    "case_id": case_id,
                    "keys": sorted(walk_keys(parsed) & {"reference", "truth"}),
                }
            )
    archive_sha = manifest["dataset"]["archive_sha256"]
    archive_path = Path(manifest["dataset"]["archive"])
    archive_crc = None
    archive_members = None
    if archive_path.is_file():
        with zipfile.ZipFile(archive_path) as archive:
            archive_crc = "PASS" if archive.testzip() is None else "FAIL"
            archive_members = len(archive.namelist())
    result = {
        "trial_records": len(records),
        "expected_trial_records": 20,
        "api_all_success": all(record.get("api_ok") for record in records),
        "api_statuses": sorted(set(api_statuses)),
        "strict_json_parse_count": sum(
            record.get("parse_status") == "STRICT_JSON" for record in records
        ),
        "independent_output_schema_valid_count": schema_valid,
        "raw_api_json_count": raw_json_valid,
        "provider_usage_present_count": usage_present,
        "official_validator_pass_count": official_valid,
        "public_case_parity_count": parity_pass,
        "public_case_count": public_case_count,
        "public_case_unique_count": len(public_case_seen),
        "public_llm_shape_pass_count": public_llm_shape_pass,
        "public_llm_prompt_parity_pass_count": public_llm_prompt_parity_pass,
        "response_format_config": config.get("response_format"),
        "enable_thinking": config.get("enable_thinking"),
        "dataset_archive_sha256": archive_sha,
        "dataset_archive_recomputed_sha256": (
            sha256_file(archive_path) if archive_path.is_file() else None
        ),
        "dataset_archive_sha256_match": (
            archive_path.is_file() and sha256_file(archive_path) == archive_sha
        ),
        "dataset_archive_crc": archive_crc,
        "dataset_archive_member_count": archive_members,
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "mean": statistics.mean(latencies) if latencies else None,
        },
        "format_failures": format_failures,
        "official_validator_failures": official_failures,
        "response_key_leak_hits": key_leak_hits,
        "environment_api_key_saved": False,
        "api_key_value_in_trial_files": (
            bool(os.environ.get("SILICONFLOW_API_KEY"))
            and any(
                os.environ["SILICONFLOW_API_KEY"] in path.read_text(
                    encoding="utf-8", errors="ignore"
                )
                for path in trial.rglob("*")
                if path.is_file() and path.name != "SHA256SUMS.txt"
            )
        ),
        "status": "PENDING",
    }
    # Keep the final status independent of the assignment-expression readability
    # in the conditional above.
    result["status"] = (
        "PASS"
        if result["trial_records"] == 20
        and result["api_all_success"]
        and result["strict_json_parse_count"] == 20
        and result["independent_output_schema_valid_count"] == 20
        and result["raw_api_json_count"] == 20
        and result["provider_usage_present_count"] == 20
        and result["public_case_parity_count"] == 20
        and result["public_llm_shape_pass_count"] == 20
        and result["public_llm_prompt_parity_pass_count"] == 20
        and result["dataset_archive_sha256_match"]
        and result["dataset_archive_crc"] == "PASS"
        and not result["response_key_leak_hits"]
        and not result["api_key_value_in_trial_files"]
        else "NOT_PASS"
    )
    write_json(trial / "INDEPENDENT_VERIFICATION.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--producer", required=True)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
