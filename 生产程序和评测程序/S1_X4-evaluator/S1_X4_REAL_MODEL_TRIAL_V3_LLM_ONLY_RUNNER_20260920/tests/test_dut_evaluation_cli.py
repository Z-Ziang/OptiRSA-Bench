from __future__ import annotations

import json
from pathlib import Path

from tests.o_family_test_utils import toy_env
from src.tasks.x2.producer import build_x2_case


def _dataset(tmp_path: Path):
    bundle = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_TEST", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    root = tmp_path / "dataset"
    cdir = root / "internal/cases/X2/X2_TEST"
    pdir = root / "internal/private/X2/X2_TEST"
    cdir.mkdir(parents=True)
    pdir.mkdir(parents=True)
    (cdir / "root_case.json").write_text(json.dumps(bundle["root_case"]), encoding="utf-8")
    (pdir / "private_truth.json").write_text(json.dumps(bundle["private_truth"]), encoding="utf-8")
    row = {
        "case_id": "X2_TEST",
        "task_type": "X2",
        "internal_case_dir": "internal/cases/X2/X2_TEST",
        "internal_private_dir": "internal/private/X2/X2_TEST",
    }
    (root / "case_index.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return root, bundle


def test_validate_dut_response_accepts_reference_and_returns_metrics(tmp_path):
    from src.case_core.dut_evaluation import validate_dut_response

    dataset, bundle = _dataset(tmp_path)
    response = tmp_path / "response.json"
    response.write_text(json.dumps(bundle["reference_output"]), encoding="utf-8")
    result = validate_dut_response(dataset, "X2", "X2_TEST", response)
    assert result["valid"] is True
    assert result["task_type"] == "X2"
    assert result["case_id"] == "X2_TEST"
    assert result["metrics"]["feasible_decision_accuracy"] == 1
    assert "private_truth" not in result


def test_validate_dut_response_rejects_malformed_output(tmp_path):
    from src.case_core.dut_evaluation import validate_dut_response

    dataset, _ = _dataset(tmp_path)
    response = tmp_path / "response.json"
    response.write_text('{"decision":"ACCEPT"}', encoding="utf-8")
    result = validate_dut_response(dataset, "X2", "X2_TEST", response)
    assert result["valid"] is False
    assert result["errors"]
