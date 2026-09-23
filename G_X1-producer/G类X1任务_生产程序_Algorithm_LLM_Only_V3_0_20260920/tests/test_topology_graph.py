import json
import pytest

from gx1.topology import TopologyError, load_topology, topology_from_dict, expand_directed_links
from gx1.graph import shortest_path_info


def test_loads_canonical_topology_and_expands_link_ids(weighted_topology_file):
    topo = load_topology(weighted_topology_file)
    assert topo.topology_id == "top_small_weighted"
    links = expand_directed_links(topo)
    assert links[0].link_id == 0 and (links[0].source_node_id, links[0].destination_node_id) == (0, 1)
    assert links[1].link_id == 1 and (links[1].source_node_id, links[1].destination_node_id) == (1, 0)
    assert links[0].length_km == 2.0 and links[1].length_km == 2.0


def test_loads_public_raw_topology_without_fabricating_lengths(tmp_path):
    raw = {
        "raw_topology_name": "tiny",
        "source_type": "REAL",
        "node_ids": [0, 1, 2],
        "undirected_edges": [[1, 0], [1, 2]],
        "normalization_target_topology_id": "top_tiny",
    }
    p = tmp_path / "raw.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    topo = load_topology(p)
    assert topo.nodes == (0, 1, 2)
    assert topo.edges[0].u == 0 and topo.edges[0].v == 1
    assert topo.edges[0].length_km is None
    assert all(x.length_km is None for x in expand_directed_links(topo))


def test_rejects_non_contiguous_nodes(weighted_topology_dict):
    d = dict(weighted_topology_dict)
    d["node_records"] = [{"node_id": 0}, {"node_id": 2}]
    with pytest.raises(TopologyError, match="连续"):
        topology_from_dict(d)


def test_rejects_duplicate_undirected_edge(weighted_topology_dict):
    d = json.loads(json.dumps(weighted_topology_dict))
    d["physical_link_records"].append({
        "physical_link_id": 8, "node_u_id": 0, "node_v_id": 1, "length_km": 2.0
    })
    with pytest.raises(TopologyError, match="重复"):
        topology_from_dict(d)


def test_shortest_path_hop_count_reports_multiple_optima(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    info = shortest_path_info(topo, 0, 3, "HOP_COUNT")
    assert info.cost == 2
    assert info.hop_count == 2
    assert info.multiplicity >= 2
    assert info.path_node_ids[0] == 0 and info.path_node_ids[-1] == 3


def test_shortest_path_length_is_unique_and_correct(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    info = shortest_path_info(topo, 0, 3, "TOTAL_LENGTH_KM")
    assert info.path_node_ids == (0, 2, 4, 3)
    assert info.path_link_ids == (4, 8, 11)
    assert info.hop_count == 3
    assert info.cost == pytest.approx(3.0)
    assert info.multiplicity == 1
