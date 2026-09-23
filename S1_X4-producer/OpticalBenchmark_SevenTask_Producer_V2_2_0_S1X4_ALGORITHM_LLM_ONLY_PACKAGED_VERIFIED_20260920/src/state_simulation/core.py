from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import fmean, pvariance
from typing import Any

import networkx as nx

from src.numeric import p90_type7

ALLOWED_REQUIRED_SLOTS = {2, 3, 5, 9}


def free_blocks(bits: list[int]) -> list[tuple[int, int]]:
    blocks = []; start = None
    for i, bit in enumerate(bits + [0]):
        if bit == 1 and start is None:
            start = i
        elif bit == 0 and start is not None:
            blocks.append((start, i - start)); start = None
    return blocks


def first_fit(path_link_ids: list[int], availability: dict[int, list[int]], required_slots: int) -> int | None:
    if required_slots not in ALLOWED_REQUIRED_SLOTS:
        return None
    slot_count = len(next(iter(availability.values())))
    for start in range(slot_count - required_slots + 1):
        if all(all(availability[link][s] == 1 for s in range(start, start + required_slots))
               for link in path_link_ids):
            return start
    return None


def reconstruct_availability(connections: list[dict], directed: dict, slot_count: int) -> dict[int, list[int]]:
    state = {record["link_id"]: [1] * slot_count for record in directed["directed_link_records"]}
    for conn in connections:
        for link in conn["path_link_ids"]:
            for slot in range(conn["slot_start"], conn["slot_start"] + conn["required_slots"]):
                if state[link][slot] == 0:
                    raise ValueError("connection overlap")
                state[link][slot] = 0
    return state


def validate_connections(connections: list[dict], directed: dict, slot_count: int, reference_time: float) -> None:
    links = {r["link_id"]: r for r in directed["directed_link_records"]}
    occupied: set[tuple[int, int]] = set()
    ids = set()
    for conn in connections:
        if conn["connection_id"] in ids: raise ValueError("duplicate connection id")
        ids.add(conn["connection_id"])
        if conn["required_slots"] not in ALLOWED_REQUIRED_SLOTS: raise ValueError("required_slots")
        if conn["slot_start"] < 0 or conn["slot_start"] + conn["required_slots"] > slot_count:
            raise ValueError("slot boundary")
        if conn["arrival_time"] + conn["holding_time"] <= reference_time:
            raise ValueError("remaining holding time")
        current = conn["source_node_id"]
        for link_id in conn["path_link_ids"]:
            link = links.get(link_id)
            if link is None or link["source_node_id"] != current: raise ValueError("path continuity")
            current = link["destination_node_id"]
            for slot in range(conn["slot_start"], conn["slot_start"] + conn["required_slots"]):
                key = (link_id, slot)
                if key in occupied: raise ValueError("connection overlap")
                occupied.add(key)
        if current != conn["destination_node_id"]: raise ValueError("path endpoint")


def spectrum_metrics(availability: dict[int, list[int]], slot_count: int) -> dict:
    link_metrics = []; utils = []; external = []
    for link_id in sorted(availability):
        bits = availability[link_id]; free = sum(bits); blocks = free_blocks(bits)
        largest = max((length for _, length in blocks), default=0)
        util = 1 - free / slot_count; utils.append(util)
        item = {"link_id": link_id, "link_utilization": util, "free_slot_count": free,
                "free_block_count": len(blocks), "largest_free_block_length": largest}
        if free:
            ef = 1 - largest / free; item["external_fragmentation"] = ef; external.append(ef)
        link_metrics.append(item)
    result = {"network_spectrum_utilization": fmean(utils),
              "max_link_utilization": max(utils), "p90_link_utilization": p90_type7(utils),
              "link_utilization_variance": pvariance(utils), "link_spectrum_metrics": link_metrics}
    if external: result["mean_link_external_fragmentation"] = fmean(external)
    return result


def _k_paths(directed: dict, source: int, destination: int, k: int) -> list[list[int]]:
    graph = nx.DiGraph(); lookup = {}
    for link in directed["directed_link_records"]:
        u, v = link["source_node_id"], link["destination_node_id"]
        graph.add_edge(u, v); lookup[(u, v)] = link["link_id"]
    paths = []
    for nodes in nx.shortest_simple_paths(graph, source, destination):
        paths.append([lookup[pair] for pair in zip(nodes, nodes[1:])])
        if len(paths) == k: break
    return paths


