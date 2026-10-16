"""Machine-readable production configuration for PUBLIC_ENVIRONMENT V1.0.

This module deliberately separates two kinds of values:

* Frozen scientific parameters: recorded in the config for auditability, but the
  loader requires their exact V1.0 values. Ordinary producers cannot change them.
* Batch parameters: topology list, resource-state policy/band/seed matrix, and
  explicitly-unfrozen concurrent/dynamic production quantities.

The distinction prevents a convenient CLI from silently turning into a new
scientific experiment.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when a production configuration violates the V1.0 contract."""


FROZEN_SCIENTIFIC_PROFILE: dict[str, Any] = {
    "od_distribution": "UNIFORM",
    "slot_count": 320,
    "payload_slot_values": [1, 2, 4, 8],
    "payload_slot_probabilities": [0.25, 0.25, 0.25, 0.25],
    "guard_band_slots": 1,
    "required_slot_values": [2, 3, 5, 9],
    "candidate_path_k": 5,
    "holding_time_rate_mu": 1.0 / 15.0,
    "request_sampling_n_gt_100": 2000,
    "max_supported_node_count": 500,
}

LOAD_BANDS: dict[str, tuple[float, float]] = {
    "LIGHT": (0.10, 0.25),
    "MEDIUM": (0.25, 0.45),
    "HIGH": (0.45, 0.65),
    "HIGH_PRESSURE": (0.65, 0.95),
}

OFFICIAL_POLICY_TO_ENGINE_ID: dict[str, str] = {
    "KSP-FF": "BASE_KSP_FF",
    "KSP-RF": "KSP_RF_PILOT",
    "Load-Balanced KSP-FF": "LOAD_BALANCED_KSP_FF_PILOT",
}


@dataclass(frozen=True)
class ScientificProfile:
    od_distribution: str
    slot_count: int
    payload_slot_values: tuple[int, ...]
    payload_slot_probabilities: tuple[float, ...]
    guard_band_slots: int
    required_slot_values: tuple[int, ...]
    candidate_path_k: int
    holding_time_rate_mu: float
    request_sampling_n_gt_100: int
    max_supported_node_count: int


@dataclass(frozen=True)
class ResourceStateJob:
    job_id: str
    policy: str
    engine_policy_id: str
    load_band: str
    target_band: tuple[float, float]
    seed: int
    confirmation_seed: int
    diagnostic: bool


@dataclass(frozen=True)
class RequestGenerationConfig:
    seed: int
    derivation_anchor_job_id: str


@dataclass(frozen=True)
class ConcurrentConfig:
    enabled: bool
    set_count: int
    requests_per_set: int
    seed: int


@dataclass(frozen=True)
class DynamicConfig:
    enabled: bool
    anchor_job_ids: tuple[str, ...]
    sequence_length: int
    sequences_per_condition: int
    arrival_rate_mode: str
    arrival_rate_multipliers: tuple[float, ...]
    arrival_rate_lambda: float | None
    allow_nonstationary_absolute_rate: bool
    seed: int


@dataclass(frozen=True)
class ExecutionConfig:
    resume: bool
    continue_on_failure: bool


@dataclass(frozen=True)
class TopologySpec:
    topology_id: str
    source_path: Path
    source_type: str
    source_sha256: str | None


@dataclass(frozen=True)
class ProductionConfig:
    schema_version: str
    batch_id: str
    scientific_profile: ScientificProfile
    resource_state_jobs: tuple[ResourceStateJob, ...]
    request_generation: RequestGenerationConfig
    concurrent: ConcurrentConfig
    dynamic: DynamicConfig
    execution: ExecutionConfig
    topologies: tuple[TopologySpec, ...]
    source_config_path: Path
    config_sha256: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"config is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("config root must be a JSON object")
    return value


