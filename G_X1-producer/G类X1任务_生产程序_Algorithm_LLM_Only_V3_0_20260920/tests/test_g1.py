import json
from random import Random

from gx1.topology import topology_from_dict
from gx1.g1 import generate_g1_case
from gx1.renderers import render_llm_case
from gx1.validators import validate_dut_output


def test_g1_edge_list_is_two_dimensional_array(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    root = generate_g1_case(topo, "G1_000001", Random(1), forced_conversion="EDGE_LIST_TO_ADJACENCY_LIST")
    assert root["source_representation"] == "EDGE_LIST"
    assert isinstance(root["source_payload"], list)
    assert all(isinstance(edge, list) and len(edge) == 2 for edge in root["source_payload"])
    assert not any(isinstance(edge, dict) for edge in root["source_payload"])


def test_g1_adjacency_list_is_complete_symmetric_and_sorted(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    root = generate_g1_case(topo, "G1_000001", Random(2), forced_conversion="ADJACENCY_LIST_TO_EDGE_LIST")
    adj = root["source_payload"]
    assert list(adj) == [str(i) for i in topo.nodes]
    for u in topo.nodes:
        assert adj[str(u)] == sorted(adj[str(u)])
        for v in adj[str(u)]:
            assert u in adj[str(v)]


def test_g1_llm_prompt_uses_structured_graph_representation(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    root = generate_g1_case(topo, "G1_000001", Random(3), forced_conversion="EDGE_LIST_TO_ADJACENCY_MATRIX")
    case = render_llm_case(root)
    assert case["case_id"] == "G1_000001"
    assert "当前边列表" in case["prompt"]
    assert "[\n  [0,1]" in case["prompt"]
    assert "endpoint_a" not in case["prompt"]
    assert "answer" in case


def test_g1_validator_accepts_semantically_equivalent_edge_order(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    root = generate_g1_case(topo, "G1_000001", Random(5), forced_conversion="ADJACENCY_LIST_TO_EDGE_LIST")
    ans = root["answer"]
    edges = [[b, a] for a, b in reversed(ans["edge_list"])]
    raw = json.dumps({"representation_type": "EDGE_LIST", "edge_list": edges})
    result = validate_dut_output(root, raw)
    assert result["valid"] is True

def test_g1_edge_list_canonical_order_is_lexicographic_even_if_physical_ids_are_not(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    root = generate_g1_case(topo, "G1_000099", Random(99), forced_conversion="EDGE_LIST_TO_ADJACENCY_LIST")
    assert root["source_payload"] == sorted(root["source_payload"], key=lambda e: (e[0], e[1]))
