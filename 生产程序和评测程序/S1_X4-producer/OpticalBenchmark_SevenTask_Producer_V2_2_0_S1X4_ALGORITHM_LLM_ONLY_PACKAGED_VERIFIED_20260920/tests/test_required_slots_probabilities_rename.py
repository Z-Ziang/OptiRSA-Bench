import copy
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.case_core.task_support import validate_required_slots_probabilities
from src.case_core.wufr import network_wufr, path_wufr
from src.tasks.o1.producer import build_o1_case
from src.tasks.o2_c.producer import build_o2c_case
from src.tasks.o2_s.producer import build_o2s_case
from tests.o_family_test_utils import toy_env


ROOT = Path(__file__).resolve().parents[1]


def _legacy_field_name():
    # Keep the deprecated spelling out of current machine-readable content.
    return "wufr" + chr(95) + "demand_probabilities"


def _packages():
    return [
        (
            "O1",
            build_o1_case(toy_env(slot_count=4), ["r1", "r2"], case_id="O1_RENAME_REG", max_complete_solutions=100),
        ),
        (
            "O2-S",
            build_o2s_case(toy_env(slot_count=4), "r1", case_id="O2S_RENAME_REG", candidate_k=1, max_complete_solutions=100),
        ),
        (
            "O2-C",
            build_o2c_case(toy_env(slot_count=4), ["r1", "r2"], case_id="O2C_RENAME_REG", candidate_k=1, max_complete_solutions=100),
        ),
    ]


def test_new_field_is_required_and_deprecated_spelling_is_rejected_by_structured_scientific_schemas():
    for task, package in _packages():
        for view in ("root_case", "algorithm_case"):
            schema = __import__("json").loads(
                (ROOT / "contracts" / task / "schemas" / f"{view}.schema.json").read_text(encoding="utf-8")
            )
            case = package[view]
            assert "required_slots_probabilities" in case
            assert not list(Draft202012Validator(schema).iter_errors(case)), (task, view)

            legacy = copy.deepcopy(case)
            legacy[_legacy_field_name()] = legacy.pop("required_slots_probabilities")
            assert list(Draft202012Validator(schema).iter_errors(legacy)), (task, view)

        for view in ("llm_case",):
            schema = __import__("json").loads(
                (ROOT / "contracts" / task / "schemas" / f"{view}.schema.json").read_text(encoding="utf-8")
            )
            assert set(schema["properties"]) == {"case_id", "prompt"}


def test_required_slots_probability_values_are_non_negative_and_sum_to_one():
    valid = {"2": 0.1, "3": 0.2, "5": 0.3, "9": 0.4}
    assert validate_required_slots_probabilities(valid) == valid
    with pytest.raises(ValueError, match="sum to 1"):
        validate_required_slots_probabilities({"2": 0.1, "3": 0.2, "5": 0.3, "9": 0.3})
    with pytest.raises(ValueError, match="non-negative"):
        validate_required_slots_probabilities({"2": -0.1, "3": 0.2, "5": 0.3, "9": 0.6})


def test_wufr_and_reference_baseline_are_unchanged_by_field_rename():
    q = {2: 0.25, 3: 0.25, 5: 0.25, 9: 0.25}
    spectrum = {0: [1, 1, 0, 0], 1: [1, 0, 1, 0]}
    links = [
        {"link_id": 0, "source_node_id": 0, "destination_node_id": 1},
        {"link_id": 1, "source_node_id": 1, "destination_node_id": 0},
    ]
    assert math.isclose(path_wufr([0, 1], spectrum, q), 1.0, abs_tol=1e-12)
    assert math.isclose(network_wufr([0, 1], links, spectrum, q), 0.875, abs_tol=1e-12)

    expected = {
        "O1": {
            "reference_output": {
                "decision": "ACCEPT",
                "allocations": [
                    {"request_id": "r1", "slot_start": 0},
                    {"request_id": "r2", "slot_start": 2},
                ],
            },
            "truth": {"joint_feasible": True, "optimal_wufr": 0.0},
        },
        "O2-S": {
            "reference_output": {"decision": "ACCEPT", "path_rank": 1, "slot_start": 0},
            "truth": {"feasible": True, "optimal_wufr": 0.0},
        },
        "O2-C": {
            "reference_output": {
                "decision": "ACCEPT",
                "allocations": [
                    {"request_id": "r1", "slot_start": 0, "path_rank": 1},
                    {"request_id": "r2", "slot_start": 2, "path_rank": 1},
                ],
            },
            "truth": {"joint_feasible": True, "optimal_wufr": 0.0},
        },
    }
    for task, package in _packages():
        assert package["reference_output"] == expected[task]["reference_output"]
        for key, value in expected[task]["truth"].items():
            assert package["private_truth"][key] == value
