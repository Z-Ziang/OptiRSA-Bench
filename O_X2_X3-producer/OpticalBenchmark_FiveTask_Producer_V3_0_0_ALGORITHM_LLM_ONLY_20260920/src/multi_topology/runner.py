from __future__ import annotations

import json
from pathlib import Path
from random import Random
from time import perf_counter

import numpy as np

from src.pipeline import build_concurrent_request_set

from .audit import build_public_topology
from .reporting import correlation_matrix, numeric_summary, write_csv, write_json, write_jsonl
from .requests import (
    RequestDeriver,
    generate_dynamic_sequence,
    generate_requests,
    ordered_request_pairs,
    stratified_request_pairs,
)
from .simulation import PathCatalog, search_snapshot
from .xlsx_reader import read_topology_workbook


RESOURCE_FIELDS = [
    "network_spectrum_utilization", "max_link_utilization", "p90_link_utilization",
    "link_utilization_variance", "mean_link_external_fragmentation",
    "historical_request_blocking_probability", "active_connection_count",
    "average_active_connection_path_hops", "maximum_used_fsu_index",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _config(config_id: str, stage: str, topology_id: str, parameters: dict,
            source_ids: list[str], seed: int | None = None, resource_fields: bool = False) -> dict:
    result = {
        "generation_config_id": config_id, "production_stage": stage,
        "topology_id": topology_id, "parameter_values": parameters,
        "generator_name": "P0R1_MULTI_TOPOLOGY_PREPRODUCTION",
        "generator_version": "1.0.0-preproduction", "source_data_ids": source_ids,
    }
    if seed is not None:
        result["random_seed"] = seed
    if resource_fields:
        result.update({"time_unit": "SIMULATION_TIME_UNIT", "payload_slot_values": [1, 2, 4, 8],
                       "payload_slot_distribution": "UNIFORM",
                       "payload_slot_probabilities": [0.25, 0.25, 0.25, 0.25],
                       "guard_band_slots": 1})
    return result


def _state_experiments(config: dict, topology_name: str, topology_index: int) -> list[dict]:
    base_seed = config["resource_state_baseline_matrix"]["random_seed_base"] + topology_index * 100
    bands = config["resource_state_baseline_matrix"]["target_bands"]
    experiments = []
    for offset, band_name in enumerate(("LIGHT", "MEDIUM", "HIGH")):
        experiments.append({"key": f"base_{band_name.lower()}_s1", "band_name": band_name,
                            "band": bands[band_name], "profile": "BASE_KSP_FF", "seed": base_seed+offset,
                            "role": "BASELINE_FIRST_SEED"})
    if topology_name in config["resource_state_high_pressure_subset"]["topologies"]:
        experiments.append({"key": "base_high_pressure_s1", "band_name": "HIGH_PRESSURE",
                            "band": config["resource_state_high_pressure_subset"]["target_band"],
                            "profile": "BASE_KSP_FF", "seed": base_seed+3, "role": "HIGH_PRESSURE_REACHABILITY"})
    if topology_name in config["resource_state_profile_comparison"]["topologies"]:
        for profile_index, profile in enumerate(config["resource_state_profile_comparison"]["profiles"]):
            experiments.append({"key": f"{profile['name'].lower()}_medium_s1", "band_name": "MEDIUM",
                                "band": config["resource_state_profile_comparison"]["target_band"],
                                "profile": profile["name"], "seed": base_seed+50+profile_index,
                                "role": "PILOT_PROFILE_COMPARISON"})
    experiments.append({"key": "base_medium_s2", "band_name": "MEDIUM", "band": bands["MEDIUM"],
                        "profile": "BASE_KSP_FF",
                        "seed": base_seed+config["stability_repeat"]["second_random_seed_offset"],
                        "role": "STABILITY_SECOND_SEED"})
    return experiments


def _percentile(values: list[int], probability: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), probability*100, method="linear"))


