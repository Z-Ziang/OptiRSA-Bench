from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import heapq
from random import Random
from time import perf_counter

import networkx as nx

from .ksp_exact import ExactYenKSP

from src.state_simulation.core import spectrum_metrics


@dataclass(frozen=True)
class Action:
    path_link_ids: list[int]
    slot_start: int


class PathCatalog:
    """Exact KSP catalog with bounded FIFO OD caching.

    The public API returns directed-link-id paths.  ``node_paths`` is exposed
    for audits and request stratification tests.  Eviction changes only runtime:
    evicted ODs are recomputed by the same exact backend.
    """

    def __init__(self, graph: nx.Graph, lookup: dict[tuple[int, int], int], k: int,
                 cache_capacity: int = 32768, workspace_capacity: int = 256):
        self.graph = graph
        self.lookup = lookup
        self.k = k
        self.cache_capacity = cache_capacity
        self._cache: OrderedDict[tuple[int, int], tuple[list[list[int]], list[list[int]]]] = OrderedDict()
        self._engine = ExactYenKSP.from_graph(graph, workspace_capacity=workspace_capacity)

    @classmethod
    def from_edges(cls, node_count: int, edges: list[tuple[int, int]], k: int,
                   cache_capacity: int = 32768, workspace_capacity: int = 256) -> "PathCatalog":
        sorted_edges = sorted(tuple(sorted(edge)) for edge in edges)
        graph = nx.Graph()
        graph.add_nodes_from(range(node_count))
        graph.add_edges_from(sorted_edges)
        lookup: dict[tuple[int, int], int] = {}
        for physical_id, (u, v) in enumerate(sorted_edges):
            lookup[(u, v)] = 2 * physical_id
            lookup[(v, u)] = 2 * physical_id + 1
        return cls(graph, lookup, k, cache_capacity=cache_capacity, workspace_capacity=workspace_capacity)

    def _compute(self, source: int, destination: int) -> tuple[list[list[int]], list[list[int]]]:
        node_paths = self._engine.node_paths(source, destination, self.k)
        link_paths = [
            [self.lookup[pair] for pair in zip(nodes, nodes[1:])]
            for nodes in node_paths
        ]
        return node_paths, link_paths

    def _entry(self, source: int, destination: int) -> tuple[list[list[int]], list[list[int]]]:
        key = (source, destination)
        entry = self._cache.get(key)
        if entry is None:
            entry = self._compute(source, destination)
            self._cache[key] = entry
            while len(self._cache) > self.cache_capacity:
                self._cache.popitem(last=False)
        return entry

    def node_paths(self, source: int, destination: int) -> list[list[int]]:
        return self._entry(source, destination)[0]

    def paths(self, source: int, destination: int) -> list[list[int]]:
        return self._entry(source, destination)[1]

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def workspace_capacity(self) -> int:
        """Capacity of the exact Yen scratch workspace used by this catalog."""
        return self._engine.workspace_capacity

    def clear_cache(self) -> None:
        """Clear the runtime-only OD cache without changing path semantics."""
        self._cache.clear()

    def fresh_runtime_copy(self) -> "PathCatalog":
        """Return a clean cache/engine instance with identical graph semantics."""
        return PathCatalog(
            self.graph, self.lookup, self.k,
            cache_capacity=self.cache_capacity,
            workspace_capacity=self._engine.workspace_capacity,
        )

    @property
    def fast_fallback_count(self) -> int:
        return self._engine.fallback_count


class IncrementalSpectrum:
    def __init__(self, link_count: int, slot_count: int):
        self.slot_count = slot_count
        self.occupancy = [0] * link_count

    def _occupied_on_path(self, path: list[int]) -> int:
        occupied = 0
        for link in path:
            occupied |= self.occupancy[link]
        return occupied

    def _feasible_start_mask(self, path: list[int], required_slots: int) -> int:
        """Bit mask whose set bits are legal contiguous allocation starts.

        This is exactly equivalent to scanning every start position, but it
        intersects shifted free-slot masks in a few integer operations.
        """
        if required_slots < 1 or required_slots > self.slot_count:
            return 0
        occupied = self._occupied_on_path(path)
        free = (~occupied) & ((1 << self.slot_count) - 1)
        valid = free
        for shift in range(1, required_slots):
            valid &= free >> shift
        valid &= (1 << (self.slot_count - required_slots + 1)) - 1
        return valid

    def feasible_starts(self, path: list[int], required_slots: int) -> list[int]:
        valid = self._feasible_start_mask(path, required_slots)
        starts: list[int] = []
        while valid:
            lowest = valid & -valid
            starts.append(lowest.bit_length() - 1)
            valid ^= lowest
        return starts

    def first_feasible_start(self, path: list[int], required_slots: int) -> int | None:
        valid = self._feasible_start_mask(path, required_slots)
        if not valid:
            return None
        return (valid & -valid).bit_length() - 1

    def allocate(self, path: list[int], start: int, required_slots: int) -> None:
        if start < 0 or start + required_slots > self.slot_count:
            raise ValueError("slot boundary")
        mask = ((1 << required_slots) - 1) << start
        if any(self.occupancy[link] & mask for link in path):
            raise ValueError("connection overlap")
        for link in path:
            self.occupancy[link] |= mask

    def release(self, path: list[int], start: int, required_slots: int) -> None:
        mask = ((1 << required_slots) - 1) << start
        for link in path:
            if self.occupancy[link] & mask != mask:
                raise ValueError("release of unoccupied slot")
            self.occupancy[link] &= ~mask

    def link_utilization(self, link_id: int) -> float:
        return self.occupancy[link_id].bit_count() / self.slot_count

    def network_utilization(self) -> float:
        return sum(row.bit_count() for row in self.occupancy) / (len(self.occupancy)*self.slot_count)

    def availability(self) -> dict[int, list[int]]:
        return {link: [0 if mask & (1 << slot) else 1 for slot in range(self.slot_count)]
                for link, mask in enumerate(self.occupancy)}


