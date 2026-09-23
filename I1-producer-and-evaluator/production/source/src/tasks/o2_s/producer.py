from __future__ import annotations

from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.projection import assert_no_private_leak
from src.case_core.search import search_single_optimum
from src.case_core.task_support import candidate_paths_for_request,q_numeric,resolve_common_context,spectrum_by_link
from src.tasks.o2_s.validator import validate_o2s_output


def build_o2s_case(env, request_id: str, *, case_id: str, candidate_k: int = 3, max_complete_solutions: int = 100_000) -> dict:
    req=env.requests[request_id]; state_id=env.derivations[request_id]["resource_state_id"]
    common=resolve_common_context(env,state_id); paths=candidate_paths_for_request(env,request_id,candidate_k=candidate_k)
    request={k:(int(req[k]) if k!='request_id' else req[k]) for k in ("request_id","source_node_id","destination_node_id","required_slots")}
    root={"case_id":case_id,"task_type":"O2-S",**{k:common[k] for k in ("topology_id","resource_state_id","nodes","directed_links","slot_count","link_spectrum_states","required_slots_probabilities")},"request":request,"candidate_paths":paths}
    result=search_single_optimum(common["nodes"],common["directed_links"],spectrum_by_link(root),q_numeric(common["required_slots_probabilities"]),request["required_slots"],paths,max_complete_solutions=max_complete_solutions)
    reference={"decision":"ACCEPT","path_rank":result.reference_action["path_rank"],"slot_start":result.reference_action["slot_start"]} if result.feasible else {"decision":"REJECT","path_rank":None,"slot_start":None}
    truth={"case_id":case_id,"task_type":"O2-S","feasible":result.feasible,"optimal_wufr":result.optimal_wufr,"equivalent_optimum_count":result.equivalent_optimum_count,"reference_output":reference}
    public_common={"case_id":case_id,"task_type":"O2-S",**{k:common[k] for k in ("topology_id","resource_state_id","nodes","directed_links","slot_count","spectrum_states","required_slots_probabilities")}}
    algorithm={**public_common,"request":request,"candidate_paths":paths}
    instance=project_algorithm_input("O2-S", algorithm)
    views=build_benchmark_views(root,reference,strict_frozen_interface=False,instance=instance)
    benchmark=views["benchmark_case"]; llm=views["llm_case"]
    for obj in (algorithm,llm): assert_no_private_leak(obj)
    validation=validate_o2s_output(root,truth,reference)
    features={"candidate_path_count":len(paths),"required_slots":request["required_slots"],"node_count":len(common["nodes"]),"resource_pressure":common["state_metrics"].get("network_spectrum_utilization"),"serialized_char_count_llm":len(llm["prompt"]),"oracle_evaluated_complete_solutions":result.evaluated_complete_solutions}
    lineage={"source_topology_id":common["topology_id"],"source_resource_state_id":state_id,"source_request_id":request_id,"candidate_k":candidate_k,"derivation_policy":"PRECOMPUTED_CANDIDATE_PATH_PREFIX"}
    return {"root_case":root,"algorithm_case":algorithm,"benchmark_case":benchmark,"llm_case":llm,"private_truth":truth,"reference_output":reference,"validation":validation,"features":features,"lineage":lineage}
