from src.case_core.wufr import (
    _adjacency_and_links,
    _lexicographic_shortest_node_path,
    _lexicographic_shortest_node_paths,
)


def test_single_source_reference_paths_match_original_pairwise_bfs():
    directed_links = [
        {"source_node_id": 0, "destination_node_id": 1, "link_id": 0},
        {"source_node_id": 0, "destination_node_id": 2, "link_id": 1},
        {"source_node_id": 1, "destination_node_id": 3, "link_id": 2},
        {"source_node_id": 2, "destination_node_id": 3, "link_id": 3},
        {"source_node_id": 1, "destination_node_id": 2, "link_id": 4},
        {"source_node_id": 2, "destination_node_id": 1, "link_id": 5},
        {"source_node_id": 3, "destination_node_id": 0, "link_id": 6},
    ]
    adjacency, _ = _adjacency_and_links(directed_links)
    optimized = _lexicographic_shortest_node_paths(0, adjacency)

    for target in sorted(adjacency):
        if target == 0:
            continue
        assert optimized[target] == _lexicographic_shortest_node_path(0, target, adjacency)

