"""Immutable runtime types produced by :mod:`src.algorithm_api.loader`."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class CompiledLink:
    link_id: int
    source_node_id: int
    destination_node_id: int


@dataclass(frozen=True)
class CompiledPath:
    path_node_ids: tuple[int, ...]
    path_link_ids: tuple[int, ...]
    path_rank: int | None = None


@dataclass(frozen=True)
class CompiledRequest:
    request_id: str
    source_node_id: int
    destination_node_id: int
    required_slots: int
    fixed_path: CompiledPath | None = None
    candidate_paths: tuple[CompiledPath, ...] = ()


@dataclass(frozen=True)
class CompiledAlgorithmCase:
    case_id: str | None
    schema_version: str
    task_type: str
    slot_count: int
    nodes: tuple[int, ...]
    directed_links: tuple[CompiledLink, ...]
    edge_src: tuple[int, ...]
    edge_dst: tuple[int, ...]
    out_edges: tuple[tuple[int, ...], ...]
    occupied_mask_by_link: Mapping[int, int]
    required_slots_probabilities: Mapping[str, float]
    requests: tuple[CompiledRequest, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "occupied_mask_by_link", MappingProxyType(dict(self.occupied_mask_by_link)))
        object.__setattr__(self, "required_slots_probabilities", MappingProxyType(dict(self.required_slots_probabilities)))