def choose_action(policy: str, catalog: PathCatalog, spectrum: IncrementalSpectrum,
                  source: int, destination: int, required_slots: int, rng: Random) -> Action | None:
    paths = catalog.paths(source, destination)
    if policy == "BASE_KSP_FF":
        for path in paths:
            start = spectrum.first_feasible_start(path, required_slots)
            if start is not None:
                return Action(path, start)
        return None
    if policy == "LOAD_BALANCED_KSP_FF_PILOT":
        path = min(
            enumerate(paths),
            key=lambda item: (
                sum(spectrum.link_utilization(link) for link in item[1]) / len(item[1]),
                item[0],
            ),
        )[1]
        start = spectrum.first_feasible_start(path, required_slots)
        return None if start is None else Action(path, start)
    feasible = [(path, spectrum.feasible_starts(path, required_slots)) for path in paths]
    feasible = [(path, starts) for path, starts in feasible if starts]
    if not feasible:
        return None
    if policy == "KSP_RF_PILOT":
        selected = rng.randrange(sum(len(starts) for _, starts in feasible))
        for path, starts in feasible:
            if selected < len(starts):
                return Action(path, starts[selected])
            selected -= len(starts)
        raise AssertionError("random feasible-action index out of range")
    raise ValueError(f"unknown allocation policy {policy}")


@dataclass
class TrialResult:
    arrival_rate_lambda: float
    seed: int
    request_count: int
    accepted_count: int
    blocked_count: int
    blocking_probability: float
    reference_time: float
    target_reached: bool
    utilization: float
    metrics: dict
    active_connections: list[dict]
    availability: dict[int, list[int]]
    runtime_seconds: float

    def trace_record(self, holding_rate_mu: float, warmup: int) -> dict:
        return {
            "arrival_rate_lambda": self.arrival_rate_lambda,
            "holding_time_rate_mu": holding_rate_mu,
            "offered_load_erlang": self.arrival_rate_lambda / holding_rate_mu,
            "seed": self.seed,
            "warmup_request_count": warmup,
            "request_count": self.request_count,
            "accepted_count": self.accepted_count,
            "blocked_count": self.blocked_count,
            "blocking_probability": self.blocking_probability,
            "network_spectrum_utilization": self.metrics["network_spectrum_utilization"],
            "max_link_utilization": self.metrics["max_link_utilization"],
            "p90_link_utilization": self.metrics["p90_link_utilization"],
            "link_utilization_variance": self.metrics["link_utilization_variance"],
            "mean_link_external_fragmentation": self.metrics.get("mean_link_external_fragmentation"),
            "reference_time": self.reference_time,
            "target_reached": self.target_reached,
            "runtime_seconds": self.runtime_seconds,
        }


@dataclass
class SearchResult:
    connection_set: dict
    resource_state: dict
    trials: list[dict]
    target_reached: bool
    actual_arrival_rate_lambda: float
    audit_metrics: dict


def _snapshot(active: dict[str, dict], spectrum: IncrementalSpectrum) -> tuple[list[dict], dict[int, list[int]], dict]:
    connections = [dict(active[key]) for key in sorted(active)]
    availability = spectrum.availability()
    metrics = spectrum_metrics(availability, spectrum.slot_count)
    return connections, availability, metrics


def simulate_trial(catalog: PathCatalog, node_count: int, link_count: int, slot_count: int,
                   arrival_rate: float, holding_rate: float, payload_values: list[int],
                   payload_probabilities: list[float], guard_slots: int, warmup: int,
                   maximum_requests: int, target_band: tuple[float, float], policy: str,
                   seed: int) -> TrialResult:
    started = perf_counter()
    rng = Random(seed)
    spectrum = IncrementalSpectrum(link_count, slot_count)
    active: dict[str, dict] = {}
    release_heap: list[tuple[float, str]] = []
    now = 0.0
    accepted = blocked = 0
    best: tuple[float, float, int, int, int, list[dict], dict[int, list[int]], dict] | None = None
    low, high = target_band
    for index in range(1, maximum_requests + 1):
        now += rng.expovariate(arrival_rate)
        while release_heap and release_heap[0][0] <= now:
            _, connection_id = heapq.heappop(release_heap)
            connection = active.pop(connection_id)
            spectrum.release(connection["path_link_ids"], connection["slot_start"], connection["required_slots"])
        source = rng.randrange(node_count)
        destination = rng.randrange(node_count - 1)
        if destination >= source:
            destination += 1
        required = rng.choices(payload_values, weights=payload_probabilities, k=1)[0] + guard_slots
        holding = rng.expovariate(holding_rate)
        action = choose_action(policy, catalog, spectrum, source, destination, required, rng)
        if action is None:
            blocked += 1
        else:
            accepted += 1
            connection_id = f"trial_conn_{index:08d}"
            connection = {
                "connection_id": connection_id,
                "source_node_id": source,
                "destination_node_id": destination,
                "path_link_ids": action.path_link_ids,
                "slot_start": action.slot_start,
                "required_slots": required,
                "arrival_time": now,
                "holding_time": holding,
            }
            spectrum.allocate(action.path_link_ids, action.slot_start, required)
            active[connection_id] = connection
            heapq.heappush(release_heap, (now + holding, connection_id))
        if index < warmup:
            continue
        utilization = spectrum.network_utilization()
        distance = 0.0 if low <= utilization < high else min(abs(utilization-low), abs(utilization-high))
        if best is None or distance < best[0]:
            connections, availability, metrics = _snapshot(active, spectrum)
            best = (distance, now, index, accepted, blocked, connections, availability, metrics)
        if distance == 0.0:
            break
    if best is None:
        raise ValueError("maximum_requests must be at least warmup")
    distance, reference, count, accepted_at_snapshot, blocked_at_snapshot, connections, availability, metrics = best
    return TrialResult(
        arrival_rate, seed, count, accepted_at_snapshot, blocked_at_snapshot,
        blocked_at_snapshot / count, reference, distance == 0.0,
        metrics["network_spectrum_utilization"], metrics, connections, availability,
        perf_counter() - started,
    )


