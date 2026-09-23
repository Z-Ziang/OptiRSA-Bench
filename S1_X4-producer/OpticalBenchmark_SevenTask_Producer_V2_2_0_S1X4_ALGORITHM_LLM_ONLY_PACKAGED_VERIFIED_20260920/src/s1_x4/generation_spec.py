from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "S1_X4_DYNAMIC_GENERATION_SPEC_V1_0"
PUBLIC_GENERATION_SPEC_SCHEMA_VERSION = "S1_X4_PUBLIC_GENERATION_SPEC_V2_0"
PUBLIC_GENERATION_SPEC_KEYS = frozenset(
    {
        "schema_version",
        "generation_spec_id",
        "topology_id",
        "condition_id",
        "resource_config",
        "initial_state_generation",
        "request_generation",
        "dynamic_generation",
        "seed_block",
    }
)
PUBLIC_GENERATION_SPEC_NESTED_KEYS = {
    "resource_config": frozenset({"episode_length", "slot_count", "guard_band_slots"}),
    "initial_state_generation": frozenset({"load_band", "policy", "candidate_path_k", "state_arrival_rate_lambda"}),
    "request_generation": frozenset({"od_distribution", "payload_slot_values", "required_slot_values", "slot_probabilities"}),
    "dynamic_generation": frozenset({"arrival_rate_mode", "arrival_rate_multiplier", "dynamic_arrival_rate_lambda", "holding_time_rate_mu"}),
}
FROZEN_TOPOLOGIES: tuple[str, ...] = (
    "topologybench_netrail",
    "topologybench_elibackbone",
    "topologybench_jpn48",
    "topologybench_conus75",
    "topohub_gabriel_125_0",
    "topohub_gabriel_175_2",
    "topohub_gabriel_250_3",
    "topohub_gabriel_375_3",
    "topohub_gabriel_450_9",
)
FROZEN_CONDITIONS: tuple[str, ...] = (
    "A_MEDIUM_MATCH",
    "B_HIGH_MATCH",
    "C_HIGH_X1P2",
)
FROZEN_SEED_BLOCKS: dict[str, dict[str, int]] = {
    "A_MEDIUM_MATCH": {
        "state_seed": 5101,
        "request_seed": 6101,
        "dynamic_seed": 8101,
        "confirmation_seed": 9101,
    },
    "B_HIGH_MATCH": {
        "state_seed": 5102,
        "request_seed": 6102,
        "dynamic_seed": 8102,
        "confirmation_seed": 9102,
    },
    "C_HIGH_X1P2": {
        "state_seed": 5103,
        "request_seed": 6103,
        "dynamic_seed": 8103,
        "confirmation_seed": 9103,
    },
}
FROZEN_CONDITION_FIELDS: dict[str, dict[str, Any]] = {
    "A_MEDIUM_MATCH": {
        "load_band": "MEDIUM",
        "arrival_rate_mode": "MATCH_STATE",
        "arrival_rate_multiplier": 1.0,
    },
    "B_HIGH_MATCH": {
        "load_band": "HIGH",
        "arrival_rate_mode": "MATCH_STATE",
        "arrival_rate_multiplier": 1.0,
    },
    "C_HIGH_X1P2": {
        "load_band": "HIGH",
        "arrival_rate_mode": "MULTIPLIER_OF_STATE",
        "arrival_rate_multiplier": 1.2,
    },
}


def frozen_matrix_keys() -> list[tuple[str, str]]:
    return [(topology, condition) for topology in FROZEN_TOPOLOGIES for condition in FROZEN_CONDITIONS]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical(value))


def _read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_sha256(path: Path | str) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _tree_sha256(root: Path | str) -> str:
    base = Path(root).resolve()
    digest = hashlib.sha256()
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        relative = path.relative_to(base).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _without_runtime_paths(value: Any) -> Any:
    ignored = {
        "source_path",
        "output_path",
        "output_dir",
        "work_dir",
        "runtime_path",
        "log_path",
    }
    if isinstance(value, dict):
        return {
            str(key): _without_runtime_paths(child)
            for key, child in value.items()
            if str(key) not in ignored
        }
    if isinstance(value, list):
        return [_without_runtime_paths(child) for child in value]
    return value


