"""One-topology end-to-end PUBLIC_ENVIRONMENT V1.0 production runner.

This is the human-readable orchestration layer.  Scientific calculations stay
in the focused topology, simulation, request and validation modules; this file
makes their execution order explicit and writes auditable production records.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from random import Random
import shutil
from time import perf_counter
from typing import Any

from src.multi_topology.reporting import write_json, write_jsonl
from src.multi_topology.requests import (
    RequestDeriver,
    generate_requests,
    ordered_request_pairs,
    stratified_request_pairs_v1,
)
from src.multi_topology.simulation import LoadSearchProtocol, PathCatalog, search_snapshot_v1
from src.multi_topology.validation import validate_multi_environment
from src.pipeline import build_concurrent_request_set
from src.production.config import ProductionConfig, TopologySpec
from src.production.topology_input import load_and_build_topology
from src.production.isolated_trial import isolated_trial_runner
from src.production.dynamic import resolve_dynamic_conditions
from scripts.validate_schemas import run_manifest


GENERATOR_NAME = "PUBLIC_ENVIRONMENT_PRODUCTION_RUNNER"
GENERATOR_VERSION = "1.0.0-reconstructed-control"


class ProductionUnitError(RuntimeError):
    """Raised when one topology cannot pass a mandatory production gate."""


def _stable_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_tree(root: Path) -> Path:
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty production unit: {root}")
    root.mkdir(parents=True, exist_ok=True)
    env = root / "public_environment"
    for relative in (
        "topologies/physical", "topologies/directed", "metrics/topology",
        "connections/initial", "states/spectrum", "requests/single",
        "requests/derivation", "requests/concurrent", "requests/dynamic",
        "scenarios", "configs",
    ):
        (env / relative).mkdir(parents=True, exist_ok=True)
    for relative in ("reports/load_search", "reports", "private/source_mappings"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return env


def _generation_config(
    *, config_id: str, stage: str, topology_id: str, parameter_values: dict,
    source_ids: list[str], seed: int | None = None, traffic: bool = False,
) -> dict:
    obj: dict[str, Any] = {
        "generation_config_id": config_id,
        "production_stage": stage,
        "topology_id": topology_id,
        "parameter_values": parameter_values,
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "source_data_ids": source_ids,
    }
    if seed is not None:
        obj["random_seed"] = seed
    if traffic:
        obj.update({
            "time_unit": "SIMULATION_TIME_UNIT",
            "payload_slot_values": [1, 2, 4, 8],
            "payload_slot_distribution": "UNIFORM",
            "payload_slot_probabilities": [0.25, 0.25, 0.25, 0.25],
            "guard_band_slots": 1,
        })
    return obj


def _dynamic_sequence(
    *, topology_id: str, sequence_index: int, node_count: int, reference_time: float,
    arrival_rate: float, holding_rate: float, required_slots: tuple[int, ...], seed: int,
    length: int, generation_context: dict,
) -> dict:
    rng = Random(seed)
    now = reference_time
    events: list[dict] = []
    for index in range(1, length + 1):
        now += rng.expovariate(arrival_rate)
        source = rng.randrange(node_count)
        destination = rng.randrange(node_count - 1)
        if destination >= source:
            destination += 1
        events.append({
            "request_id": f"dynreq_{topology_id[4:]}_{sequence_index:03d}_{index:06d}",
            "source_node_id": source,
            "destination_node_id": destination,
            "required_slots": rng.choice(required_slots),
            "arrival_time": now,
            "holding_time": rng.expovariate(holding_rate),
        })
    return {
        "request_sequence_id": f"seq_{topology_id[4:]}_{sequence_index:03d}",
        "dynamic_request_events": events,
        "arrival_rate_lambda": arrival_rate,
        "holding_time_rate_mu": holding_rate,
        "generation_context": dict(generation_context),
    }


def _policy_audit(config: ProductionConfig) -> dict:
    return {
        "official_to_engine_mapping": [
            {"official_name": job.policy, "engine_policy_id": job.engine_policy_id, "job_id": job.job_id}
            for job in config.resource_state_jobs
        ],
        "semantics": {
            "KSP-FF": "Try K=5 candidate paths in exact KSP rank order; use the first path with a feasible contiguous block; choose the smallest feasible slot_start (First-Fit).",
            "KSP-RF": "Enumerate all feasible (candidate path, slot_start) actions over K=5 and select uniformly with the independent random-policy RNG stream.",
            "Load-Balanced KSP-FF": "Choose the KSP candidate with lowest current mean link utilization, tie-break by KSP rank, then First-Fit on that chosen path only; no fallback to another path when the chosen path is spectrum-infeasible.",
        },
        "ksp_pfa_status": "OUT_OF_SCOPE",
        "od_distribution": "UNIFORM_ONLY",
    }


def _manifest(root: Path) -> dict:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name not in {"SHA256SUMS.txt", "MANIFEST.json"}):
        files.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return {"schema_version": "PUBLIC_ENV_UNIT_MANIFEST_V1_0", "file_count": len(files), "files": files}


def _write_hashes(root: Path) -> None:
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        lines.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_one_topology(
    config: ProductionConfig,
    topology_spec: TopologySpec,
    output_root: Path | str,
    *,
    protocol: LoadSearchProtocol | None = None,
) -> dict:
    """Produce and validate one topology's complete public environment.

    ``protocol`` is intentionally not exposed by the CLI.  It is only an
    injection point for fast tests; normal production always gets the frozen
    default LOAD_SEARCH_V1_0 protocol.
    """
    started = perf_counter()
    output_root = Path(output_root).resolve()
    env = _prepare_tree(output_root)
    profile = config.scientific_profile
    use_isolated_trials = protocol is None
    protocol = protocol or LoadSearchProtocol()

    # Step 1-3: canonical topology, directed-resource expansion and metrics.
    topology_started = perf_counter()
    artifacts = load_and_build_topology(topology_spec)
    physical, directed, metrics = artifacts.physical, artifacts.directed, artifacts.metrics
    node_count = metrics["node_count"]
    if node_count > profile.max_supported_node_count:
        raise ProductionUnitError(
            f"N={node_count} exceeds V1.0 formal support boundary N<={profile.max_supported_node_count}"
        )
    write_json(env / f"topologies/physical/{topology_spec.topology_id}.json", physical)
    write_json(env / f"topologies/directed/{topology_spec.topology_id}.json", directed)
    write_json(env / f"metrics/topology/{topology_spec.topology_id}.json", metrics)
    write_json(output_root / f"private/source_mappings/{topology_spec.topology_id}.json", artifacts.private_mapping)
    topology_seconds = perf_counter() - topology_started

    source_sha = _sha256(topology_spec.source_path)
    topology_gen = _generation_config(
        config_id=f"genconf_{topology_spec.topology_id[4:]}_topology",
        stage="TOPOLOGY", topology_id=topology_spec.topology_id,
        parameter_values={
            "source_type": topology_spec.source_type,
            "source_file": str(topology_spec.source_path),
            "source_sha256": source_sha,
            "unknown_distance_unit_policy": "OMIT_LENGTH_KM",
            "continuous_zero_based_ids": True,
        },
        source_ids=[source_sha],
    )
    write_json(env / f"configs/{topology_gen['generation_config_id']}.json", topology_gen)

    # Step 4-7: every requested policy x band x seed is calibrated independently.
    edges = [(item["node_u_id"], item["node_v_id"]) for item in physical["physical_link_records"]]
    catalog = PathCatalog.from_edges(node_count, edges, profile.candidate_path_k, cache_capacity=32768)
    state_results: dict[str, dict] = {}
    connection_results: dict[str, dict] = {}
    selected_state_lambdas: dict[str, float] = {}
    load_search_audit: list[dict] = []
    for job in config.resource_state_jobs:
        state_id = f"rs_{topology_spec.topology_id[4:]}_{job.job_id}"
        connection_id = f"icset_{topology_spec.topology_id[4:]}_{job.job_id}"
        search = search_snapshot_v1(
            topology_id=topology_spec.topology_id,
            state_id=state_id,
            connection_set_id=connection_id,
            catalog=catalog,
            node_count=node_count,
            link_count=metrics["directed_link_count"],
            slot_count=profile.slot_count,
            holding_rate=profile.holding_time_rate_mu,
            payload_values=list(profile.payload_slot_values),
            payload_probabilities=list(profile.payload_slot_probabilities),
            guard_slots=profile.guard_band_slots,
            target_band=job.target_band,
            policy=job.engine_policy_id,
            seed=job.seed,
            confirmation_seed=job.confirmation_seed,
            average_shortest_path_hops=metrics["average_shortest_path_hops"],
            protocol=protocol,
            trial_runner=isolated_trial_runner if use_isolated_trials else None,
        )
        trace = {
            "job_id": job.job_id,
            "official_policy": job.policy,
            "engine_policy_id": job.engine_policy_id,
            "load_band": job.load_band,
            "target_band": list(job.target_band),
            "seed": job.seed,
            "confirmation_seed": job.confirmation_seed,
            "lambda0": search.lambda0,
            "final_status": search.status,
            "reason": search.reason,
            "selected_lambda": search.actual_arrival_rate_lambda,
            "selected_snapshot_request_index": search.snapshot_request_index,
            "selected_snapshot_utilization": search.snapshot_utilization,
            "preferred_region_hit": search.preferred_region_hit,
            "band_fallback": search.band_fallback,
            "audit_metrics": search.audit_metrics,
            "trials": search.trials,
        }
        write_json(output_root / f"reports/load_search/{job.job_id}.json", trace)
        load_search_audit.append(trace)
        if search.status != "TARGET_REACHED" or search.connection_set is None or search.resource_state is None:
            write_json(output_root / "reports/LOAD_SEARCH_AUDIT.json", {"pass": False, "jobs": load_search_audit})
            raise ProductionUnitError(f"LOAD_SEARCH failed for {job.job_id}: {search.status} ({search.reason})")
        write_json(env / f"connections/initial/{connection_id}.json", search.connection_set)
        write_json(env / f"states/spectrum/{state_id}.json", search.resource_state)
        state_results[job.job_id] = search.resource_state
        connection_results[job.job_id] = search.connection_set
        selected_state_lambdas[job.job_id] = float(search.actual_arrival_rate_lambda)
        state_gen = _generation_config(
            config_id=f"genconf_{topology_spec.topology_id[4:]}_state_{job.job_id}",
            stage="RESOURCE_STATE", topology_id=topology_spec.topology_id,
            parameter_values={
                "official_policy": job.policy,
                "engine_policy_id": job.engine_policy_id,
                "load_band": job.load_band,
                "target_band": list(job.target_band),
                "slot_count": profile.slot_count,
                "candidate_path_k": profile.candidate_path_k,
                "holding_time_rate_mu": profile.holding_time_rate_mu,
                "selected_arrival_rate_lambda": search.actual_arrival_rate_lambda,
                "load_search_protocol": "LOAD_SEARCH_V1_0",
                "load_search_status": search.status,
                "band_fallback": search.band_fallback,
            },
            source_ids=[topology_spec.topology_id], seed=job.seed, traffic=True,
        )
        write_json(env / f"configs/{state_gen['generation_config_id']}.json", state_gen)
    write_json(output_root / "reports/LOAD_SEARCH_AUDIT.json", {"pass": True, "jobs": load_search_audit})

    # Step 8-10: formal request pool and RequestDerivation on the frozen anchor state.
    request_started = perf_counter()
    request_rng = Random(_stable_seed(config.request_generation.seed, f"{topology_spec.topology_id}|request_demand"))
    if node_count <= 100:
        pairs = ordered_request_pairs(node_count)
        sampling_audit = {
            "sampling_policy": "ALL_ORDERED_SOURCE_DESTINATION_PAIRS",
            "population_size": len(pairs), "sample_size": len(pairs), "repair_count": 0,
            "coverage_after": {"all_sources_covered": True, "all_destinations_covered": True},
        }
    else:
        sampling_rng = Random(_stable_seed(config.request_generation.seed, f"{topology_spec.topology_id}|od_sampling"))
        pairs, sampling_audit = stratified_request_pairs_v1(
            node_count, edges, profile.request_sampling_n_gt_100, sampling_rng
        )
    requests = generate_requests(
        topology_spec.topology_id, pairs, list(profile.required_slot_values), request_rng
    )
    write_jsonl(env / f"requests/single/requests_{topology_spec.topology_id}.jsonl", requests)
    anchor_job_id = config.request_generation.derivation_anchor_job_id
    anchor_state = state_results[anchor_job_id]
    anchor_connection = connection_results[anchor_job_id]
    deriver = RequestDeriver.from_objects(physical, anchor_state, profile.candidate_path_k)
    derivations = [deriver.derive(request) for request in requests]
    write_jsonl(env / f"requests/derivation/derivations_{topology_spec.topology_id}.jsonl", derivations)
    request_seconds = perf_counter() - request_started
    sampling_audit.update({
        "topology_id": topology_spec.topology_id,
        "request_count": len(requests),
        "derivation_anchor_job_id": anchor_job_id,
        "derivation_anchor_resource_state_id": anchor_state["resource_state_id"],
    })
    write_json(output_root / "reports/REQUEST_SAMPLING_AUDIT.json", sampling_audit)
    request_gen = _generation_config(
        config_id=f"genconf_{topology_spec.topology_id[4:]}_request",
        stage="REQUEST", topology_id=topology_spec.topology_id,
        parameter_values={
            "request_policy": sampling_audit["sampling_policy"],
            "request_count": len(requests),
            "candidate_path_k": profile.candidate_path_k,
            "derivation_anchor_job_id": anchor_job_id,
            "resource_state_id": anchor_state["resource_state_id"],
            "required_slots_include_guard": True,
        },
        source_ids=[topology_spec.topology_id, anchor_state["resource_state_id"]],
        seed=config.request_generation.seed, traffic=True,
    )
    write_json(env / f"configs/{request_gen['generation_config_id']}.json", request_gen)

    request_index = {item["request_id"]: item for item in requests}
    derivation_index = {item["request_id"]: item for item in derivations}

    # Step 11: optional concurrent sets. Counts are task-sheet variables, not frozen science constants.
    concurrent_items: list[dict] = []
    if config.concurrent.enabled:
        concurrent_rng = Random(_stable_seed(config.concurrent.seed, topology_spec.topology_id))
        if config.concurrent.requests_per_set > len(requests):
            raise ProductionUnitError("concurrent.requests_per_set exceeds request pool size")
        for set_index in range(1, config.concurrent.set_count + 1):
            selected = concurrent_rng.sample(requests, config.concurrent.requests_per_set)
            request_ids = [item["request_id"] for item in selected]
            request_set_id = f"reqset_{topology_spec.topology_id[4:]}_{set_index:04d}"
            item = build_concurrent_request_set(
                request_set_id, request_ids, request_index, derivation_index, anchor_state["resource_state_id"]
            )
            concurrent_items.append(item)
            write_json(env / f"requests/concurrent/{request_set_id}.json", item)

    # Step 12: dynamic sequences are explicitly coupled to calibrated initial-state load.
    # No release_time is serialized; the evaluator derives it privately from arrival+holding time.
    dynamic_items: list[dict] = []
    dynamic_conditions = []
    if config.dynamic.enabled:
        jobs_by_id = {job.job_id: job for job in config.resource_state_jobs}
        dynamic_conditions = resolve_dynamic_conditions(config.dynamic, jobs_by_id, selected_state_lambdas)
        sequence_index = 0
        for condition in dynamic_conditions:
            condition_state = state_results[condition.anchor_job_id]
            for replicate_index in range(1, config.dynamic.sequences_per_condition + 1):
                sequence_index += 1
                generation_context = {
                    "anchor_job_id": condition.anchor_job_id,
                    "initial_load_band": condition.initial_load_band,
                    "state_arrival_rate_lambda": condition.state_arrival_rate_lambda,
                    "dynamic_arrival_rate_lambda": condition.arrival_rate_lambda,
                    "arrival_rate_mode": condition.arrival_rate_mode,
                    "requested_arrival_rate_multiplier": condition.arrival_rate_multiplier,
                    "lambda_ratio": condition.lambda_ratio,
                }
                seed_label = (
                    f"{topology_spec.topology_id}|{condition.anchor_job_id}|"
                    f"{condition.arrival_rate_mode}|{condition.lambda_ratio:.12g}|{replicate_index}"
                )
                item = _dynamic_sequence(
                    topology_id=topology_spec.topology_id,
                    sequence_index=sequence_index,
                    node_count=node_count,
                    reference_time=condition_state["reference_time"],
                    arrival_rate=condition.arrival_rate_lambda,
                    holding_rate=profile.holding_time_rate_mu,
                    required_slots=profile.required_slot_values,
                    seed=_stable_seed(config.dynamic.seed, seed_label),
                    length=config.dynamic.sequence_length,
                    generation_context=generation_context,
                )
                dynamic_items.append(item)
                write_json(env / f"requests/dynamic/{item['request_sequence_id']}.json", item)
        dynamic_gen = _generation_config(
            config_id=f"genconf_{topology_spec.topology_id[4:]}_dynamic",
            stage="DYNAMIC_REQUEST", topology_id=topology_spec.topology_id,
            parameter_values={
                "anchor_job_ids": list(config.dynamic.anchor_job_ids),
                "arrival_rate_mode": config.dynamic.arrival_rate_mode,
                "arrival_rate_multipliers": list(config.dynamic.arrival_rate_multipliers),
                "absolute_arrival_rate_lambda": config.dynamic.arrival_rate_lambda,
                "sequences_per_condition": config.dynamic.sequences_per_condition,
                "sequence_length": config.dynamic.sequence_length,
                "resolved_conditions": [
                    {
                        "anchor_job_id": c.anchor_job_id,
                        "initial_load_band": c.initial_load_band,
                        "state_arrival_rate_lambda": c.state_arrival_rate_lambda,
                        "dynamic_arrival_rate_lambda": c.arrival_rate_lambda,
                        "arrival_rate_mode": c.arrival_rate_mode,
                        "requested_arrival_rate_multiplier": c.arrival_rate_multiplier,
                        "lambda_ratio": c.lambda_ratio,
                    } for c in dynamic_conditions
                ],
            },
            source_ids=[state_results[job_id]["resource_state_id"] for job_id in config.dynamic.anchor_job_ids],
            seed=config.dynamic.seed, traffic=True,
        )
        write_json(env / f"configs/{dynamic_gen['generation_config_id']}.json", dynamic_gen)

    # Step 13: BaseScenario index. Every single request gets a direct scene; each
    # state also gets a state-only NONE scene; concurrent/dynamic data get scenes.
    scenarios: list[dict] = []
    for job in config.resource_state_jobs:
        state = state_results[job.job_id]
        connection = connection_results[job.job_id]
        scenarios.append({
            "base_scenario_id": f"bs_{topology_spec.topology_id[4:]}_state_{job.job_id}",
            "topology_id": topology_spec.topology_id,
            "resource_state_id": state["resource_state_id"],
            "initial_existing_connection_set_id": connection["initial_existing_connection_set_id"],
            "request_data_type": "NONE",
        })
    for request in requests:
        scenarios.append({
            "base_scenario_id": f"bs_{topology_spec.topology_id[4:]}_single_{request['request_id'].split('_')[-1]}",
            "topology_id": topology_spec.topology_id,
            "resource_state_id": anchor_state["resource_state_id"],
            "initial_existing_connection_set_id": anchor_connection["initial_existing_connection_set_id"],
            "request_data_type": "SINGLE",
            "request_data_id": request["request_id"],
        })
    for item in concurrent_items:
        scenarios.append({
            "base_scenario_id": f"bs_{item['request_set_id'][7:]}_concurrent",
            "topology_id": topology_spec.topology_id,
            "resource_state_id": anchor_state["resource_state_id"],
            "initial_existing_connection_set_id": anchor_connection["initial_existing_connection_set_id"],
            "request_data_type": "CONCURRENT",
            "request_data_id": item["request_set_id"],
        })
    for item in dynamic_items:
        dynamic_anchor_job_id = item["generation_context"]["anchor_job_id"]
        dynamic_state = state_results[dynamic_anchor_job_id]
        dynamic_connection = connection_results[dynamic_anchor_job_id]
        scenarios.append({
            "base_scenario_id": f"bs_{item['request_sequence_id'][4:]}_dynamic",
            "topology_id": topology_spec.topology_id,
            "resource_state_id": dynamic_state["resource_state_id"],
            "initial_existing_connection_set_id": dynamic_connection["initial_existing_connection_set_id"],
            "request_data_type": "DYNAMIC",
            "request_data_id": item["request_sequence_id"],
        })
    for scene in scenarios:
        write_json(env / f"scenarios/{scene['base_scenario_id']}.json", scene)
    scenario_gen = _generation_config(
        config_id=f"genconf_{topology_spec.topology_id[4:]}_scenario",
        stage="BASE_SCENARIO", topology_id=topology_spec.topology_id,
        parameter_values={
            "single_scenario_count": len(requests),
            "concurrent_scenario_count": len(concurrent_items),
            "dynamic_scenario_count": len(dynamic_items),
            "state_only_scenario_count": len(config.resource_state_jobs),
        },
        source_ids=[topology_spec.topology_id, anchor_state["resource_state_id"]],
    )
    write_json(env / f"configs/{scenario_gen['generation_config_id']}.json", scenario_gen)

    # Step 14: independent schema + cross-file/reconstruction/dynamic replay gates.
    project_root = Path(__file__).resolve().parents[2]
    schema_audit = run_manifest(project_root / "schemas/schema_manifest.json", env)
    schema_pass = schema_audit["summary"]["invalid"] == 0
    write_json(output_root / "reports/SCHEMA_AUDIT.json", schema_audit)
    cross_file = validate_multi_environment(env)
    write_json(output_root / "reports/CROSS_FILE_AUDIT.json", cross_file)
    if not schema_pass or not cross_file["pass"]:
        raise ProductionUnitError(
            f"validation failed: schema_pass={schema_pass}, cross_file_pass={cross_file['pass']}"
        )

    policy_audit = _policy_audit(config)
    write_json(output_root / "reports/POLICY_AUDIT.json", policy_audit)
    object_counts = {
        "physical_topologies": 1,
        "directed_topologies": 1,
        "topology_metrics": 1,
        "connection_sets": len(connection_results),
        "resource_states": len(state_results),
        "requests": len(requests),
        "request_derivations": len(derivations),
        "concurrent_request_sets": len(concurrent_items),
        "dynamic_sequences": len(dynamic_items),
        "dynamic_events": sum(len(item["dynamic_request_events"]) for item in dynamic_items),
        "base_scenarios": len(scenarios),
    }
    acceptance = {
        "schema_version": "PUBLIC_ENV_UNIT_ACCEPTANCE_V1_0",
        "status": "PASS",
        "batch_id": config.batch_id,
        "topology_id": topology_spec.topology_id,
        "source_path": str(topology_spec.source_path),
        "source_sha256": source_sha,
        "node_count": node_count,
        "physical_link_count": metrics["physical_link_count"],
        "directed_link_count": metrics["directed_link_count"],
        "config_sha256": config.config_sha256,
        "load_search_pass": True,
        "schema_pass": schema_pass,
        "cross_file_validation_pass": cross_file["pass"],
        "state_reconstruction_pass": cross_file["state_reconstruction_pass"],
        "spectrum_metric_recomputation_pass": cross_file["spectrum_metric_recomputation_pass"],
        "dynamic_replay_pass": cross_file["dynamic_replay_pass"],
        "request_sampling_policy": sampling_audit["sampling_policy"],
        "request_count": len(requests),
        "object_counts": object_counts,
        "topology_seconds": topology_seconds,
        "request_and_derivation_seconds": request_seconds,
        "runtime_seconds": perf_counter() - started,
        "ksp_backend": "NUMBA_EXACT_YEN_V2_RECONSTRUCTED",
        "ksp_fast_fallback_count": catalog.fast_fallback_count,
    }
    write_json(output_root / "reports/UNIT_ACCEPTANCE.json", acceptance)
    summary_md = f"""# 单拓扑生产结果\n\n- 状态：**PASS**\n- topology_id：`{topology_spec.topology_id}`\n- 节点数：{node_count}\n- 物理链路数：{metrics['physical_link_count']}\n- 有向链路数：{metrics['directed_link_count']}\n- 资源状态数：{len(state_results)}\n- Request：{len(requests)}\n- RequestDerivation：{len(derivations)}\n- ConcurrentRequestSet：{len(concurrent_items)}\n- DynamicRequestSequence：{len(dynamic_items)}\n- BaseScenario：{len(scenarios)}\n- Schema：PASS\n- 跨文件/状态重构/指标复算/动态回放：PASS\n- KSP 快路径回退次数：{catalog.fast_fallback_count}\n"""
    (output_root / "reports/PRODUCTION_SUMMARY.md").write_text(summary_md, encoding="utf-8")

    manifest = _manifest(output_root)
    write_json(output_root / "MANIFEST.json", manifest)
    _write_hashes(output_root)
    return acceptance
