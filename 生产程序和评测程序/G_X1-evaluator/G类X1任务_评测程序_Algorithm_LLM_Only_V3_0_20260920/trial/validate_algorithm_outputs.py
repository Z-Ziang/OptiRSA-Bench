#!/usr/bin/env python3
"""Offline Algorithm-output evaluation with the producer's canonical Validator."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any


TASKS = ("G1", "G2", "G3", "X1")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case_dirs(dataset: Path):
    for task in TASKS:
        task_dir = dataset / "cases" / task
        if task_dir.exists():
            for case_dir in sorted(path for path in task_dir.iterdir() if path.is_dir()):
                yield task, case_dir


def _find_output(outputs: Path, task: str, case_id: str) -> Path | None:
    candidates = [
        outputs / task / f"{case_id}.json",
        outputs / task / f"{case_id}.txt",
        outputs / f"{case_id}.json",
        outputs / f"{case_id}.txt",
        outputs / task / case_id / "output.json",
        outputs / task / case_id / "model_output.txt",
    ]
    return next((path for path in candidates if path.is_file()), None)


def validate_algorithm_outputs(
    producer_dir: str | Path,
    dataset_dir: str | Path,
    outputs_dir: str | Path,
    results_dir: str | Path,
) -> dict[str, Any]:
    producer = Path(producer_dir).resolve()
    if str(producer) not in sys.path:
        sys.path.insert(0, str(producer))
    from gx1.validators import validate_dut_output

    dataset = Path(dataset_dir).resolve()
    outputs = Path(outputs_dir).resolve()
    results = Path(results_dir).resolve()
    rows: list[dict[str, Any]] = []
    for task, case_dir in _case_dirs(dataset):
        root = json.loads((case_dir / "root_case.json").read_text(encoding="utf-8"))
        case_id = root["case_id"]
        output_path = _find_output(outputs, task, case_id)
        if output_path is None:
            validation = {"valid": False, "reason": "MISSING_ALGORITHM_OUTPUT"}
            raw = None
            status = "MISSING_OUTPUT"
        else:
            raw = output_path.read_text(encoding="utf-8")
            try:
                validation = validate_dut_output(root, raw)
                status = "SUCCESS" if validation.get("valid") else "ALGORITHM_WRONG"
            except Exception as exc:
                validation = {"valid": False, "reason": "VALIDATOR_ERROR", "error": str(exc)}
                status = "PRODUCER_OR_VALIDATOR_ERROR"
        case_result = results / task / case_id
        case_result.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            (case_result / "algorithm_output.txt").write_text(raw, encoding="utf-8")
        _write_json(case_result / "validation_result.json", validation)
        record = {
            "task": task,
            "case_id": case_id,
            "output_path": str(output_path) if output_path else None,
            "status": status,
            "validator_pass": bool(validation.get("valid")),
            "validation_reason": validation.get("reason"),
        }
        _write_json(case_result / "evaluation_record.json", record)
        rows.append(record)

    completed = sum(row["output_path"] is not None for row in rows)
    passed = sum(row["validator_pass"] for row in rows)
    by_task = {
        task: {
            "case_count": sum(row["task"] == task for row in rows),
            "completed": sum(row["task"] == task and row["output_path"] is not None for row in rows),
            "validator_pass": sum(row["task"] == task and row["validator_pass"] for row in rows),
        }
        for task in TASKS
    }
    for task, item in by_task.items():
        item["accuracy"] = item["validator_pass"] / item["completed"] if item["completed"] else None
    summary = {
        "track": "algorithm",
        "case_count": len(rows),
        "completed": completed,
        "missing_output": len(rows) - completed,
        "validator_pass": passed,
        "validator_fail": completed - passed,
        "accuracy": passed / completed if completed else None,
        "by_task": by_task,
    }
    _write_json(results / "summary.json", summary)
    with (results / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task", "case_id", "output_path", "status", "validator_pass", "validation_reason"])
        writer.writeheader()
        writer.writerows(rows)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate G1/G2/G3/X1 Algorithm outputs offline")
    parser.add_argument("--producer-dir", required=True)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--outputs-dir", required=True)
    parser.add_argument("--results-dir", required=True)
    args = parser.parse_args(argv)
    summary = validate_algorithm_outputs(args.producer_dir, args.dataset_dir, args.outputs_dir, args.results_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["missing_output"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
