from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator
from src.i1.version import I1_PRODUCER_VERSION

TASKS = ("I1-S", "I1-C", "I1-D")


def _write_json(path: Path, obj, *, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(schema_path: Path, obj, label: str) -> None:
    schema = _read_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(obj), key=lambda error: list(error.path)
    )
    if errors:
        raise ValueError(f"{label} schema violation: {errors[0].message}")


def export_i1_base_dataset(
    output_root: Path | str,
    records_by_task: dict,
    *,
    contracts_root: Path | str,
    production_metadata: dict,
) -> dict:
    root = Path(output_root).resolve()
    contracts = Path(contracts_root).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    rows = []
    counts = {}
    for task in TASKS:
        records = records_by_task.get(task, [])
        counts[task] = len(records)
        if records:
            public_task = root / "base_case" / task
            public_task.mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                contracts / task / "llm_system_prompt.txt",
                public_task / "llm_system_prompt.txt",
            )
            shutil.copytree(contracts / task, root / "internal" / "contracts" / task)

        for ordinal, record in enumerate(records, 1):
            case_id = record["case_id"]
            answer = record["canonical_answer"]
            prompt = record["base_prompt"]
            base_case = {"case_id": case_id, "llm_prompt": prompt, "answer": answer}
            _validate(
                contracts / task / "schemas" / "benchmark_case.schema.json",
                base_case,
                f"{task}/{case_id}/base_case",
            )
            _validate(
                contracts / task / "output_schema.json",
                answer,
                f"{task}/{case_id}/answer",
            )

            name = f"case_{ordinal:06d}.json"
            public_path = root / "base_case" / task / "cases" / name
            _write_json(public_path, base_case)

            internal = root / "internal" / "cases" / task / case_id
            _write_json(internal / "canonical_answer.json", answer, sort_keys=True)
            (internal / "base_prompt.txt").parent.mkdir(parents=True, exist_ok=True)
            (internal / "base_prompt.txt").write_text(prompt + "\n", encoding="utf-8")
            _write_json(internal / "lineage.json", record["lineage"], sort_keys=True)

            rows.append(
                {
                    "case_id": case_id,
                    "task_type": task,
                    "source_ref": record["source_ref"],
                    "base_case_path": public_path.relative_to(root).as_posix(),
                    "internal_case_dir": internal.relative_to(root).as_posix(),
                }
            )

    rows.sort(key=lambda row: (row["task_type"], row["case_id"]))
    (root / "base_case_index.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "schema_version": "I1_BASE_PRODUCTION_SUMMARY_V2_1_3",
        "producer_version": I1_PRODUCER_VERSION,
        "stage": "BASE_TEMPLATE",
        "case_count": len(rows),
        "task_counts": counts,
        "production_metadata": production_metadata,
        "public_case_shape": ["case_id", "llm_prompt", "answer"],
    }
    _write_json(root / "base_production_summary.json", summary, sort_keys=True)

    files = []
    for path in sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.name not in {"BASE_RUN_MANIFEST.json", "SHA256SUMS.txt"}
    ):
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
        )
    _write_json(
        root / "BASE_RUN_MANIFEST.json",
        {
            "schema_version": "I1_BASE_RUN_MANIFEST_V2_1_3",
            "producer_version": I1_PRODUCER_VERSION,
            "file_count": len(files),
            "files": files,
        },
        sort_keys=True,
    )
    checksum_paths = sorted(
        p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"
    )
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(f"{_sha(path)}  {path.relative_to(root).as_posix()}" for path in checksum_paths)
        + "\n",
        encoding="utf-8",
    )
    return summary


def verify_i1_base_dataset(dataset_root: Path | str) -> dict:
    root = Path(dataset_root).resolve()
    errors = []
    seen = set()
    count = 0
    if not root.is_dir():
        return {"valid": False, "case_count": 0, "errors": [f"dataset not found: {root}"]}
    if (root / "benchmark_case").exists() or (root / "evaluation_case").exists():
        errors.append("base dataset must not contain final benchmark/evaluation views")

    index = root / "base_case_index.jsonl"
    if not index.is_file():
        return {"valid": False, "case_count": 0, "errors": ["missing base_case_index.jsonl"]}
    rows = [
        json.loads(line)
        for line in index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contracts = root / "internal" / "contracts"

    for task in TASKS:
        case_dir = root / "base_case" / task / "cases"
        if case_dir.is_dir() and any(case_dir.glob("*.json")):
            prompt_path = root / "base_case" / task / "llm_system_prompt.txt"
            if not prompt_path.is_file():
                errors.append(f"{task}: missing llm_system_prompt.txt copy")

    for row in rows:
        task = row.get("task_type")
        case_id = row.get("case_id")
        if task not in TASKS:
            errors.append(f"unknown task: {task}")
            continue
        count += 1
        if case_id in seen:
            errors.append(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        try:
            case = _read_json(root / row["base_case_path"])
            internal = root / row["internal_case_dir"]
            answer = _read_json(internal / "canonical_answer.json")
            base_prompt = (internal / "base_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
            lineage = _read_json(internal / "lineage.json")
            if set(case) != {"case_id", "llm_prompt", "answer"}:
                raise ValueError("base_case fields")
            if case["case_id"] != case_id:
                raise ValueError("case_id mismatch")
            if case["llm_prompt"] != base_prompt:
                raise ValueError("base prompt differs from internal base_prompt")
            if case["answer"] != answer:
                raise ValueError("base answer differs from canonical_answer")
            if lineage.get("canonical_answer_sha256") is None or lineage.get("base_prompt_sha256") is None:
                raise ValueError("incomplete base lineage")
            _validate(
                contracts / task / "schemas" / "benchmark_case.schema.json",
                case,
                f"{task}/{case_id}/base_case",
            )
            _validate(
                contracts / task / "output_schema.json",
                answer,
                f"{task}/{case_id}/answer",
            )
        except Exception as exc:
            errors.append(f"{task}/{case_id}: {type(exc).__name__}: {exc}")

    sums = root / "SHA256SUMS.txt"
    if not sums.is_file():
        errors.append("missing SHA256SUMS.txt")
    else:
        for line in sums.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            expected, rel = line.split("  ", 1)
            path = root / rel
            if not path.is_file() or _sha(path) != expected:
                errors.append(f"SHA256 mismatch: {rel}")

    return {"valid": not errors, "case_count": count, "errors": errors}