def estimate_arrival_rate(target_midpoint: float, holding_rate: float, directed_link_count: int,
                          slot_count: int, average_required_slots: float,
                          average_shortest_path_hops: float) -> float:
    return (
        target_midpoint * holding_rate * directed_link_count * slot_count
        / (average_required_slots * average_shortest_path_hops)
    )


def search_snapshot(*, topology_id: str, state_id: str, connection_set_id: str,
                    catalog: PathCatalog, node_count: int, link_count: int, slot_count: int,
                    holding_rate: float, payload_values: list[int], payload_probabilities: list[float],
                    guard_slots: int, warmup: int, maximum_requests: int,
                    target_band: tuple[float, float], policy: str, seed: int,
                    average_shortest_path_hops: float, fallback_grid: list[float]) -> SearchResult:
    average_required = sum((payload+guard_slots)*probability
                           for payload, probability in zip(payload_values, payload_probabilities))
    estimate = estimate_arrival_rate(
        sum(target_band)/2, holding_rate, link_count, slot_count,
        average_required, average_shortest_path_hops,
    )
    rates = []
    for rate in [estimate, *fallback_grid]:
        if rate > 0 and all(abs(rate-existing) > 1e-12 for existing in rates):
            rates.append(float(rate))
    trials: list[TrialResult] = []
    for rate in rates:
        trial = simulate_trial(
            catalog, node_count, link_count, slot_count, rate, holding_rate,
            payload_values, payload_probabilities, guard_slots, warmup,
            maximum_requests, target_band, policy, seed,
        )
        trials.append(trial)
        if trial.target_reached:
            break
    if not any(trial.target_reached for trial in trials):
        lower = max((trial for trial in trials if trial.utilization < target_band[0]),
                    key=lambda trial: trial.arrival_rate_lambda, default=None)
        upper = min((trial for trial in trials if trial.utilization >= target_band[1]),
                    key=lambda trial: trial.arrival_rate_lambda, default=None)
        if lower and upper:
            for _ in range(4):
                rate = (lower.arrival_rate_lambda + upper.arrival_rate_lambda)/2
                trial = simulate_trial(
                    catalog, node_count, link_count, slot_count, rate, holding_rate,
                    payload_values, payload_probabilities, guard_slots, warmup,
                    maximum_requests, target_band, policy, seed,
                )
                trials.append(trial)
                if trial.target_reached:
                    break
                if trial.utilization < target_band[0]:
                    lower = trial
                else:
                    upper = trial
    chosen = next((trial for trial in trials if trial.target_reached), None)
    if chosen is None:
        chosen = min(trials, key=lambda trial: min(abs(trial.utilization-target_band[0]),
                                                    abs(trial.utilization-target_band[1])))
    connections = []
    for index, item in enumerate(chosen.active_connections, 1):
        connection = dict(item)
        connection["connection_id"] = f"{connection_set_id}_conn_{index:06d}"
        connections.append(connection)
    connection_set = {
        "initial_existing_connection_set_id": connection_set_id,
        "topology_id": topology_id,
        "reference_time": chosen.reference_time,
        "existing_connections": connections,
    }
    resource_state = {
        "resource_state_id": state_id,
        "topology_id": topology_id,
        "reference_time": chosen.reference_time,
        "slot_count": slot_count,
        "initial_existing_connection_set_id": connection_set_id,
        "link_spectrum_states": [
            {"link_id": link_id, "slot_availability": chosen.availability[link_id]}
            for link_id in sorted(chosen.availability)
        ],
        "spectrum_state_metrics": chosen.metrics,
    }
    maximum_used = max(
        (connection["slot_start"] + connection["required_slots"] - 1 for connection in connections),
        default=-1,
    )
    audit_metrics = {
        "historical_request_blocking_probability": chosen.blocking_probability,
        "active_connection_count": len(connections),
        "average_active_connection_path_hops": (
            sum(len(connection["path_link_ids"]) for connection in connections)/len(connections)
            if connections else None
        ),
        "maximum_used_fsu_index": maximum_used if maximum_used >= 0 else None,
    }
    return SearchResult(
        connection_set, resource_state,
        [trial.trace_record(holding_rate, warmup) for trial in trials],
        chosen.target_reached, chosen.arrival_rate_lambda, audit_metrics,
    )

# ---------------------------------------------------------------------------
# V1.0 formal production search path
# ---------------------------------------------------------------------------

from hashlib import sha256
from statistics import fmean
from typing import Callable


