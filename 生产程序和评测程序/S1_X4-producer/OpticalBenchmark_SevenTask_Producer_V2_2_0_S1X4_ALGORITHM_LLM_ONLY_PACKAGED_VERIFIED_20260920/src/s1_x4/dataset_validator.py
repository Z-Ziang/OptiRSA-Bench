from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .algorithm_api.resolver import audit_public_launcher, resolve_algorithm_launcher


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_check(schema_path: Path, obj: dict) -> None:
    schema = _read(schema_path)
    errors = list(Draft202012Validator(schema).iter_errors(obj))
    if errors:
        raise ValueError(errors[0].message)


def _check_algorithm_public_view(algorithm: dict, root_case: dict, task: str) -> None:
    audit = audit_public_launcher(algorithm)
    if audit["forbidden_key_hits"] or audit["forbidden_value_hits"]:
        raise ValueError(f"algorithm public leakage: {audit}")
    text = json.dumps(algorithm, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "request_events",
        "initial_existing_connections",
        "active_connection",
        "release_time",
        "remaining_holding_time",
        "released_connection",
        "difficulty_context",
        "reference",
        "private_truth",
    )
    leaked = [token for token in forbidden if token in text]
    if leaked:
        raise ValueError(f"algorithm public leakage: {leaked}")
    for future in [x["request_id"] for x in root_case.get("request_events", [])[1:]]:
        if future in text:
            raise ValueError(f"algorithm future request leakage: {future}")
    if task == "X4":
        x4_forbidden = (
            "candidate_paths",
            "candidate_actions",
            "feasible_paths",
            "feasible_actions",
            "path_rank",
            "recommended_action",
        )
        leaked = [token for token in x4_forbidden if token in text]
        if leaked:
            raise ValueError(f"algorithm X4 candidate oracle leakage: {leaked}")
    if algorithm.get("case_id") != root_case.get("case_id") or algorithm.get("task_type") != task:
        raise ValueError("algorithm launcher identity mismatch")
    if algorithm.get("static_context", {}).get("case_id") != root_case.get("case_id"):
        raise ValueError("algorithm static context identity mismatch")


def verify_s1x4_dataset(dataset_root: Path | str) -> dict:
    root = Path(dataset_root).resolve()
    errors = []
    count = 0
    algorithm_pass = 0
    if not root.is_dir():
        return {"valid": False, "case_count": 0, "errors": [f"dataset not found: {root}"]}
    index_path = root / "case_index.jsonl"
    rows = (
        [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if index_path.is_file()
        else []
    )
    if not index_path.is_file():
        errors.append("missing case_index.jsonl")
    for row in rows:
        if row.get("task_type") not in {"S1", "X4"}:
            continue
        count += 1
        task = row["task_type"]
        case_id = row["case_id"]
        try:
            benchmark = _read(root / row["benchmark_case_path"])
            llm = _read(root / row["llm_evaluation_path"])
            algorithm_path_value = row.get("algorithm_evaluation_path")
            if not algorithm_path_value:
                raise ValueError("missing algorithm_evaluation_path")
            algorithm_path = root / algorithm_path_value
            algorithm = _read(algorithm_path)
            root_case_path = root / row["internal_case_dir"] / "root_case.json"
            root_case = _read(root_case_path)
            if set(benchmark) != {"case_id", "llm_prompt", "reference"}:
                raise ValueError("benchmark_case fields")
            if set(llm) != {"case_id", "prompt"}:
                raise ValueError("evaluation case must contain id + prompt only")
            if not all(item["case_id"] == case_id for item in (benchmark, llm, root_case)):
                raise ValueError("case_id mismatch")
            _check_algorithm_public_view(algorithm, root_case, task)
            _schema_check(
                root / "internal/contracts" / task / "schemas" / "algorithm_evaluation_case.schema.json",
                algorithm,
            )
            resolved = resolve_algorithm_launcher(algorithm_path, root, expected_task=task)
            if resolved.root_case_path != root_case_path.resolve():
                raise ValueError("opaque registry root path mismatch")
            algorithm_pass += 1
            if benchmark["llm_prompt"] != llm["prompt"]:
                raise ValueError("benchmark/evaluation prompt mismatch")
            if len(root_case["request_events"]) != root_case["episode_length"]:
                raise ValueError("episode length mismatch")
            future_ids = [event["request_id"] for event in root_case["request_events"][1:]]
            visible = benchmark["llm_prompt"] + llm["prompt"]
            if any(value in visible for value in future_ids):
                raise ValueError("future request leakage")
            private_dynamic = (
                "release_time",
                "remaining_holding_time",
                "initial_existing_connections",
                "request_events",
            )
            if any(value in visible for value in private_dynamic):
                raise ValueError("private dynamic state leakage")
            if task == "X4" and ("候选路径" in visible or "path_rank" in visible):
                raise ValueError("X4 candidate-path leakage")
        except Exception as exc:
            errors.append(f"{task}/{case_id}: {type(exc).__name__}: {exc}")
    hash_manifest = root / "SHA256SUMS.txt"
    if not hash_manifest.is_file():
        errors.append("missing SHA256SUMS.txt")
    else:
        for line in hash_manifest.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            expected, relative = line.split("  ", 1)
            path = root / relative
            if not path.is_file() or _sha(path) != expected:
                errors.append(f"SHA256 mismatch: {relative}")
    return {
        "valid": not errors,
        "case_count": count,
        "algorithm_view_pass_count": algorithm_pass,
        "errors": errors,
    }