def _coverage_row(name: str, topology_id: str, requests: list[dict], derivations: list[dict],
                  concurrent: list[dict], policy: str) -> dict:
    required = {value: 0 for value in (2, 3, 5, 9)}
    for request in requests:
        required[request["required_slots"]] += 1
    hops = [item["shortest_path_hops"] for item in derivations]
    feasible = {"0": 0, "1": 0, ">=2": 0}
    actions = {"0": 0, "1": 0, "2-5": 0, "6-20": 0, ">20": 0}
    local = {"1": 0, ">=2": 0}
    rank_errors = 0
    for item in derivations:
        count = item["feasible_candidate_path_count"]
        feasible["0" if count == 0 else "1" if count == 1 else ">=2"] += 1
        count = item["feasible_action_count"]
        key = "0" if count == 0 else "1" if count == 1 else "2-5" if count <= 5 else "6-20" if count <= 20 else ">20"
        actions[key] += 1
        local["1" if item["local_edge_connectivity"] == 1 else ">=2"] += 1
        ranks = [candidate["rank"] for candidate in item["candidate_paths"]]
        rank_errors += ranks != list(range(1, len(ranks)+1))
    overlap = [item["candidate_path_link_overlap_density"] for item in concurrent
               if "candidate_path_link_overlap_density" in item]
    joint = {status: sum(item["joint_feasibility_status"] == status for item in concurrent)
             for status in ("FEASIBLE", "INFEASIBLE", "UNKNOWN")}
    return {
        "topology_name": name, "topology_id": topology_id, "request_policy": policy,
        "request_count": len(requests), **{f"required_slots_{key}": value for key, value in required.items()},
        "shortest_path_hops_min": min(hops), "shortest_path_hops_max": max(hops),
        "shortest_path_hops_p33": _percentile(hops, 0.33), "shortest_path_hops_p66": _percentile(hops, 0.66),
        **{f"local_connectivity_{key}": value for key, value in local.items()},
        **{f"feasible_paths_{key}": value for key, value in feasible.items()},
        **{f"feasible_actions_{key}": value for key, value in actions.items()},
        "candidate_rank_error_count": rank_errors,
        "overlap_density_count": len(overlap),
        "overlap_density_min": min(overlap) if overlap else None,
        "overlap_density_max": max(overlap) if overlap else None,
        **{f"joint_{key}": value for key, value in joint.items()},
    }


def _scenarios(topology_id: str, state_id: str, connection_id: str,
               request_id: str, request_set_id: str, sequence_id: str) -> list[dict]:
    suffix = topology_id[4:]
    common = {"topology_id": topology_id, "resource_state_id": state_id,
              "initial_existing_connection_set_id": connection_id}
    return [
        {"base_scenario_id": f"bs_{suffix}_none", "topology_id": topology_id, "request_data_type": "NONE"},
        {"base_scenario_id": f"bs_{suffix}_single", **common,
         "request_data_type": "SINGLE", "request_data_id": request_id},
        {"base_scenario_id": f"bs_{suffix}_concurrent", **common,
         "request_data_type": "CONCURRENT", "request_data_id": request_set_id},
        {"base_scenario_id": f"bs_{suffix}_dynamic", **common,
         "request_data_type": "DYNAMIC", "request_data_id": sequence_id},
    ]


