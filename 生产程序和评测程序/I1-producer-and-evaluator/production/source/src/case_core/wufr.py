from __future__ import annotations

from collections import deque
from math import isclose

from src.case_core.allocation_validation import assignment_interval

WUFR_ABS_TOL = 1e-12
CANONICAL_REQUIRED_SLOTS = (2, 3, 5, 9)


def _validate_required_slots_probabilities(required_slots_probabilities: dict[int, float]) -> dict[int, float]:
    if not isinstance(required_slots_probabilities, dict) or not required_slots_probabilities:
        raise ValueError("required_slots probabilities must be a non-empty mapping")
    out: dict[int, float] = {}
    total = 0.0
    for width, probability in required_slots_probabilities.items():
        if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
            raise ValueError("required_slots width must be a positive integer")
        p = float(probability)
        if p < 0:
            raise ValueError("required_slots probability must be non-negative")
        out[int(width)] = p
        total += p
    if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("required_slots probabilities must sum to 1")
    return out


def _common_free_blocks(path_link_ids: list[int], spectrum_by_link: dict[int, list[int]]) -> list[tuple[int, int]]:
    if not path_link_ids:
        raise ValueError("reference path must contain at least one link")
    rows = []
    slot_count: int | None = None
    for link_id in path_link_ids:
        if int(link_id) not in spectrum_by_link:
            raise ValueError(f"missing spectrum row for link {link_id}")
        row = spectrum_by_link[int(link_id)]
        if slot_count is None:
            slot_count = len(row)
        elif len(row) != slot_count:
            raise ValueError("inconsistent spectrum row lengths")
        if any(v not in (0, 1) for v in row):
            raise ValueError("spectrum rows must use 1=free, 0=occupied")
        rows.append(row)
    assert slot_count is not None
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for f in range(slot_count):
        all_free = all(row[f] == 1 for row in rows)
        if all_free and start is None:
            start = f
        elif not all_free and start is not None:
            blocks.append((start, f - 1))
            start = None
    if start is not None:
        blocks.append((start, slot_count - 1))
    return blocks


def path_wufr(
    path_link_ids: list[int],
    spectrum_by_link: dict[int, list[int]],
    required_slots_probabilities: dict[int, float],
) -> float:
    q = _validate_required_slots_probabilities(required_slots_probabilities)
    if not path_link_ids:
        raise ValueError("path_link_ids must be non-empty")
    rows = [spectrum_by_link[int(link_id)] for link_id in path_link_ids]
    slot_count = len(rows[0])
    if any(len(row) != slot_count for row in rows):
        raise ValueError("inconsistent spectrum row lengths")
    n_p = len(rows)
    c = [sum(row[f] == 1 for row in rows) for f in range(slot_count)]
    free_total = float(sum(c))
    if free_total == 0:
        return 0.0
    wasted = float(sum(count for count in c if 0 < count < n_p))
    unusable = 0.0
    for start, end in _common_free_blocks(path_link_ids, spectrum_by_link):
        length = end - start + 1
        p_fit = sum(prob for width, prob in q.items() if width <= length)
        unusable += n_p * length * (1.0 - p_fit)
    value = (wasted + unusable) / free_total
    return float(value)


def _adjacency_and_links(directed_links: list[dict]) -> tuple[dict[int, list[int]], dict[tuple[int, int], int]]:
    adjacency: dict[int, set[int]] = {}
    edge_to_link: dict[tuple[int, int], int] = {}
    for row in directed_links:
        u = int(row["source_node_id"])
        v = int(row["destination_node_id"])
        link_id = int(row["link_id"])
        adjacency.setdefault(u, set()).add(v)
        adjacency.setdefault(v, set())
        key = (u, v)
        if key in edge_to_link and edge_to_link[key] != link_id:
            raise ValueError("parallel directed links are unsupported by canonical reference path selection")
        edge_to_link[key] = link_id
    return {u: sorted(vs) for u, vs in adjacency.items()}, edge_to_link


def _lexicographic_shortest_node_path(source: int, target: int, adjacency: dict[int, list[int]]) -> list[int]:
    queue = deque([[source]])
    best_depth: dict[int, int] = {source: 0}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == target:
            return path
        depth = len(path) - 1
        for neighbor in adjacency.get(node, []):
            next_depth = depth + 1
            previous = best_depth.get(neighbor)
            if previous is None or next_depth <= previous:
                # Allow equal-depth alternatives so queue order determines lexicographic first target path.
                best_depth[neighbor] = next_depth
                if neighbor not in path:
                    queue.append(path + [neighbor])
    raise ValueError(f"no directed path from {source} to {target}")


def _lexicographic_shortest_node_paths(source: int, adjacency: dict[int, list[int]]) -> dict[int, list[int]]:
    """Return the lexicographically first shortest path to every reachable node.

    Adjacency is traversed in sorted order.  Standard BFS therefore discovers
    each node through its lexicographically first shortest path; retaining only
    that first discovery is equivalent to the legacy pairwise BFS while
    avoiding its exponential equal-depth path queue.
    """
    source = int(source)
    paths: dict[int, list[int]] = {source: [source]}
    queue = deque([source])
    while queue:
        node = queue.popleft()
        path = paths[node]
        for neighbor in adjacency.get(node, []):
            neighbor = int(neighbor)
            if neighbor in path or neighbor in paths:
                continue
            paths[neighbor] = path + [neighbor]
            queue.append(neighbor)
    return paths


def build_reference_paths(nodes: list[int], directed_links: list[dict]) -> list[dict]:
    ordered_nodes = sorted(int(x) for x in nodes)
    adjacency, edge_to_link = _adjacency_and_links(directed_links)
    refs: list[dict] = []
    for source in ordered_nodes:
        paths_from_source = _lexicographic_shortest_node_paths(source, adjacency)
        for target in ordered_nodes:
            if source == target:
                continue
            node_path = paths_from_source.get(target)
            if node_path is None:
                raise ValueError(f"no directed path from {source} to {target}")
            link_path = [edge_to_link[(u, v)] for u, v in zip(node_path, node_path[1:])]
            refs.append({
                "source_node_id": source,
                "destination_node_id": target,
                "path_node_ids": node_path,
                "path_link_ids": link_path,
            })
    return refs


def network_wufr(
    nodes: list[int],
    directed_links: list[dict],
    spectrum_by_link: dict[int, list[int]],
    required_slots_probabilities: dict[int, float],
    reference_paths: list[dict] | None = None,
) -> float:
    refs = reference_paths if reference_paths is not None else build_reference_paths(nodes, directed_links)
    if not refs:
        raise ValueError("network must contain at least two connected nodes")
    return float(sum(path_wufr(item["path_link_ids"], spectrum_by_link, required_slots_probabilities) for item in refs) / len(refs))


def apply_allocations_copy(spectrum_by_link: dict[int, list[int]], allocations: list[dict]) -> dict[int, list[int]]:
    result = {int(link_id): list(values) for link_id, values in spectrum_by_link.items()}
    if not result:
        raise ValueError("empty spectrum state")
    slot_count = len(next(iter(result.values())))
    for item in allocations:
        path_link_ids = [int(x) for x in item["path_link_ids"]]
        slot_start = int(item["slot_start"])
        required_slots = int(item["required_slots"])
        interval = assignment_interval(slot_start, required_slots, slot_count)
        for link_id in path_link_ids:
            row = result.get(link_id)
            if row is None:
                raise ValueError(f"unknown link_id {link_id}")
            for slot in interval:
                if row[slot] != 1:
                    raise ValueError("allocation collides with occupied spectrum")
                row[slot] = 0
    return result
