from __future__ import annotations

import heapq
import json
from itertools import combinations
from pathlib import Path
from random import Random
from statistics import fmean

import networkx as nx
import numpy as np

from src.numeric import values_equal
from src.pipeline import build_concurrent_request_set
from src.state_simulation.core import reconstruct_availability, spectrum_metrics, validate_connections

from .requests import RequestDeriver
from .simulation import IncrementalSpectrum, PathCatalog, choose_action


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _topology_metrics(physical: dict) -> dict:
    node_ids = [item["node_id"] for item in physical["node_records"]]
    if node_ids != list(range(len(node_ids))) or len(node_ids) != len(set(node_ids)):
        raise ValueError("node ids are not unique continuous zero-based")
    edges = []
    seen = set()
    for index, item in enumerate(physical["physical_link_records"]):
        if item["physical_link_id"] != index:
            raise ValueError("physical link ids are not continuous")
        u, v = item["node_u_id"], item["node_v_id"]
        if u >= v:
            raise ValueError("physical endpoints not canonical or self-loop")
        if (u, v) in seen:
            raise ValueError("duplicate physical edge")
        seen.add((u, v))
        edges.append((u, v, item.get("length_km")))
    graph = nx.Graph()
    graph.add_nodes_from(node_ids)
    graph.add_edges_from((u, v) for u, v, _ in edges)
    if not nx.is_connected(graph):
        raise ValueError("physical topology disconnected")
    pair_list = list(combinations(node_ids, 2))
    distances = dict(nx.all_pairs_shortest_path_length(graph))
    bridges = list(nx.bridges(graph))
    centrality = nx.edge_betweenness_centrality(graph, normalized=True, weight=None)
    adjacency = nx.to_numpy_array(graph, nodelist=node_ids, dtype=np.float64)
    degree = adjacency.sum(axis=1)
    inverse = np.diag(1.0/np.sqrt(degree))
    eigen = np.linalg.eigvalsh(np.eye(len(node_ids))-inverse@adjacency@inverse)
    result = {
        "topology_id": physical["topology_id"], "node_count": len(node_ids),
        "physical_link_count": len(edges), "directed_link_count": 2*len(edges),
        "average_node_degree": 2*len(edges)/len(node_ids),
        "edge_density": 2*len(edges)/(len(node_ids)*(len(node_ids)-1)),
        "average_clustering_coefficient": nx.average_clustering(graph),
        "diameter_hops": max(distances[u][v] for u, v in pair_list),
        "average_shortest_path_hops": fmean(distances[u][v] for u, v in pair_list),
        "global_edge_connectivity": int(nx.edge_connectivity(graph)),
        "bridge_count": len(bridges), "bridge_ratio": len(bridges)/len(edges),
        "max_normalized_edge_betweenness": max(centrality.values()),
        "normalized_algebraic_connectivity": float(eigen[1]),
    }
    if all(length is not None for _, _, length in edges):
        weighted = nx.Graph()
        weighted.add_nodes_from(node_ids)
        weighted.add_weighted_edges_from(((u, v, length) for u, v, length in edges), weight="length_km")
        length_distances = dict(nx.all_pairs_dijkstra_path_length(weighted, weight="length_km"))
        result.update({
            "average_physical_link_length_km": fmean(length for _, _, length in edges),
            "diameter_physical_length_km": max(length_distances[u][v] for u, v in pair_list),
            "average_shortest_path_physical_length_km": fmean(length_distances[u][v] for u, v in pair_list),
        })
    elif any(length is not None for _, _, length in edges):
        raise ValueError("partial physical lengths violate conditional metric rule")
    return result


def _validate_directed(physical: dict, directed: dict) -> None:
    expected = []
    for edge in physical["physical_link_records"]:
        p, u, v = edge["physical_link_id"], edge["node_u_id"], edge["node_v_id"]
        expected.extend([
            {"link_id": 2*p, "source_node_id": u, "destination_node_id": v, "physical_link_id": p},
            {"link_id": 2*p+1, "source_node_id": v, "destination_node_id": u, "physical_link_id": p},
        ])
    if directed["topology_id"] != physical["topology_id"] or directed["directed_link_records"] != expected:
        raise ValueError("directed resource topology mapping mismatch")


