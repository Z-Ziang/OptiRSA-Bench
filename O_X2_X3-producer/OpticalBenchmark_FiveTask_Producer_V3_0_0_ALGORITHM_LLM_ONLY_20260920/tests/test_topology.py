import pytest

from src.topology.core import build_topology


def raw(nodes, edges):
    return {"node_count": nodes, "undirected_edges": [list(edge) for edge in edges]}


def test_path_graph_metrics_are_hand_checkable():
    physical, directed, metrics = build_topology(raw(3, [(1, 2), (0, 1)]), "top_x", "REAL")
    assert [n["node_id"] for n in physical["node_records"]] == [0, 1, 2]
    assert physical["physical_link_records"] == [
        {"physical_link_id": 0, "node_u_id": 0, "node_v_id": 1},
        {"physical_link_id": 1, "node_u_id": 1, "node_v_id": 2},
    ]
    assert directed["directed_link_records"][0] == {
        "link_id": 0, "source_node_id": 0, "destination_node_id": 1, "physical_link_id": 0
    }
    assert directed["directed_link_records"][1]["source_node_id"] == 1
    assert metrics["average_node_degree"] == pytest.approx(4 / 3)
    assert metrics["edge_density"] == pytest.approx(2 / 3)
    assert metrics["diameter_hops"] == 2
    assert metrics["average_shortest_path_hops"] == pytest.approx(4 / 3)
    assert metrics["bridge_count"] == 2
    assert not any("length" in key for key in metrics)


@pytest.mark.parametrize("edges", [[(0, 0), (0, 1)], [(0, 1), (1, 0)]])
def test_rejects_self_loop_or_duplicate_undirected_edge(edges):
    with pytest.raises(ValueError):
        build_topology(raw(2, edges), "top_x", "REAL")


def test_rejects_disconnected_graph():
    with pytest.raises(ValueError, match="connected"):
        build_topology(raw(4, [(0, 1), (2, 3)]), "top_x", "REAL")
