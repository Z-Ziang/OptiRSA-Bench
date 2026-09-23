"""Batch orchestration for repeated one-topology production.

Each topology is produced in an isolated staging directory.  A unit is moved
into ``units/<topology_id>`` only after all mandatory gates pass.  Failed units
are retained under ``failed/`` for diagnosis, so batch continuation never hides
partial or invalid output among released units.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter

from src.multi_topology.reporting import write_json
from src.multi_topology.simulation import LoadSearchProtocol
from src.production.config import ProductionConfig
from src.production.one_topology import ProductionUnitError, run_one_topology


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_hashes(root: Path) -> None:
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        lines.append(f"{_hash(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _can_resume(unit_dir: Path, config: ProductionConfig, source_path: Path) -> bool:
    acceptance_path = unit_dir / "reports/UNIT_ACCEPTANCE.json"
    if not acceptance_path.is_file():
        return False
    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        acceptance.get("status") == "PASS"
        and acceptance.get("config_sha256") == config.config_sha256
        and acceptance.get("source_sha256") == _hash(source_path)
    )


def run_batch(
    config: ProductionConfig,
    output_root: Path | str,
    *,
    protocol: LoadSearchProtocol | None = None,
) -> dict:
    """Run the same single-topology production program over all registered inputs."""
    started = perf_counter()
    output_root = Path(output_root).resolve()
    units_dir = output_root / "units"
    staging_dir = output_root / "_staging"
    failed_dir = output_root / "failed"
    reports_dir = output_root / "reports"
    for directory in (units_dir, staging_dir, failed_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    unit_records: list[dict] = []
    for spec in config.topologies:
        final_dir = units_dir / spec.topology_id
        if config.execution.resume and _can_resume(final_dir, config, spec.source_path):
            acceptance = json.loads((final_dir / "reports/UNIT_ACCEPTANCE.json").read_text(encoding="utf-8"))
            unit_records.append({"topology_id": spec.topology_id, "status": "PASS", "action": "RESUMED", "acceptance": acceptance})
            continue

        stage = staging_dir / spec.topology_id
        if stage.exists():
            shutil.rmtree(stage)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        try:
            acceptance = run_one_topology(config, spec, stage, protocol=protocol)
            stage.replace(final_dir)
            unit_records.append({"topology_id": spec.topology_id, "status": "PASS", "action": "PRODUCED", "acceptance": acceptance})
        except Exception as exc:  # Preserve exact failed evidence and continue only if configured.
            failure_target = failed_dir / spec.topology_id
            if failure_target.exists():
                shutil.rmtree(failure_target)
            if stage.exists():
                stage.replace(failure_target)
            record = {
                "topology_id": spec.topology_id,
                "status": "BLOCKED",
                "action": "FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failed_output": str(failure_target),
            }
            unit_records.append(record)
            if not config.execution.continue_on_failure:
                break

    passed = sum(record["status"] == "PASS" for record in unit_records)
    failed = sum(record["status"] != "PASS" for record in unit_records)
    attempted = len(unit_records)
    status = "PASS" if failed == 0 and attempted == len(config.topologies) else "BLOCKED"
    acceptance = {
        "schema_version": "PUBLIC_ENV_BATCH_ACCEPTANCE_V1_0",
        "status": status,
        "batch_id": config.batch_id,
        "config_path": str(config.source_config_path),
        "config_sha256": config.config_sha256,
        "topology_count_requested": len(config.topologies),
        "topology_count_attempted": attempted,
        "passed_topology_count": passed,
        "failed_topology_count": failed,
        "runtime_seconds": perf_counter() - started,
        "units": unit_records,
    }
    write_json(reports_dir / "BATCH_ACCEPTANCE.json", acceptance)
    write_json(output_root / "BATCH_MANIFEST.json", {
        "batch_id": config.batch_id,
        "released_units": [record["topology_id"] for record in unit_records if record["status"] == "PASS"],
        "blocked_units": [record["topology_id"] for record in unit_records if record["status"] != "PASS"],
    })
    _write_hashes(output_root)
    return acceptance
