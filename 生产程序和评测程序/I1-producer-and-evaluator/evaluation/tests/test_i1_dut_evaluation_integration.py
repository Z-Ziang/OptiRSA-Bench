from __future__ import annotations

import json
from pathlib import Path


def _i1_dataset(tmp_path: Path):
    root = tmp_path / "dataset"
    cid = "I1_S_TEST"
    internal = root / "internal/cases/I1-S" / cid
    internal.mkdir(parents=True)
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 1,
        "destination_node_id": 6,
        "required_slots": 9,
        "objectives": ["MIN-FRAGMENTATION"],
    }
    (internal / "canonical_answer.json").write_text(
        json.dumps(answer, ensure_ascii=False), encoding="utf-8"
    )
    row = {
        "case_id": cid,
        "task_type": "I1-S",
        "internal_case_dir": f"internal/cases/I1-S/{cid}",
    }
    (root / "case_index.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return root, cid, answer


def test_unified_dut_evaluator_supports_i1_strict_json(tmp_path):
    from src.case_core.dut_evaluation import validate_dut_response

    root, cid, answer = _i1_dataset(tmp_path)
    response = tmp_path / "response.txt"
    response.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    result = validate_dut_response(root, "I1-S", cid, response)
    assert result["valid"] is True
    assert result["metrics"]["raw_format_compliance"] == 1
    assert result["metrics"]["semantic_intent_accuracy"] == 1
    assert result["metrics"]["final_case_accuracy"] == 1


def test_unified_dut_evaluator_reports_fenced_json_as_format_only_failure(tmp_path):
    from src.case_core.dut_evaluation import validate_dut_response

    root, cid, answer = _i1_dataset(tmp_path)
    response = tmp_path / "response.txt"
    response.write_text(
        "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```",
        encoding="utf-8",
    )
    result = validate_dut_response(root, "I1-S", cid, response)
    assert result["valid"] is False
    assert result["metrics"]["raw_format_compliance"] == 0
    assert result["metrics"]["semantic_intent_accuracy"] == 1
    assert result["metrics"]["final_case_accuracy"] == 0
