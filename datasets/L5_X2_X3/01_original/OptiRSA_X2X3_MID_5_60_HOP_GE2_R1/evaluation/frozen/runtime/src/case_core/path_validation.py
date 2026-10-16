from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PathValidationResult:
    valid: bool
    error: str | None = None


def _link_index(directed_links: list[dict]) -> dict[int, dict]:
    idx: dict[int, dict] = {}
    for row in directed_links:
        link_id = int(row["link_id"])
        if link_id in idx:
            raise ValueError(f"duplicate link_id {link_id}")
        idx[link_id] = row
    return idx


def path_nodes_from_links(path_link_ids: list[int], directed_links: list[dict]) -> list[int]:
    if not path_link_ids:
        raise ValueError("path_link_ids must be non-empty")
    idx = _link_index(directed_links)
    try:
        first = idx[int(path_link_ids[0])]
    except KeyError as exc:
        raise ValueError(f"unknown link_id {path_link_ids[0]}") from exc
    nodes = [int(first["source_node_id"]), int(first["destination_node_id"])]
    for link_id in path_link_ids[1:]:
        try:
            row = idx[int(link_id)]
        except KeyError as exc:
            raise ValueError(f"unknown link_id {link_id}") from exc
        if int(row["source_node_id"]) != nodes[-1]:
            raise ValueError("path links are not directionally contiguous")
        nodes.append(int(row["destination_node_id"]))
    return nodes


def validate_directed_path(
    path_link_ids: list[int],
    path_node_ids: list[int],
    directed_links: list[dict],
    source_node_id: int,
    destination_node_id: int,
) -> PathValidationResult:
    try:
        reconstructed = path_nodes_from_links(path_link_ids, directed_links)
    except ValueError as exc:
        return PathValidationResult(False, str(exc))
    if reconstructed != list(path_node_ids):
        return PathValidationResult(False, "path_node_ids do not match path_link_ids")
    if reconstructed[0] != source_node_id or reconstructed[-1] != destination_node_id:
        return PathValidationResult(False, "path endpoints do not match request endpoints")
    if len(set(reconstructed)) != len(reconstructed):
        return PathValidationResult(False, "path is not simple")
    return PathValidationResult(True, None)