def _replay(sequence: dict, connection_set: dict, physical: dict, slot_count: int) -> dict[int, list[int]]:
    edges = [(item["node_u_id"], item["node_v_id"]) for item in physical["physical_link_records"]]
    catalog = PathCatalog.from_edges(len(physical["node_records"]), edges, 5)
    spectrum = IncrementalSpectrum(2*len(edges), slot_count)
    active = {}
    releases = []
    for connection in connection_set["existing_connections"]:
        spectrum.allocate(connection["path_link_ids"], connection["slot_start"], connection["required_slots"])
        active[connection["connection_id"]] = connection
        heapq.heappush(releases, (connection["arrival_time"]+connection["holding_time"], connection["connection_id"]))
    now = connection_set["reference_time"]
    times = [item["arrival_time"] for item in sequence["dynamic_request_events"]]
    if not times or times != sorted(times) or times[0] < now:
        raise ValueError("dynamic arrival order or first-event reference constraint")
    rng = Random(0)
    for index, event in enumerate(sequence["dynamic_request_events"], 1):
        now = event["arrival_time"]
        while releases and releases[0][0] <= now:
            _, connection_id = heapq.heappop(releases)
            connection = active.pop(connection_id)
            spectrum.release(connection["path_link_ids"], connection["slot_start"], connection["required_slots"])
        action = choose_action("BASE_KSP_FF", catalog, spectrum, event["source_node_id"],
                               event["destination_node_id"], event["required_slots"], rng)
        if action is not None:
            connection = {**event, "connection_id": f"replay_{index:04d}",
                          "path_link_ids": action.path_link_ids, "slot_start": action.slot_start}
            spectrum.allocate(action.path_link_ids, action.slot_start, event["required_slots"])
            active[connection["connection_id"]] = connection
            heapq.heappush(releases, (event["arrival_time"]+event["holding_time"], connection["connection_id"]))
    return spectrum.availability()


