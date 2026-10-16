"""Derive K=3 O2 inputs that retain an exact full-space X2/X3 witness.

The public O2 case contains only ordinary candidate paths.  Oracle provenance
and the identity of the included witness stay in the private derivation record.
This module reuses an existing exact X2/X3 result and independently solves the
new O2 objective over the three-path subset; it never reruns X2/X3.
"""

from __future__ import annotations

from copy import deepcopy
from math import isclose
from typing import Any

import networkx as nx

from src.case_core.o2_lexicographic import O2C_CONTRACT, O2S_CONTRACT
from src.case_core.o2_migration import recompute_algorithm_case
from src.case_core.path_validation import validate_directed_path
from src.case_core.spectrum_codec import compress_resource_state
from src.case_core.wufr import WUFR_ABS_TOL
from src.case_core.full_rsa import link_maps, path_from_nodes
from src.tasks.x2.validator import validate_x2_output
from src.tasks.x3.validator import validate_x3_output


class CandidatePathInsufficient(ValueError):
    """The topology has fewer than K distinct routes for a request."""


class GlobalOptimumNotPreserved(AssertionError):
    """The restricted O2 solve disagrees with its exact full-space witness."""


def _signature(path: dict[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(int(x) for x in path["path_link_ids"]),
        tuple(int(x) for x in path["path_node_ids"]),
    )


def _canonical_path(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "path_node_ids": [int(x) for x in path["path_node_ids"]],
        "path_link_ids": [int(x) for x in path["path_link_ids"]],
    }


def select_candidate_paths(
    request: dict[str, Any],
    directed_links: list[dict[str, Any]],
    exact_witness: dict[str, Any],
    *,
    candidate_k: int = 3,
) -> tuple[list[dict[str, Any]], int]:
    """Return witness + first two distinct unweighted K-shortest alternatives.

    The route universe is every directed simple source-destination path in the
    actual graph.  Alternatives follow the frozen project's existing
    ``networkx.shortest_simple_paths`` convention (unweighted).  The exact
    oracle path is always inserted first as a required member, then candidates
    are canonically ranked for the public O2 input.  If three distinct paths
    do not exist, this raises instead of duplicating paths or shrinking K.
    """
    if candidate_k != 3:
        raise ValueError("oracle-contained O2 v1 freezes K=3: witness plus two routes")
    source = int(request["source_node_id"])
    destination = int(request["destination_node_id"])
    witness = _canonical_path(exact_witness)
    witness_check = validate_directed_path(
        witness["path_link_ids"], witness["path_node_ids"], directed_links, source, destination
    )
    if not witness_check.valid:
        raise ValueError("exact oracle witness is not a valid directed simple route: " + str(witness_check.error))

    # link_maps also enforces the source kernel's no-parallel-directed-link rule.
    link_maps(directed_links)
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(int(x) for x in {source, destination} | {
        int(n) for row in directed_links for n in (row["source_node_id"], row["destination_node_id"])
    }))
    for row in sorted(directed_links, key=lambda item: int(item["link_id"])):
        graph.add_edge(int(row["source_node_id"]), int(row["destination_node_id"]))

    witness_signature = _signature(witness)
    selected = [witness]
    seen = {witness_signature}
    try:
        generator = nx.shortest_simple_paths(graph, source, destination)
        for node_path in generator:
            candidate = path_from_nodes([int(x) for x in node_path], directed_links)
            candidate = _canonical_path(candidate)
            signature = _signature(candidate)
            if signature in seen:
                continue
            checked = validate_directed_path(
                candidate["path_link_ids"], candidate["path_node_ids"], directed_links, source, destination
            )
            if not checked.valid:
                raise ValueError("path generator returned an invalid route: " + str(checked.error))
            selected.append(candidate)
            seen.add(signature)
            if len(selected) == candidate_k:
                break
    except nx.NetworkXNoPath as exc:
        raise ValueError("exact feasible witness exists but the graph reports no route") from exc

    if len(selected) != candidate_k:
        raise CandidatePathInsufficient(
            f"need {candidate_k} distinct simple routes including the exact witness; found {len(selected)}"
        )

    selected.sort(key=lambda path: (
        len(path["path_link_ids"]), tuple(path["path_link_ids"]), tuple(path["path_node_ids"])
    ))
    output = [{"path_rank": rank, **path} for rank, path in enumerate(selected, 1)]
    witness_rank = next(rank for rank, path in enumerate(output, 1) if _signature(path) == witness_signature)
    return output, witness_rank


