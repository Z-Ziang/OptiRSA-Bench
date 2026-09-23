from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .bitset import binary_to_free_words
from .types import (
    AlgorithmObservation,
    AlgorithmStaticContext,
    CandidatePath,
    CompiledSpectrum,
    CompiledTopology,
)


def compile_spectrum(
    spectrum_by_link: Mapping[int, Sequence[int]], slot_count: int
) -> CompiledSpectrum:
    link_ids = sorted(int(link_id) for link_id in spectrum_by_link)
    if not link_ids:
        raise ValueError("spectrum must contain at least one link")
    rows = []
    for link_id in link_ids:
        values = list(spectrum_by_link[link_id])
        if len(values) != int(slot_count):
            raise ValueError("spectrum row length does not match slot_count")
        rows.append(binary_to_free_words(values))
    return CompiledSpectrum(
        slot_count=int(slot_count),
        link_ids=np.asarray(link_ids, dtype=np.int32),
        free_words=np.stack(rows, axis=0),
    )


def compile_static_context(episode: Mapping[str, Any]) -> AlgorithmStaticContext:
    raw_nodes = sorted({int(node_id) for node_id in episode["nodes"]})
    raw_links = sorted(episode["directed_links"], key=lambda row: int(row["link_id"]))
    link_ids = [int(row["link_id"]) for row in raw_links]
    if len(set(link_ids)) != len(link_ids):
        raise ValueError("directed topology contains duplicate link_id")
    node_ids = np.asarray(raw_nodes, dtype=np.int32)
    sources = np.asarray([int(row["source_node_id"]) for row in raw_links], dtype=np.int32)
    destinations = np.asarray([int(row["destination_node_id"]) for row in raw_links], dtype=np.int32)
    link_array = np.asarray(link_ids, dtype=np.int32)
    node_row = {node_id: row for row, node_id in enumerate(raw_nodes)}
    order = sorted(
        range(len(raw_links)),
        key=lambda row: (int(sources[row]), int(destinations[row]), int(link_array[row])),
    )
    counts = [0] * len(raw_nodes)
    for row in order:
        if int(sources[row]) not in node_row:
            raise ValueError("directed link source is not present in nodes")
        counts[node_row[int(sources[row])]] += 1
    offsets = np.zeros(len(raw_nodes) + 1, dtype=np.int32)
    offsets[1:] = np.cumsum(np.asarray(counts, dtype=np.int32))
    return AlgorithmStaticContext(
        case_id=str(episode["case_id"]),
        task_type=str(episode["task_type"]),
        topology_id=str(episode["topology_id"]),
        slot_count=int(episode["slot_count"]),
        topology=CompiledTopology(
            node_ids=node_ids,
            link_ids=link_array,
            sources=sources,
            destinations=destinations,
            adjacency_offsets=offsets,
            adjacency_link_indices=np.asarray(order, dtype=np.int32),
        ),
    )


def _public_request(request: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "request_id",
        "source_node_id",
        "destination_node_id",
        "required_slots",
        "arrival_time",
        "holding_time",
    )
    missing = [name for name in allowed if name not in request]
    if missing:
        raise ValueError(f"current request missing fields: {missing}")
    return {
        name: (str(request[name]) if name == "request_id" else request[name])
        for name in allowed
    }


def compile_observation(context: Mapping[str, Any]) -> AlgorithmObservation:
    task_type = str(context["task_type"])
    request = _public_request(context["request"])
    spectrum = compile_spectrum(context["spectrum_by_link"], int(context["slot_count"]))
    if task_type == "S1":
        paths = tuple(
            CandidatePath(
                path_rank=int(path["path_rank"]),
                path_node_ids=tuple(int(x) for x in path["path_node_ids"]),
                path_link_ids=tuple(int(x) for x in path["path_link_ids"]),
            )
            for path in context["candidate_paths"]
        )
        actions = np.asarray(
            [
                [int(action["path_rank"]), int(action["slot_start"])]
                for action in context.get("candidate_actions", [])
            ],
            dtype=np.int32,
        )
        return AlgorithmObservation(
            case_id=str(context["case_id"]),
            task_type=task_type,
            step_index=int(context["step_index_internal"]),
            current_time=float(context["current_time"]),
            request=request,
            spectrum=spectrum,
            candidate_paths=paths,
            feasible_actions=actions,
        )
    if task_type == "X4":
        return AlgorithmObservation(
            case_id=str(context["case_id"]),
            task_type=task_type,
            step_index=int(context["step_index_internal"]),
            current_time=float(context["current_time"]),
            request=request,
            spectrum=spectrum,
        )
    raise ValueError("task_type must be S1 or X4")
