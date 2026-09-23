from __future__ import annotations

from random import Random

import networkx as nx

from src.state_simulation.core import free_blocks


def generate_single_requests(topology_id: str, node_count: int, required_values: list[int], rng: Random,
                             prefix: str = "req") -> list[dict]:
    requests=[]; index=1
    for source in range(node_count):
        for destination in range(node_count):
            if source == destination: continue
            requests.append({"request_id":f"{prefix}_{index:04d}","topology_id":topology_id,
                             "source_node_id":source,"destination_node_id":destination,
                             "required_slots":rng.choice(required_values)})
            index += 1
    return requests


def _graphs(physical: dict, directed: dict):
    graph=nx.Graph(); graph.add_nodes_from(r["node_id"] for r in physical["node_records"])
    graph.add_edges_from((e["node_u_id"],e["node_v_id"]) for e in physical["physical_link_records"])
    lookup={(e["source_node_id"],e["destination_node_id"]):e["link_id"] for e in directed["directed_link_records"]}
    return graph,lookup


def derive_request(request: dict, physical: dict, directed: dict, state: dict, k: int) -> dict:
    graph,lookup=_graphs(physical,directed); source=request["source_node_id"]; dest=request["destination_node_id"]
    availability={x["link_id"]:x["slot_availability"] for x in state["link_spectrum_states"]}
    candidates=[]
    for rank,nodes in enumerate(nx.shortest_simple_paths(graph,source,dest),1):
        link_ids=[lookup[p] for p in zip(nodes,nodes[1:])]
        common=[int(all(availability[l][s] for l in link_ids)) for s in range(state["slot_count"])]
        blocks=free_blocks(common); required=request["required_slots"]
        starts=[s for s in range(state["slot_count"]-required+1) if all(common[s:s+required])]
        candidates.append({"rank":rank,"path_link_ids":link_ids,"common_free_block_count":len(blocks),
                           "largest_common_free_block_length":max((n for _,n in blocks),default=0),
                           "feasible_slot_starts":starts})
        if rank == k: break
    return {"request_id":request["request_id"],"resource_state_id":state["resource_state_id"],
            "shortest_path_hops":nx.shortest_path_length(graph,source,dest),
            "local_edge_connectivity":nx.edge_connectivity(graph,source,dest),"candidate_path_k":k,
            "candidate_paths":candidates,
            "feasible_candidate_path_count":sum(bool(c["feasible_slot_starts"]) for c in candidates),
            "feasible_action_count":sum(len(c["feasible_slot_starts"]) for c in candidates)}


def generate_dynamic_sequence(sequence_id: str, prefix: str, node_count: int, reference_time: float,
                              arrival_rate: float, holding_rate: float, required_values: list[int], rng: Random) -> dict:
    now=reference_time; events=[]
    for i in range(1,21):
        now += rng.expovariate(arrival_rate); source=rng.randrange(node_count); dest=rng.randrange(node_count-1)
        if dest >= source: dest += 1
        events.append({"request_id":f"{prefix}_{i:04d}","source_node_id":source,"destination_node_id":dest,
                       "required_slots":rng.choice(required_values),"arrival_time":now,
                       "holding_time":rng.expovariate(holding_rate)})
    return {"request_sequence_id":sequence_id,"dynamic_request_events":events,
            "arrival_rate_lambda":arrival_rate,"holding_time_rate_mu":holding_rate}
