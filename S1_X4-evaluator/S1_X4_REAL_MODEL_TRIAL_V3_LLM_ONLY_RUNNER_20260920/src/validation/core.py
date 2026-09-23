from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.request_generation.core import derive_request
from src.numeric import values_equal
from src.state_simulation.core import first_fit, reconstruct_availability, spectrum_metrics, validate_connections
from src.topology.core import build_topology


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_path(source: int, destination: int, path: list[int], links: dict[int, dict]) -> None:
    if not path: raise ValueError("path continuity: empty")
    current=source; visited={source}
    for link_id in path:
        link=links.get(link_id)
        if link is None or link["source_node_id"] != current: raise ValueError("path continuity or direction")
        current=link["destination_node_id"]
        if current in visited: raise ValueError("path simplicity")
        visited.add(current)
    if current != destination: raise ValueError("path continuity endpoint")


def validate_base_scenario(scene: dict, states: dict, icsets: dict, requests: dict,
                           concurrent: dict, dynamic: dict) -> None:
    has_state="resource_state_id" in scene; has_ic="initial_existing_connection_set_id" in scene
    if has_state != has_ic: raise ValueError("state ids must be paired")
    dtype=scene["request_data_type"]; data_id=scene.get("request_data_id")
    pools={"SINGLE":requests,"CONCURRENT":concurrent,"DYNAMIC":dynamic}
    if dtype == "NONE":
        if data_id is not None: raise ValueError("NONE request data")
        return
    if data_id not in pools[dtype]: raise ValueError("request data id/type mismatch")
    if has_state:
        state=states.get(scene["resource_state_id"]); ic=icsets.get(scene["initial_existing_connection_set_id"])
        if not state or not ic or state["topology_id"] != scene["topology_id"] or ic["topology_id"] != scene["topology_id"]:
            raise ValueError("scenario topology mismatch")
        if not values_equal(state["reference_time"],ic["reference_time"]): raise ValueError("scenario time mismatch")
        if dtype == "DYNAMIC" and pools[dtype][data_id]["dynamic_request_events"][0]["arrival_time"] < state["reference_time"]:
            raise ValueError("dynamic first arrival")


def replay_dynamic(sequence: dict, icset: dict, directed: dict, k: int = 5) -> dict[int,list[int]]:
    active=[dict(c) for c in icset["existing_connections"]]; now=icset["reference_time"]
    node_count=1+max(max(x["source_node_id"],x["destination_node_id"]) for x in directed["directed_link_records"])
    from src.state_simulation.core import _k_paths
    for index,event in enumerate(sequence["dynamic_request_events"],1):
        if event["arrival_time"] < now: raise ValueError("dynamic arrival order")
        now=event["arrival_time"]
        active=[c for c in active if c["arrival_time"]+c["holding_time"] > now]
        availability=reconstruct_availability(active,directed,320)
        for path in _k_paths(directed,event["source_node_id"],event["destination_node_id"],k):
            start=first_fit(path,availability,event["required_slots"])
            if start is not None:
                active.append({"connection_id":f"dynamic_replay_{index:04d}","source_node_id":event["source_node_id"],
                               "destination_node_id":event["destination_node_id"],"path_link_ids":path,
                               "slot_start":start,"required_slots":event["required_slots"],
                               "arrival_time":event["arrival_time"],"holding_time":event["holding_time"]})
                break
    return reconstruct_availability(active,directed,320)


