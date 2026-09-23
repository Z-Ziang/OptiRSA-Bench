from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.case_core.natural_language_renderer import build_benchmark_views


ROOT = Path(__file__).resolve().parents[1]
TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")


def _o1_root_case() -> dict:
    return {
        "case_id": "O1_INSTANCE_RENAME_TEST",
        "task_type": "O1",
        "slot_count": 6,
        "nodes": [0, 1],
        "directed_links": [{"link_id": 0, "source_node_id": 0, "destination_node_id": 1}],
        "link_spectrum_states": [{"link_id": 0, "slot_availability": [1, 1, 1, 1, 1, 1]}],
        "requests": [
            {
                "request_id": "r1",
                "source_node_id": 0,
                "destination_node_id": 1,
                "required_slots": 2,
                "fixed_path": {"path_node_ids": [0, 1], "path_link_ids": [0]},
            }
        ],
    }


def _benchmark_schema(task: str) -> dict:
    return json.loads(
        (ROOT / "contracts" / task / "schemas" / "benchmark_case.schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_benchmark_view_uses_instance_as_the_only_structured_problem_field() -> None:
    instance = {"task_type": "O1", "slot_count": 6, "nodes": [0, 1]}

    views = build_benchmark_views(
        _o1_root_case(),
        {"decision": "REJECT"},
        strict_frozen_interface=False,
        instance=instance,
    )

    benchmark = views["benchmark_case"]
    assert list(benchmark) == ["case_id", "instance", "llm_prompt", "reference"]
    assert benchmark["instance"] == instance
    assert "algorithm_input" not in benchmark
    assert "algorithm_case" not in benchmark
    assert "algorithm_view" not in benchmark
    assert "case_body" not in benchmark


def test_new_benchmark_schema_accepts_instance_and_rejects_legacy_field() -> None:
    valid = {
        "case_id": "X2_INSTANCE_RENAME_TEST",
        "instance": {},
        "llm_prompt": "llm",
        "reference": {},
    }

    for task in TASKS:
        validator = Draft202012Validator(_benchmark_schema(task))
        assert list(validator.iter_errors(valid)) == [], task

        legacy = dict(valid)
        legacy["algorithm_input"] = legacy.pop("instance")
        assert list(validator.iter_errors(legacy)), task


def test_all_five_benchmark_schemas_have_the_same_frozen_envelope() -> None:
    expected = ["case_id", "instance", "llm_prompt", "reference"]
    for task in TASKS:
        schema = _benchmark_schema(task)
        assert schema["additionalProperties"] is False
        assert schema["required"] == expected
        assert list(schema["properties"]) == expected
        assert "algorithm_input" not in schema["properties"]
        assert "algorithm_case" not in schema["properties"]
        assert "algorithm_view" not in schema["properties"]
        assert "case_body" not in schema["properties"]
