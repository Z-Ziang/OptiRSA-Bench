from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


def test_run_python_child_is_a_real_separate_process(tmp_path):
    from src.five_task_orchestrator import run_python_child

    script = tmp_path / "child.py"
    output = tmp_path / "pid.json"
    script.write_text(
        "import json,os,sys; json.dump({'pid':os.getpid()}, open(sys.argv[1],'w'))",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    run_python_child([sys.executable, str(script), str(output)], report)
    assert json.loads(output.read_text())["pid"] != os.getpid()
    saved = json.loads(report.read_text())
    assert saved["returncode"] == 0
    assert saved["command"][0] == sys.executable


def test_run_python_child_fails_closed_and_writes_report(tmp_path):
    from src.five_task_orchestrator import run_python_child

    script = tmp_path / "fail.py"
    script.write_text("import sys; print('boom'); print('bad', file=sys.stderr); raise SystemExit(7)", encoding="utf-8")
    report = tmp_path / "report.json"
    with pytest.raises(RuntimeError, match="exit code 7"):
        run_python_child([sys.executable, str(script)], report)
    saved = json.loads(report.read_text())
    assert saved["returncode"] == 7
    assert "boom" in saved["stdout"]
    assert "bad" in saved["stderr"]


def test_merge_family_outputs_creates_one_five_task_tree(tmp_path):
    from src.five_task_orchestrator import merge_family_outputs

    o = tmp_path / "o"
    x = tmp_path / "x"
    out = tmp_path / "merged"
    for family, tasks in ((o, ("O1", "O2-S", "O2-C")), (x, ("X2", "X3"))):
        rows = []
        for task in tasks:
            (family / "benchmark_case" / task).mkdir(parents=True)
            (family / "evaluation_case" / task).mkdir(parents=True)
            (family / "internal" / "contracts" / task).mkdir(parents=True)
            (family / "internal" / "cases" / task / f"{task}_T").mkdir(parents=True)
            (family / "internal" / "private" / task / f"{task}_T").mkdir(parents=True)
            (family / "benchmark_case" / task / "marker.txt").write_text(task)
            rows.append({"case_id": f"{task}_T", "task_type": task})
        (family / "case_index.jsonl").write_text("".join(json.dumps(r)+"\n" for r in rows))
        (family / "production_summary.json").write_text(json.dumps({"task_counts": {t: 1 for t in tasks}}))
    summary = merge_family_outputs(o, x, out, environment_root="/tmp/env")
    assert summary["task_counts"] == {"O1": 1, "O2-S": 1, "O2-C": 1, "X2": 1, "X3": 1}
    assert summary["total_case_count"] == 5
    for task in ("O1", "O2-S", "O2-C", "X2", "X3"):
        assert (out / "benchmark_case" / task / "marker.txt").is_file()
    rows = [json.loads(line) for line in (out / "case_index.jsonl").read_text().splitlines()]
    assert [r["task_type"] for r in rows] == ["O1", "O2-C", "O2-S", "X2", "X3"]
    assert (out / "RUN_MANIFEST.json").is_file()
    assert (out / "SHA256SUMS.txt").is_file()