@dataclass(frozen=True)
class LoadSearchProtocol:
    """Frozen LOAD_SEARCH_V1_0 engineering gates.

    Non-default values exist only to make fast unit/integration tests possible.
    The production orchestrator always uses the default instance.
    """

    warmup_min_requests: int = 5000
    warmup_min_time_factor: float = 5.0
    observation_min_requests: int = 10000
    observation_min_time_factor: float = 2.5
    initial_observation_blocks: int = 2
    max_observation_blocks: int = 4
    utilization_stability_tolerance: float = 0.01
    blocking_stability_tolerance: float = 0.02
    sample_interval_requests: int = 100
    max_coarse_expansions: int = 8
    max_fine_rounds: int = 8
    fine_ratio_stop: float = 1.01


@dataclass
class SteadyTrialV1:
    arrival_rate_lambda: float
    seed: int
    warmup_request_count: int
    warmup_simulated_time: float
    total_request_count: int
    total_simulated_time: float
    accepted_count: int
    blocked_count: int
    blocks: list[dict]
    steady_confirmed: bool
    stable_mean_utilization: float | None
    stable_mean_blocking_probability: float | None
    ksp_fast_fallback_count: int
    runtime_seconds: float

    def trace_record(self, *, holding_rate_mu: float, phase: str) -> dict:
        return {
            "phase": phase,
            "arrival_rate_lambda": self.arrival_rate_lambda,
            "holding_time_rate_mu": holding_rate_mu,
            "offered_load_erlang": self.arrival_rate_lambda / holding_rate_mu,
            "seed": self.seed,
            "warmup_request_count": self.warmup_request_count,
            "warmup_simulated_time": self.warmup_simulated_time,
            "total_request_count": self.total_request_count,
            "total_simulated_time": self.total_simulated_time,
            "accepted_count": self.accepted_count,
            "blocked_count": self.blocked_count,
            "steady_confirmed": self.steady_confirmed,
            "stable_mean_utilization": self.stable_mean_utilization,
            "stable_mean_blocking_probability": self.stable_mean_blocking_probability,
            "ksp_fast_fallback_count": self.ksp_fast_fallback_count,
            "blocks": self.blocks,
            "runtime_seconds": self.runtime_seconds,
        }


@dataclass
class SearchResultV1:
    status: str
    reason: str | None
    connection_set: dict | None
    resource_state: dict | None
    trials: list[dict]
    target_reached: bool
    band_fallback: bool
    preferred_region_hit: bool
    lambda0: float
    actual_arrival_rate_lambda: float | None
    snapshot_request_index: int | None
    snapshot_utilization: float | None
    audit_metrics: dict


