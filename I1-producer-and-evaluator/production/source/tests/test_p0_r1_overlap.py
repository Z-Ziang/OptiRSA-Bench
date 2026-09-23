import json
from pathlib import Path

from jsonschema import Draft202012Validator


def candidate(path, starts):
    return {"path_link_ids": path, "feasible_slot_starts": starts}


def test_infeasible_candidate_paths_do_not_enter_overlap_numerator_or_denominator():
    from src.pipeline import candidate_path_link_overlap_density

    derivations = {
        "a": {"candidate_paths": [candidate([1], [0]), candidate([2], [])]},
        "b": {"candidate_paths": [candidate([2], [0])]},
    }
    assert candidate_path_link_overlap_density(["a", "b"], derivations) == 0.0


def test_zero_comparable_path_pairs_omit_overlap_field():
    from src.pipeline import build_concurrent_request_set

    requests = {"a": {"required_slots": 2}, "b": {"required_slots": 2}}
    derivations = {
        "a": {"candidate_paths": [candidate([1], [])]},
        "b": {"candidate_paths": [candidate([1], [0])]},
    }
    item = build_concurrent_request_set("reqset_x", ["a", "b"], requests, derivations)
    assert "candidate_path_link_overlap_density" not in item


def test_old_candidate_conflict_field_is_rejected_by_schema():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/concurrent_request_set.schema.json").read_text(encoding="utf-8"))
    instance = {
        "request_set_id": "reqset_x",
        "resource_state_id": "rs_0001",
        "request_ids": ["a", "b"],
        "candidate_path_conflict_density": 0.5,
        "joint_feasibility_status": "FEASIBLE",
    }
    errors = list(Draft202012Validator(schema).iter_errors(instance))
    assert any(error.validator == "additionalProperties" for error in errors)