@dataclass
class SimulationResult:
    connection_set: dict
    resource_state: dict
    search_trace: list[dict]
    target_reached: bool
    actual_arrival_rate_lambda: float


def _simulate_rate(directed: dict, node_count: int, cfg: dict, rate: float, seed: int) -> tuple[dict, float, list[dict]]:
    rng = Random(seed); now = 0.0; active = []; best = None; trace = []
    slot_count = cfg["slot_count"]; k = cfg["historical_candidate_path_k"]
    payloads = cfg["payload_slot_values"]; probs = cfg["payload_slot_probabilities"]
    low, high = cfg["target_network_spectrum_utilization_band"]
    for index in range(1, cfg["maximum_simulated_request_count"] + 1):
        now += rng.expovariate(rate)
        active = [c for c in active if c["arrival_time"] + c["holding_time"] > now]
        availability = reconstruct_availability(active, directed, slot_count)
        source = rng.randrange(node_count); destination = rng.randrange(node_count - 1)
        if destination >= source: destination += 1
        required = rng.choices(payloads, weights=probs, k=1)[0] + cfg["guard_band_slots"]
        holding = rng.expovariate(cfg["holding_time_rate_mu"])
        chosen = None
        for path in _k_paths(directed, source, destination, k):
            start = first_fit(path, availability, required)
            if start is not None: chosen = (path, start); break
        if chosen:
            active.append({"connection_id": f"conn_{index:06d}", "source_node_id": source,
                           "destination_node_id": destination, "path_link_ids": chosen[0],
                           "slot_start": chosen[1], "required_slots": required,
                           "arrival_time": now, "holding_time": holding})
            availability = reconstruct_availability(active, directed, slot_count)
        util = spectrum_metrics(availability, slot_count)["network_spectrum_utilization"]
        if index >= cfg["warmup_request_count"]:
            distance = 0 if low <= util < high else min(abs(util-low), abs(util-high))
            if best is None or distance < best[0]: best = (distance, now, [dict(c) for c in active], util, index)
            if low <= util < high:
                trace.append({"request_count": index, "utilization": util, "reference_time": now})
                return {"now": now, "active": active, "availability": availability, "count": index}, util, trace
    assert best is not None
    _, now, active, util, count = best; availability = reconstruct_availability(active, directed, slot_count)
    trace.append({"request_count": count, "utilization": util, "reference_time": now})
    return {"now": now, "active": active, "availability": availability, "count": count}, util, trace


def simulate_snapshot(directed: dict, node_count: int, cfg: dict) -> SimulationResult:
    rates = [cfg["arrival_rate_lambda_initial"]]
    if cfg.get("load_search_allowed"):
        rates += [rates[0] * factor for factor in (0.5, 1.5, 0.25, 2.0, 3.0)]
    attempts=[]; best=None; low, high=cfg["target_network_spectrum_utilization_band"]
    for i, rate in enumerate(rates):
        snap, util, detail = _simulate_rate(directed, node_count, cfg, rate, cfg["random_seed"] + i)
        attempt={"arrival_rate_lambda": rate,"target_reached":low<=util<high,"snapshot_utilization":util,
                 "request_count":snap["count"],"reference_time":snap["now"]}; attempts.append(attempt)
        dist=0 if low<=util<high else min(abs(util-low),abs(util-high))
        if best is None or dist<best[0]: best=(dist,rate,snap,util)
        if low<=util<high: break
    _, rate, snap, util=best
    reference=snap["now"]; connections=[]
    for i, conn in enumerate(sorted(snap["active"], key=lambda c: c["connection_id"]),1):
        c=dict(conn); c["connection_id"]=f"conn_{i:04d}"; connections.append(c)
    availability=reconstruct_availability(connections,directed,cfg["slot_count"])
    icset={"initial_existing_connection_set_id":"icset_0001","topology_id":directed["topology_id"],
           "reference_time":reference,"existing_connections":connections}
    state={"resource_state_id":"rs_0001","topology_id":directed["topology_id"],"reference_time":reference,
           "slot_count":cfg["slot_count"],"initial_existing_connection_set_id":"icset_0001",
           "link_spectrum_states":[{"link_id":i,"slot_availability":availability[i]} for i in sorted(availability)],
           "spectrum_state_metrics":spectrum_metrics(availability,cfg["slot_count"])}
    return SimulationResult(icset,state,attempts,low<=util<high,rate)
