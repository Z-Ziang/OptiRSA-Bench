"""Independent verifier for an I1 V2.1.3 pre-production directory."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from jsonschema import Draft202012Validator

from src.i1.production import normalized_prompt, validate_one_prompt_per_truth


TASKS = ("I1-S", "I1-C", "I1-D")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_error(schema_path: Path, value: dict) -> str | None:
    schema = _read_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    return errors[0].message if errors else None


def verify_preproduction_dataset(
    dataset_root: Path | str,
    *,
    expected_counts: dict[str, int] | None = None,
    contracts_root: Path | str | None = None,
) -> dict:
    root = Path(dataset_root).resolve()
    errors: list[str] = []
    expected_counts = expected_counts or {"I1-S": 90, "I1-C": 100, "I1-D": 20}
    if not root.is_dir():
        return {"valid": False, "errors": [f"dataset not found: {root}"]}

    index = root / "preproduction_dataset" / "case_index.jsonl"
    if not index.is_file():
        return {"valid": False, "errors": ["missing preproduction_dataset/case_index.jsonl"]}
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen_case_ids: set[str] = set()
    prompts: list[str] = []
    prompt_rows: list[dict] = []
    counts: Counter[str] = Counter()
    if contracts_root is not None:
        contract_root = Path(contracts_root).resolve()
    else:
        environment_path = root / "ENVIRONMENT.json"
        environment = _read_json(environment_path) if environment_path.is_file() else {}
        source_root = environment.get("source_root")
        contract_root = Path(source_root).resolve() / "contracts" if source_root else root / "contracts"
        if not contract_root.is_dir():
            contract_root = root.parent.parent / "contracts"
    for row in rows:
        case_id = row.get("case_id")
        task = row.get("task_type")
        if not isinstance(case_id, str) or task not in TASKS:
            errors.append(f"invalid index row: {case_id}/{task}")
            continue
        if case_id in seen_case_ids:
            errors.append(f"duplicate case_id: {case_id}")
        seen_case_ids.add(case_id)
        counts[task] += 1
        try:
            benchmark = _read_json(root / row["benchmark_case_path"])
            evaluation = _read_json(root / row["evaluation_case_path"])
            truth = _read_json(root / row["canonical_truth_path"])
            record = _read_json(root / row["production_record_path"])
            validation = _read_json(root / "rewrite_validation" / f"{case_id}.json")
            if set(benchmark) != {"case_id", "prompt", "answer"}:
                errors.append(f"{case_id}: benchmark shape")
            if set(evaluation) != {"case_id", "prompt"}:
                errors.append(f"{case_id}: evaluation shape")
            if any(key in evaluation for key in ("answer", "truth", "difficulty", "canonical_answer")):
                errors.append(f"{case_id}: evaluation leakage")
            if benchmark["case_id"] != case_id or evaluation["case_id"] != case_id:
                errors.append(f"{case_id}: case_id mismatch")
            if evaluation["prompt"] != benchmark["prompt"]:
                errors.append(f"{case_id}: evaluation prompt mismatch")
            if truth["canonical_answer"] != benchmark["answer"]:
                errors.append(f"{case_id}: Truth/public answer mismatch")
            if record["final_prompt"] != benchmark["prompt"]:
                errors.append(f"{case_id}: lineage final prompt mismatch")
            if record["canonical_answer"] != truth["canonical_answer"]:
                errors.append(f"{case_id}: lineage answer mismatch")
            if record["lineage"].get("one_truth_one_prompt") is not True:
                errors.append(f"{case_id}: one_truth_one_prompt lineage missing")
            if validation.get("overall") != "PASS" or validation.get("final_validation", {}).get("overall") != "PASS":
                errors.append(f"{case_id}: rewrite validation not PASS")
            for schema_name, value in (
                ("benchmark_case.schema.json", benchmark),
                ("evaluation_case.schema.json", evaluation),
            ):
                schema_path = contract_root / task / "schemas" / schema_name
                if schema_path.is_file():
                    error = _schema_error(schema_path, value)
                    if error:
                        errors.append(f"{case_id}: {schema_name}: {error}")
            answer_schema = contract_root / task / "output_schema.json"
            if answer_schema.is_file():
                error = _schema_error(answer_schema, benchmark["answer"])
                if error:
                    errors.append(f"{case_id}: output schema: {error}")
            prompts.append(benchmark["prompt"])
            prompt_rows.append({"truth_id": truth.get("truth_id", case_id), "final_prompt": benchmark["prompt"]})
        except Exception as exc:
            errors.append(f"{case_id}: {type(exc).__name__}: {exc}")

    try:
        validate_one_prompt_per_truth(
            prompt_rows
        )
    except Exception as exc:
        errors.append(f"one truth/one prompt: {type(exc).__name__}: {exc}")
    normalized_duplicate_count = len(prompts) - len({normalized_prompt(prompt) for prompt in prompts})
    if normalized_duplicate_count:
        errors.append(f"normalized prompt duplicates: {normalized_duplicate_count}")
    if dict(counts) != expected_counts:
        errors.append(f"case counts differ: expected {expected_counts}, got {dict(counts)}")

    sums = root / "SHA256SUMS.txt"
    sum_count = 0
    if not sums.is_file():
        errors.append("missing SHA256SUMS.txt")
    else:
        for line in sums.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            sum_count += 1
            try:
                expected, relative = line.split("  ", 1)
                path = root / relative
                if not path.is_file() or _sha256(path) != expected:
                    errors.append(f"SHA256 mismatch: {relative}")
            except Exception as exc:
                errors.append(f"invalid checksum line: {type(exc).__name__}")

    manifest_path = root / "MANIFEST.json"
    manifest_count = 0
    if not manifest_path.is_file():
        errors.append("missing MANIFEST.json")
    else:
        manifest = _read_json(manifest_path)
        manifest_count = len(manifest.get("files", []))
        if manifest_count != manifest.get("file_count_excluding_manifest_and_sums"):
            errors.append("manifest file count mismatch")
        for item in manifest.get("files", []):
            path = root / item["path"]
            if not path.is_file() or _sha256(path) != item["sha256"] or path.stat().st_size != item["size_bytes"]:
                errors.append(f"manifest mismatch: {item.get('path')}")

    secret_hits = 0
    secret = os.environ.get("SILICONFLOW_API_KEY")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"Authorization:" in data or b"Bearer " in data or b"SILICONFLOW_API_KEY=" in data:
            secret_hits += 1
        if secret and secret.encode("utf-8") in data:
            secret_hits += 1
    if secret_hits:
        errors.append(f"secret scan hits: {secret_hits}")
    return {
        "valid": not errors,
        "case_count": len(rows),
        "counts": dict(counts),
        "normalized_duplicate_count": normalized_duplicate_count,
        "manifest_file_count": manifest_count,
        "sha_line_count": sum_count,
        "secret_hit_count": secret_hits,
        "errors": errors,
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="verify I1 V2.1.3 preproduction dataset")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--contracts-root")
    args = parser.parse_args(argv)
    result = verify_preproduction_dataset(args.dataset, contracts_root=args.contracts_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