def validate_environment(env: Path) -> dict[str, Any]:
    errors=[]
    try:
        physical=_load(env/"topologies/physical/top_0001.json"); directed=_load(env/"topologies/directed/top_0001.json")
        stored_metrics=_load(env/"metrics/topology/top_0001.json")
        raw={"node_ids":[n["node_id"] for n in physical["node_records"]],
             "undirected_edges":[[e["node_u_id"],e["node_v_id"]] for e in physical["physical_link_records"]]}
        rp,rd,rm=build_topology(raw,physical["topology_id"],physical["source_type"])
        if rp != physical: errors.append("physical topology recomputation mismatch")
        if rd != directed: errors.append("directed mapping mismatch")
        if not values_equal(rm,stored_metrics): errors.append("topology metrics mismatch")
        links={x["link_id"]:x for x in directed["directed_link_records"]}
        icset=_load(env/"connections/initial/icset_0001.json"); state=_load(env/"states/spectrum/rs_0001.json")
        validate_connections(icset["existing_connections"],directed,state["slot_count"],state["reference_time"])
        reconstructed=reconstruct_availability(icset["existing_connections"],directed,state["slot_count"])
        saved={x["link_id"]:x["slot_availability"] for x in state["link_spectrum_states"]}
        reconstruction_pass=reconstructed == saved
        if not reconstruction_pass: errors.append("state reconstruction mismatch")
        metrics_pass=values_equal(spectrum_metrics(saved,state["slot_count"]),state["spectrum_state_metrics"])
        if not metrics_pass: errors.append("spectrum metrics mismatch")
        requests={x["request_id"]:x for x in _jsonl(env/"requests/single/requests_batch_001.jsonl")}
        derivations={x["request_id"]:x for x in _jsonl(env/"requests/derivation/derivations_batch_001.jsonl")}
        if len(requests)!=182 or len(derivations)!=182: errors.append("request count or uniqueness")
        for rid,request in requests.items():
            validate=derive_request(request,physical,directed,state,derivations[rid]["candidate_path_k"])
            if not values_equal(validate,derivations[rid]): errors.append(f"derivation mismatch {rid}"); break
            for candidate in validate["candidate_paths"]: validate_path(request["source_node_id"],request["destination_node_id"],candidate["path_link_ids"],links)
        concurrent={x["request_set_id"]:x for x in map(_load,sorted((env/"requests/concurrent").glob("*.json")))}
        for item in concurrent.values():
            if len(item["request_ids"])!=len(set(item["request_ids"])) or any(r not in requests for r in item["request_ids"]): errors.append("concurrent references")
            if item["resource_state_id"] != state["resource_state_id"]: errors.append("concurrent state")
            feasible={rid:[path for path in derivations[rid]["candidate_paths"] if path["feasible_slot_starts"]] for rid in item["request_ids"]}
            pair_count=overlap_count=0
            for index,rid_a in enumerate(item["request_ids"]):
                for rid_b in item["request_ids"][index+1:]:
                    for path_a in feasible[rid_a]:
                        for path_b in feasible[rid_b]:
                            pair_count+=1; overlap_count+=bool(set(path_a["path_link_ids"]) & set(path_b["path_link_ids"]))
            field="candidate_path_link_overlap_density"
            if pair_count == 0 and field in item: errors.append("zero-denominator overlap field must be omitted")
            if pair_count and (field not in item or not values_equal(item[field],overlap_count/pair_count)):
                errors.append("candidate path link overlap density mismatch")
        dynamic={x["request_sequence_id"]:x for x in map(_load,sorted((env/"requests/dynamic").glob("*.json")))}
        sequence=next(iter(dynamic.values())); times=[x["arrival_time"] for x in sequence["dynamic_request_events"]]
        if times != sorted(times) or times[0] < state["reference_time"]: errors.append("dynamic time order")
        replay1=replay_dynamic(sequence,icset,directed); replay2=replay_dynamic(sequence,icset,directed)
        replay_pass=replay1==replay2
        if not replay_pass: errors.append("dynamic replay nondeterministic")
        states={state["resource_state_id"]:state}; icsets={icset["initial_existing_connection_set_id"]:icset}
        for scene in map(_load,sorted((env/"scenarios").glob("*.json"))):
            if scene["topology_id"] != physical["topology_id"]: raise ValueError("scenario topology")
            validate_base_scenario(scene,states,icsets,requests,concurrent,dynamic)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        reconstruction_pass=metrics_pass=replay_pass=False
    return {"pass":not errors,"errors":errors,"state_reconstruction_pass":reconstruction_pass,
            "metrics_recomputation_pass":metrics_pass,"dynamic_replay_pass":replay_pass}
