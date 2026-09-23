from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.o_family_test_utils import toy_env
from src.tasks.o1.producer import build_o1_case
from src.tasks.o2_s.producer import build_o2s_case
from src.tasks.o2_c.producer import build_o2c_case
from src.tasks.x2.producer import build_x2_case
from src.tasks.x3.producer import build_x3_case


ROOT = Path(__file__).resolve().parents[1]
TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")


def _bundles() -> dict[str, dict]:
    env = toy_env(slot_count=6)
    return {
        "O1": build_o1_case(env, ["r1", "r2"], case_id="O1_ALGORITHM_VIEW", max_complete_solutions=1000),
        "O2-S": build_o2s_case(env, "r1", case_id="O2S_ALGORITHM_VIEW", candidate_k=1, max_complete_solutions=1000),
        "O2-C": build_o2c_case(env, ["r1", "r2"], case_id="O2C_ALGORITHM_VIEW", candidate_k=1, max_complete_solutions=1000),
        "X2": build_x2_case(env, "r1", case_id="X2_ALGORITHM_VIEW", required_slots=2, max_simple_paths=1000, max_optimal_actions=1000),
        "X3": build_x3_case(env, ["r1", "r2"], case_id="X3_ALGORITHM_VIEW", max_simple_paths_per_request=1000, max_complete_optimal_solutions=1000),
    }


def _projection(task: str, internal: dict) -> dict:
    try:
        module = importlib.import_module("src.case_core.algorithm_projection")
    except ModuleNotFoundError as exc:
        pytest.fail(f"expected Algorithm projection module is missing: {exc}")
    return module.project_algorithm_input(task, internal)


def test_five_task_benchmark_bundle_has_exact_algorithm_llm_envelope() -> None:
    expected = {"case_id", "instance", "llm_prompt", "reference"}
    for bundle in _bundles().values():
        assert set(bundle["benchmark_case"]) == expected


@pytest.mark.parametrize("task", TASKS)
def test_algorithm_input_is_unified_and_task_specific(task: str) -> None:
    bundle = _bundles()[task]
    value = _projection(task, bundle["algorithm_case"])
    assert list(value) == [
        "task_type",
        "slot_count",
        "nodes",
        "directed_links",
        "link_spectrum_states",
        "requests",
    ]
    assert "schema_version" not in value
    assert value["task_type"] == task
    assert "required_slots_probabilities" not in value
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "topology_id",
        "resource_state_id",
        "private_truth",
        "reference_output",
        "oracle",
        "calibration",
        "feasible_slot_starts",
        "feasible_action_count",
    ):
        assert forbidden not in serialized
    if task == "O1":
        assert len(value["requests"]) >= 2
        assert all("fixed_path" in request for request in value["requests"])
    elif task == "O2-S":
        assert len(value["requests"]) == 1
        assert "candidate_paths" in value["requests"][0]
    elif task == "O2-C":
        assert len(value["requests"]) >= 2
        assert all("candidate_paths" in request for request in value["requests"])
    elif task == "X2":
        assert len(value["requests"]) == 1
        assert "fixed_path" not in value["requests"][0]
        assert "candidate_paths" not in value["requests"][0]
    else:
        assert len(value["requests"]) >= 2
        assert all("fixed_path" not in request and "candidate_paths" not in request for request in value["requests"])


def test_algorithm_contract_assets_exist_for_five_tasks_only() -> None:
    for task in TASKS:
        base = ROOT / "contracts" / task
        assert (base / "algorithm_contract.json").is_file()
        assert (base / "schemas" / "algorithm_input.schema.json").is_file()
        assert (base / "schemas" / "algorithm_evaluation_case.schema.json").is_file()
        contract = json.loads((base / "algorithm_contract.json").read_text(encoding="utf-8"))
        assert contract["input_schema_version"] == "ALGORITHM_INPUT_V1_0"
        assert contract["slot_count"] == 320
        assert contract["metric_contract"]["included_in_algorithm_input"] is False
        assert contract["metric_contract"]["required_slots_probabilities"] == {
            "2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25
        }
def test_algorithm_input_schema_rejects_task_constant_from_per_case_input() -> None:
    bundle = _bundles()["X2"]
    value = _projection("X2", bundle["algorithm_case"])
    value["required_slots_probabilities"] = {"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25}
    schema = json.loads((ROOT / "contracts" / "X2" / "schemas" / "algorithm_input.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(value))