def run_selected_pipeline(source_dir: Path, output_root: Path) -> dict:
    config = _load(output_root/"configs"/"cross_topology_pilot_config.json")
    env = output_root/"public_environment"
    if env.exists():
        raise FileExistsError(f"refusing to overwrite existing public environment: {env}")
    for relative in ("topologies/physical", "topologies/directed", "metrics/topology",
                     "connections/initial", "states/spectrum", "requests/single",
                     "requests/derivation", "requests/concurrent", "requests/dynamic",
                     "scenarios", "configs", "reports"):
        (env/relative).mkdir(parents=True, exist_ok=True)
    files = {read_topology_workbook(path).name: path for path in source_dir.glob("*.xlsx")}
    names = config["topology_scope"]["full_pipeline_topology_names"]
    common = config["resource_state_common"]
    topologies: dict[str, dict] = {}
    state_index: dict[tuple[str, str], dict] = {}
    resource_rows = []
    state_trace_summary = []
    coverage_rows = []
    scaling_rows = []
    generation_configs = []
    object_counts = {"physical_topologies": 0, "directed_topologies": 0, "topology_metrics": 0,
                     "connection_sets": 0, "resource_states": 0, "requests": 0,
                     "request_derivations": 0, "concurrent_request_sets": 0,
                     "dynamic_sequences": 0, "dynamic_events": 0, "base_scenarios": 0,
                     "generation_configs": 0}
    for topology_index, name in enumerate(names, 1):
        topology_id = f"top_{topology_index:04d}"
        import_started = perf_counter()
        imported = read_topology_workbook(files[name])
        import_seconds = perf_counter()-import_started
        metric_started = perf_counter()
        physical, directed, metrics, private = build_public_topology(imported, topology_id)
        metric_seconds = perf_counter()-metric_started
        write_json(env/"topologies/physical"/f"{topology_id}.json", physical)
        write_json(env/"topologies/directed"/f"{topology_id}.json", directed)
        write_json(env/"metrics/topology"/f"{topology_id}.json", metrics)
        write_json(output_root/"audit/topology_105/private_selected_mappings"/f"{topology_id}_{name}.json", private)
        generation_configs.append(_config(
            f"genconf_{topology_id[4:]}_topology", "TOPOLOGY", topology_id,
            {"source_file": imported.source_file, "source_topology_name": name,
             "source_ids_remapped_continuously": True, "source_anomaly_policy": "REJECT"},
            [imported.source_file],
        ))
        object_counts["physical_topologies"] += 1
        object_counts["directed_topologies"] += 1
        object_counts["topology_metrics"] += 1
        edges = [(item["node_u_id"], item["node_v_id"]) for item in physical["physical_link_records"]]
        catalog = PathCatalog.from_edges(len(physical["node_records"]), edges,
                                         common["historical_candidate_path_k"])
        experiment_timings = []
        for experiment in _state_experiments(config, name, topology_index):
            state_id = f"rs_{topology_id[4:]}_{experiment['key']}"
            connection_id = f"icset_{topology_id[4:]}_{experiment['key']}"
            search = search_snapshot(
                topology_id=topology_id, state_id=state_id, connection_set_id=connection_id,
                catalog=catalog, node_count=len(physical["node_records"]),
                link_count=len(directed["directed_link_records"]), slot_count=common["slot_count"],
                holding_rate=common["holding_time_rate_mu"],
                payload_values=common["payload_slot_values"],
                payload_probabilities=common["payload_slot_probabilities"],
                guard_slots=common["guard_band_slots"], warmup=common["warmup_request_count"],
                maximum_requests=common["maximum_simulated_request_count_per_load_trial"],
                target_band=tuple(experiment["band"]), policy=experiment["profile"], seed=experiment["seed"],
                average_shortest_path_hops=metrics["average_shortest_path_hops"],
                fallback_grid=common["fallback_arrival_rate_lambda_grid"],
            )
            write_json(env/"connections/initial"/f"{connection_id}.json", search.connection_set)
            write_json(env/"states/spectrum"/f"{state_id}.json", search.resource_state)
            trace_record = {
                "topology_id": topology_id, "topology_name": name, "resource_state_id": state_id,
                "profile": experiment["profile"], "load_band_name": experiment["band_name"],
                "target_band": experiment["band"], "role": experiment["role"],
                "target_reached": search.target_reached,
                "actual_arrival_rate_lambda": search.actual_arrival_rate_lambda,
                "trials": search.trials, "audit_only_candidate_metrics": search.audit_metrics,
            }
            write_json(output_root/"audit/metric_sufficiency/state_search_traces"/f"{state_id}.json", trace_record)
            state_trace_summary.append(trace_record)
            flat = {"topology_name": name, "topology_id": topology_id, "resource_state_id": state_id,
                    "profile": experiment["profile"], "load_band_name": experiment["band_name"],
                    "seed_role": experiment["role"], "seed": experiment["seed"],
                    "target_reached": search.target_reached,
                    **{field: search.resource_state["spectrum_state_metrics"].get(field) for field in RESOURCE_FIELDS},
                    **search.audit_metrics}
            resource_rows.append(flat)
            experiment_timings.append({"state_id": state_id, "runtime_seconds": sum(t["runtime_seconds"] for t in search.trials)})
            generation_configs.append(_config(
                f"genconf_{state_id}", "RESOURCE_STATE", topology_id,
                {"profile": experiment["profile"], "profile_status": experiment["role"],
                 "target_band_name": experiment["band_name"], "target_band": experiment["band"],
                 "target_reached": search.target_reached,
                 "actual_arrival_rate_lambda": search.actual_arrival_rate_lambda,
                 "load_search": "MODEL_ESTIMATE_THEN_CONFIG_LOG_GRID_AND_BISECTION",
                 "load_search_trace_audit_file": f"audit/metric_sufficiency/state_search_traces/{state_id}.json",
                 "slot_count": common["slot_count"], "holding_time_rate_mu": common["holding_time_rate_mu"],
                 "historical_candidate_path_k": common["historical_candidate_path_k"]},
                [topology_id], experiment["seed"], True,
            ))
            state_index[(topology_id, experiment["key"])] = search.resource_state
            state_index[(topology_id, experiment["key"]+"_connection")] = search.connection_set
            object_counts["resource_states"] += 1
            object_counts["connection_sets"] += 1
        # Request production uses the first-seed MEDIUM BASE_KSP_FF snapshot.
        medium_state = state_index[(topology_id, "base_medium_s1")]
        medium_connection = state_index[(topology_id, "base_medium_s1_connection")]
        request_cfg = config["request_generation"]
        request_rng = Random(202608072000 + topology_index)
        if len(physical["node_records"]) <= 100:
            pairs = ordered_request_pairs(len(physical["node_records"]))
            request_policy = "ALL_ORDERED_SOURCE_DESTINATION_PAIRS"
        else:
            pairs = stratified_request_pairs(len(physical["node_records"]), edges,
                                             request_cfg["n_gt_100_pilot_sample_count"], request_rng)
            request_policy = "PILOT_STRATIFIED_SAMPLE_NOT_FORMAL_PRODUCTION_RULE"
        request_started = perf_counter()
        requests = generate_requests(topology_id, pairs, [2, 3, 5, 9], request_rng)
        request_seconds = perf_counter()-request_started
        write_jsonl(env/"requests/single"/f"requests_{topology_id}.jsonl", requests)
        derivation_started = perf_counter()
        deriver = RequestDeriver.from_objects(physical, medium_state, request_cfg["candidate_path_k"])
        derivations = [deriver.derive(request) for request in requests]
        derivation_seconds = perf_counter()-derivation_started
        write_jsonl(env/"requests/derivation"/f"derivations_{topology_id}.jsonl", derivations)
        request_index = {item["request_id"]: item for item in requests}
        derivation_index = {item["request_id"]: item for item in derivations}
        selected = request_rng.sample(requests, 12)
        concurrent = []
        for set_index in range(3):
            request_ids = [item["request_id"] for item in selected[set_index*4:(set_index+1)*4]]
            item = build_concurrent_request_set(
                f"reqset_{topology_id[4:]}_{set_index+1:02d}", request_ids,
                request_index, derivation_index, medium_state["resource_state_id"],
            )
            concurrent.append(item)
            write_json(env/"requests/concurrent"/f"{item['request_set_id']}.json", item)
        sequence = generate_dynamic_sequence(
            topology_id, len(physical["node_records"]), medium_state["reference_time"],
            request_cfg["dynamic_arrival_rate_lambda"], request_cfg["dynamic_holding_time_rate_mu"],
            [2, 3, 5, 9], request_rng, request_cfg["dynamic_sequence_length"],
        )
        write_json(env/"requests/dynamic"/f"{sequence['request_sequence_id']}.json", sequence)
        scenarios = _scenarios(
            topology_id, medium_state["resource_state_id"],
            medium_connection["initial_existing_connection_set_id"], requests[0]["request_id"],
            concurrent[0]["request_set_id"], sequence["request_sequence_id"],
        )
        for scenario in scenarios:
            write_json(env/"scenarios"/f"{scenario['base_scenario_id']}.json", scenario)
        generation_configs.extend([
            _config(f"genconf_{topology_id[4:]}_request", "REQUEST", topology_id,
                    {"request_policy": request_policy, "request_count": len(requests),
                     "candidate_path_k": request_cfg["candidate_path_k"],
                     "resource_state_id": medium_state["resource_state_id"],
                     "n_gt_100_sample_count_status": request_cfg["n_gt_100_sample_count_status"]},
                    [topology_id, medium_state["resource_state_id"]], 202608072000+topology_index, True),
            _config(f"genconf_{topology_id[4:]}_scenario", "BASE_SCENARIO", topology_id,
                    {"scenario_types": ["NONE", "SINGLE", "CONCURRENT", "DYNAMIC"]},
                    [topology_id, medium_state["resource_state_id"],
                     medium_connection["initial_existing_connection_set_id"], requests[0]["request_id"],
                     concurrent[0]["request_set_id"], sequence["request_sequence_id"]]),
        ])
        coverage_rows.append(_coverage_row(name, topology_id, requests, derivations, concurrent, request_policy))
        object_counts["requests"] += len(requests)
        object_counts["request_derivations"] += len(derivations)
        object_counts["concurrent_request_sets"] += len(concurrent)
        object_counts["dynamic_sequences"] += 1
        object_counts["dynamic_events"] += len(sequence["dynamic_request_events"])
        object_counts["base_scenarios"] += len(scenarios)
        scaling_rows.append({
            "topology_name": name, "topology_id": topology_id, "node_count": metrics["node_count"],
            "physical_link_count": metrics["physical_link_count"], "topology_read_seconds": import_seconds,
            "topology_metric_seconds": metric_seconds,
            "resource_state_total_seconds": sum(item["runtime_seconds"] for item in experiment_timings),
            "resource_state_count": len(experiment_timings), "request_count": len(requests),
            "request_pool_seconds": request_seconds, "request_derivation_seconds": derivation_seconds,
            "request_jsonl_bytes": (env/"requests/single"/f"requests_{topology_id}.jsonl").stat().st_size,
            "derivation_jsonl_bytes": (env/"requests/derivation"/f"derivations_{topology_id}.jsonl").stat().st_size,
        })
        topologies[topology_id] = {"name": name, "physical": physical, "directed": directed, "metrics": metrics}
    for item in generation_configs:
        write_json(env/"configs"/f"{item['generation_config_id']}.json", item)
    object_counts["generation_configs"] = len(generation_configs)
    # Resource metric summaries and correlations.
    write_csv(output_root/"audit/metric_sufficiency"/"resource_state_metrics_all.csv", resource_rows)
    write_csv(output_root/"audit/metric_sufficiency"/"resource_state_metric_summary.csv",
              numeric_summary(resource_rows, RESOURCE_FIELDS))
    write_csv(output_root/"audit/metric_sufficiency"/"resource_metric_pearson.csv",
              correlation_matrix(resource_rows, RESOURCE_FIELDS, "PEARSON"))
    write_csv(output_root/"audit/metric_sufficiency"/"resource_metric_spearman.csv",
              correlation_matrix(resource_rows, RESOURCE_FIELDS, "SPEARMAN"))
    matched = []
    for name in names:
        base = next((row for row in resource_rows if row["topology_name"] == name and
                     row["profile"] == "BASE_KSP_FF" and row["seed_role"] == "BASELINE_FIRST_SEED" and
                     row["load_band_name"] == "MEDIUM"), None)
        if base:
            for profile in ("KSP_RF_PILOT", "LOAD_BALANCED_KSP_FF_PILOT"):
                alternate = next((row for row in resource_rows if row["topology_name"] == name and
                                  row["profile"] == profile), None)
                if alternate:
                    record = {"topology_name": name, "comparison_profile": profile}
                    for field in RESOURCE_FIELDS[:5]:
                        record[f"base_{field}"] = base.get(field)
                        record[f"profile_{field}"] = alternate.get(field)
                        record[f"difference_{field}"] = alternate.get(field)-base.get(field)
                    matched.append(record)
    stability = []
    for name in names:
        first = next(row for row in resource_rows if row["topology_name"] == name and
                     row["seed_role"] == "BASELINE_FIRST_SEED" and row["load_band_name"] == "MEDIUM")
        second = next(row for row in resource_rows if row["topology_name"] == name and
                      row["seed_role"] == "STABILITY_SECOND_SEED")
        record = {"topology_name": name}
        for field in RESOURCE_FIELDS:
            difference = abs(second[field]-first[field]) if first.get(field) is not None and second.get(field) is not None else None
            record[f"absolute_difference_{field}"] = difference
            record[f"relative_difference_{field}"] = (
                None if difference is None or abs(first[field]) <= 1e-12 else difference/abs(first[field])
            )
        stability.append(record)
    write_csv(output_root/"audit/metric_sufficiency"/"matched_profile_comparison.csv", matched)
    write_csv(output_root/"audit/metric_sufficiency"/"seed_stability.csv", stability)
    write_csv(output_root/"audit/metric_sufficiency"/"request_stratum_coverage.csv", coverage_rows)
    write_csv(output_root/"audit/scaling"/"production_scaling.csv", scaling_rows)
    write_json(output_root/"audit/metric_sufficiency"/"state_experiment_summary.json", {
        "experiment_count": len(state_trace_summary),
        "target_reached_count": sum(item["target_reached"] for item in state_trace_summary),
        "target_unreached_count": sum(not item["target_reached"] for item in state_trace_summary),
        "unreached": [{key: item[key] for key in ("topology_id", "topology_name", "resource_state_id",
                                                    "profile", "load_band_name", "target_band")}
                      for item in state_trace_summary if not item["target_reached"]],
    })
    return {"object_counts": object_counts, "resource_rows": resource_rows,
            "coverage_rows": coverage_rows, "scaling_rows": scaling_rows,
            "state_trace_summary": state_trace_summary, "topologies": topologies}
