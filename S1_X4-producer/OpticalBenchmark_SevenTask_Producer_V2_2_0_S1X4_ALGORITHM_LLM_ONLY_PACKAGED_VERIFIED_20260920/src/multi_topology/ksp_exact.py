"""Exact, semantics-preserving unweighted Yen K-shortest-simple-path backend.

The compiled path reproduces NetworkX ``shortest_simple_paths(..., weight=None)``
ordering for the supported V1.0 domain (simple undirected integer-node graphs,
K<=8).  It mirrors NetworkX's bidirectional BFS direction choice, neighbour
iteration order, cumulative ignored-edge behaviour, and PathBuffer insertion
counter.  If the bounded candidate workspace is insufficient, the wrapper
falls back to NetworkX rather than returning an approximation.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice

import networkx as nx
import numpy as np
from numba import njit


@njit(cache=True)
def _edge_ignored(u: int, v: int, edge_u: np.ndarray, edge_v: np.ndarray, edge_count: int) -> bool:
    for i in range(edge_count):
        a = edge_u[i]
        b = edge_v[i]
        if (a == u and b == v) or (a == v and b == u):
            return True
    return False


@njit(cache=True)
def _bidirectional_bfs(
    offsets: np.ndarray,
    neighbors: np.ndarray,
    source: int,
    target: int,
    ignore_nodes: np.ndarray,
    ignore_edge_u: np.ndarray,
    ignore_edge_v: np.ndarray,
    ignore_edge_count: int,
    path_out: np.ndarray,
) -> int:
    n = len(offsets) - 1
    if ignore_nodes[source] or ignore_nodes[target]:
        return 0
    if source == target:
        path_out[0] = source
        return 1

    pred = np.full(n, -2, dtype=np.int64)
    succ = np.full(n, -2, dtype=np.int64)
    pred[source] = -1
    succ[target] = -1
    forward = np.empty(n, dtype=np.int64)
    reverse = np.empty(n, dtype=np.int64)
    next_fringe = np.empty(n, dtype=np.int64)
    forward[0] = source
    reverse[0] = target
    f_count = 1
    r_count = 1
    meet = -1

    while f_count > 0 and r_count > 0:
        if f_count <= r_count:
            next_count = 0
            for fi in range(f_count):
                v = forward[fi]
                for pos in range(offsets[v], offsets[v + 1]):
                    w = neighbors[pos]
                    if ignore_nodes[w] or _edge_ignored(v, w, ignore_edge_u, ignore_edge_v, ignore_edge_count):
                        continue
                    if pred[w] == -2:
                        next_fringe[next_count] = w
                        next_count += 1
                        pred[w] = v
                    if succ[w] != -2:
                        meet = w
                        break
                if meet != -1:
                    break
            if meet != -1:
                break
            for i in range(next_count):
                forward[i] = next_fringe[i]
            f_count = next_count
        else:
            next_count = 0
            for ri in range(r_count):
                v = reverse[ri]
                for pos in range(offsets[v], offsets[v + 1]):
                    w = neighbors[pos]
                    if ignore_nodes[w] or _edge_ignored(v, w, ignore_edge_u, ignore_edge_v, ignore_edge_count):
                        continue
                    if succ[w] == -2:
                        succ[w] = v
                        next_fringe[next_count] = w
                        next_count += 1
                    if pred[w] != -2:
                        meet = w
                        break
                if meet != -1:
                    break
            if meet != -1:
                break
            for i in range(next_count):
                reverse[i] = next_fringe[i]
            r_count = next_count

    if meet == -1:
        return 0

    backward = np.empty(n, dtype=np.int64)
    b_count = 0
    w = meet
    while w != -1:
        backward[b_count] = w
        b_count += 1
        w = pred[w]
    out_count = 0
    for i in range(b_count - 1, -1, -1):
        path_out[out_count] = backward[i]
        out_count += 1
    w = succ[meet]
    while w != -1:
        path_out[out_count] = w
        out_count += 1
        w = succ[w]
    return out_count


@njit(cache=True)
def _prefix_equal(path_a: np.ndarray, len_a: int, path_b: np.ndarray, prefix_len: int) -> bool:
    if len_a < prefix_len:
        return False
    for i in range(prefix_len):
        if path_a[i] != path_b[i]:
            return False
    return True


@njit(cache=True)
def _same_path(path_a: np.ndarray, len_a: int, path_b: np.ndarray, len_b: int) -> bool:
    if len_a != len_b:
        return False
    for i in range(len_a):
        if path_a[i] != path_b[i]:
            return False
    return True


@njit(cache=True)
def _yen_k_paths(
    offsets: np.ndarray,
    neighbors: np.ndarray,
    source: int,
    target: int,
    k: int,
    workspace_capacity: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (paths, lengths, status). status 0=ok, -2=workspace overflow."""
    n = len(offsets) - 1
    output = np.full((k, n), -1, dtype=np.int64)
    output_len = np.zeros(k, dtype=np.int64)
    ignore_nodes = np.zeros(n, dtype=np.bool_)
    max_ignore_edges = max(1, n * k)
    ignore_u = np.empty(max_ignore_edges, dtype=np.int64)
    ignore_v = np.empty(max_ignore_edges, dtype=np.int64)
    first = np.empty(n, dtype=np.int64)
    empty_u = np.empty(1, dtype=np.int64)
    empty_v = np.empty(1, dtype=np.int64)
    first_len = _bidirectional_bfs(offsets, neighbors, source, target, ignore_nodes, empty_u, empty_v, 0, first)
    if first_len == 0:
        return output, output_len, 0
    for i in range(first_len):
        output[0, i] = first[i]
    output_len[0] = first_len
    produced = 1

    cand_paths = np.full((workspace_capacity, n), -1, dtype=np.int64)
    cand_len = np.zeros(workspace_capacity, dtype=np.int64)
    cand_cost = np.zeros(workspace_capacity, dtype=np.int64)
    cand_counter = np.zeros(workspace_capacity, dtype=np.int64)
    cand_active = np.zeros(workspace_capacity, dtype=np.bool_)
    insertion_counter = 1  # NetworkX's initial shortest path consumed counter=0.

    while produced < k:
        prev_index = produced - 1
        prev_len = output_len[prev_index]
        for i in range(n):
            ignore_nodes[i] = False
        ignore_edge_count = 0

        for prefix_len in range(1, prev_len):
            # NetworkX's ignore_edges set is cumulative across spur positions.
            for accepted_index in range(produced):
                if _prefix_equal(output[accepted_index], output_len[accepted_index], output[prev_index], prefix_len):
                    u = output[accepted_index, prefix_len - 1]
                    v = output[accepted_index, prefix_len]
                    exists = False
                    for e in range(ignore_edge_count):
                        if (ignore_u[e] == u and ignore_v[e] == v) or (ignore_u[e] == v and ignore_v[e] == u):
                            exists = True
                            break
                    if not exists:
                        if ignore_edge_count >= max_ignore_edges:
                            return output, output_len, -2
                        ignore_u[ignore_edge_count] = u
                        ignore_v[ignore_edge_count] = v
                        ignore_edge_count += 1

            spur = np.empty(n, dtype=np.int64)
            spur_source = output[prev_index, prefix_len - 1]
            spur_len = _bidirectional_bfs(
                offsets, neighbors, spur_source, target, ignore_nodes,
                ignore_u, ignore_v, ignore_edge_count, spur,
            )
            if spur_len > 0:
                combined_len = prefix_len - 1 + spur_len
                combined = np.empty(n, dtype=np.int64)
                for j in range(prefix_len - 1):
                    combined[j] = output[prev_index, j]
                for j in range(spur_len):
                    combined[prefix_len - 1 + j] = spur[j]

                duplicate = False
                for slot in range(workspace_capacity):
                    if cand_active[slot] and _same_path(cand_paths[slot], cand_len[slot], combined, combined_len):
                        duplicate = True
                        break
                if not duplicate:
                    free_slot = -1
                    for slot in range(workspace_capacity):
                        if not cand_active[slot]:
                            free_slot = slot
                            break
                    if free_slot == -1:
                        return output, output_len, -2
                    for j in range(combined_len):
                        cand_paths[free_slot, j] = combined[j]
                    cand_len[free_slot] = combined_len
                    cand_cost[free_slot] = prefix_len + spur_len
                    cand_counter[free_slot] = insertion_counter
                    cand_active[free_slot] = True
                    insertion_counter += 1

            ignore_nodes[output[prev_index, prefix_len - 1]] = True

        best_slot = -1
        best_cost = 0
        best_counter = 0
        for slot in range(workspace_capacity):
            if not cand_active[slot]:
                continue
            if best_slot == -1 or cand_cost[slot] < best_cost or (
                cand_cost[slot] == best_cost and cand_counter[slot] < best_counter
            ):
                best_slot = slot
                best_cost = cand_cost[slot]
                best_counter = cand_counter[slot]
        if best_slot == -1:
            break
        length = cand_len[best_slot]
        for j in range(length):
            output[produced, j] = cand_paths[best_slot, j]
        output_len[produced] = length
        cand_active[best_slot] = False
        produced += 1

    return output, output_len, 0


