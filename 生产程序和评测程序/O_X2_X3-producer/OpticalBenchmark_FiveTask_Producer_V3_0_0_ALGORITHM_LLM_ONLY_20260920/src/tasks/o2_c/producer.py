from __future__ import annotations

from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.projection import assert_no_private_leak
from src.case_core.search import search_joint_optimum
from src.case_core.task_support import candidate_paths_for_request,q_numeric,resolve_common_context,source_resource_state_id,spectrum_by_link
from src.tasks.o2_c.validator import validate_o2c_output


def build_o2c_case(env, request_ids: list[str], *, case_id: str, candidate_k: int = 3, max_complete_solutions: int = 100_000) -> dict:
    if len(request_ids)<2 or len(set(request_ids))!=len(request_ids): raise ValueError("O2-C requires at least two distinct requests")
    state_id=source_resource_state_id(env,request_ids); common=resolve_common_context(env,state_id)
    root_requests=[]; search_requests=[]
    for rid in request_ids:
        req=env.requests[rid]; paths=candidate_paths_for_request(env,rid,candidate_k=candidate_k)
        item={"request_id":rid,"source_node_id":int(req["source_node_id"]),"destination_node_id":int(req["destination_node_id"]),"required_slots":int(req["required_slots"]),"candidate_paths":paths}
        root_requests.append(item); search_requests.append({"request_id":rid,"required_slots":item["required_slots"],"paths":paths})
    root={"case_id":case_id,"task_type":"O2-C",**{k:common[k] for k in ("topology_id","resource_state_id","nodes","directed_links","slot_count","link_spectrum_states","required_slots_probabilities")},"requests":root_requests}
    result=search_joint_optimum(common["nodes"],common["directed_links"],spectrum_by_link(root),q_numeric(common["required_slots_probabilities"]),search_requests,max_complete_solutions=max_complete_solutions)
    reference={"decision":"ACCEPT","allocations":result.reference_action["allocations"]} if result.feasible else {"decision":"REJECT","allocations":[]}
    truth={"case_id":case_id,"task_type":"O2-C","joint_feasible":result.feasible,"optimal_wufr":result.optimal_wufr,"equivalent_optimum_count":result.equivalent_optimum_count,"reference_output":reference}
    public_common={"case_id":case_id,"task_type":"O2-C",**{k:common[k] for k in ("topology_id","resource_state_id","nodes","directed_links","slot_count","spectrum_states","required_slots_probabilities")}}
    algorithm={**public_common,"requests":root_requests}
    instance=project_algorithm_input("O2-C", algorithm)
    views=build_benchmark_views(root,reference,strict_frozen_interface=False,instance=instance)
    benchmark=views["benchmark_case"]; llm=views["llm_case"]
    for obj in (algorithm,llm): assert_no_private_leak(obj)
    validation=validate_o2c_output(root,truth,reference)
    features={"request_count":len(root_requests),"candidate_path_count":candidate_k,"required_slots_profile":[x["required_slots"] for x in root_requests],"node_count":len(common["nodes"]),"resource_pressure":common["state_metrics"].get("network_spectrum_utilization"),"serialized_char_count_llm":len(llm["prompt"]),"oracle_evaluated_complete_solutions":result.evaluated_complete_solutions}
    lineage={"source_topology_id":common["topology_id"],"source_resource_state_id":state_id,"source_request_ids":list(request_ids),"candidate_k":candidate_k,"derivation_policy":"PRECOMPUTED_CANDIDATE_PATH_PREFIX"}
    return {"root_case":root,"algorithm_case":algorithm,"benchmark_case":benchmark,"llm_case":llm,"private_truth":truth,"reference_output":reference,"validation":validation,"features":features,"lineage":lineage}
