import json
from pathlib import Path
import pytest

@pytest.fixture
def weighted_topology_dict():
    # Connected simple undirected graph with deterministic positive lengths.
    return {
        "topology_id": "top_small_weighted",
        "source_type": "SYNTHETIC",
        "node_records": [{"node_id": i} for i in range(6)],
        "physical_link_records": [
            {"physical_link_id": 0, "node_u_id": 0, "node_v_id": 1, "length_km": 2.0},
            {"physical_link_id": 1, "node_u_id": 1, "node_v_id": 3, "length_km": 2.0},
            {"physical_link_id": 2, "node_u_id": 0, "node_v_id": 2, "length_km": 1.0},
            {"physical_link_id": 3, "node_u_id": 2, "node_v_id": 3, "length_km": 5.0},
            {"physical_link_id": 4, "node_u_id": 2, "node_v_id": 4, "length_km": 1.0},
            {"physical_link_id": 5, "node_u_id": 3, "node_v_id": 4, "length_km": 1.0},
            {"physical_link_id": 6, "node_u_id": 3, "node_v_id": 5, "length_km": 1.0},
            {"physical_link_id": 7, "node_u_id": 1, "node_v_id": 2, "length_km": 2.5},
        ],
    }

@pytest.fixture
def weighted_topology_file(tmp_path, weighted_topology_dict):
    p = tmp_path / "topology.json"
    p.write_text(json.dumps(weighted_topology_dict, ensure_ascii=False), encoding="utf-8")
    return p

@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]