def _source_validation(source_root: dict, source_truth: dict, source_reference: dict) -> dict:
    task = source_root.get("task_type")
    if task == "X2":
        return validate_x2_output(source_root, source_truth, source_reference)
    if task == "X3":
        return validate_x3_output(source_root, source_truth, source_reference)
    raise ValueError("source task must be exact X2 or X3")


def _source_witnesses(source_root: dict, source_truth: dict, source_reference: dict, target_task: str) -> list[dict]:
    source_task = source_root["task_type"]
    if source_truth.get("oracle_certification") != "EXACT_CERTIFIED":
        raise ValueError("only a feasible EXACT_CERTIFIED source oracle result may supply a witness")
    if source_reference.get("decision") != "ACCEPT":
        raise ValueError("the source global oracle has no accepted standard-answer path")

    if target_task == "O2-S":
        if source_task != "X2":
            raise ValueError("O2-S must derive from a matching X2 full-space exact result")
        request = source_root.get("request")
        if not isinstance(request, dict):
            raise ValueError("X2 source request is missing")
        witness = {key: source_reference[key] for key in ("path_node_ids", "path_link_ids")}
        return [{"request": deepcopy(request), "witness": witness}]

    if target_task == "O2-C":
        if source_task != "X3":
            raise ValueError("O2-C must derive from a matching X3 full-space exact result")
        requests = source_root.get("requests")
        allocations = source_reference.get("allocations")
        if not isinstance(requests, list) or not isinstance(allocations, list):
            raise ValueError("X3 N-request input or reference allocations are missing")
        by_id = {str(item.get("request_id")): item for item in allocations}
        if len(requests) < 2 or set(by_id) != {str(item["request_id"]) for item in requests}:
            raise ValueError("X3 source allocation/request identities do not match")
        return [
            {
                "request": deepcopy(request),
                "witness": {
                    "path_node_ids": by_id[str(request["request_id"])]["path_node_ids"],
                    "path_link_ids": by_id[str(request["request_id"])]["path_link_ids"],
                },
            }
            for request in requests
        ]
    raise ValueError("target_task must be O2-S or O2-C")


def _compare_global_objective(target_task: str, source_truth: dict, target_truth: dict) -> dict:
    if target_task == "O2-S":
        global_primary = source_truth["optimal_hop_count"]
        global_secondary = source_truth["optimal_wufr_at_optimal_hop"]
        target_primary = target_truth["optimal_hop_count"]
        target_secondary = target_truth["optimal_wufr"]
    else:
        global_primary = source_truth["optimal_delta_tso"]
        global_secondary = source_truth["optimal_wufr_at_optimal_delta_tso"]
        target_primary = target_truth["optimal_delta_tso"]
        target_secondary = target_truth["optimal_wufr"]

    primary_equal = global_primary == target_primary
    secondary_equal = (
        global_secondary is not None
        and target_secondary is not None
        and isclose(float(global_secondary), float(target_secondary), rel_tol=0.0, abs_tol=WUFR_ABS_TOL)
    )
    if not primary_equal or not secondary_equal:
        raise GlobalOptimumNotPreserved(
            "the candidate-restricted exact objective differs from the exact full-space source oracle"
        )
    return {
        "global_primary": global_primary,
        "candidate_primary": target_primary,
        "primary_equal": primary_equal,
        "global_secondary_wufr": global_secondary,
        "candidate_secondary_wufr": target_secondary,
        "secondary_equal_with_frozen_tolerance": secondary_equal,
    }