def _require_exact_frozen_profile(value: Any) -> ScientificProfile:
    if not isinstance(value, dict):
        raise ConfigurationError("scientific_profile must be an object")
    expected_keys = set(FROZEN_SCIENTIFIC_PROFILE)
    actual_keys = set(value)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ConfigurationError(f"scientific_profile keys mismatch; missing={missing}, extra={extra}")
    for key, expected in FROZEN_SCIENTIFIC_PROFILE.items():
        actual = value[key]
        if isinstance(expected, float):
            if not isinstance(actual, (int, float)) or abs(float(actual) - expected) > 1e-15:
                raise ConfigurationError(f"frozen scientific parameter {key} must equal {expected!r}")
        elif actual != expected:
            raise ConfigurationError(f"frozen scientific parameter {key} must equal {expected!r}")
    return ScientificProfile(
        od_distribution=value["od_distribution"],
        slot_count=int(value["slot_count"]),
        payload_slot_values=tuple(int(x) for x in value["payload_slot_values"]),
        payload_slot_probabilities=tuple(float(x) for x in value["payload_slot_probabilities"]),
        guard_band_slots=int(value["guard_band_slots"]),
        required_slot_values=tuple(int(x) for x in value["required_slot_values"]),
        candidate_path_k=int(value["candidate_path_k"]),
        holding_time_rate_mu=float(value["holding_time_rate_mu"]),
        request_sampling_n_gt_100=int(value["request_sampling_n_gt_100"]),
        max_supported_node_count=int(value["max_supported_node_count"]),
    )


def _positive_int(value: Any, name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{name} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value


def _parse_jobs(raw_jobs: Any) -> tuple[ResourceStateJob, ...]:
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ConfigurationError("resource_state_jobs must be a non-empty array")
    result: list[ResourceStateJob] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_jobs):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"resource_state_jobs[{index}] must be an object")
        job_id = str(raw.get("job_id", "")).strip()
        if not job_id:
            raise ConfigurationError(f"resource_state_jobs[{index}].job_id is required")
        if job_id in seen:
            raise ConfigurationError(f"duplicate resource_state job_id: {job_id}")
        seen.add(job_id)
        policy = raw.get("policy")
        if policy not in OFFICIAL_POLICY_TO_ENGINE_ID:
            raise ConfigurationError(
                f"resource_state_jobs[{index}].policy must be one of {sorted(OFFICIAL_POLICY_TO_ENGINE_ID)}"
            )
        load_band = raw.get("load_band")
        if load_band not in LOAD_BANDS:
            raise ConfigurationError(f"unknown load_band {load_band!r}")
        diagnostic = bool(raw.get("diagnostic", False))
        if load_band == "HIGH_PRESSURE" and not diagnostic:
            raise ConfigurationError("HIGH_PRESSURE is diagnostic-only and requires diagnostic=true")
        if load_band != "HIGH_PRESSURE" and diagnostic:
            raise ConfigurationError("diagnostic=true is reserved for HIGH_PRESSURE jobs")
        seed = _positive_int(raw.get("seed"), f"resource_state_jobs[{index}].seed", allow_zero=True)
        confirmation_seed = _positive_int(
            raw.get("confirmation_seed"), f"resource_state_jobs[{index}].confirmation_seed", allow_zero=True
        )
        if seed == confirmation_seed:
            raise ConfigurationError(f"resource_state_jobs[{index}] confirmation_seed must differ from seed")
        result.append(ResourceStateJob(
            job_id=job_id,
            policy=str(policy),
            engine_policy_id=OFFICIAL_POLICY_TO_ENGINE_ID[str(policy)],
            load_band=str(load_band),
            target_band=LOAD_BANDS[str(load_band)],
            seed=seed,
            confirmation_seed=confirmation_seed,
            diagnostic=diagnostic,
        ))
    return tuple(result)


