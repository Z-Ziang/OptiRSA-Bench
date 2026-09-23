from __future__ import annotations

from collections.abc import Iterator

from src.s1_x4.algorithm_api.types import AlgorithmObservation, AlgorithmStaticContext


class FirstFeasibleS1:
    """A deterministic legal S1 policy using the complete public action array."""

    def solve(self, static: AlgorithmStaticContext, observation: AlgorithmObservation) -> dict:
        if static.task_type != "S1" or observation.task_type != "S1":
            raise ValueError("FirstFeasibleS1 requires an S1 observation")
        if observation.feasible_actions is None or observation.feasible_actions.size == 0:
            return {"decision": "REJECT", "path_rank": None, "slot_start": None}
        path_rank, slot_start = observation.feasible_actions[0]
        return {
            "decision": "ACCEPT",
            "path_rank": int(path_rank),
            "slot_start": int(slot_start),
        }


def _simple_paths(static: AlgorithmStaticContext, source: int, destination: int) -> Iterator[tuple[list[int], list[int]]]:
    topology = static.topology

    def visit(node: int, nodes: list[int], links: list[int], visited: set[int]):
        if node == destination:
            yield list(nodes), list(links)
            return
        for link_index in topology.outgoing_link_indices(node).tolist():
            next_node = int(topology.destinations[int(link_index)])
            if next_node in visited:
                continue
            yield from visit(
                next_node,
                nodes + [next_node],
                links + [int(topology.link_ids[int(link_index)])],
                visited | {next_node},
            )

    yield from visit(int(source), [int(source)], [], {int(source)})


class SimpleFullSpaceX4:
    """A small deterministic X4 full-space RSA policy over public structures only."""

    def solve(self, static: AlgorithmStaticContext, observation: AlgorithmObservation) -> dict:
        if static.task_type != "X4" or observation.task_type != "X4":
            raise ValueError("SimpleFullSpaceX4 requires an X4 observation")
        request = observation.request
        required = int(request["required_slots"])
        source = int(request["source_node_id"])
        destination = int(request["destination_node_id"])
        for nodes, links in _simple_paths(static, source, destination):
            common = set(range(observation.spectrum.slot_count))
            for link_id in links:
                common.intersection_update(observation.spectrum.free_slots(link_id))
            for start in range(observation.spectrum.slot_count - required + 1):
                if all(start + offset in common for offset in range(required)):
                    return {
                        "decision": "ACCEPT",
                        "path_node_ids": nodes,
                        "path_link_ids": links,
                        "slot_start": start,
                    }
        return {"decision": "REJECT", "path_node_ids": [], "path_link_ids": [], "slot_start": None}
