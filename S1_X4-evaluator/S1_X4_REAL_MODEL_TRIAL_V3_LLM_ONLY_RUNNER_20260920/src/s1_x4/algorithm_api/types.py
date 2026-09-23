from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np


def _readonly_array(value: Any, *, dtype: Any) -> np.ndarray:
    array = np.array(value, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class CompiledTopology:
    node_ids: np.ndarray
    link_ids: np.ndarray
    sources: np.ndarray
    destinations: np.ndarray
    adjacency_offsets: np.ndarray
    adjacency_link_indices: np.ndarray

    def __post_init__(self) -> None:
        for name in (
            "node_ids",
            "link_ids",
            "sources",
            "destinations",
            "adjacency_offsets",
            "adjacency_link_indices",
        ):
            object.__setattr__(self, name, _readonly_array(getattr(self, name), dtype=np.int32))

    def outgoing_link_indices(self, node_id: int) -> np.ndarray:
        matches = np.flatnonzero(self.node_ids == int(node_id))
        if len(matches) == 0:
            return np.array([], dtype=np.int32)
        row = int(matches[0])
        start, end = self.adjacency_offsets[row : row + 2]
        return self.adjacency_link_indices[int(start) : int(end)]

    def link_row(self, link_id: int) -> int:
        matches = np.flatnonzero(self.link_ids == int(link_id))
        if len(matches) == 0:
            raise KeyError(f"unknown link_id: {link_id}")
        return int(matches[0])

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "node_ids": [int(x) for x in self.node_ids.tolist()],
            "directed_links": [
                {
                    "link_id": int(link_id),
                    "source_node_id": int(source),
                    "destination_node_id": int(destination),
                }
                for link_id, source, destination in zip(
                    self.link_ids.tolist(), self.sources.tolist(), self.destinations.tolist()
                )
            ],
        }


@dataclass(frozen=True)
class CompiledSpectrum:
    slot_count: int
    link_ids: np.ndarray
    free_words: np.ndarray

    def __post_init__(self) -> None:
        if not isinstance(self.slot_count, int) or isinstance(self.slot_count, bool) or self.slot_count <= 0:
            raise ValueError("slot_count must be a positive integer")
        object.__setattr__(self, "link_ids", _readonly_array(self.link_ids, dtype=np.int32))
        words = np.array(self.free_words, dtype=np.uint64, copy=True)
        expected_words = (self.slot_count + 63) // 64
        if words.ndim != 2 or words.shape != (len(self.link_ids), expected_words):
            raise ValueError("compiled spectrum shape does not match link and slot counts")
        words.setflags(write=False)
        object.__setattr__(self, "free_words", words)
        if len(set(int(x) for x in self.link_ids.tolist())) != len(self.link_ids):
            raise ValueError("compiled spectrum contains duplicate link_id")

    def row_for_link(self, link_id: int) -> int:
        matches = np.flatnonzero(self.link_ids == int(link_id))
        if len(matches) == 0:
            raise KeyError(f"unknown link_id: {link_id}")
        return int(matches[0])

    def free_slots(self, link_id: int) -> list[int]:
        row = self.free_words[self.row_for_link(link_id)]
        return [
            slot
            for slot in range(self.slot_count)
            if int(row[slot // 64]) & (1 << (slot % 64))
        ]

    def to_binary_by_link(self) -> dict[int, list[int]]:
        from .bitset import free_words_to_binary

        return {
            int(link_id): free_words_to_binary(self.free_words[row], self.slot_count)
            for row, link_id in enumerate(self.link_ids.tolist())
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "slot_count": self.slot_count,
            "link_spectrum_states": [
                {"link_id": int(link_id), "slot_availability": values}
                for link_id, values in sorted(self.to_binary_by_link().items())
            ],
        }


@dataclass(frozen=True)
class CandidatePath:
    path_rank: int
    path_node_ids: tuple[int, ...]
    path_link_ids: tuple[int, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "path_rank": self.path_rank,
            "path_node_ids": list(self.path_node_ids),
            "path_link_ids": list(self.path_link_ids),
        }


@dataclass(frozen=True)
class AlgorithmStaticContext:
    case_id: str
    task_type: str
    topology_id: str
    slot_count: int
    topology: CompiledTopology

    def to_public_dict(self) -> dict[str, Any]:
        topology = self.topology.to_public_dict()
        return {
            "schema_version": "S1_X4_ALGORITHM_STATIC_CONTEXT_V1_0",
            "case_id": self.case_id,
            "task_type": self.task_type,
            "topology_id": self.topology_id,
            "node_ids": topology["node_ids"],
            "directed_links": topology["directed_links"],
            "slot_count": self.slot_count,
        }


@dataclass(frozen=True)
class AlgorithmObservation:
    case_id: str
    task_type: str
    step_index: int
    current_time: float
    request: Mapping[str, Any]
    spectrum: CompiledSpectrum
    candidate_paths: tuple[CandidatePath, ...] | None = None
    feasible_actions: np.ndarray | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request", MappingProxyType(dict(self.request)))
        if self.task_type == "S1":
            if self.candidate_paths is None or self.feasible_actions is None:
                raise ValueError("S1 observations require candidate_paths and feasible_actions")
            actions = _readonly_array(self.feasible_actions, dtype=np.int32)
            if actions.size == 0:
                actions = actions.reshape((0, 2))
            if actions.ndim != 2 or actions.shape[1] != 2:
                raise ValueError("S1 feasible_actions must have shape (N,2)")
            object.__setattr__(self, "feasible_actions", actions)
            object.__setattr__(self, "candidate_paths", tuple(self.candidate_paths))
        elif self.task_type == "X4":
            if self.candidate_paths is not None or self.feasible_actions is not None:
                raise ValueError("X4 observations cannot contain candidate paths or actions")
        else:
            raise ValueError("task_type must be S1 or X4")

    def to_public_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": "S1_X4_ALGORITHM_OBSERVATION_V1_0",
            "case_id": self.case_id,
            "task_type": self.task_type,
            "step_index": self.step_index,
            "current_time": self.current_time,
            "request": dict(self.request),
            "spectrum": self.spectrum.to_public_dict(),
        }
        if self.task_type == "S1":
            out["candidate_paths"] = [p.to_public_dict() for p in self.candidate_paths or ()]
            out["feasible_actions"] = [
                {"path_rank": int(row[0]), "slot_start": int(row[1])}
                for row in self.feasible_actions.tolist()
            ]
        return out
