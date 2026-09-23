"""Prepare a private, runner-readable view from a unified public dataset.

The unified public package intentionally omits root_case and actual request
files.  This adapter joins it with the matching internal evidence package,
checks that the public reference agrees with the private canonical answer, and
copies only the files needed by the evaluation runner.  It never sends the
private files to a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


TASKS = ("G1", "G2", "G3", "X1")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_unified_dataset(public_dataset: str | Path, internal_evidence: str | Path, output: str | Path) -> dict[str, Any]:
    public = Path(public_dataset).resolve()
    evidence = Path(internal_evidence).resolve()
    target = Path(output).resolve()
    rows: list[dict[str, Any]] = []
    for task in TASKS:
        public_cases = public / "benchmark_case" / task / "cases"
        evidence_task = evidence / task
        if not public_cases.is_dir() or not evidence_task.is_dir():
            raise FileNotFoundError(f"missing public/evidence task directory for {task}")
        for public_path in sorted(public_cases.glob("*.json")):
            public_case = _read_json(public_path)
            case_id = str(public_case.get("case_id") or "")
            if not case_id:
                raise ValueError(f"public case has no case_id: {public_path}")
            evidence_case = evidence_task / case_id
            root_path = evidence_case / "root_case.json"
            llm_path = evidence_case / "actual_llm_request.json"
            if not all(path.is_file() for path in (root_path, llm_path)):
                raise FileNotFoundError(f"incomplete internal evidence for {case_id}")
            root = _read_json(root_path)
            if root.get("case_id") != case_id or root.get("task_type") != task:
                raise ValueError(f"evidence identity mismatch for {case_id}")
            if public_case.get("reference") != root.get("answer"):
                raise ValueError(f"public reference differs from canonical answer for {case_id}")
            destination = target / "cases" / task / case_id
            destination.mkdir(parents=True, exist_ok=True)
            for source in (root_path, llm_path):
                shutil.copy2(source, destination / source.name)
            rows.append({
                "task": task,
                "case_id": case_id,
                "public_case": str(public_path),
                "public_case_sha256": _sha256(public_path),
                "root_case_sha256": _sha256(root_path),
                "actual_llm_request_sha256": _sha256(llm_path),
            })
    manifest = {
        "adapter": "prepare_unified_dataset.py",
        "public_dataset": str(public),
        "internal_evidence": str(evidence),
        "case_count": len(rows),
        "task_counts": {task: sum(row["task"] == task for row in rows) for task in TASKS},
        "rows": rows,
        "private_evidence_note": "root_case is used only by the local canonical Validator; actual model requests are assembled from actual_llm_request.json and boundary-scanned before sending.",
    }
    _write_json(target / "adapter_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Join unified public cases with matching private evidence for local evaluation")
    parser.add_argument("--public-dataset", required=True)
    parser.add_argument("--internal-evidence", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = prepare_unified_dataset(args.public_dataset, args.internal_evidence, args.output)
    print(json.dumps({"status": "PASS", "output": str(Path(args.output).resolve()), "case_count": result["case_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