def _episode_scientific_payload(episode: Mapping[str, Any]) -> dict[str, Any]:
    """Return the task-independent, reproducibility-bearing Episode fields."""

    keys = (
        "topology_id",
        "resource_state_id",
        "initial_existing_connection_set_id",
        "request_sequence_id",
        "source_base_scenario_id",
        "nodes",
        "directed_links",
        "slot_count",
        "initial_link_spectrum_states",
        "initial_existing_connections",
        "episode_length",
        "request_events",
        "initial_reference_time",
        "holding_time_rate_mu",
        "difficulty_context",
        "pairing_id",
    )
    return {key: episode[key] for key in keys if key in episode}


def episode_scientific_fingerprint(episode: Mapping[str, Any]) -> str:
    """Hash the shared underlying realization, excluding task/case view fields."""

    return _sha256_json(_episode_scientific_payload(episode))


def _config_value(config: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in config:
            return config[key]
    return default


def _first_resource_job(config: Mapping[str, Any], preferred_job_id: str | None = None) -> Mapping[str, Any]:
    jobs = config.get("resource_state_jobs")
    if isinstance(jobs, list) and jobs and isinstance(jobs[0], Mapping):
        if preferred_job_id:
            for job in jobs:
                if isinstance(job, Mapping) and job.get("job_id") == preferred_job_id:
                    return job
        return jobs[0]
    return {}


def _condition_fields(condition_id: str, config: Mapping[str, Any], episode: Mapping[str, Any]) -> dict[str, Any]:
    fixed = dict(FROZEN_CONDITION_FIELDS.get(condition_id, {}))
    dynamic = config.get("dynamic") if isinstance(config.get("dynamic"), Mapping) else {}
    difficulty = episode.get("difficulty_context") if isinstance(episode.get("difficulty_context"), Mapping) else {}
    fixed["load_band"] = fixed.get("load_band", _first_resource_job(config).get("load_band", difficulty.get("initial_load_band")))
    fixed["arrival_rate_mode"] = fixed.get("arrival_rate_mode", dynamic.get("arrival_rate_mode", difficulty.get("arrival_rate_mode")))
    fixed["arrival_rate_multiplier"] = fixed.get(
        "arrival_rate_multiplier",
        difficulty.get("requested_arrival_rate_multiplier", 1.0),
    )
    return fixed


def build_generation_spec(
    *,
    topology_id: str,
    condition_id: str,
    production_config: Mapping[str, Any],
    episode: Mapping[str, Any],
    canonical_topology_sha256: str,
    source_environment_tree_sha256: str | None = None,
    paired_episode: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one canonical spec from actual production evidence and an Episode."""

    if str(episode.get("topology_id")) != str(topology_id):
        raise ValueError("episode topology_id does not match generation spec")
    if not isinstance(canonical_topology_sha256, str) or len(canonical_topology_sha256) != 64:
        raise ValueError("canonical_topology_sha256 must be a SHA256 hex string")
    config = dict(production_config)
    dynamic = config.get("dynamic") if isinstance(config.get("dynamic"), Mapping) else {}
    anchor_ids = dynamic.get("anchor_job_ids") if isinstance(dynamic.get("anchor_job_ids"), list) else []
    job = _first_resource_job(config, str(anchor_ids[0]) if anchor_ids else None)
    profile = config.get("scientific_profile") if isinstance(config.get("scientific_profile"), Mapping) else {}
    difficulty = episode.get("difficulty_context") if isinstance(episode.get("difficulty_context"), Mapping) else {}
    seeds = dict(FROZEN_SEED_BLOCKS.get(condition_id, {}))
    for key in ("state_seed", "request_seed", "dynamic_seed", "confirmation_seed"):
        if key not in seeds:
            source_key = {
                "state_seed": "seed",
                "request_seed": "seed",
                "dynamic_seed": "seed",
                "confirmation_seed": "confirmation_seed",
            }[key]
            if source_key in dynamic:
                seeds[key] = int(dynamic[source_key])
            elif source_key in job:
                seeds[key] = int(job[source_key])
    condition = _condition_fields(condition_id, config, episode)
    required_values = list(profile.get("required_slot_values", [2, 3, 5, 9]))
    payload_values = list(profile.get("payload_slot_values", [1, 2, 4, 8]))
    payload_probabilities = list(profile.get("payload_slot_probabilities", [0.25] * len(payload_values)))
    requested_multiplier = difficulty.get("requested_arrival_rate_multiplier", condition.get("arrival_rate_multiplier"))
    s1_case_id = str(episode.get("case_id", "")).replace("X4_", "S1_", 1)
    x4_case_id = str(episode.get("case_id", "")).replace("S1_", "X4_", 1)
    if paired_episode is not None:
        s1_case_id = str(paired_episode.get("case_id", s1_case_id)) if paired_episode.get("task_type") == "S1" else s1_case_id
        x4_case_id = str(paired_episode.get("case_id", x4_case_id)) if paired_episode.get("task_type") == "X4" else x4_case_id
    task_config = episode.get("task_config") if isinstance(episode.get("task_config"), Mapping) else {}
    spec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generation_spec_id": f"S1X4_{topology_id}_{condition_id}",
        "topology_id": str(topology_id),
        "canonical_topology": {
            "topology_id": str(topology_id),
            "source_type": "CANONICAL_PHYSICAL_JSON",
            "sha256": canonical_topology_sha256.lower(),
            "node_count": len(episode.get("nodes", [])),
            "directed_link_count": len(episode.get("directed_links", [])),
        },
        "condition_id": str(condition_id),
        "condition": condition,
        "episode": {
            "episode_length": int(episode["episode_length"]),
            "slot_count": int(episode["slot_count"]),
            "initial_reference_time": float(episode["initial_reference_time"]),
            "holding_time_rate_mu": float(episode["holding_time_rate_mu"]),
        },
        "arrival_rate": {
            "mode": condition.get("arrival_rate_mode"),
            "state_arrival_rate_lambda": difficulty.get("state_arrival_rate_lambda"),
            "dynamic_arrival_rate_lambda": difficulty.get("dynamic_arrival_rate_lambda"),
            "requested_arrival_rate_multiplier": requested_multiplier,
            "lambda_ratio": difficulty.get("lambda_ratio"),
        },
        "holding_time_model": {
            "distribution": "EXPONENTIAL",
            "rate_mu": float(episode["holding_time_rate_mu"]),
        },
        "required_slots_distribution": {
            "od_distribution": str(profile.get("od_distribution", "UNIFORM")),
            "required_slot_values": [int(x) for x in required_values],
            "payload_slot_values": [int(x) for x in payload_values],
            "payload_slot_probabilities": [float(x) for x in payload_probabilities],
            "guard_band_slots": int(profile.get("guard_band_slots", 1)),
        },
        "state_generation": {
            "policy": str(job.get("policy", "KSP-FF")),
            "candidate_path_k": int(profile.get("candidate_path_k", 5)),
            "decision_k": int(task_config.get("k", 3)),
        },
        "seed_block": seeds,
        "producer_runtime": {
            "producer_contract_version": "S1X4_DYNAMIC_CASE_PRODUCER_V1_0",
            "source_environment_tree_sha256": source_environment_tree_sha256,
        },
        "scientific_config_fingerprint": _sha256_json(_without_runtime_paths(config)),
        "expected_underlying_episode_fingerprint": episode_scientific_fingerprint(episode),
        "pairing": {
            "pairing_id": str(episode.get("pairing_id", "")),
            "s1_case_id": s1_case_id,
            "x4_case_id": x4_case_id,
        },
        "regeneration": {
            "base_scenario_id": str(episode.get("source_base_scenario_id", "")),
            "resource_state_id": str(episode.get("resource_state_id", "")),
            "request_sequence_id": str(episode.get("request_sequence_id", "")),
            "initial_existing_connection_set_id": str(episode.get("initial_existing_connection_set_id", "")),
        },
        "task_views": {
            "S1": {"decision_k": 3},
            "X4": {"reference_k": int(task_config.get("reference_k", 3))},
        },
    }
    return spec


def validate_generation_spec(spec: Mapping[str, Any], *, strict_matrix: bool = False) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "generation_spec_id",
        "topology_id",
        "canonical_topology",
        "condition_id",
        "condition",
        "episode",
        "arrival_rate",
        "holding_time_model",
        "required_slots_distribution",
        "state_generation",
        "seed_block",
        "producer_runtime",
        "scientific_config_fingerprint",
        "expected_underlying_episode_fingerprint",
        "pairing",
        "regeneration",
        "task_views",
    }
    errors.extend(f"missing:{key}" for key in sorted(required - set(spec)))
    if errors:
        return errors
    if spec.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version")
    topology = str(spec.get("topology_id"))
    condition = str(spec.get("condition_id"))
    if spec.get("generation_spec_id") != f"S1X4_{topology}_{condition}":
        errors.append("generation_spec_id")
    canonical = spec.get("canonical_topology")
    if not isinstance(canonical, Mapping) or canonical.get("topology_id") != topology:
        errors.append("canonical_topology.identity")
    else:
        digest = canonical.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            errors.append("canonical_topology.sha256")
    episode = spec.get("episode")
    if not isinstance(episode, Mapping):
        errors.append("episode")
    elif strict_matrix and (episode.get("episode_length") != 512 or episode.get("slot_count") != 320):
        errors.append("episode.H_or_slot_count")
    state_generation = spec.get("state_generation")
    if not isinstance(state_generation, Mapping) or (
        strict_matrix
        and (state_generation.get("candidate_path_k") != 5 or state_generation.get("decision_k") != 3)
    ):
        errors.append("state_generation.K")
    seeds = spec.get("seed_block")
    if not isinstance(seeds, Mapping):
        errors.append("seed_block")
    elif strict_matrix and condition in FROZEN_SEED_BLOCKS and dict(seeds) != FROZEN_SEED_BLOCKS[condition]:
        errors.append("seed_block.frozen_value")
    if strict_matrix and condition not in FROZEN_CONDITIONS:
        errors.append("condition_id")
    if strict_matrix and topology not in FROZEN_TOPOLOGIES:
        errors.append("topology_id")
    for field in ("scientific_config_fingerprint", "expected_underlying_episode_fingerprint"):
        value = spec.get(field)
        if not isinstance(value, str) or len(value) != 64:
            errors.append(field)
    pairing = spec.get("pairing")
    if not isinstance(pairing, Mapping) or not all(isinstance(pairing.get(key), str) and pairing.get(key) for key in ("pairing_id", "s1_case_id", "x4_case_id")):
        errors.append("pairing")
    distribution = spec.get("required_slots_distribution")
    if isinstance(distribution, Mapping):
        values = distribution.get("required_slot_values")
        probabilities = distribution.get("payload_slot_probabilities")
        if strict_matrix and values != [2, 3, 5, 9]:
            errors.append("required_slots_distribution.values")
        if not isinstance(probabilities, list) or abs(sum(float(x) for x in probabilities) - 1.0) > 1e-9:
            errors.append("required_slots_distribution.probabilities")
    else:
        errors.append("required_slots_distribution")
    return errors


def validate_public_generation_spec(spec: Mapping[str, Any], *, strict_matrix: bool = False) -> list[str]:
    """Validate the compact public projection without requiring private audit metadata."""

    errors: list[str] = []
    if not isinstance(spec, Mapping):
        return ["object"]
    missing = PUBLIC_GENERATION_SPEC_KEYS - set(spec)
    unexpected = set(spec) - PUBLIC_GENERATION_SPEC_KEYS
    errors.extend(f"missing:{key}" for key in sorted(missing))
    errors.extend(f"unexpected:{key}" for key in sorted(unexpected))
    if errors:
        return errors
    if spec.get("schema_version") != PUBLIC_GENERATION_SPEC_SCHEMA_VERSION:
        errors.append("schema_version")
    topology = str(spec.get("topology_id"))
    condition = str(spec.get("condition_id"))
    if spec.get("generation_spec_id") != f"S1X4_{topology}_{condition}":
        errors.append("generation_spec_id")
    if strict_matrix and topology not in FROZEN_TOPOLOGIES:
        errors.append("topology_id")
    if strict_matrix and condition not in FROZEN_CONDITIONS:
        errors.append("condition_id")

    def _object_keys(name: str) -> Mapping[str, Any] | None:
        value = spec.get(name)
        if not isinstance(value, Mapping):
            errors.append(name)
            return None
        expected = PUBLIC_GENERATION_SPEC_NESTED_KEYS[name]
        errors.extend(f"{name}.missing:{key}" for key in sorted(expected - set(value)))
        errors.extend(f"{name}.unexpected:{key}" for key in sorted(set(value) - expected))
        return value

    resource = _object_keys("resource_config")
    initial = _object_keys("initial_state_generation")
    request = _object_keys("request_generation")
    dynamic = _object_keys("dynamic_generation")
    seeds = spec.get("seed_block")
    if not isinstance(seeds, Mapping):
        errors.append("seed_block")
    else:
        expected_seed_keys = set(FROZEN_SEED_BLOCKS[condition]) if condition in FROZEN_SEED_BLOCKS else set(FROZEN_SEED_BLOCKS["A_MEDIUM_MATCH"])
        errors.extend(f"seed_block.missing:{key}" for key in sorted(expected_seed_keys - set(seeds)))
        errors.extend(f"seed_block.unexpected:{key}" for key in sorted(set(seeds) - expected_seed_keys))
        if strict_matrix and condition in FROZEN_SEED_BLOCKS and dict(seeds) != FROZEN_SEED_BLOCKS[condition]:
            errors.append("seed_block.frozen_value")

    if resource is not None:
        for key in ("episode_length", "slot_count", "guard_band_slots"):
            value = resource.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"resource_config.{key}")
        if strict_matrix and (resource.get("episode_length") != 512 or resource.get("slot_count") != 320):
            errors.append("resource_config.H_or_slot_count")
    if initial is not None:
        if initial.get("load_band") is not None and not isinstance(initial.get("load_band"), str):
            errors.append("initial_state_generation.load_band")
        if not isinstance(initial.get("policy"), str) or not initial.get("policy"):
            errors.append("initial_state_generation.policy")
        for key in ("candidate_path_k",):
            value = initial.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                errors.append(f"initial_state_generation.{key}")
        if strict_matrix and initial.get("candidate_path_k") != 5:
            errors.append("initial_state_generation.candidate_path_k")
        for key in ("state_arrival_rate_lambda",):
            value = initial.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                errors.append(f"initial_state_generation.{key}")
    if request is not None:
        if not isinstance(request.get("od_distribution"), str) or not request.get("od_distribution"):
            errors.append("request_generation.od_distribution")
        payload_values = request.get("payload_slot_values")
        required_values = request.get("required_slot_values")
        probabilities = request.get("slot_probabilities")
        if not isinstance(payload_values, list) or not payload_values or any(isinstance(x, bool) or not isinstance(x, int) for x in payload_values):
            errors.append("request_generation.payload_slot_values")
        if not isinstance(required_values, list) or not required_values or any(isinstance(x, bool) or not isinstance(x, int) for x in required_values):
            errors.append("request_generation.required_slot_values")
        if not isinstance(probabilities, list) or len(probabilities) != len(payload_values or []) or any(isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0 for x in probabilities):
            errors.append("request_generation.slot_probabilities")
        elif abs(sum(float(x) for x in probabilities) - 1.0) > 1e-9:
            errors.append("request_generation.slot_probabilities.sum")
        if strict_matrix:
            if payload_values != [1, 2, 4, 8]:
                errors.append("request_generation.payload_slot_values.frozen_value")
            if required_values != [2, 3, 5, 9]:
                errors.append("request_generation.required_slot_values.frozen_value")
    if dynamic is not None:
        if dynamic.get("arrival_rate_mode") is not None and not isinstance(dynamic.get("arrival_rate_mode"), str):
            errors.append("dynamic_generation.arrival_rate_mode")
        multiplier = dynamic.get("arrival_rate_multiplier")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier <= 0:
            errors.append("dynamic_generation.arrival_rate_multiplier")
        for key in ("dynamic_arrival_rate_lambda", "holding_time_rate_mu"):
            value = dynamic.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                errors.append(f"dynamic_generation.{key}")
        if dynamic.get("holding_time_rate_mu") is not None and float(dynamic["holding_time_rate_mu"]) <= 0:
            errors.append("dynamic_generation.holding_time_rate_mu")
    return errors


def _find_single(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} under {path}, found {len(matches)}")
    return matches[0]


def build_matrix_specs_from_handoff(handoff_root: Path | str) -> list[dict[str, Any]]:
    """Read the 27 real production configs and frozen Episodes from a handoff."""

    root = Path(handoff_root).resolve()
    phase = root / "PHASE_B_RUN"
    specs: list[dict[str, Any]] = []
    for topology_id, condition_id in frozen_matrix_keys():
        condition_root = phase / topology_id / condition_id
        config_path = _find_single(condition_root / "configs", "*.json")
        production_config = _read_json(config_path)
        dynamic_config = production_config.get("dynamic") if isinstance(production_config.get("dynamic"), Mapping) else {}
        anchor_ids = dynamic_config.get("anchor_job_ids") if isinstance(dynamic_config.get("anchor_job_ids"), list) else []
        resource_job = _first_resource_job(production_config, str(anchor_ids[0]) if anchor_ids else None)
        request_config = production_config.get("request_generation") if isinstance(production_config.get("request_generation"), Mapping) else {}
        actual_seeds = {
            "state_seed": resource_job.get("seed"),
            "request_seed": request_config.get("seed"),
            "dynamic_seed": dynamic_config.get("seed"),
            "confirmation_seed": resource_job.get("confirmation_seed"),
        }
        if condition_id in FROZEN_SEED_BLOCKS and actual_seeds != FROZEN_SEED_BLOCKS[condition_id]:
            raise ValueError(f"production config seed block mismatch: {topology_id}/{condition_id}: {actual_seeds}")
        environment_root = condition_root / "production_batch" / "units" / topology_id / "public_environment"
        if not environment_root.is_dir():
            raise ValueError(f"missing public environment: {environment_root}")
        s1_path = _find_single(condition_root / "s1x4_dataset" / "internal" / "cases" / "S1", "*/root_case.json")
        x4_path = _find_single(condition_root / "s1x4_dataset" / "internal" / "cases" / "X4", "*/root_case.json")
        s1_episode = _read_json(s1_path)
        x4_episode = _read_json(x4_path)
        if episode_scientific_fingerprint(s1_episode) != episode_scientific_fingerprint(x4_episode):
            raise ValueError(f"S1/X4 scientific fingerprints differ: {topology_id}/{condition_id}")
        topology_path = environment_root / "topologies" / "physical" / f"{topology_id}.json"
        if not topology_path.is_file():
            raise ValueError(f"missing physical topology: {topology_path}")
        summary_path = condition_root / "s1x4_dataset" / "production_summary.json"
        source_environment_tree_sha256 = None
        if summary_path.is_file():
            summary = _read_json(summary_path)
            metadata = summary.get("production_metadata") if isinstance(summary, Mapping) else None
            if isinstance(metadata, Mapping):
                source_environment_tree_sha256 = metadata.get("source_environment_tree_sha256")
        if not isinstance(source_environment_tree_sha256, str) or len(source_environment_tree_sha256) != 64:
            source_environment_tree_sha256 = _tree_sha256(environment_root)
        spec = build_generation_spec(
            topology_id=topology_id,
            condition_id=condition_id,
            production_config=production_config,
            episode=s1_episode,
            paired_episode=x4_episode,
            canonical_topology_sha256=_file_sha256(topology_path),
            source_environment_tree_sha256=source_environment_tree_sha256,
        )
        spec["source_evidence"] = {
            "production_config_ref": config_path.relative_to(root).as_posix(),
            "environment_ref": environment_root.relative_to(root).as_posix(),
            "s1_episode_ref": s1_path.relative_to(root).as_posix(),
            "x4_episode_ref": x4_path.relative_to(root).as_posix(),
        }
        errors = validate_generation_spec(spec, strict_matrix=True)
        if errors:
            raise ValueError(f"invalid generated spec {topology_id}/{condition_id}: {errors}")
        specs.append(spec)
    return specs


def regenerate_episode_from_spec(
    spec: Mapping[str, Any],
    *,
    environment_root: Path | str,
    task_type: str,
) -> dict[str, Any]:
    """Regenerate one task view through the existing official producer loader."""

    errors = validate_generation_spec(spec)
    if errors:
        raise ValueError(f"invalid generation spec: {errors}")
    if task_type not in {"S1", "X4"}:
        raise ValueError("task_type must be S1 or X4")
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    regeneration = spec["regeneration"]
    pairing = spec["pairing"]
    case_id = pairing["s1_case_id"] if task_type == "S1" else pairing["x4_case_id"]
    task_view = spec["task_views"][task_type]
    k = int(task_view.get("decision_k", 3)) if task_type == "S1" else int(task_view.get("reference_k", 3))
    index = load_dynamic_public_environment(environment_root)
    return build_episode_definition(
        index,
        str(regeneration["base_scenario_id"]),
        task_type,
        str(case_id),
        k=k,
        pairing_id=str(pairing["pairing_id"]),
    )


def spec_matches_episode(spec: Mapping[str, Any], episode: Mapping[str, Any]) -> bool:
    return episode_scientific_fingerprint(episode) == spec.get("expected_underlying_episode_fingerprint")
