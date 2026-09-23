import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from gx1.production import produce_batch
from gx1.unified_schema import (
    assemble_unified_request,
    build_benchmark_case,
    build_evaluation_case,
    export_unified,
    forbidden_field_hits,
    validate_public_case_schema,
    verify_unified_export,
)


TASKS = ["G1", "G2", "G3", "X1"]
FORBIDDEN = {"answer", "truth", "oracle", "private_truth", "reference"}


def _representative_source(project_root, tmp_path):
    source = tmp_path / "legacy_source"
    produce_batch(project_root / "configs" / "representative_four_cases.json", source)
    return source


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha_tree(root: Path):
    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _schema_validate(schema_path: Path, value):
    schema = _read_json(schema_path)
    jsonschema.Draft202012Validator(schema).validate(value)


def test_benchmark_projection_has_exactly_three_fields_and_rejects_private_fields(
    project_root, tmp_path
):
    source = _representative_source(project_root, tmp_path)
    root = _read_json(source / "cases" / "G1" / "G1_000001" / "root_case.json")

    public_case = build_benchmark_case(root)

    assert list(public_case) == ["case_id", "llm_prompt", "reference"]
    assert public_case["reference"] == root["answer"]
    assert validate_public_case_schema(public_case, "benchmark") == []

    for extra in [
        {"answer": root["answer"]},
        {"system_prompt": "private"},
        {"topology_metadata": {}},
    ]:
        invalid = {**public_case, **extra}
        assert validate_public_case_schema(invalid, "benchmark")


def test_evaluation_projection_has_exactly_two_fields_and_rejects_private_fields():
    evaluation_case = build_evaluation_case("G1_000001", "prompt")

    assert list(evaluation_case) == ["case_id", "prompt"]
    assert validate_public_case_schema(evaluation_case, "evaluation") == []
    for name in sorted(FORBIDDEN):
        invalid = {**evaluation_case, name: {}}
        assert validate_public_case_schema(invalid, "evaluation")


def test_export_is_deterministic_and_all_public_files_validate(project_root, tmp_path):
    source = _representative_source(project_root, tmp_path)
    output_a = tmp_path / "unified_a"
    output_b = tmp_path / "unified_b"

    result_a = export_unified(source, output_a)
    result_b = export_unified(source, output_b)

    assert result_a["valid"] is True
    assert result_b["valid"] is True
    assert _sha_tree(output_a) == _sha_tree(output_b)
    assert verify_unified_export(output_a)["valid"] is True

    for task in TASKS:
        schema_benchmark = output_a / "schemas" / "benchmark_case.schema.json"
        schema_evaluation = output_a / "schemas" / "evaluation_case.schema.json"
        for path in sorted((output_a / "benchmark_case" / task / "cases").glob("*.json")):
            case = _read_json(path)
            _schema_validate(schema_benchmark, case)
            assert list(case) == ["case_id", "llm_prompt", "reference"]
        for path in sorted((output_a / "evaluation_case" / task / "llm").glob("*.json")):
            case = _read_json(path)
            _schema_validate(schema_evaluation, case)
            assert list(case) == ["case_id", "prompt"]


def test_task_level_contracts_are_llm_only_and_keep_full_public_input(project_root, tmp_path):
    source = _representative_source(project_root, tmp_path)
    output = tmp_path / "unified"
    export_unified(source, output)

    for task in TASKS:
        task_dir = output / "benchmark_case" / task
        benchmark = _read_json(next((task_dir / "cases").glob("*.json")))
        llm_prompt = benchmark["llm_prompt"]
        assert (task_dir / "llm_system_prompt.txt").is_file()
        if task in {"G2", "G3", "X1"}:
            assert "当前有向链路" in llm_prompt


def test_evaluation_prompts_are_deterministic_projections_and_requests_have_no_private_keys(
    project_root, tmp_path
):
    source = _representative_source(project_root, tmp_path)
    output = tmp_path / "unified"
    export_unified(source, output)

    for task in TASKS:
        case_path = next((output / "benchmark_case" / task / "cases").glob("*.json"))
        benchmark = _read_json(case_path)
        case_id = benchmark["case_id"]
        llm_eval = _read_json(output / "evaluation_case" / task / "llm" / "case_000001.json")
        assert llm_eval == {"case_id": case_id, "prompt": benchmark["llm_prompt"]}
        request = assemble_unified_request(output, task, case_id)
        assert forbidden_field_hits(request) == []
        assert set(request) == {"case_id", "messages"}
        assert all(isinstance(message["content"], str) for message in request["messages"])


def test_g1_semantic_reference_and_validator_are_not_replaced_by_text_equality(
    project_root, tmp_path
):
    source = _representative_source(project_root, tmp_path)
    output = tmp_path / "unified"
    export_unified(source, output)
    root = _read_json(source / "cases" / "G1" / "G1_000001" / "root_case.json")
    public_case = _read_json(output / "benchmark_case" / "G1" / "cases" / "case_000001.json")

    assert public_case["reference"] == root["answer"]
    assert public_case["reference"] is not root["answer"]
    assert "reference" not in _read_json(output / "evaluation_case" / "G1" / "llm" / "case_000001.json")


def test_stage1_internal_evidence_layout_is_a_supported_export_source(project_root, tmp_path):
    legacy = _representative_source(project_root, tmp_path)
    regression_root = tmp_path / "stage1"
    for task in TASKS:
        evidence_dir = regression_root / "02_INTERNAL_EVIDENCE" / task
        evidence_dir.mkdir(parents=True)
        root = _read_json(legacy / "cases" / task / f"{task}_000001" / "root_case.json")
        (evidence_dir / "root_case.json").write_text(
            json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    output = tmp_path / "unified"
    result = export_unified(regression_root, output)

    assert result["valid"] is True
    assert result["case_count"] == 4
    assert result["task_counts"] == {task: 1 for task in TASKS}
    migrated_case = _read_json(output / "benchmark_case" / "G2" / "cases" / "case_000001.json")
    assert list(migrated_case) == ["case_id", "llm_prompt", "reference"]