def derive_o2_from_exact_case(
    source_root: dict[str, Any],
    source_truth: dict[str, Any],
    source_reference: dict[str, Any],
    *,
    target_task: str,
    case_id: str,
    source_binding: dict[str, Any],
    max_complete_solutions: int = 100_000,
    candidate_k: int = 3,
) -> dict[str, Any]:
    """Derive and validate one O2 case from an existing exact X2/X3 result."""
    if target_task not in ("O2-S", "O2-C"):
        raise ValueError("target_task must be O2-S or O2-C")
    if source_root.get("case_id") != source_truth.get("case_id"):
        raise ValueError("source root/truth case IDs do not match")
    if source_root.get("task_type") != source_truth.get("task_type"):
        raise ValueError("source root/truth task types do not match")
    source_validation = _source_validation(source_root, source_truth, source_reference)
    if not source_validation.get("valid"):
        raise ValueError("stored exact X2/X3 result does not pass the unchanged source Validator")

    request_witnesses = _source_witnesses(source_root, source_truth, source_reference, target_task)
    requests_with_paths = []
    witness_ranks = {}
    for pair in request_witnesses:
        request = pair["request"]
        paths, witness_rank = select_candidate_paths(
            request,
            source_root["directed_links"],
            pair["witness"],
            candidate_k=candidate_k,
        )
        requests_with_paths.append({**request, "candidate_paths": paths})
        witness_ranks[str(request["request_id"])] = witness_rank

    contract = O2S_CONTRACT if target_task == "O2-S" else O2C_CONTRACT
    common = {
        "case_id": str(case_id),
        "task_type": target_task,
        "objective_contract_id": contract,
        "topology_id": source_root["topology_id"],
        "resource_state_id": source_root["resource_state_id"],
        "nodes": deepcopy(source_root["nodes"]),
        "directed_links": deepcopy(source_root["directed_links"]),
        "slot_count": int(source_root["slot_count"]),
        "spectrum_states": compress_resource_state(source_root),
        "required_slots_probabilities": deepcopy(source_root["required_slots_probabilities"]),
    }
    if target_task == "O2-S":
        algorithm_case = {
            **common,
            "request": {
                key: value
                for key, value in requests_with_paths[0].items()
                if key != "candidate_paths"
            },
            "candidate_paths": requests_with_paths[0]["candidate_paths"],
        }
    else:
        algorithm_case = {**common, "requests": requests_with_paths}

    bundle = recompute_algorithm_case(
        algorithm_case,
        case_id=case_id,
        source_binding={**deepcopy(source_binding), "candidate_k": candidate_k},
        max_complete_solutions=max_complete_solutions,
    )
    objective_comparison = _compare_global_objective(target_task, source_truth, bundle["private_truth"])
    proof = {
        "source_case_id": source_root["case_id"],
        "source_task": source_root["task_type"],
        "source_oracle_certification": source_truth["oracle_certification"],
        "source_validator_pass": True,
        "source_validation_metrics": deepcopy(source_validation.get("metrics", {})),
        "candidate_k_per_request": candidate_k,
        "candidate_generation_policy": "exact full-space oracle witness plus first two distinct unweighted K-shortest simple alternatives",
        "path_universe": "all directed simple source-destination paths in the same frozen graph",
        "candidate_set_is_subset_of_path_universe": True,
        "witness_rank_by_request": witness_ranks,
        "all_global_witness_paths_in_candidate_sets": len(witness_ranks) == len(requests_with_paths),
        "candidate_exact_objective_matches_global_oracle": True,
        "objective_comparison": objective_comparison,
        "selection_uses_outcome_or_seed": False,
        "no_x2_x3_resolve_performed": True,
        "candidate_o2_solver_certification": bundle["private_truth"]["oracle_certification"],
        "candidate_o2_validator_pass": bundle["validation"]["valid"],
    }
    bundle["proof"] = proof
    bundle["lineage"].update({
        "migration": "derived from a Validator-passing exact full-space X2/X3 result; O2 exact objective solved anew over the witness-containing candidate subset",
        "derivation_policy": "EXACT_X2_X3_WITNESS_PLUS_TWO_GLOBAL_KSP_ALTERNATIVES",
        "source_case_id": source_root["case_id"],
        "source_task": source_root["task_type"],
        "source_case_contract": source_truth.get("objective_contract_id"),
        "source_binding": deepcopy(source_binding),
        "candidate_k": candidate_k,
        "candidate_witness_rank_by_request": witness_ranks,
        "candidate_objective_equality_to_global_oracle": True,
    })
    return bundle
