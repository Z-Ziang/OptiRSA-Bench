from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from random import Random

import networkx as nx

from src.state_simulation.core import free_blocks

from .simulation import PathCatalog


def ordered_request_pairs(node_count: int) -> list[tuple[int, int]]:
    return [(source, destination) for source in range(node_count)
            for destination in range(node_count) if source != destination]


def _quantile(sorted_values: list[int], probability: float) -> float:
    position = (len(sorted_values)-1)*probability
    low = int(position)
    high = min(low+1, len(sorted_values)-1)
    fraction = position-low
    return sorted_values[low]*(1-fraction)+sorted_values[high]*fraction


def stratified_request_pairs(node_count: int, edges: list[tuple[int, int]], sample_size: int,
                             rng: Random) -> list[tuple[int, int]]:
    pairs = ordered_request_pairs(node_count)
    if sample_size > len(pairs):
        raise ValueError("sample size exceeds ordered pair population")
    graph = nx.Graph()
    graph.add_nodes_from(range(node_count))
    graph.add_edges_from(edges)
    distances = dict(nx.all_pairs_shortest_path_length(graph))
    hops = sorted(distances[source][destination] for source, destination in pairs)
    p33, p66 = _quantile(hops, 0.33), _quantile(hops, 0.66)
    bridge_graph = graph.copy()
    bridge_graph.remove_edges_from(nx.bridges(graph))
    component = {}
    for index, nodes in enumerate(nx.connected_components(bridge_graph)):
        for node in nodes:
            component[node] = index
    strata: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for source, destination in pairs:
        hop = distances[source][destination]
        hop_band = "LOW" if hop <= p33 else "MID" if hop <= p66 else "HIGH"
        connectivity = "GE2" if component[source] == component[destination] else "EQ1"
        strata[(hop_band, connectivity)].append((source, destination))
    for values in strata.values():
        rng.shuffle(values)
    nonempty = [key for key in sorted(strata) if strata[key]]
    result = []
    positions = {key: 0 for key in nonempty}
    while len(result) < sample_size:
        progressed = False
        for key in nonempty:
            position = positions[key]
            if position < len(strata[key]):
                result.append(strata[key][position])
                positions[key] += 1
                progressed = True
                if len(result) == sample_size:
                    break
        if not progressed:
            raise RuntimeError("stratified sampler exhausted unexpectedly")
    return result


def nearest_rank_cutpoints(values: list[int]) -> tuple[int, int]:
    """Return V1.0 P33/P66 nearest-rank cut points (no interpolation)."""
    import math
    if not values:
        raise ValueError("cannot compute cutpoints from an empty population")
    ordered = sorted(int(value) for value in values)
    p33 = ordered[math.ceil(0.33 * len(ordered)) - 1]
    p66 = ordered[math.ceil(0.66 * len(ordered)) - 1]
    return p33, p66


def _largest_remainder_quotas(strata: dict[str, list[tuple[int, int]]], sample_size: int) -> dict[str, int]:
    import math
    nonempty = {key: values for key, values in strata.items() if values}
    if sample_size < len(nonempty):
        raise ValueError("sample_size is smaller than the number of nonempty strata")
    population = sum(len(values) for values in nonempty.values())
    raw = {key: sample_size * len(values) / population for key, values in nonempty.items()}
    quotas = {key: max(1, math.floor(raw[key])) for key in nonempty}
    while sum(quotas.values()) < sample_size:
        candidates = sorted(nonempty, key=lambda key: (-(raw[key] - math.floor(raw[key])), key))
        for key in candidates:
            if quotas[key] < len(nonempty[key]):
                quotas[key] += 1
                break
        else:
            raise RuntimeError("largest-remainder allocation exhausted")
    while sum(quotas.values()) > sample_size:
        candidates = sorted(
            (key for key in nonempty if quotas[key] > 1),
            key=lambda key: (raw[key] - math.floor(raw[key]), key),
        )
        if not candidates:
            raise RuntimeError("cannot enforce minimum-one quota within sample_size")
        quotas[candidates[0]] -= 1
    return {key: quotas[key] for key in sorted(quotas)}


def _coverage(selected_by_stratum: dict[str, list[tuple[int, int]]], node_count: int) -> tuple[dict[int, int], dict[int, int]]:
    source_counts = {node: 0 for node in range(node_count)}
    destination_counts = {node: 0 for node in range(node_count)}
    for values in selected_by_stratum.values():
        for source, destination in values:
            source_counts[source] += 1
            destination_counts[destination] += 1
    return source_counts, destination_counts


