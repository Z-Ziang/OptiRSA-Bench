import json
from random import Random

from gx1.topology import topology_from_dict


def make_path_topology(n=120):
    return topology_from_dict({
        "topology_id": f"path_{n}",
        "source_type": "SYNTHETIC",
        "node_records": [{"node_id": i} for i in range(n)],
        "physical_link_records": [
            {"physical_link_id": i, "node_u_id": i, "node_v_id": i+1, "length_km": 1.0}
            for i in range(n-1)
        ],
    })


def test_g2_sampling_is_bounded(monkeypatch):
    import gx1.g2 as mod
    topo = make_path_topology()
    original = mod.shortest_path_info
    calls = {"n": 0}
    def wrapped(*a, **k):
        calls["n"] += 1
        return original(*a, **k)
    monkeypatch.setattr(mod, "shortest_path_info", wrapped)
    mod.generate_g2_case(topo, "G2_000001", Random(1), forced_label="VALID", min_hops=2, max_hops=20, max_sampling_attempts=200)
    assert calls["n"] <= 200


def test_x1_sampling_is_bounded(monkeypatch):
    import gx1.x1 as mod
    topo = make_path_topology()
    original = mod.shortest_path_info
    calls = {"n": 0}
    def wrapped(*a, **k):
        calls["n"] += 1
        return original(*a, **k)
    monkeypatch.setattr(mod, "shortest_path_info", wrapped)
    mod.generate_x1_case(topo, "X1_000001", Random(2), forced_metric="HOP_COUNT", min_hops=2, max_hops=20, max_sampling_attempts=200)
    assert calls["n"] <= 200


def test_g3_sampling_is_bounded(monkeypatch):
    import gx1.g3 as mod
    topo = make_path_topology()
    original = mod.shortest_path_info
    calls = {"n": 0}
    def wrapped(*a, **k):
        calls["n"] += 1
        return original(*a, **k)
    monkeypatch.setattr(mod, "shortest_path_info", wrapped)
    mod.generate_g3_case(topo, "G3_000001", Random(3), forced_metric="HOP_COUNT", forced_shared=None, min_hops=2, max_hops=20, max_sampling_attempts=300)
    assert calls["n"] <= 300


def test_large_g1_production_filters_matrix_conversions(tmp_path):
    from gx1.production import produce_batch
    n = 101
    topo = {
        "topology_id": "large101",
        "source_type": "SYNTHETIC",
        "node_records": [{"node_id": i} for i in range(n)],
        "physical_link_records": [
            {"physical_link_id": i, "node_u_id": i, "node_v_id": i+1}
            for i in range(n-1)
        ],
    }
    tp = tmp_path / "topo.json"; tp.write_text(json.dumps(topo), encoding="utf-8")
    cfg = {
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_0",
        "batch_id": "LARGE_G1",
        "seed": 7,
        "topologies": [str(tp)],
        "case_counts": {"G1": 12, "G2": 0, "G3": 0, "X1": 0},
        "tasks": {
            "G1": {"conversion_weights": {
                "EDGE_LIST_TO_ADJACENCY_LIST": 1,
                "EDGE_LIST_TO_ADJACENCY_MATRIX": 1,
                "ADJACENCY_LIST_TO_EDGE_LIST": 1,
                "ADJACENCY_LIST_TO_ADJACENCY_MATRIX": 1,
                "ADJACENCY_MATRIX_TO_EDGE_LIST": 1,
                "ADJACENCY_MATRIX_TO_ADJACENCY_LIST": 1
            }}, "G2": {}, "G3": {}, "X1": {}
        }
    }
    cp = tmp_path / "cfg.json"; cp.write_text(json.dumps(cfg), encoding="utf-8")
    out = tmp_path / "out"
    produce_batch(cp, out)
    roots = [json.loads(p.read_text(encoding="utf-8")) for p in (out/"cases"/"G1").glob("*/root_case.json")]
    assert roots
    assert {r["conversion"] for r in roots} <= {"EDGE_LIST_TO_ADJACENCY_LIST", "ADJACENCY_LIST_TO_EDGE_LIST"}
