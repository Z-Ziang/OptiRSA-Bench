from __future__ import annotations

from src.case_core.allocation_validation import joint_allocations_feasible
from src.case_core.task_support import q_numeric, spectrum_by_link, validate_output_schema, validate_required_slots_probabilities
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def validate_o1_output(root_case: dict, truth: dict, output: dict) -> dict:
    errors = validate_output_schema("O1", output)
    metrics = {"joint_feasible_decision_accuracy": 0, "wufr_gap": None}
    result = {"valid": False, "errors": errors, "metrics": metrics, "submitted_wufr": None}
    if errors:
        return result
    try:
        required_slots_probabilities = validate_required_slots_probabilities(root_case["required_slots_probabilities"])
    except (KeyError, TypeError, ValueError) as exc:
        result["errors"].append(f"invalid required_slots_probabilities: {exc}")
        return result
    true_feasible = bool(truth["joint_feasible"])
    if output["decision"] == "REJECT":
        metrics["joint_feasible_decision_accuracy"] = int(not true_feasible)
        result["valid"] = not true_feasible
        if true_feasible:
            result["errors"].append("REJECT is incorrect because a complete joint feasible solution exists")
        return result
    request_specs = {x["request_id"]: x for x in root_case["requests"]}
    if len(output["allocations"]) != len(request_specs) or len({x["request_id"] for x in output["allocations"]}) != len(request_specs):
        result["errors"].append("ACCEPT must cover every request exactly once")
        return result
    path_specs = {rid: spec["fixed_path"] for rid, spec in request_specs.items()}
    spectrum = spectrum_by_link(root_case)
    if not joint_allocations_feasible(output["allocations"], request_specs, path_specs, spectrum):
        result["errors"].append("submitted joint allocation is not feasible")
        return result
    if not true_feasible:
        result["errors"].append("truth inconsistency: legal ACCEPT found while truth is infeasible")
        return result
    full = []
    for item in output["allocations"]:
        req = request_specs[item["request_id"]]
        full.append({"path_link_ids": req["fixed_path"]["path_link_ids"], "slot_start": item["slot_start"], "required_slots": req["required_slots"]})
    post = apply_allocations_copy(spectrum, full)
    submitted = network_wufr(root_case["nodes"], root_case["directed_links"], post, q_numeric(required_slots_probabilities))
    gap = submitted - float(truth["optimal_wufr"])
    if abs(gap) <= WUFR_ABS_TOL:
        gap = 0.0
    if gap < -WUFR_ABS_TOL:
        result["errors"].append("submitted WUFR is below stored optimum; truth is inconsistent")
        return result
    metrics["joint_feasible_decision_accuracy"] = 1
    metrics["wufr_gap"] = float(gap)
    result["submitted_wufr"] = float(submitted)
    result["valid"] = True
    return result