def _repair_coverage(
    selected_by_stratum: dict[str, list[tuple[int, int]]],
    population_by_stratum: dict[str, list[tuple[int, int]]],
    node_count: int,
) -> int:
    """Repair source/destination coverage using same-stratum replacements only."""
    repair_count = 0
    max_iterations = 4 * node_count + 10
    for _ in range(max_iterations):
        source_counts, destination_counts = _coverage(selected_by_stratum, node_count)
        missing_sources = [node for node, count in source_counts.items() if count == 0]
        missing_destinations = [node for node, count in destination_counts.items() if count == 0]
        if not missing_sources and not missing_destinations:
            return repair_count

        target_kind = "source" if missing_sources else "destination"
        target = (missing_sources if missing_sources else missing_destinations)[0]
        repaired = False
        for stratum in sorted(population_by_stratum):
            selected = selected_by_stratum[stratum]
            selected_set = set(selected)
            candidates = [pair for pair in population_by_stratum[stratum] if pair not in selected_set and
                          (pair[0] == target if target_kind == "source" else pair[1] == target)]
            for candidate in candidates:
                cs, cd = candidate
                for victim_index, victim in enumerate(selected):
                    vs, vd = victim
                    # Removing the victim must not destroy already achieved coverage.
                    if source_counts[vs] <= 1 or destination_counts[vd] <= 1:
                        continue
                    selected[victim_index] = candidate
                    repair_count += 1
                    repaired = True
                    break
                if repaired:
                    break
            if repaired:
                break
        if not repaired:
            raise ValueError(
                f"same-stratum node coverage repair is impossible for missing {target_kind} node {target}"
            )
    raise RuntimeError("node coverage repair exceeded deterministic iteration budget")


def stratified_request_pairs_v1(
    node_count: int,
    edges: list[tuple[int, int]],
    sample_size: int,
    rng: Random,
) -> tuple[list[tuple[int, int]], dict]:
    """Formal V1.0 request sampler for 100<N<=500 (also testable on smaller graphs).

    It implements proportional short/middle/long hop band x local-edge-
    connectivity {1,>=2} stratification, nearest-rank P33/P66, largest-
    remainder quotas, sampling without replacement, and same-stratum node
    source/destination coverage repair.
    """
    if sample_size < node_count:
        raise ValueError("sample_size is too small to guarantee source/destination node coverage")
    pairs = ordered_request_pairs(node_count)
    if sample_size > len(pairs):
        raise ValueError("sample size exceeds ordered pair population")
    graph = nx.Graph()
    graph.add_nodes_from(range(node_count))
    graph.add_edges_from(edges)
    if not nx.is_connected(graph):
        raise ValueError("request sampling requires a connected topology")
    distances = dict(nx.all_pairs_shortest_path_length(graph))
    hop_values = [distances[source][destination] for source, destination in pairs]
    p33, p66 = nearest_rank_cutpoints(hop_values)

    # For a connected undirected graph, s and t have local edge connectivity >=2
    # iff they remain in the same component after all bridges are removed.
    bridge_free = graph.copy()
    bridge_free.remove_edges_from(nx.bridges(graph))
    component: dict[int, int] = {}
    for component_id, nodes in enumerate(nx.connected_components(bridge_free)):
        for node in nodes:
            component[node] = component_id

    strata: dict[str, list[tuple[int, int]]] = defaultdict(list)
    pair_stratum: dict[tuple[int, int], str] = {}
    for source, destination in pairs:
        hops = distances[source][destination]
        hop_band = "SHORT" if hops <= p33 else "MEDIUM" if hops <= p66 else "LONG"
        connectivity_band = "EC_GE2" if component[source] == component[destination] else "EC_EQ1"
        key = f"{hop_band}__{connectivity_band}"
        strata[key].append((source, destination))
        pair_stratum[(source, destination)] = key

    quotas = _largest_remainder_quotas(strata, sample_size)
    selected_by_stratum: dict[str, list[tuple[int, int]]] = {}
    for key in sorted(quotas):
        values = list(strata[key])
        rng.shuffle(values)
        selected_by_stratum[key] = values[: quotas[key]]

    source_before, destination_before = _coverage(selected_by_stratum, node_count)
    repair_count = _repair_coverage(selected_by_stratum, strata, node_count)
    source_after, destination_after = _coverage(selected_by_stratum, node_count)

    selected: list[tuple[int, int]] = []
    # Preserve deterministic stratum grouping; the later request generator has its
    # own frozen random stream for slot-demand selection.
    for key in sorted(selected_by_stratum):
        selected.extend(selected_by_stratum[key])
    if len(selected) != sample_size or len(set(selected)) != sample_size:
        raise RuntimeError("V1.0 sampler produced an invalid sample cardinality")

    final_pair_to_stratum = {f"{source}->{destination}": pair_stratum[(source, destination)]
                             for source, destination in selected}
    audit = {
        "sampling_policy": "V1_STRATIFIED_SAMPLE_S2000_PROPORTIONAL_COVERAGE_REPAIRED",
        "population_size": len(pairs),
        "sample_size": sample_size,
        "p33_nearest_rank": p33,
        "p66_nearest_rank": p66,
        "stratum_population_counts": {key: len(strata[key]) for key in sorted(strata) if strata[key]},
        "quotas": quotas,
        "repair_count": repair_count,
        "coverage_before": {
            "all_sources_covered": all(source_before.values()),
            "all_destinations_covered": all(destination_before.values()),
            "missing_sources": [node for node, count in source_before.items() if count == 0],
            "missing_destinations": [node for node, count in destination_before.items() if count == 0],
        },
        "coverage_after": {
            "all_sources_covered": all(source_after.values()),
            "all_destinations_covered": all(destination_after.values()),
            "missing_sources": [node for node, count in source_after.items() if count == 0],
            "missing_destinations": [node for node, count in destination_after.items() if count == 0],
        },
        "pair_to_stratum": final_pair_to_stratum,
    }
    return selected, audit


