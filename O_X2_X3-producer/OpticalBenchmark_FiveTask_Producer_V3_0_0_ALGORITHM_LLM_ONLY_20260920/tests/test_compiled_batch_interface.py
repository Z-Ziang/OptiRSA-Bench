from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compiled_release_metadata_and_benchmark_field_order() -> None:
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == (
        "OpticalBenchmark_FiveTask_Producer_V3_0_0_ALGORITHM_LLM_ONLY_20260920"
    )
    lock = json.loads((ROOT / "RUNTIME_LOCK.json").read_text(encoding="utf-8"))
    assert lock["release_version"] == "3.0.0"
    assert lock["five_task_benchmark_interface"] == "DUAL_VIEW_ALGORITHM_LLM_V1_0_COMPILED_NPZ"
    for task in ("O1", "O2-S", "O2-C", "X2", "X3"):
        contract = json.loads((ROOT / "contracts" / task / "task_contract.json").read_text(encoding="utf-8"))
        assert contract["benchmark_case_fields"] == [
            "case_id", "instance", "llm_prompt", "reference"
        ]
        assert contract["benchmark_interface"] == "DUAL_VIEW_ALGORITHM_LLM_V1_0_COMPILED_NPZ"


def test_case_id_namespace_is_deterministic_and_distinguishes_topology_units() -> None:
    from src.o_family_pipeline import _case_id as o_case_id
    from src.x2x3_pipeline import _case_id as x_case_id

    assert o_case_id("O1", 1, "topologybench_netrail") == "O1_topologybench_netrail_000001"
    assert x_case_id("X2", 1, "topologybench_netrail") == "X2_topologybench_netrail_000001"
    assert o_case_id("O1", 1, None) == "O1_000001"
    assert o_case_id("O1", 1, "topologybench_netrail") != o_case_id("O1", 1, "topologybench_jpn48")


def test_public_algorithm_input_schemas_reject_redundant_schema_version() -> None:
    from jsonschema import Draft202012Validator
    from tests.test_compiled_algorithm_npz import _input

    for task in ("O1", "O2-S", "O2-C", "X2", "X3"):
        schema = json.loads((ROOT / "contracts" / task / "schemas" / "algorithm_input.schema.json").read_text(encoding="utf-8"))
        valid = _input(task)
        valid["schema_version"] = "ALGORITHM_INPUT_V1_0"
        assert list(Draft202012Validator(schema).iter_errors(valid))