def _stream_seed(seed: int, stream_name: str) -> int:
    digest = sha256(f"PUBLIC_ENV_V1|{seed}|{stream_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _new_rng_streams(seed: int) -> tuple[Random, Random, Random, Random, Random]:
    return (
        Random(_stream_seed(seed, "arrival_unit_exponential")),
        Random(_stream_seed(seed, "od_uniform")),
        Random(_stream_seed(seed, "payload_slots")),
        Random(_stream_seed(seed, "holding_unit_exponential")),
        Random(_stream_seed(seed, "random_policy")),
    )


def _simulate_one_request_v1(
    *,
    index: int,
    now: float,
    arrival_rate: float,
    holding_rate: float,
    node_count: int,
    payload_values: list[int],
    payload_probabilities: list[float],
    guard_slots: int,
    policy: str,
    catalog: PathCatalog,
    spectrum: IncrementalSpectrum,
    active: dict[str, dict],
    release_heap: list[tuple[float, str]],
    arrival_rng: Random,
    od_rng: Random,
    payload_rng: Random,
    holding_rng: Random,
    policy_rng: Random,
) -> tuple[float, bool]:
    # Unit exponentials make the random sequence common across lambda trials;
    # lambda only rescales the same arrival variates.
    now += arrival_rng.expovariate(1.0) / arrival_rate
    while release_heap and release_heap[0][0] <= now:
        _, connection_id = heapq.heappop(release_heap)
        connection = active.pop(connection_id)
        spectrum.release(connection["path_link_ids"], connection["slot_start"], connection["required_slots"])

    source = od_rng.randrange(node_count)
    destination = od_rng.randrange(node_count - 1)
    if destination >= source:
        destination += 1
    payload = payload_rng.choices(payload_values, weights=payload_probabilities, k=1)[0]
    required_slots = int(payload) + guard_slots
    holding_time = holding_rng.expovariate(1.0) / holding_rate
    action = choose_action(policy, catalog, spectrum, source, destination, required_slots, policy_rng)
    accepted = action is not None
    if accepted:
        connection_id = f"trial_conn_{index:08d}"
        connection = {
            "connection_id": connection_id,
            "source_node_id": source,
            "destination_node_id": destination,
            "path_link_ids": action.path_link_ids,
            "slot_start": action.slot_start,
            "required_slots": required_slots,
            "arrival_time": now,
            "holding_time": holding_time,
        }
        spectrum.allocate(action.path_link_ids, action.slot_start, required_slots)
        active[connection_id] = connection
        heapq.heappush(release_heap, (now + holding_time, connection_id))
    return now, accepted


def run_steady_trial_v1(
    *,
    catalog: PathCatalog,
    node_count: int,
    link_count: int,
    slot_count: int,
    arrival_rate: float,
    holding_rate: float,
    payload_values: list[int],
    payload_probabilities: list[float],
    guard_slots: int,
    policy: str,
    seed: int,
    target_band: tuple[float, float],
    protocol: LoadSearchProtocol | None = None,
) -> SteadyTrialV1:
    """Run one independent lambda trial from an empty state.

    This function records only block statistics and lightweight snapshot
    metadata.  The selected final state is materialized later by deterministic
    replay, preventing search-time memory growth from full slot matrices.
    """
    if arrival_rate <= 0 or holding_rate <= 0:
        raise ValueError("arrival_rate and holding_rate must be positive")
    protocol = protocol or LoadSearchProtocol()
    started = perf_counter()
    # A bounded FIFO cache is deliberately reset per independent lambda trial.
    # Otherwise, the shared CRN OD sequence can create a pathological FIFO
    # thrash across repeated trials even though cached paths are semantically
    # identical.  Clearing affects runtime only.
    catalog = catalog.fresh_runtime_copy()
    spectrum = IncrementalSpectrum(link_count, slot_count)
    active: dict[str, dict] = {}
    release_heap: list[tuple[float, str]] = []
    arrival_rng, od_rng, payload_rng, holding_rng, policy_rng = _new_rng_streams(seed)
    now = 0.0
    index = 0
    accepted_total = 0
    blocked_total = 0

    warmup_min_time = protocol.warmup_min_time_factor / holding_rate
    while index < protocol.warmup_min_requests or now < warmup_min_time:
        index += 1
        now, accepted = _simulate_one_request_v1(
            index=index, now=now, arrival_rate=arrival_rate, holding_rate=holding_rate,
            node_count=node_count, payload_values=payload_values,
            payload_probabilities=payload_probabilities, guard_slots=guard_slots,
            policy=policy, catalog=catalog, spectrum=spectrum, active=active,
            release_heap=release_heap, arrival_rng=arrival_rng, od_rng=od_rng,
            payload_rng=payload_rng, holding_rng=holding_rng, policy_rng=policy_rng,
        )
        if accepted:
            accepted_total += 1
        else:
            blocked_total += 1
    warmup_request_count = index
    warmup_simulated_time = now

    blocks: list[dict] = []
    steady = False
    observation_min_time = protocol.observation_min_time_factor / holding_rate
    for block_index in range(1, protocol.max_observation_blocks + 1):
        start_request_index = index + 1
        start_time = now
        block_accepted = 0
        block_blocked = 0
        samples: list[float] = []
        snapshot_candidates: list[dict] = []
        block_requests = 0
        while block_requests < protocol.observation_min_requests or (now - start_time) < observation_min_time:
            index += 1
            block_requests += 1
            now, accepted = _simulate_one_request_v1(
                index=index, now=now, arrival_rate=arrival_rate, holding_rate=holding_rate,
                node_count=node_count, payload_values=payload_values,
                payload_probabilities=payload_probabilities, guard_slots=guard_slots,
                policy=policy, catalog=catalog, spectrum=spectrum, active=active,
                release_heap=release_heap, arrival_rng=arrival_rng, od_rng=od_rng,
                payload_rng=payload_rng, holding_rng=holding_rng, policy_rng=policy_rng,
            )
            if accepted:
                accepted_total += 1
                block_accepted += 1
            else:
                blocked_total += 1
                block_blocked += 1
            if block_requests % protocol.sample_interval_requests == 0:
                utilization = spectrum.network_utilization()
                samples.append(utilization)
                if target_band[0] <= utilization < target_band[1]:
                    snapshot_candidates.append({
                        "request_index": index,
                        "simulation_time": now,
                        "network_spectrum_utilization": utilization,
                    })
        if not samples:
            samples.append(spectrum.network_utilization())
        block_record = {
            "block_index": block_index,
            "start_request_index": start_request_index,
            "end_request_index": index,
            "request_count": block_requests,
            "start_time": start_time,
            "end_time": now,
            "simulated_time": now - start_time,
            "mean_utilization": fmean(samples),
            "blocking_probability": block_blocked / block_requests,
            "accepted_count": block_accepted,
            "blocked_count": block_blocked,
            "utilization_sample_count": len(samples),
            "target_band_snapshot_candidates": snapshot_candidates,
        }
        blocks.append(block_record)
        if block_index >= protocol.initial_observation_blocks:
            prev, current = blocks[-2], blocks[-1]
            if (
                abs(current["mean_utilization"] - prev["mean_utilization"])
                <= protocol.utilization_stability_tolerance
                and abs(current["blocking_probability"] - prev["blocking_probability"])
                <= protocol.blocking_stability_tolerance
            ):
                steady = True
                break

    stable_u = None
    stable_bp = None
    if steady:
        stable_u = fmean([blocks[-2]["mean_utilization"], blocks[-1]["mean_utilization"]])
        stable_bp = fmean([blocks[-2]["blocking_probability"], blocks[-1]["blocking_probability"]])
    return SteadyTrialV1(
        arrival_rate_lambda=arrival_rate,
        seed=seed,
        warmup_request_count=warmup_request_count,
        warmup_simulated_time=warmup_simulated_time,
        total_request_count=index,
        total_simulated_time=now,
        accepted_count=accepted_total,
        blocked_count=blocked_total,
        blocks=blocks,
        steady_confirmed=steady,
        stable_mean_utilization=stable_u,
        stable_mean_blocking_probability=stable_bp,
        ksp_fast_fallback_count=catalog.fast_fallback_count,
        runtime_seconds=perf_counter() - started,
    )


def _replay_snapshot_at_request_index_v1(
    *,
    catalog: PathCatalog,
    node_count: int,
    link_count: int,
    slot_count: int,
    arrival_rate: float,
    holding_rate: float,
    payload_values: list[int],
    payload_probabilities: list[float],
    guard_slots: int,
    policy: str,
    seed: int,
    request_index: int,
) -> tuple[float, list[dict], dict[int, list[int]], dict]:
    catalog = catalog.fresh_runtime_copy()
    spectrum = IncrementalSpectrum(link_count, slot_count)
    active: dict[str, dict] = {}
    release_heap: list[tuple[float, str]] = []
    arrival_rng, od_rng, payload_rng, holding_rng, policy_rng = _new_rng_streams(seed)
    now = 0.0
    for index in range(1, request_index + 1):
        now, _ = _simulate_one_request_v1(
            index=index, now=now, arrival_rate=arrival_rate, holding_rate=holding_rate,
            node_count=node_count, payload_values=payload_values,
            payload_probabilities=payload_probabilities, guard_slots=guard_slots,
            policy=policy, catalog=catalog, spectrum=spectrum, active=active,
            release_heap=release_heap, arrival_rng=arrival_rng, od_rng=od_rng,
            payload_rng=payload_rng, holding_rng=holding_rng, policy_rng=policy_rng,
        )
    connections, availability, metrics = _snapshot(active, spectrum)
    return now, connections, availability, metrics


def _replay_find_snapshot_v1(
    *,
    trial: SteadyTrialV1,
    target_band: tuple[float, float],
    target_midpoint: float,
    catalog: PathCatalog,
    node_count: int,
    link_count: int,
    slot_count: int,
    holding_rate: float,
    payload_values: list[int],
    payload_probabilities: list[float],
    guard_slots: int,
    policy: str,
) -> tuple[int, float, list[dict], dict[int, list[int]], dict] | None:
    # First use the lightweight every-N candidates from the two stable blocks.
    candidate_meta = [item for block in trial.blocks[-2:]
                      for item in block["target_band_snapshot_candidates"]]
    if candidate_meta:
        selected = min(
            candidate_meta,
            key=lambda item: (abs(item["network_spectrum_utilization"] - target_midpoint),
                              item["simulation_time"], item["request_index"]),
        )
        now, connections, availability, metrics = _replay_snapshot_at_request_index_v1(
            catalog=catalog, node_count=node_count, link_count=link_count, slot_count=slot_count,
            arrival_rate=trial.arrival_rate_lambda, holding_rate=holding_rate,
            payload_values=payload_values, payload_probabilities=payload_probabilities,
            guard_slots=guard_slots, policy=policy, seed=trial.seed,
            request_index=int(selected["request_index"]),
        )
        if target_band[0] <= metrics["network_spectrum_utilization"] < target_band[1]:
            return int(selected["request_index"]), now, connections, availability, metrics

    # If coarse sampling missed the band, deterministically replay each request
    # in exactly the recent two stable observation-block ranges.
    first_index = int(trial.blocks[-2]["start_request_index"])
    last_index = int(trial.blocks[-1]["end_request_index"])
    best: tuple[float, float, int, list[dict], dict[int, list[int]], dict] | None = None
    # This path is intentionally rare.  Replaying from zero for every request
    # would be quadratic, so replay once and inspect the live spectrum at each step.
    catalog = catalog.fresh_runtime_copy()
    spectrum = IncrementalSpectrum(link_count, slot_count)
    active: dict[str, dict] = {}
    release_heap: list[tuple[float, str]] = []
    arrival_rng, od_rng, payload_rng, holding_rng, policy_rng = _new_rng_streams(trial.seed)
    now = 0.0
    for index in range(1, last_index + 1):
        now, _ = _simulate_one_request_v1(
            index=index, now=now, arrival_rate=trial.arrival_rate_lambda, holding_rate=holding_rate,
            node_count=node_count, payload_values=payload_values,
            payload_probabilities=payload_probabilities, guard_slots=guard_slots,
            policy=policy, catalog=catalog, spectrum=spectrum, active=active,
            release_heap=release_heap, arrival_rng=arrival_rng, od_rng=od_rng,
            payload_rng=payload_rng, holding_rng=holding_rng, policy_rng=policy_rng,
        )
        if index < first_index:
            continue
        utilization = spectrum.network_utilization()
        if target_band[0] <= utilization < target_band[1]:
            distance = abs(utilization - target_midpoint)
            if best is None or (distance, now, index) < (best[0], best[1], best[2]):
                connections, availability, metrics = _snapshot(active, spectrum)
                best = (distance, now, index, connections, availability, metrics)
    if best is None:
        return None
    _, reference_time, request_index, connections, availability, metrics = best
    return request_index, reference_time, connections, availability, metrics


def _middle_third(target_band: tuple[float, float]) -> tuple[float, float]:
    low, high = target_band
    width = high - low
    return low + width / 3.0, low + 2.0 * width / 3.0


def search_snapshot_v1(
    *,
    topology_id: str,
    state_id: str,
    connection_set_id: str,
    catalog: PathCatalog,
    node_count: int,
    link_count: int,
    slot_count: int,
    holding_rate: float,
    payload_values: list[int],
    payload_probabilities: list[float],
    guard_slots: int,
    target_band: tuple[float, float],
    policy: str,
    seed: int,
    confirmation_seed: int,
    average_shortest_path_hops: float,
    protocol: LoadSearchProtocol | None = None,
    trial_runner: Callable[..., SteadyTrialV1] | None = None,
) -> SearchResultV1:
    """Formal LOAD_SEARCH_V1_0 implementation used by production runners."""
    protocol = protocol or LoadSearchProtocol()
    trial_runner = trial_runner or run_steady_trial_v1
    average_required = sum((payload + guard_slots) * probability
                           for payload, probability in zip(payload_values, payload_probabilities))
    midpoint = (target_band[0] + target_band[1]) / 2.0
    preferred_low, preferred_high = _middle_third(target_band)
    lambda0 = estimate_arrival_rate(
        midpoint, holding_rate, link_count, slot_count, average_required, average_shortest_path_hops
    )
    traces: list[dict] = []
    main_trials: list[SteadyTrialV1] = []
    confirmation_trials: list[SteadyTrialV1] = []
    evaluated: dict[float, SteadyTrialV1] = {}

    def run(rate: float, trial_seed: int, phase: str, *, main: bool) -> SteadyTrialV1:
        key = float(rate)
        if main and key in evaluated:
            return evaluated[key]
        result = trial_runner(
            catalog=catalog, node_count=node_count, link_count=link_count, slot_count=slot_count,
            arrival_rate=key, holding_rate=holding_rate, payload_values=payload_values,
            payload_probabilities=payload_probabilities, guard_slots=guard_slots,
            policy=policy, seed=trial_seed, target_band=target_band, protocol=protocol,
        )
        traces.append(result.trace_record(holding_rate_mu=holding_rate, phase=phase))
        if main:
            evaluated[key] = result
            main_trials.append(result)
        else:
            confirmation_trials.append(result)
        return result

    def fail(status: str, reason: str) -> SearchResultV1:
        return SearchResultV1(
            status=status, reason=reason, connection_set=None, resource_state=None,
            trials=traces, target_reached=False, band_fallback=False,
            preferred_region_hit=False, lambda0=lambda0,
            actual_arrival_rate_lambda=None, snapshot_request_index=None,
            snapshot_utilization=None,
            audit_metrics={"ksp_fast_fallback_count": sum(item.ksp_fast_fallback_count for item in main_trials + confirmation_trials) + catalog.fast_fallback_count},
        )

    def check_steady(trial: SteadyTrialV1) -> SearchResultV1 | None:
        if not trial.steady_confirmed:
            return fail("STEADY_STATE_NOT_CONFIRMED", f"lambda={trial.arrival_rate_lambda} did not stabilize by B4")
        return None

    def check_nonmonotonic() -> SearchResultV1 | None:
        stable = sorted((trial for trial in main_trials if trial.steady_confirmed),
                        key=lambda item: item.arrival_rate_lambda)
        for lower, upper in zip(stable, stable[1:]):
            assert lower.stable_mean_utilization is not None and upper.stable_mean_utilization is not None
            if upper.stable_mean_utilization < lower.stable_mean_utilization - protocol.utilization_stability_tolerance:
                lower_c = run(lower.arrival_rate_lambda, confirmation_seed, "NONMONOTONIC_CONFIRM_LOW", main=False)
                upper_c = run(upper.arrival_rate_lambda, confirmation_seed, "NONMONOTONIC_CONFIRM_HIGH", main=False)
                if lower_c.steady_confirmed and upper_c.steady_confirmed:
                    assert lower_c.stable_mean_utilization is not None and upper_c.stable_mean_utilization is not None
                    if upper_c.stable_mean_utilization < lower_c.stable_mean_utilization - protocol.utilization_stability_tolerance:
                        return fail(
                            "SEARCH_RESPONSE_NON_MONOTONIC",
                            f"confirmed utilization inversion between lambda={lower.arrival_rate_lambda} and {upper.arrival_rate_lambda}",
                        )
        return None

    first = run(lambda0, seed, "INITIAL", main=True)
    failed = check_steady(first)
    if failed:
        return failed

    def u(trial: SteadyTrialV1) -> float:
        assert trial.stable_mean_utilization is not None
        return trial.stable_mean_utilization

    def legal(trial: SteadyTrialV1) -> bool:
        return trial.steady_confirmed and target_band[0] <= u(trial) < target_band[1]

    def preferred(trial: SteadyTrialV1) -> bool:
        return legal(trial) and preferred_low <= u(trial) < preferred_high

    current = first
    if not preferred(first):
        if u(first) < target_band[0] or (legal(first) and u(first) < preferred_low):
            direction = 1
        elif u(first) >= target_band[1] or (legal(first) and u(first) >= preferred_high):
            direction = -1
        else:
            direction = 0
        for coarse_index in range(1, protocol.max_coarse_expansions + 1):
            if direction == 0:
                break
            rate = current.arrival_rate_lambda * (2.0 if direction > 0 else 0.5)
            current = run(rate, seed, f"COARSE_{coarse_index}", main=True)
            failed = check_steady(current)
            if failed:
                return failed
            failed = check_nonmonotonic()
            if failed:
                return failed
            if preferred(current):
                break

            # Upward-only plateau test, and only while no legal point exists.
            if direction > 0 and not any(legal(item) for item in main_trials):
                increasing = sorted((item for item in main_trials if item.steady_confirmed),
                                    key=lambda item: item.arrival_rate_lambda)
                if len(increasing) >= 3:
                    a, b, c = increasing[-3:]
                    doubled = abs(b.arrival_rate_lambda / a.arrival_rate_lambda - 2.0) <= 1e-12 and \
                              abs(c.arrival_rate_lambda / b.arrival_rate_lambda - 2.0) <= 1e-12
                    if doubled and all(u(item) < target_band[0] for item in (a, b, c)) and \
                       abs(u(b) - u(a)) <= protocol.utilization_stability_tolerance and \
                       abs(u(c) - u(b)) <= protocol.utilization_stability_tolerance and \
                       u(c) <= target_band[0] - protocol.utilization_stability_tolerance:
                        confirms = [run(item.arrival_rate_lambda, confirmation_seed,
                                        f"PLATEAU_CONFIRM_{idx}", main=False)
                                    for idx, item in enumerate((a, b, c), 1)]
                        if all(item.steady_confirmed for item in confirms):
                            cu = [item.stable_mean_utilization for item in confirms]
                            assert all(value is not None for value in cu)
                            if all(value < target_band[0] for value in cu) and \
                               abs(cu[1] - cu[0]) <= protocol.utilization_stability_tolerance and \
                               abs(cu[2] - cu[1]) <= protocol.utilization_stability_tolerance and \
                               cu[2] <= target_band[0] - protocol.utilization_stability_tolerance:
                                return fail(
                                    "TARGET_BAND_NOT_REACHED_UNDER_SEARCH_PROTOCOL",
                                    "PLATEAU_CONFIRMED",
                                )

            below = [item for item in main_trials if item.steady_confirmed and u(item) < target_band[0]]
            above = [item for item in main_trials if item.steady_confirmed and u(item) >= target_band[1]]
            if below and above:
                break

    # Geometric fine search when hard-band boundary evidence brackets the target.
    below = [item for item in main_trials if item.steady_confirmed and u(item) < target_band[0]]
    above = [item for item in main_trials if item.steady_confirmed and u(item) >= target_band[1]]
    fine_attempted = False
    if below and above and not any(preferred(item) for item in main_trials):
        lower = max(below, key=lambda item: item.arrival_rate_lambda)
        upper = min(above, key=lambda item: item.arrival_rate_lambda)
        for fine_index in range(1, protocol.max_fine_rounds + 1):
            if upper.arrival_rate_lambda / lower.arrival_rate_lambda <= protocol.fine_ratio_stop:
                break
            fine_attempted = True
            rate = (lower.arrival_rate_lambda * upper.arrival_rate_lambda) ** 0.5
            trial = run(rate, seed, f"FINE_{fine_index}", main=True)
            failed = check_steady(trial)
            if failed:
                return failed
            failed = check_nonmonotonic()
            if failed:
                return failed
            if preferred(trial):
                break
            if u(trial) < target_band[0]:
                lower = trial
            elif u(trial) >= target_band[1]:
                upper = trial
            elif u(trial) < preferred_low:
                # Legal but below preferred area: it is safe as a preference-search lower bound.
                lower = trial
            else:
                upper = trial

    legal_trials = [item for item in main_trials if legal(item)]
    if not legal_trials:
        if fine_attempted:
            return fail(
                "TARGET_BAND_NOT_RESOLVED_WITHIN_FINE_SEARCH",
                "no stable legal point was found within the geometric fine-search budget",
            )
        return fail("SEARCH_BUDGET_EXHAUSTED", "no stable legal point was found within the coarse-search budget")

    preferred_trials = [item for item in legal_trials if preferred(item)]
    candidates = preferred_trials or legal_trials
    chosen = min(candidates, key=lambda item: (abs(u(item) - midpoint), item.arrival_rate_lambda))
    band_fallback = not bool(preferred_trials)
    replayed = _replay_find_snapshot_v1(
        trial=chosen, target_band=target_band, target_midpoint=midpoint,
        catalog=catalog, node_count=node_count, link_count=link_count, slot_count=slot_count,
        holding_rate=holding_rate, payload_values=payload_values,
        payload_probabilities=payload_probabilities, guard_slots=guard_slots, policy=policy,
    )
    if replayed is None:
        return fail(
            "SNAPSHOT_NOT_FOUND_IN_TARGET_BAND",
            "stable legal trial exists but no real per-request snapshot was found inside the hard target band",
        )
    snapshot_request_index, reference_time, active_connections, availability, metrics = replayed
    final_connections: list[dict] = []
    for index, item in enumerate(active_connections, 1):
        connection = dict(item)
        connection["connection_id"] = f"{connection_set_id}_conn_{index:06d}"
        final_connections.append(connection)
    connection_set = {
        "initial_existing_connection_set_id": connection_set_id,
        "topology_id": topology_id,
        "reference_time": reference_time,
        "existing_connections": final_connections,
    }
    resource_state = {
        "resource_state_id": state_id,
        "topology_id": topology_id,
        "reference_time": reference_time,
        "slot_count": slot_count,
        "initial_existing_connection_set_id": connection_set_id,
        "link_spectrum_states": [
            {"link_id": link_id, "slot_availability": availability[link_id]}
            for link_id in sorted(availability)
        ],
        "spectrum_state_metrics": metrics,
    }
    maximum_used = max(
        (connection["slot_start"] + connection["required_slots"] - 1 for connection in final_connections),
        default=-1,
    )
    audit_metrics = {
        "historical_request_blocking_probability": chosen.stable_mean_blocking_probability,
        "active_connection_count": len(final_connections),
        "average_active_connection_path_hops": (
            sum(len(connection["path_link_ids"]) for connection in final_connections) / len(final_connections)
            if final_connections else None
        ),
        "maximum_used_fsu_index": maximum_used if maximum_used >= 0 else None,
        "preferred_region": [preferred_low, preferred_high],
        "selected_stable_mean_utilization": chosen.stable_mean_utilization,
        "ksp_fast_fallback_count": sum(item.ksp_fast_fallback_count for item in main_trials + confirmation_trials) + catalog.fast_fallback_count,
    }
    return SearchResultV1(
        status="TARGET_REACHED", reason="BAND_FALLBACK" if band_fallback else None,
        connection_set=connection_set, resource_state=resource_state, trials=traces,
        target_reached=True, band_fallback=band_fallback,
        preferred_region_hit=not band_fallback, lambda0=lambda0,
        actual_arrival_rate_lambda=chosen.arrival_rate_lambda,
        snapshot_request_index=snapshot_request_index,
        snapshot_utilization=metrics["network_spectrum_utilization"],
        audit_metrics=audit_metrics,
    )