@dataclass
class RequestDeriver:
    topology_id: str
    resource_state_id: str
    graph: nx.Graph
    catalog: PathCatalog
    availability: dict[int, list[int]]
    physical_lengths: dict[int, float]
    connectivity_tree: nx.Graph

    @classmethod
    def from_objects(cls, physical: dict, state: dict, candidate_path_k: int) -> "RequestDeriver":
        edges = [(item["node_u_id"], item["node_v_id"]) for item in physical["physical_link_records"]]
        graph = nx.Graph()
        graph.add_nodes_from(item["node_id"] for item in physical["node_records"])
        graph.add_edges_from(edges, capacity=1)
        catalog = PathCatalog.from_edges(len(physical["node_records"]), edges, candidate_path_k)
        availability = {item["link_id"]: item["slot_availability"] for item in state["link_spectrum_states"]}
        lengths = {item["physical_link_id"]: item["length_km"] for item in physical["physical_link_records"]
                   if "length_km" in item}
        tree = nx.gomory_hu_tree(graph, capacity="capacity")
        return cls(physical["topology_id"], state["resource_state_id"], graph, catalog,
                   availability, lengths, tree)

    def local_edge_connectivity(self, source: int, destination: int) -> int:
        tree_path = nx.shortest_path(self.connectivity_tree, source, destination)
        return int(min(self.connectivity_tree[u][v]["weight"] for u, v in zip(tree_path, tree_path[1:])))

    def derive(self, request: dict) -> dict:
        source, destination = request["source_node_id"], request["destination_node_id"]
        required = request["required_slots"]
        candidates = []
        for rank, path in enumerate(self.catalog.paths(source, destination), 1):
            common = [int(all(self.availability[link][slot] for link in path))
                      for slot in range(len(next(iter(self.availability.values()))))]
            blocks = free_blocks(common)
            starts = [start for start in range(len(common)-required+1) if all(common[start:start+required])]
            item = {
                "rank": rank,
                "path_link_ids": path,
                "common_free_block_count": len(blocks),
                "largest_common_free_block_length": max((length for _, length in blocks), default=0),
                "feasible_slot_starts": starts,
            }
            if self.physical_lengths:
                item["total_length_km"] = sum(self.physical_lengths[link//2] for link in path)
            candidates.append(item)
        return {
            "request_id": request["request_id"], "resource_state_id": self.resource_state_id,
            "shortest_path_hops": nx.shortest_path_length(self.graph, source, destination),
            "local_edge_connectivity": self.local_edge_connectivity(source, destination),
            "candidate_path_k": self.catalog.k, "candidate_paths": candidates,
            "feasible_candidate_path_count": sum(bool(item["feasible_slot_starts"]) for item in candidates),
            "feasible_action_count": sum(len(item["feasible_slot_starts"]) for item in candidates),
        }


def generate_requests(topology_id: str, pairs: list[tuple[int, int]], required_slots: list[int],
                      rng: Random) -> list[dict]:
    return [
        {"request_id": f"req_{topology_id[4:]}_{index:06d}", "topology_id": topology_id,
         "source_node_id": source, "destination_node_id": destination,
         "required_slots": rng.choice(required_slots)}
        for index, (source, destination) in enumerate(pairs, 1)
    ]


def generate_dynamic_sequence(topology_id: str, node_count: int, reference_time: float,
                              arrival_rate: float, holding_rate: float, required_slots: list[int],
                              rng: Random, length: int = 20) -> dict:
    now = reference_time
    events = []
    for index in range(1, length+1):
        now += rng.expovariate(arrival_rate)
        source = rng.randrange(node_count)
        destination = rng.randrange(node_count-1)
        if destination >= source:
            destination += 1
        events.append({
            "request_id": f"dynreq_{topology_id[4:]}_{index:04d}",
            "source_node_id": source, "destination_node_id": destination,
            "required_slots": rng.choice(required_slots), "arrival_time": now,
            "holding_time": rng.expovariate(holding_rate),
        })
    return {"request_sequence_id": f"seq_{topology_id[4:]}", "dynamic_request_events": events,
            "arrival_rate_lambda": arrival_rate, "holding_time_rate_mu": holding_rate}
