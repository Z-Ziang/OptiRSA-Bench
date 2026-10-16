from __future__ import annotations

import json
from math import isclose, isfinite
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from src.case_core.path_validation import path_nodes_from_links, validate_directed_path
from src.case_core.spectrum_codec import compress_resource_state
from src.case_core.scenario_loader import PublicEnvironmentIndex


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SLOTS_PROBABILITY_KEYS = ("2", "3", "5", "9")
REQUIRED_SLOTS_PROBABILITY_TOL = 1e-12


def validate_required_slots_probabilities(probabilities: object) -> dict[str, float]:
    """Validate and normalize the public required-slots probability distribution."""
    if not isinstance(probabilities, dict):
        raise ValueError("required_slots_probabilities must be an object")
    if set(probabilities) != set(REQUIRED_SLOTS_PROBABILITY_KEYS):
        raise ValueError("required_slots_probabilities keys must be exactly 2, 3, 5, and 9")
    normalized: dict[str, float] = {}
    for key in REQUIRED_SLOTS_PROBABILITY_KEYS:
        value = probabilities[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"probability for required_slots={key} must be a number")
        probability = float(value)
        if not isfinite(probability):
            raise ValueError("required_slots_probabilities values must be finite")
        if probability < 0.0:
            raise ValueError("required_slots_probabilities values must be non-negative")
        if probability > 1.0:
            raise ValueError("required_slots_probabilities values must be at most 1")
        normalized[key] = probability
    if not isclose(sum(normalized.values()), 1.0, rel_tol=0.0, abs_tol=REQUIRED_SLOTS_PROBABILITY_TOL):
        raise ValueError("required_slots_probabilities must sum to 1")
    return normalized


def public_directed_links(directed_topology: dict) -> list[dict]:
    rows = [
        {
            "link_id": int(x["link_id"]),
            "source_node_id": int(x["source_node_id"]),
            "destination_node_id": int(x["destination_node_id"]),
        }
        for x in directed_topology["directed_link_records"]
    ]
    return sorted(rows, key=lambda x: x["link_id"])


def node_ids(physical_topology: dict) -> list[int]:
    return sorted(int(x["node_id"]) for x in physical_topology["node_records"])


def canonical_spectrum_rows(resource_state: dict) -> list[dict]:
    return sorted(
        [
            {"link_id": int(x["link_id"]), "slot_availability": [int(v) for v in x["slot_availability"]]}
            for x in resource_state["link_spectrum_states"]
        ],
        key=lambda x: x["link_id"],
    )


def spectrum_by_link(resource_state_or_root: dict) -> dict[int, list[int]]:
    rows = resource_state_or_root["link_spectrum_states"]
    return {int(x["link_id"]): [int(v) for v in x["slot_availability"]] for x in rows}


def infer_required_slots_probabilities(env: PublicEnvironmentIndex, topology_id: str) -> dict[str, float]:
    candidates = []
    for cfg in env.generation_configs.values():
        if cfg.get("topology_id") != topology_id:
            continue
        values = cfg.get("payload_slot_values")
        probabilities = cfg.get("payload_slot_probabilities")
        guard = cfg.get("guard_band_slots")
        if isinstance(values, list) and isinstance(probabilities, list) and len(values) == len(probabilities) and isinstance(guard, int):
            mapped = {str(int(v) + guard): float(p) for v, p in zip(values, probabilities)}
            if set(mapped) == {"2", "3", "5", "9"}:
                candidates.append(validate_required_slots_probabilities(mapped))
    if not candidates:
        raise ValueError(f"cannot infer required_slots probabilities for topology {topology_id}")
    first = candidates[0]
    if any(c != first for c in candidates[1:]):
        raise ValueError("inconsistent required_slots probability profiles in source environment")
    return {key: first[key] for key in REQUIRED_SLOTS_PROBABILITY_KEYS}


def q_numeric(public_q: dict[str, float]) -> dict[int, float]:
    validated = validate_required_slots_probabilities(public_q)
    return {int(k): float(v) for k, v in validated.items()}


def resolve_common_context(env: PublicEnvironmentIndex, resource_state_id: str) -> dict:
    if resource_state_id not in env.resource_states:
        raise KeyError(resource_state_id)
    state = env.resource_states[resource_state_id]
    topology_id = state["topology_id"]
    physical = env.physical_topologies[topology_id]
    directed = env.directed_topologies[topology_id]
    nodes = node_ids(physical)
    links = public_directed_links(directed)
    return {
        "topology_id": topology_id,
        "resource_state_id": resource_state_id,
        "nodes": nodes,
        "directed_links": links,
        "slot_count": int(state["slot_count"]),
        "link_spectrum_states": canonical_spectrum_rows(state),
        "spectrum_states": compress_resource_state(state),
        "required_slots_probabilities": infer_required_slots_probabilities(env, topology_id),
        "state_metrics": state.get("spectrum_state_metrics", {}),
    }


def candidate_paths_for_request(
    env: PublicEnvironmentIndex, request_id: str, *, candidate_k: int | None = None
) -> list[dict]:
    request = env.requests[request_id]
    derivation = env.derivations[request_id]
    state = env.resource_states[derivation["resource_state_id"]]
    directed = public_directed_links(env.directed_topologies[state["topology_id"]])
    source = int(request["source_node_id"])
    destination = int(request["destination_node_id"])
    source_paths = sorted(derivation["candidate_paths"], key=lambda x: int(x["rank"]))
    if candidate_k is not None:
        if candidate_k < 1 or candidate_k > len(source_paths):
            raise ValueError(f"candidate_k={candidate_k} unavailable for request {request_id}")
        source_paths = source_paths[:candidate_k]
    result = []
    for expected_rank, item in enumerate(source_paths, 1):
        rank = int(item["rank"])
        if rank != expected_rank:
            raise ValueError(f"candidate ranks are not one-based continuous for {request_id}")
        link_ids = [int(x) for x in item["path_link_ids"]]
        node_path = path_nodes_from_links(link_ids, directed)
        check = validate_directed_path(link_ids, node_path, directed, source, destination)
        if not check.valid:
            raise ValueError(f"illegal precomputed candidate path for {request_id}: {check.error}")
        result.append({"path_rank": rank, "path_node_ids": node_path, "path_link_ids": link_ids})
    return result


def source_resource_state_id(env: PublicEnvironmentIndex, request_ids: Iterable[str]) -> str:
    ids = {env.derivations[rid]["resource_state_id"] for rid in request_ids}
    if len(ids) != 1:
        raise ValueError("selected requests do not share one derivation resource state")
    return next(iter(ids))


def validate_output_schema(task: str, output: dict) -> list[str]:
    schema_path = PROJECT_ROOT / "contracts" / task / "output_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [err.message for err in sorted(validator.iter_errors(output), key=lambda e: list(e.path))]


def serialized_char_count(obj: dict) -> int:
    return len(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