def _csr_from_graph(graph: nx.Graph) -> tuple[np.ndarray, np.ndarray]:
    nodes = list(graph.nodes)
    if nodes != list(range(len(nodes))):
        raise ValueError("ExactYenKSP requires contiguous integer nodes 0..N-1")
    offsets = np.zeros(len(nodes) + 1, dtype=np.int64)
    flattened: list[int] = []
    for node in nodes:
        flattened.extend(int(neighbor) for neighbor in graph.neighbors(node))
        offsets[node + 1] = len(flattened)
    return offsets, np.asarray(flattened, dtype=np.int64)


@dataclass
class ExactYenKSP:
    graph: nx.Graph
    offsets: np.ndarray
    neighbors: np.ndarray
    workspace_capacity: int = 256
    fallback_count: int = 0

    @classmethod
    def from_graph(cls, graph: nx.Graph, workspace_capacity: int = 256) -> "ExactYenKSP":
        if graph.is_directed() or graph.is_multigraph():
            raise ValueError("ExactYenKSP V1.0 backend supports simple undirected graphs only")
        offsets, neighbors = _csr_from_graph(graph)
        return cls(graph.copy(), offsets, neighbors, workspace_capacity)

    def node_paths(self, source: int, target: int, k: int) -> list[list[int]]:
        if k < 1:
            return []
        if k > 8:
            self.fallback_count += 1
            return list(islice(nx.shortest_simple_paths(self.graph, source, target), k))
        output, lengths, status = _yen_k_paths(
            self.offsets, self.neighbors, int(source), int(target), int(k), int(self.workspace_capacity)
        )
        if status == -2:
            self.fallback_count += 1
            return list(islice(nx.shortest_simple_paths(self.graph, source, target), k))
        result: list[list[int]] = []
        for row, length in zip(output, lengths):
            if length <= 0:
                break
            result.append([int(x) for x in row[: int(length)]])
        return result
