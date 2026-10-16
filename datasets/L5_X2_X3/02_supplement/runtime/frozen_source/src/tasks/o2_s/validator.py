from __future__ import annotations

from src.case_core.allocation_validation import is_assignment_feasible
from src.case_core.task_support import q_numeric, spectrum_by_link, validate_output_schema, validate_required_slots_probabilities
from src.case_core.o2_lexicographic import O2S_CONTRACT
from src.case_core.o2_scoring import require_new_truth,score_lexicographic
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def validate_o2s_output(root_case: dict, truth: dict, output: dict) -> dict:
    errors = validate_output_schema("O2-S", output)
    metrics = {"feasible_decision_accuracy": 0, "hop_count_gap": None, "wufr_gap": None}
    result = {"valid": False, "errors": errors, "metrics": metrics, "submitted_wufr": None}
    result.update(primary_optimal=None,secondary_comparable=None,lexicographic_optimal=None)
    try:require_new_truth(truth,O2S_CONTRACT)
    except ValueError as e:result["errors"].append(str(e));return result
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
    metrics["feasible_decision_accuracy"]=1
    score_lexicographic(result,truth,len(path["path_link_ids"]),submitted,"optimal_hop_count")
    return result
