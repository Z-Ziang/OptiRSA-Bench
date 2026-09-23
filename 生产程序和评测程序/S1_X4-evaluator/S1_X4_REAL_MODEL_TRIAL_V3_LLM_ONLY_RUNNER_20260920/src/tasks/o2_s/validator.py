from __future__ import annotations

from src.case_core.allocation_validation import is_assignment_feasible
from src.case_core.task_support import q_numeric, spectrum_by_link, validate_output_schema, validate_required_slots_probabilities
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def validate_o2s_output(root_case: dict, truth: dict, output: dict) -> dict:
    errors = validate_output_schema("O2-S", output)
    metrics = {"feasible_decision_accuracy": 0, "wufr_gap": None}
    result = {"valid": False, "errors": errors, "metrics": metrics, "submitted_wufr": None}
    if errors:
        return result
    try:
        required_slots_probabilities = validate_required_slots_probabilities(root_case["required_slots_probabilities"])
    except (KeyError, TypeError, ValueError) as exc:
        result["errors"].append(f"invalid required_slots_probabilities: {exc}")
        return result
    true_feasible = bool(truth["feasible"])
    if output["decision"] == "REJECT":
        metrics["feasible_decision_accuracy"] = int(not true_feasible)
        result["valid"] = not true_feasible
        if true_feasible:
            result["errors"].append("REJECT is incorrect because a legal action exists")
        return result
    paths = {int(x["path_rank"]): x for x in root_case["candidate_paths"]}
    rank = output["path_rank"]
    if rank not in paths:
        result["errors"].append("path_rank is outside the public candidate set")
        return result
    req = root_case["request"]
    spectrum = spectrum_by_link(root_case)
    path = paths[rank]
    if not is_assignment_feasible(path["path_link_ids"], output["slot_start"], req["required_slots"], spectrum):
        result["errors"].append("submitted action is not spectrum-feasible")
        return result
    if not true_feasible:
        result["errors"].append("truth inconsistency: legal ACCEPT found while truth is infeasible")
        return result
    post = apply_allocations_copy(spectrum,[{"path_link_ids":path["path_link_ids"],"slot_start":output["slot_start"],"required_slots":req["required_slots"]}])
    submitted = network_wufr(root_case["nodes"],root_case["directed_links"],post,q_numeric(required_slots_probabilities))
    gap=submitted-float(truth["optimal_wufr"])
    if abs(gap)<=WUFR_ABS_TOL: gap=0.0
    if gap < -WUFR_ABS_TOL:
        result["errors"].append("submitted WUFR is below stored optimum; truth is inconsistent")
        return result
    metrics["feasible_decision_accuracy"]=1
    metrics["wufr_gap"]=float(gap)
    result["submitted_wufr"]=float(submitted)
    result["valid"]=True
    return result