def validate_multi_environment(env: Path) -> dict:
    errors = []
    topology_reports = []
    physical_items = list(map(_load, sorted((env/"topologies/physical").glob("*.json"))))
    directed_items = list(map(_load, sorted((env/"topologies/directed").glob("*.json"))))
    metric_items = list(map(_load, sorted((env/"metrics/topology").glob("*.json"))))
    physicals = {item["topology_id"]: item for item in physical_items}
    directeds = {item["topology_id"]: item for item in directed_items}
    metrics = {item["topology_id"]: item for item in metric_items}
    if not (len(physicals) == len(physical_items) == len(directeds) == len(directed_items)
            == len(metrics) == len(metric_items)):
        errors.append("duplicate or inconsistent topology ids across topology object types")
    for topology_id, physical in physicals.items():
        local_errors = []
        try:
            _validate_directed(physical, directeds[topology_id])
            recomputed = _topology_metrics(physical)
            if not values_equal(recomputed, metrics[topology_id]):
                raise ValueError("topology metrics recomputation mismatch")
        except Exception as exc:
            local_errors.append(f"{type(exc).__name__}: {exc}")
            errors.append(f"{topology_id}: {local_errors[-1]}")
        topology_reports.append({"topology_id": topology_id, "pass": not local_errors, "errors": local_errors})
    connection_items = list(map(_load, sorted((env/"connections/initial").glob("*.json"))))
    state_items = list(map(_load, sorted((env/"states/spectrum").glob("*.json"))))
    connection_sets = {item["initial_existing_connection_set_id"]: item for item in connection_items}
    states = {item["resource_state_id"]: item for item in state_items}
    if len(connection_sets) != len(connection_items) or len(states) != len(state_items):
        errors.append("duplicate connection-set or resource-state id")
    reconstruction_pass = True
    metric_pass = True
    state_reports = []
    for state_id, state in states.items():
        local_errors = []
        try:
            connection_set = connection_sets[state["initial_existing_connection_set_id"]]
            if connection_set["topology_id"] != state["topology_id"] or not values_equal(
                    connection_set["reference_time"], state["reference_time"]):
                raise ValueError("state/connection topology or reference-time mismatch")
            directed = directeds[state["topology_id"]]
            validate_connections(connection_set["existing_connections"], directed,
                                 state["slot_count"], state["reference_time"])
            rebuilt = reconstruct_availability(connection_set["existing_connections"], directed, state["slot_count"])
            saved = {item["link_id"]: item["slot_availability"] for item in state["link_spectrum_states"]}
            if rebuilt != saved:
                reconstruction_pass = False
                raise ValueError("state reconstruction mismatch")
            if not values_equal(spectrum_metrics(rebuilt, state["slot_count"]), state["spectrum_state_metrics"]):
                metric_pass = False
                raise ValueError("spectrum metrics recomputation mismatch")
        except Exception as exc:
            local_errors.append(f"{type(exc).__name__}: {exc}")
            errors.append(f"{state_id}: {local_errors[-1]}")
        state_reports.append({"resource_state_id": state_id, "pass": not local_errors, "errors": local_errors})
    requests = {}
    requests_by_topology = {}
    derivations = {}
    for path in sorted((env/"requests/single").glob("*.jsonl")):
        for item in _jsonl(path):
            if item["request_id"] in requests:
                errors.append(f"duplicate request id {item['request_id']}")
            requests[item["request_id"]] = item
            requests_by_topology.setdefault(item["topology_id"], []).append(item)
    for path in sorted((env/"requests/derivation").glob("*.jsonl")):
        for item in _jsonl(path):
            if item["request_id"] in derivations:
                errors.append(f"duplicate derivation request id {item['request_id']}")
            derivations[item["request_id"]] = item
    request_reports = []
    for topology_id, topology_requests in requests_by_topology.items():
        local_errors = []
        try:
            state_ids = {derivations[item["request_id"]]["resource_state_id"] for item in topology_requests}
            if len(state_ids) != 1:
                raise ValueError("request batch binds multiple resource states")
            state = states[next(iter(state_ids))]
            deriver = RequestDeriver.from_objects(physicals[topology_id], state, 5)
            links = {item["link_id"]: item for item in directeds[topology_id]["directed_link_records"]}
            for request in topology_requests:
                stored = derivations.get(request["request_id"])
                if stored is None or not values_equal(deriver.derive(request), stored):
                    raise ValueError(f"request derivation mismatch {request['request_id']}")
                for candidate in stored["candidate_paths"]:
                    if candidate["rank"] < 1 or candidate["rank"] > stored["candidate_path_k"]:
                        raise ValueError("candidate rank boundary")
                    current = request["source_node_id"]
                    visited = {current}
                    for link_id in candidate["path_link_ids"]:
                        link = links[link_id]
                        if link["source_node_id"] != current:
                            raise ValueError("candidate path direction/continuity")
                        current = link["destination_node_id"]
                        if current in visited:
                            raise ValueError("candidate path simplicity")
                        visited.add(current)
                    if current != request["destination_node_id"]:
                        raise ValueError("candidate path endpoint")
        except Exception as exc:
            local_errors.append(f"{type(exc).__name__}: {exc}")
            errors.append(f"{topology_id} request batch: {local_errors[-1]}")
        request_reports.append({"topology_id": topology_id, "request_count": len(topology_requests),
                                "pass": not local_errors, "errors": local_errors})
    concurrent_items = list(map(_load, sorted((env/"requests/concurrent").glob("*.json"))))
    concurrent = {item["request_set_id"]: item for item in concurrent_items}
    if len(concurrent) != len(concurrent_items):
        errors.append("duplicate concurrent request-set id")
    for request_set_id, item in concurrent.items():
        try:
            if len(item["request_ids"]) != len(set(item["request_ids"])):
                raise ValueError("duplicate concurrent request reference")
            recomputed = build_concurrent_request_set(request_set_id, item["request_ids"], requests,
                                                      derivations, item["resource_state_id"])
            if not values_equal(recomputed, item):
                raise ValueError("concurrent overlap density or joint feasibility mismatch")
        except Exception as exc:
            errors.append(f"{request_set_id}: {type(exc).__name__}: {exc}")
    sequence_items = list(map(_load, sorted((env/"requests/dynamic").glob("*.json"))))
    sequences = {item["request_sequence_id"]: item for item in sequence_items}
    if len(sequences) != len(sequence_items):
        errors.append("duplicate dynamic sequence id")
    dynamic_request_ids = [event["request_id"] for sequence in sequence_items
                           for event in sequence["dynamic_request_events"]]
    if len(dynamic_request_ids) != len(set(dynamic_request_ids)) or set(dynamic_request_ids) & set(requests):
        errors.append("dynamic requests are not globally new request instances")
    scenarios = list(map(_load, sorted((env/"scenarios").glob("*.json"))))
    scenario_ids = [item["base_scenario_id"] for item in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        errors.append("duplicate BaseScenario id")
    dynamic_replay_pass = True
    for scene in scenarios:
        try:
            has_state = "resource_state_id" in scene
            has_connection = "initial_existing_connection_set_id" in scene
            if has_state != has_connection:
                raise ValueError("BaseScenario state pairing")
            if scene["topology_id"] not in physicals:
                raise ValueError("BaseScenario topology reference")
            dtype = scene["request_data_type"]
            if dtype == "NONE":
                if "request_data_id" in scene:
                    raise ValueError("NONE carries request reference")
            elif dtype == "SINGLE" and scene["request_data_id"] not in requests:
                raise ValueError("SINGLE reference")
            elif dtype == "CONCURRENT" and scene["request_data_id"] not in concurrent:
                raise ValueError("CONCURRENT reference")
            elif dtype == "DYNAMIC":
                sequence = sequences[scene["request_data_id"]]
                state = states[scene["resource_state_id"]]
                connection_set = connection_sets[scene["initial_existing_connection_set_id"]]
                if state["topology_id"] != scene["topology_id"] or connection_set["topology_id"] != scene["topology_id"]:
                    raise ValueError("DYNAMIC topology pairing")
                replay_one = _replay(sequence, connection_set, physicals[scene["topology_id"]], state["slot_count"])
                replay_two = _replay(sequence, connection_set, physicals[scene["topology_id"]], state["slot_count"])
                if replay_one != replay_two:
                    dynamic_replay_pass = False
                    raise ValueError("dynamic replay nondeterministic")
        except Exception as exc:
            errors.append(f"{scene.get('base_scenario_id')}: {type(exc).__name__}: {exc}")
    return {
        "pass": not errors, "errors": errors, "topology_count": len(physicals),
        "state_count": len(states), "request_count": len(requests),
        "topology_reports": topology_reports, "state_reports": state_reports,
        "request_reports": request_reports, "state_reconstruction_pass": reconstruction_pass,
        "spectrum_metric_recomputation_pass": metric_pass,
        "dynamic_replay_pass": dynamic_replay_pass,
    }
