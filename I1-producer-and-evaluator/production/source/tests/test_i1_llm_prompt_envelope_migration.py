from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.i1.pipeline import derive_i1_dataset
from src.i1.production import build_formal_benchmark_case, build_formal_evaluation_case
from src.i1.renderer import render_base_prompt


ROOT = Path(__file__).resolve().parents[1]
TASKS = ("I1-S", "I1-C", "I1-D")
ENV = ROOT / "tests" / "fixtures" / "public_environment_gabriel10"


def _answer(task: str) -> dict:
    if task == "I1-S":
        return {
            "intent_type": "SINGLE",
            "source_node_id": 0,
            "destination_node_id": 4,
            "required_slots": 5,
            "objectives": ["MIN-FRAGMENTATION"],
        }
    if task == "I1-C":
        return {
            "intent_type": "CONCURRENT",
            "requests": [
                {
                    "request_id": "req_a",
                    "source_node_id": 0,
                    "destination_node_id": 4,
                    "required_slots": 3,
                },
                {
                    "request_id": "req_b",
                    "source_node_id": 1,
                    "destination_node_id": 5,
                    "required_slots": 5,
                },
            ],
            "objectives": ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
        }
    return {
        "intent_type": "DYNAMIC",
        "request": {
            "request_id": "dyn_a",
            "source_node_id": 0,
            "destination_node_id": 4,
            "required_slots": 2,
            "arrival_time": 3.25,
            "holding_time": 7.5,
        },
        "objectives": ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"],
    }


def _schema(task: str, name: str) -> dict:
    return json.loads(
        (ROOT / "contracts" / task / "schemas" / name).read_text(encoding="utf-8")
    )


def _valid(schema: dict, value: dict) -> bool:
    return not list(Draft202012Validator(schema).iter_errors(value))


def test_i1_benchmark_schemas_require_llm_prompt_and_only_three_fields():
    for task in TASKS:
        schema = _schema(task, "benchmark_case.schema.json")
        assert schema["required"] == ["case_id", "llm_prompt", "answer"]
        assert set(schema["properties"]) == {"case_id", "llm_prompt", "answer"}
        assert "prompt" not in schema["properties"]
        assert schema["additionalProperties"] is False


def test_old_benchmark_prompt_envelope_is_rejected():
    for task in TASKS:
        schema = _schema(task, "benchmark_case.schema.json")
        old = {"case_id": "old", "prompt": "旧字段", "answer": _answer(task)}
        assert not _valid(schema, old)


def test_benchmark_envelope_with_both_prompt_names_is_rejected():
    for task in TASKS:
        schema = _schema(task, "benchmark_case.schema.json")
        both = {
            "case_id": "both",
            "prompt": "旧字段",
            "llm_prompt": "新字段",
            "answer": _answer(task),
        }
        assert not _valid(schema, both)


def test_evaluation_schema_remains_case_id_plus_prompt_only():
    for task in TASKS:
        schema = _schema(task, "evaluation_case.schema.json")
        assert schema["required"] == ["case_id", "prompt"]
        assert set(schema["properties"]) == {"case_id", "prompt"}
        assert "llm_prompt" not in schema["properties"]
        assert schema["additionalProperties"] is False
        assert _valid(schema, {"case_id": "eval", "prompt": "模型输入"})
        assert not _valid(schema, {"case_id": "eval", "llm_prompt": "模型输入"})


def test_formal_builder_maps_llm_prompt_to_evaluation_prompt_exactly():
    answer = _answer("I1-S")
    llm_prompt = render_base_prompt(answer)
    public = build_formal_benchmark_case("I1-S_000001", llm_prompt, answer)
    evaluation = build_formal_evaluation_case(public)

    assert set(public) == {"case_id", "llm_prompt", "answer"}
    assert set(evaluation) == {"case_id", "prompt"}
    assert evaluation["prompt"] == public["llm_prompt"]
    assert "answer" not in evaluation


def test_i1_s_c_d_answer_shapes_are_unchanged():
    for task in TASKS:
        schema = _schema(task, "benchmark_case.schema.json")
        answer_schema = schema["properties"]["answer"]
        answer = _answer(task)
        assert _valid(answer_schema, answer)
        if task == "I1-S":
            assert set(answer) == {
                "intent_type",
                "source_node_id",
                "destination_node_id",
                "required_slots",
                "objectives",
            }
        elif task == "I1-C":
            assert set(answer) == {"intent_type", "requests", "objectives"}
        else:
            assert set(answer) == {"intent_type", "request", "objectives"}


def test_i1_pipeline_exports_new_benchmark_envelope_and_exact_evaluation_pair(tmp_path):
    out = tmp_path / "i1"
    summary = derive_i1_dataset(ENV, ROOT / "configs" / "i1_representative.json", out)
    assert summary["case_count"] == 6
    for task in TASKS:
        benchmark_path = sorted((out / "benchmark_case" / task / "cases").glob("*.json"))[0]
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        evaluation = json.loads(
            (out / "evaluation_case" / task / "cases" / benchmark_path.name).read_text(
                encoding="utf-8"
            )
        )
        assert set(benchmark) == {"case_id", "llm_prompt", "answer"}
        assert set(evaluation) == {"case_id", "prompt"}
        assert evaluation["prompt"] == benchmark["llm_prompt"]
        assert "answer" not in evaluation

