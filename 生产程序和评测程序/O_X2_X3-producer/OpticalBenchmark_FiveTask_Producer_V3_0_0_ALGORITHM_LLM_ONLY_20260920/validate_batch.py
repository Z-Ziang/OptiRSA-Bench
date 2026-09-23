#!/usr/bin/env python3
"""Independently re-check released production units without regenerating them."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.multi_topology.reporting import write_json
from src.multi_topology.validation import validate_multi_environment
from scripts.validate_schemas import run_manifest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sha_file(unit: Path) -> dict:
    sha_file = unit / "SHA256SUMS.txt"
    errors = []
    for line in sha_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = unit / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
        elif _sha(path) != expected:
            errors.append(f"sha256 mismatch: {relative}")
    return {"pass": not errors, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    root = args.batch_output.resolve()
    project_root = Path(__file__).resolve().parent
    records = []
    for unit in sorted((root / "units").glob("*")):
        if not unit.is_dir():
            continue
        sha = verify_sha_file(unit)
        schema = run_manifest(project_root / "schemas/schema_manifest.json", unit / "public_environment")
        cross = validate_multi_environment(unit / "public_environment")
        records.append({
            "topology_id": unit.name,
            "sha256_pass": sha["pass"],
            "schema_pass": schema["summary"]["invalid"] == 0,
            "cross_file_pass": cross["pass"],
            "state_reconstruction_pass": cross["state_reconstruction_pass"],
            "dynamic_replay_pass": cross["dynamic_replay_pass"],
            "sha256_errors": sha["errors"],
            "cross_file_errors": cross["errors"],
        })
    report = {"pass": bool(records) and all(all(item[key] for key in (
        "sha256_pass", "schema_pass", "cross_file_pass", "state_reconstruction_pass", "dynamic_replay_pass"
    )) for item in records), "unit_count": len(records), "units": records}
    report_path = args.report or (root / "reports/INDEPENDENT_REVALIDATION.json")
    write_json(report_path, report)
    print(report_path)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