def _parse_topologies(raw: Any, config_dir: Path) -> tuple[TopologySpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigurationError("topologies must be a non-empty array")
    result: list[TopologySpec] = []
    seen: set[str] = set()
    allowed_types = {"GABRIEL_JSON", "TOPOLOGYBENCH_XLSX", "CANONICAL_PHYSICAL_JSON"}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigurationError(f"topologies[{index}] must be an object")
        topology_id = str(item.get("topology_id", "")).strip()
        if not topology_id:
            raise ConfigurationError(f"topologies[{index}].topology_id is required")
        if topology_id in seen:
            raise ConfigurationError(f"duplicate topology_id: {topology_id}")
        seen.add(topology_id)
        source_type = item.get("source_type")
        if source_type not in allowed_types:
            raise ConfigurationError(f"topologies[{index}].source_type must be one of {sorted(allowed_types)}")
        raw_path = item.get("source_path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigurationError(f"topologies[{index}].source_path is required")
        source_path = Path(raw_path)
        if not source_path.is_absolute():
            source_path = (config_dir / source_path).resolve()
        if not source_path.is_file():
            raise ConfigurationError(f"topology source file not found: {source_path}")
        source_sha256 = item.get("source_sha256")
        if source_sha256 is not None:
            if not isinstance(source_sha256, str) or len(source_sha256) != 64:
                raise ConfigurationError(f"topologies[{index}].source_sha256 must be a 64-character SHA-256")
            actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if actual.lower() != source_sha256.lower():
                raise ConfigurationError(
                    f"topology source SHA-256 mismatch for {topology_id}: expected {source_sha256}, actual {actual}"
                )
        result.append(TopologySpec(topology_id, source_path, str(source_type), source_sha256))
    return tuple(result)


def load_production_config(path: str | Path) -> ProductionConfig:
    """Load and semantically validate a V1.0 batch configuration."""
    path = Path(path).resolve()
    raw = _read_json(path)
    if raw.get("schema_version") != "PUBLIC_ENV_PRODUCTION_CONFIG_V1_0":
        raise ConfigurationError("schema_version must be PUBLIC_ENV_PRODUCTION_CONFIG_V1_0")
    batch_id = str(raw.get("batch_id", "")).strip()
    if not batch_id:
        raise ConfigurationError("batch_id is required")
    profile = _require_exact_frozen_profile(raw.get("scientific_profile"))
    jobs = _parse_jobs(raw.get("resource_state_jobs"))

    request = raw.get("request_generation")
    if not isinstance(request, dict):
        raise ConfigurationError("request_generation must be an object")
    request_cfg = RequestGenerationConfig(
        seed=_positive_int(request.get("seed"), "request_generation.seed", allow_zero=True),
        derivation_anchor_job_id=str(request.get("derivation_anchor_job_id", "")).strip(),
    )
    jobs_by_id = {job.job_id: job for job in jobs}
    anchor = jobs_by_id.get(request_cfg.derivation_anchor_job_id)
    if anchor is None or anchor.policy != "KSP-FF" or anchor.load_band != "MEDIUM" or anchor.diagnostic:
        raise ConfigurationError(
            "request derivation anchor must reference a non-diagnostic KSP-FF/MEDIUM resource_state job"
        )

    concurrent = raw.get("concurrent", {})
    if not isinstance(concurrent, dict):
        raise ConfigurationError("concurrent must be an object")
    concurrent_cfg = ConcurrentConfig(
        enabled=bool(concurrent.get("enabled", False)),
        set_count=_positive_int(concurrent.get("set_count", 0), "concurrent.set_count", allow_zero=True),
        requests_per_set=_positive_int(
            concurrent.get("requests_per_set", 0), "concurrent.requests_per_set", allow_zero=True
        ),
        seed=_positive_int(concurrent.get("seed", 0), "concurrent.seed", allow_zero=True),
    )
    if concurrent_cfg.enabled and (concurrent_cfg.set_count < 1 or concurrent_cfg.requests_per_set < 2):
        raise ConfigurationError("enabled concurrent production requires set_count>=1 and requests_per_set>=2")

    dynamic = raw.get("dynamic", {})
    if not isinstance(dynamic, dict):
        raise ConfigurationError("dynamic must be an object")
    dynamic_enabled = bool(dynamic.get("enabled", False))
    anchor_job_ids_raw = dynamic.get("anchor_job_ids", [])
    if not isinstance(anchor_job_ids_raw, list) or any(not isinstance(x, str) or not x.strip() for x in anchor_job_ids_raw):
        raise ConfigurationError("dynamic.anchor_job_ids must be an array of non-empty job ids")
    anchor_job_ids = tuple(x.strip() for x in anchor_job_ids_raw)
    if len(set(anchor_job_ids)) != len(anchor_job_ids):
        raise ConfigurationError("dynamic.anchor_job_ids must not contain duplicates")
    mode = str(dynamic.get("arrival_rate_mode", "MATCH_STATE")).strip()
    if mode not in {"MATCH_STATE", "MULTIPLIER_OF_STATE", "ABSOLUTE"}:
        raise ConfigurationError("dynamic.arrival_rate_mode must be MATCH_STATE, MULTIPLIER_OF_STATE, or ABSOLUTE")
    multipliers_raw = dynamic.get("arrival_rate_multipliers", [1.0] if mode == "MATCH_STATE" else [])
    if not isinstance(multipliers_raw, list):
        raise ConfigurationError("dynamic.arrival_rate_multipliers must be an array")
    try:
        multipliers = tuple(float(x) for x in multipliers_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("dynamic.arrival_rate_multipliers must contain numbers") from exc
    if any(x <= 0 for x in multipliers):
        raise ConfigurationError("dynamic.arrival_rate_multipliers must all be > 0")
    if mode == "MATCH_STATE":
        if multipliers not in {(), (1.0,)}:
            raise ConfigurationError("MATCH_STATE does not accept multipliers other than 1.0")
        multipliers = (1.0,)
    elif mode == "MULTIPLIER_OF_STATE" and not multipliers:
        raise ConfigurationError("MULTIPLIER_OF_STATE requires dynamic.arrival_rate_multipliers")
    elif mode == "ABSOLUTE" and multipliers:
        raise ConfigurationError("ABSOLUTE does not use dynamic.arrival_rate_multipliers")
    arrival_rate_raw = dynamic.get("arrival_rate_lambda")
    arrival_rate: float | None = None
    if arrival_rate_raw is not None:
        try:
            arrival_rate = float(arrival_rate_raw)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("dynamic.arrival_rate_lambda must be numeric") from exc
        if arrival_rate <= 0 and dynamic_enabled:
            raise ConfigurationError("dynamic.arrival_rate_lambda must be > 0 when provided")
    allow_absolute = bool(dynamic.get("allow_nonstationary_absolute_rate", False))
    if mode == "ABSOLUTE":
        if arrival_rate is None or arrival_rate <= 0:
            raise ConfigurationError("ABSOLUTE requires dynamic.arrival_rate_lambda>0")
        if not allow_absolute:
            raise ConfigurationError("ABSOLUTE requires allow_nonstationary_absolute_rate=true")
    elif arrival_rate is not None and dynamic_enabled:
        raise ConfigurationError("arrival_rate_lambda is only valid in ABSOLUTE mode")
    for anchor_job_id in anchor_job_ids:
        dynamic_anchor = jobs_by_id.get(anchor_job_id)
        if dynamic_anchor is None:
            raise ConfigurationError(f"dynamic anchor job does not exist: {anchor_job_id}")
        if dynamic_anchor.diagnostic:
            raise ConfigurationError(f"dynamic anchor must reference a non-diagnostic resource state: {anchor_job_id}")
    dynamic_cfg = DynamicConfig(
        enabled=dynamic_enabled,
        anchor_job_ids=anchor_job_ids,
        sequence_length=_positive_int(dynamic.get("sequence_length", 0), "dynamic.sequence_length", allow_zero=True),
        sequences_per_condition=_positive_int(dynamic.get("sequences_per_condition", 0), "dynamic.sequences_per_condition", allow_zero=True),
        arrival_rate_mode=mode,
        arrival_rate_multipliers=multipliers,
        arrival_rate_lambda=arrival_rate,
        allow_nonstationary_absolute_rate=allow_absolute,
        seed=_positive_int(dynamic.get("seed", 0), "dynamic.seed", allow_zero=True),
    )
    if dynamic_cfg.enabled and (
        not dynamic_cfg.anchor_job_ids or dynamic_cfg.sequence_length < 1 or dynamic_cfg.sequences_per_condition < 1
    ):
        raise ConfigurationError(
            "enabled dynamic production requires anchor_job_ids, sequence_length>=1, and sequences_per_condition>=1"
        )

    execution = raw.get("execution", {})
    if not isinstance(execution, dict):
        raise ConfigurationError("execution must be an object")
    execution_cfg = ExecutionConfig(
        resume=bool(execution.get("resume", True)),
        continue_on_failure=bool(execution.get("continue_on_failure", True)),
    )
    topologies = _parse_topologies(raw.get("topologies"), path.parent)
    return ProductionConfig(
        schema_version=str(raw["schema_version"]),
        batch_id=batch_id,
        scientific_profile=profile,
        resource_state_jobs=jobs,
        request_generation=request_cfg,
        concurrent=concurrent_cfg,
        dynamic=dynamic_cfg,
        execution=execution_cfg,
        topologies=topologies,
        source_config_path=path,
        config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
