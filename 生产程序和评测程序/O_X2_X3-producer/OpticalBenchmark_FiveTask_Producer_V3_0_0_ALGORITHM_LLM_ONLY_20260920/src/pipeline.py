from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
from pathlib import Path
from random import Random
from typing import Any

from jsonschema import Draft202012Validator

from src.request_generation.core import derive_request, generate_dynamic_sequence, generate_single_requests
from src.numeric import json_ready
from src.scenario_assembly.core import assemble_scenarios
from src.state_simulation.core import simulate_snapshot
from src.topology.core import build_topology
from src.validation.core import validate_environment
from scripts.validate_schemas import run_suite

VERSION="p0-r1-1.0.0"


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(json_ready(obj),ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("".join(json.dumps(json_ready(x),ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n" for x in items),encoding="utf-8")


def _load(path: Path): return json.loads(path.read_text(encoding="utf-8"))


def _joint_feasible(request_ids: list[str], requests: dict, derivations: dict) -> bool:
    actions={}
    for rid in request_ids:
        width=requests[rid]["required_slots"]
        actions[rid]=[(c["path_link_ids"],s,width) for c in derivations[rid]["candidate_paths"] for s in c["feasible_slot_starts"]]
        if not actions[rid]: return False
    order=sorted(request_ids,key=lambda rid:len(actions[rid])); occupied=set()
    def visit(i):
        if i==len(order): return True
        for path,start,width in actions[order[i]]:
            cells={(link,slot) for link in path for slot in range(start,start+width)}
            if occupied.isdisjoint(cells):
                occupied.update(cells)
                if visit(i+1): return True
                occupied.difference_update(cells)
        return False
    return visit(0)


def candidate_path_link_overlap_density(request_ids: list[str], derivations: dict) -> float | None:
    total=overlaps=0
    for i,a in enumerate(request_ids):
        for b in request_ids[i+1:]:
            feasible_a=[path for path in derivations[a]["candidate_paths"] if path["feasible_slot_starts"]]
            feasible_b=[path for path in derivations[b]["candidate_paths"] if path["feasible_slot_starts"]]
            for path_a in feasible_a:
                for path_b in feasible_b:
                    total+=1
                    overlaps+=bool(set(path_a["path_link_ids"]) & set(path_b["path_link_ids"]))
    return overlaps / total if total else None


def build_concurrent_request_set(request_set_id: str, request_ids: list[str], requests: dict,
                                 derivations: dict, resource_state_id: str = "rs_0001") -> dict:
    item={"request_set_id":request_set_id,"resource_state_id":resource_state_id,"request_ids":request_ids,
          "joint_feasibility_status":"FEASIBLE" if _joint_feasible(request_ids,requests,derivations) else "INFEASIBLE"}
    density=candidate_path_link_overlap_density(request_ids,derivations)
    if density is not None:
        item["candidate_path_link_overlap_density"]=density
    return item


def schema_validate(output_root: Path) -> dict:
    schemas=output_root/"schemas"; env=output_root/"public_environment"
    manifest=_load(schemas/"schema_manifest.json"); errors=[]; checked=0
    for mapping in manifest["mappings"]:
        validator=Draft202012Validator(_load(schemas/mapping["schema"]))
        for path in sorted(p for p in env.rglob("*") if p.is_file() and fnmatch.fnmatch(p.relative_to(env).as_posix(),mapping["pattern"])):
            if path.suffix==".jsonl":
                for line_no,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
                    if not line.strip(): continue
                    checked+=1
                    for err in validator.iter_errors(json.loads(line)): errors.append({"file":str(path.relative_to(env)),"line":line_no,"message":err.message})
            else:
                checked+=1
                for err in validator.iter_errors(_load(path)): errors.append({"file":str(path.relative_to(env)),"line":None,"message":err.message})
    return {"pass":not errors,"checked_instance_count":checked,"errors":errors}


def _config(cid,stage,topology,parameters,sources,seed=None,with_traffic=False):
    obj={"generation_config_id":cid,"production_stage":stage,"topology_id":topology,
         "parameter_values":parameters,"generator_name":"nsfnet_p0_pipeline","generator_version":VERSION,
         "source_data_ids":sources}
    if seed is not None: obj["random_seed"]=seed
    if with_traffic:
        obj.update({"time_unit":"SIMULATION_TIME_UNIT","payload_slot_values":[1,2,4,8],
                    "payload_slot_distribution":"UNIFORM","payload_slot_probabilities":[.25]*4,"guard_band_slots":1})
    return obj


def _issue_markdown(issues: list[dict]) -> str:
    cols=["issue_id","severity","category","source_file","location","object_or_field","observed_evidence","impact","implemented_handling","recommendation"]
    rows=["| "+" | ".join(cols)+" |","| "+" | ".join("---" for _ in cols)+" |"]
    for issue in issues: rows.append("| "+" | ".join(str(issue[c]).replace("|","\\|").replace("\n"," ") for c in cols)+" |")
    return "# P0-R1 规范问题审计\n\n"+"\n".join(rows)+"\n"


def semantic_hashes(env: Path) -> dict[str,str]:
    hashes={}
    for p in sorted(x for x in env.rglob("*") if x.is_file() and "reports" not in x.parts and x.suffix in {".json",".jsonl"}):
        if p.suffix==".json": canonical=json.dumps(_load(p),ensure_ascii=False,sort_keys=True,separators=(",",":"))
        else: canonical="\n".join(json.dumps(json.loads(line),ensure_ascii=False,sort_keys=True,separators=(",",":")) for line in p.read_text(encoding="utf-8").splitlines() if line)
        hashes[p.relative_to(env).as_posix()]=hashlib.sha256(canonical.encode()).hexdigest()
    return hashes


def write_sha256s(root: Path) -> None:
    lines=[]
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name!="SHA256SUMS.txt" and "__pycache__" not in x.parts and ".pytest_cache" not in x.parts):
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}")
    (root/"SHA256SUMS.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")


def run_pipeline(input_root: Path, output_root: Path) -> dict:
    input_root=Path(input_root); output_root=Path(output_root); env=output_root/"public_environment"
    output_root.mkdir(parents=True,exist_ok=True)
    source_schemas=(input_root/"schemas").resolve()
    target_schemas=(output_root/"schemas").resolve()
    if source_schemas != target_schemas:
        shutil.copytree(source_schemas,target_schemas,dirs_exist_ok=True)
    raw=_load(input_root/"inputs/nsfnet14_raw.json"); cfg=_load(input_root/"inputs/p0_pilot_parameters.json")
    physical,directed,top_metrics=build_topology(raw,"top_0001","REAL")
    write_json(env/"topologies/physical/top_0001.json",physical); write_json(env/"topologies/directed/top_0001.json",directed); write_json(env/"metrics/topology/top_0001.json",top_metrics)
    sim=simulate_snapshot(directed,14,cfg["resource_state"])
    write_json(env/"connections/initial/icset_0001.json",sim.connection_set); write_json(env/"states/spectrum/rs_0001.json",sim.resource_state)
    req_cfg=cfg["request"]; required=[2,3,5,9]; rng=Random(req_cfg["random_seed"])
    requests=generate_single_requests("top_0001",14,required,rng); write_jsonl(env/"requests/single/requests_batch_001.jsonl",requests)
    derivations=[derive_request(r,physical,directed,sim.resource_state,req_cfg["candidate_path_k"]) for r in requests]
    write_jsonl(env/"requests/derivation/derivations_batch_001.jsonl",derivations)
    req_index={x["request_id"]:x for x in requests}; der_index={x["request_id"]:x for x in derivations}
    concurrent=[]
    for i in range(3):
        ids=[requests[i*4+j]["request_id"] for j in range(4)]
        item=build_concurrent_request_set(f"reqset_{i+1:04d}",ids,req_index,der_index)
        concurrent.append(item); write_json(env/f"requests/concurrent/reqset_{i+1:04d}.json",item)
    sequence=generate_dynamic_sequence("seq_0001","dynreq",14,sim.resource_state["reference_time"],
        req_cfg["dynamic_arrival_rate_lambda"],req_cfg["dynamic_holding_time_rate_mu"],required,rng)
    write_json(env/"requests/dynamic/seq_0001.json",sequence)
    configs=[
        _config("genconf_0001","TOPOLOGY","top_0001",{"raw_input":"nsfnet14_raw.json","length_policy":"OMIT_IF_UNAVAILABLE"},[]),
        _config("genconf_0002","RESOURCE_STATE","top_0001",{**cfg["resource_state"],"actual_arrival_rate_lambda":sim.actual_arrival_rate_lambda,
                "target_reached":sim.target_reached,"load_search_trace":sim.search_trace},["top_0001"],cfg["resource_state"]["random_seed"],True),
        _config("genconf_0003","REQUEST","top_0001",req_cfg,["top_0001","rs_0001"],req_cfg["random_seed"],True),
        _config("genconf_0004","BASE_SCENARIO","top_0001",cfg["base_scenario"],["top_0001","rs_0001","icset_0001","req_0001","reqset_0001","seq_0001"]),
    ]
    for i,obj in enumerate(configs,1): write_json(env/f"configs/generation_config_{i:04d}.json",obj)
    scenes=assemble_scenarios({"topology_id":"top_0001","resource_state_id":"rs_0001","initial_existing_connection_set_id":"icset_0001",
        "single_request_id":"req_0001","concurrent_request_set_id":"reqset_0001","dynamic_request_sequence_id":"seq_0001"})
    for i,obj in enumerate(scenes,1): write_json(env/f"scenarios/bs_{i:04d}.json",obj)
    issues=[]
    if not sim.target_reached:
        issues.append({"issue_id":"P0-005","severity":"HIGH","category":"PARAMETER_NOT_REACHABLE","source_file":"pilot_config/p0_pilot_parameters.json","location":"resource_state target band","object_or_field":"target_network_spectrum_utilization_band","observed_evidence":json.dumps(sim.search_trace,ensure_ascii=False),"impact":"资源状态未进入目标轻载带。","implemented_handling":"保存最接近实际状态和全部搜索轨迹，发布状态降为 PARTIAL。","recommendation":"调整到达率搜索范围或停止条件后重跑。"})
    reports=env/"reports"; reports.mkdir(parents=True,exist_ok=True)
    suite_report=run_suite(input_root/"examples/test_suite.json")
    write_json(reports/"input_schema_suite_report.json",suite_report)
    suite_pass=suite_report["summary"]["failed"] == 0
    (reports/"specification_issues.md").write_text(_issue_markdown(issues),encoding="utf-8")
    schema=schema_validate(output_root); write_json(reports/"schema_validation_report.json",schema)
    validation=validate_environment(env)
    write_json(reports/"cross_file_validation_report.json",{"pass":validation["pass"],"errors":validation["errors"]})
    write_json(reports/"domain_validation_report.json",validation)
    write_json(reports/"state_reconstruction_report.json",{"pass":validation["state_reconstruction_pass"],"connection_count":len(sim.connection_set["existing_connections"])})
    write_json(reports/"dynamic_replay_report.json",{"pass":validation["dynamic_replay_pass"],"event_count":20,"policy":"release-before-arrival; deterministic KSP/First-Fit"})
    write_json(reports/"metrics_recomputation_report.json",{"pass":validation["metrics_recomputation_pass"],"topology_metrics_equal":"topology metrics mismatch" not in validation["errors"],"p90_method":"Hyndman-Fan Type 7 linear interpolation","variance_method":"population variance","float_comparison":{"rel_tol":1e-9,"abs_tol":1e-12}})
    write_json(reports/"load_search_report.json",{"target_band":cfg["resource_state"]["target_network_spectrum_utilization_band"],"upper_inclusive":False,"target_reached":sim.target_reached,"actual_arrival_rate_lambda":sim.actual_arrival_rate_lambda,"trace":sim.search_trace})
    write_json(reports/"semantic_hashes.json",semantic_hashes(env))
    status_value="FAIL" if not(suite_pass and schema["pass"] and validation["pass"]) else ("PASS" if sim.target_reached else "PARTIAL")
    status={"status":status_value,"p0_scope_complete":True,"schema_suite_pass":suite_pass,"generated_file_schema_pass":schema["pass"],
            "cross_file_validation_pass":validation["pass"],"state_reconstruction_pass":validation["state_reconstruction_pass"],
            "dynamic_replay_pass":validation["dynamic_replay_pass"],"full_reproduction_pass":False,
            "specification_issue_count":len(issues),"high_severity_issue_count":sum(i["severity"]=="HIGH" for i in issues),
            "case_generation_executed":False,"i1_executed":False,"formal_difficulty_labels_generated":False}
    write_json(output_root/"RELEASE_STATUS.json",status)
    write_sha256s(output_root)
    return {"status":status_value,"object_counts":{"physical_topologies":1,"directed_topologies":1,"topology_metrics":1,
            "connection_sets":1,"resource_states":1,"existing_connections":len(sim.connection_set["existing_connections"]),
            "single_requests":len(requests),"request_derivations":len(derivations),"concurrent_request_sets":3,
            "dynamic_sequences":1,"dynamic_events":20,"base_scenarios":4,"generation_configs":4},
            "schema":schema,"validation":validation,"target_reached":sim.target_reached}
