from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

_TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_python_child(command: list[str], report_path: str | Path, *, cwd: str | Path | None = None) -> dict:
    report_path = Path(report_path)
    result = subprocess.run(
        [str(x) for x in command],
        cwd=None if cwd is None else str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = {
        "command": [str(x) for x in command],
        "returncode": int(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    _write_json(report_path, report)
    if result.returncode != 0:
        raise RuntimeError(f"child process failed with exit code {result.returncode}; report={report_path}")
    return report


def _copy_tree_contents(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda p: p.name):
        target = destination / item.name
        if item.is_dir():
            if target.exists():
                _copy_tree_contents(item, target)
            else:
                shutil.copytree(item, target)
        else:
            if target.exists() and target.read_bytes() != item.read_bytes():
                raise ValueError(f"merge collision with different bytes: {target}")
            shutil.copy2(item, target)


def _read_index(root: Path) -> list[dict]:
    path = root / "case_index.jsonl"
    if not path.is_file():
        raise ValueError(f"missing family case_index.jsonl: {root}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_summary(root: Path) -> dict:
    path = root / "production_summary.json"
    if not path.is_file():
        raise ValueError(f"missing family production_summary.json: {root}")
    return json.loads(path.read_text(encoding="utf-8"))


def _finalize_hashes(root: Path) -> None:
    for stale in (root / "RUN_MANIFEST.json", root / "SHA256SUMS.txt"):
        stale.unlink(missing_ok=True)
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name not in {"RUN_MANIFEST.json", "SHA256SUMS.txt"}):
        files.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    _write_json(root / "RUN_MANIFEST.json", {
        "schema_version": "FIVE_TASK_RUN_MANIFEST_V2_0",
        "file_count": len(files),
        "files": files,
    })
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in paths),
        encoding="utf-8",
    )


def merge_family_outputs(o_family_root: str | Path, x2x3_root: str | Path, output_root: str | Path, *, environment_root: str | Path) -> dict:
    o_root = Path(o_family_root).resolve()
    x_root = Path(x2x3_root).resolve()
    out = Path(output_root).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for family_root in (o_root, x_root):
        for rel in ("benchmark_case", "evaluation_case", "internal"):
            _copy_tree_contents(family_root / rel, out / rel)

    rows = _read_index(o_root) + _read_index(x_root)
    rows.sort(key=lambda row: (str(row["task_type"]), str(row["case_id"])))
    (out / "case_index.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    o_summary = _read_summary(o_root)
    x_summary = _read_summary(x_root)
    task_counts = {task: 0 for task in _TASKS}
    for family_summary in (o_summary, x_summary):
        for task, count in family_summary.get("task_counts", {}).items():
            if task in task_counts:
                task_counts[task] = int(count)
    summary = {
        "schema_version": "FIVE_TASK_PRODUCTION_SUMMARY_V2_0",
        "status": "PASS",
        "environment_root": str(Path(environment_root).resolve()),
        "task_counts": task_counts,
        "total_case_count": sum(task_counts.values()),
        "benchmark_interface": "NATURAL_LANGUAGE_DUAL_ENDPOINT_V2_0",
        "family_summaries": {"O_FAMILY": o_summary, "X2X3": x_summary},
    }
    _write_json(out / "production_summary.json", summary)

    reports = out / "reports" / "family"
    reports.mkdir(parents=True, exist_ok=True)
    for label, family_root in (("O_FAMILY", o_root), ("X2X3", x_root)):
        for name in ("production_summary.json", "RUN_MANIFEST.json", "SHA256SUMS.txt"):
            src = family_root / name
            if src.is_file():
                shutil.copy2(src, reports / f"{label}_{name}")
        family_reports = family_root / "reports"
        if family_reports.is_dir():
            _copy_tree_contents(family_reports, reports / label)
    _finalize_hashes(out)
    return summary


def derive_five_task_dataset(environment_root: str | Path, o_config: str | Path, x_config: str | Path, output_root: str | Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    out = Path(output_root).resolve()
    work = out.with_name(out.name + ".family_work")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        o_out = work / "O_FAMILY"
        x_out = work / "X2X3"
        reports = work / "process_reports"
        run_python_child([
            sys.executable, str(root / "benchmark.py"), "derive-cases",
            "--environment", str(Path(environment_root).resolve()),
            "--config", str(Path(o_config).resolve()),
            "--output", str(o_out),
        ], reports / "O_FAMILY.json", cwd=root)
        run_python_child([
            sys.executable, str(root / "benchmark_x2x3.py"), "derive-cases",
            "--environment", str(Path(environment_root).resolve()),
            "--config", str(Path(x_config).resolve()),
            "--output", str(x_out),
        ], reports / "X2X3.json", cwd=root)
        summary = merge_family_outputs(o_out, x_out, out, environment_root=environment_root)
        _copy_tree_contents(reports, out / "reports" / "process")
        _finalize_hashes(out)
        return summary
    except Exception:
        if out.exists():
            shutil.rmtree(out)
        raise
    finally:
        if work.exists():
            shutil.rmtree(work)


def verify_five_task_dataset(dataset_root: str | Path) -> dict:
    from src.case_core.dataset_validator import verify_dataset as verify_o
    from src.x2x3_dataset_validator import verify_x2x3_dataset as verify_x

    o_result = verify_o(dataset_root)
    x_result = verify_x(dataset_root)
    return {
        "valid": bool(o_result.get("valid")) and bool(x_result.get("valid")),
        "total_case_count": int(o_result.get("case_count", 0)) + int(x_result.get("case_count", 0)),
        "reference_replay_pass_count": int(o_result.get("reference_replay_pass_count", 0)) + int(x_result.get("reference_replay_pass_count", 0)),
        "o_family": o_result,
        "x2x3": x_result,
    }


def produce_environment_and_five_tasks(environment_config: str | Path, o_config: str | Path, x_config: str | Path, output_root: str | Path) -> dict:
    from src.production.batch import run_batch
    from src.production.config import load_production_config

    out = Path(output_root).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    batch_root = out / "public_environment_batch"
    batch_result = run_batch(load_production_config(Path(environment_config).resolve()), batch_root)
    if batch_result.get("status") != "PASS":
        raise RuntimeError(f"public-environment batch did not PASS: {batch_result.get('status')}")
    datasets = {}
    for unit in sorted((batch_root / "units").iterdir()):
        if not unit.is_dir():
            continue
        ds = out / "datasets" / unit.name
        datasets[unit.name] = derive_five_task_dataset(unit / "public_environment", o_config, x_config, ds)
        verified = verify_five_task_dataset(ds)
        if not verified["valid"]:
            raise RuntimeError(f"global dataset verification failed for {unit.name}: {verified['o_family']['errors'] + verified['x2x3']['errors']}")
    result = {
        "status": "PASS",
        "public_environment_batch_id": batch_result.get("batch_id"),
        "topology_count": len(datasets),
        "datasets": datasets,
    }
    _write_json(out / "FIVE_TASK_PRODUCTION_RESULT.json", result)
    return result
