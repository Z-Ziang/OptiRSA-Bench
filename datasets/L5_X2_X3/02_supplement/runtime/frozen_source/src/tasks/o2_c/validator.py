from __future__ import annotations

from src.case_core.allocation_validation import joint_allocations_feasible
from src.case_core.task_support import q_numeric, spectrum_by_link, validate_output_schema, validate_required_slots_probabilities
from src.case_core.o2_lexicographic import O2C_CONTRACT
from src.case_core.o2_scoring import require_new_truth,score_lexicographic
from src.case_core.wufr import WUFR_ABS_TOL, apply_allocations_copy, network_wufr


def validate_o2c_output(root_case: dict, truth: dict, output: dict) -> dict:
    errors=validate_output_schema("O2-C",output)
    metrics={"joint_feasible_decision_accuracy":0,"delta_tso_gap":None,"wufr_gap":None}
    result={"valid":False,"errors":errors,"metrics":metrics,"submitted_wufr":None}
    result.update(primary_optimal=None,secondary_comparable=None,lexicographic_optimal=None)
    try:require_new_truth(truth,O2C_CONTRACT)
    except ValueError as e:result["errors"].append(str(e));return result
    if errors: return result
    try:
        required_slots_probabilities = validate_required_slots_probabilities(root_case["required_slots_probabilities"])
    except (KeyError, TypeError, ValueError) as exc:
        result["errors"].append(f"invalid required_slots_probabilities: {exc}")
        return result
    true_feasible=bool(truth["joint_feasible"])
    if output["decision"]=="REJECT":
        metrics["joint_feasible_decision_accuracy"]=int(not true_feasible)
        result["valid"]=not true_feasible
        if true_feasible: result["errors"].append("REJECT is incorrect because a complete joint feasible solution exists")
        return result
    request_specs={x["request_id"]:x for x in root_case["requests"]}
    if len(output["allocations"])!=len(request_specs) or len({x["request_id"] for x in output["allocations"]})!=len(request_specs):
        result["errors"].append("ACCEPT must cover every request exactly once")
        return result
    path_specs={}
    for item in output["allocations"]:
        rid=item["request_id"]
        if rid not in request_specs:
            result["errors"].append("unknown request_id")
            return result
        choices={int(p["path_rank"]):p for p in request_specs[rid]["candidate_paths"]}
        if item["path_rank"] not in choices:
            result["errors"].append("path_rank is outside the request candidate set")
            return result
        path_specs[rid]=choices[item["path_rank"]]
    spectrum=spectrum_by_link(root_case)
    if not joint_allocations_feasible(output["allocations"],request_specs,path_specs,spectrum):
        result["errors"].append("submitted joint allocation is not feasible")
        return result
    if not true_feasible:
        result["errors"].append("truth inconsistency: legal ACCEPT found while truth is infeasible")
        return result
    full=[]
    for item in output["allocations"]:
        req=request_specs[item["request_id"]]
        full.append({"path_link_ids":path_specs[item["request_id"]]["path_link_ids"],"slot_start":item["slot_start"],"required_slots":req["required_slots"]})
    post=apply_allocations_copy(spectrum,full)
    submitted=network_wufr(root_case["nodes"],root_case["directed_links"],post,q_numeric(required_slots_probabilities))
    metrics["joint_feasible_decision_accuracy"]=1
    primary=sum(len(a["path_link_ids"])*a["required_slots"] for a in full)
    score_lexicographic(result,truth,primary,submitted,"optimal_delta_tso")
    return result
