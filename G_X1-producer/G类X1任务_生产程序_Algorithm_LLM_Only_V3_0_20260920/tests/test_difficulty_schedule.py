import json
from pathlib import Path
from random import Random

import pytest

from gx1.topology import topology_from_dict
from gx1.x1 import generate_x1_case


def _path_topology_dict(topology_id: str, n: int):
    return {
        "topology_id": topology_id,
        "source_type": "SYNTHETIC",
        "node_records": [{"node_id": i} for i in range(n)],
        "physical_link_records": [
            {"physical_link_id": i, "node_u_id": i, "node_v_id": i + 1, "length_km": 1.0}
            for i in range(n - 1)
        ],
    }


def test_x1_can_filter_shortest_path_multiplicity(weighted_topology_dict):
    topo = topology_from_dict(weighted_topology_dict)
    multiple = generate_x1_case(
        topo,
        "X1_000001",
        Random(7),
        forced_metric="HOP_COUNT",
        forced_multiplicity="MULTIPLE",
        min_hops=2,
        max_hops=2,
        max_sampling_attempts=256,
    )
    assert multiple["shortest_path_multiplicity"] > 1

    unique = generate_x1_case(
        topo,
        "X1_000002",
        Random(8),
        forced_metric="TOTAL_LENGTH_KM",
        forced_multiplicity="UNIQUE",
        min_hops=1,
        max_hops=5,
        max_sampling_attempts=256,
    )
    assert unique["shortest_path_multiplicity"] == 1


def test_production_respects_topology_and_hop_range_schedule(tmp_path):
    from gx1.production import produce_batch

    small = tmp_path / "small.json"
    medium = tmp_path / "medium.json"
    small.write_text(json.dumps(_path_topology_dict("small_path", 8)), encoding="utf-8")
    medium.write_text(json.dumps(_path_topology_dict("medium_path", 20)), encoding="utf-8")

    cfg = {
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_1",
        "batch_id": "SCHEDULE_TEST",
        "seed": 11,
        "topologies": [str(small), str(medium)],
        "case_counts": {"G1": 0, "G2": 2, "G3": 0, "X1": 2},
        "tasks": {
            "G1": {},
            "G2": {
                "label_schedule": ["VALID", "VALID"],
                "topology_schedule": ["small_path", "medium_path"],
                "hop_range_schedule": [[2, 3], [8, 12]],
                "max_sampling_attempts": 1024,
            },
            "G3": {},
            "X1": {
                "metric_schedule": ["HOP_COUNT", "HOP_COUNT"],
                "topology_schedule": ["small_path", "medium_path"],
                "hop_range_schedule": [[2, 3], [8, 12]],
                "multiplicity_schedule": ["UNIQUE", "UNIQUE"],
                "max_sampling_attempts": 1024,
            },
        },
    }
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps(cfg), encoding="utf-8")
    out = tmp_path / "out"
    produce_batch(cp, out)

    g2_roots = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "cases" / "G2").glob("*/root_case.json"))]
    x1_roots = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "cases" / "X1").glob("*/root_case.json"))]

    assert [r["topology_id"] for r in g2_roots] == ["small_path", "medium_path"]
    assert [r["topology_id"] for r in x1_roots] == ["small_path", "medium_path"]
    assert 2 <= len(g2_roots[0]["candidate_path"]["path_link_ids"]) <= 3
    assert 8 <= len(g2_roots[1]["candidate_path"]["path_link_ids"]) <= 12
    assert 2 <= x1_roots[0]["answer"]["hop_count"] <= 3
    assert 8 <= x1_roots[1]["answer"]["hop_count"] <= 12
    assert x1_roots[0]["generation_metadata"]["requested_hop_range"] == [2, 3]
    assert x1_roots[1]["generation_metadata"]["requested_multiplicity"] == "UNIQUE"


def test_v20_config_remains_accepted(project_root, tmp_path):
    from gx1.production import produce_batch
    out = tmp_path / "legacy"
    manifest = produce_batch(project_root / "configs" / "representative_four_cases.json", out)
    assert manifest["case_counts"] == {"G1": 1, "G2": 1, "G3": 1, "X1": 1}


def test_g2_hop_range_applies_to_final_repeated_node_candidate(tmp_path):
    from gx1.g2 import generate_g2_case
    topo = topology_from_dict(_path_topology_dict("ringish_path", 20))
    root = generate_g2_case(
        topo, "G2_000001", Random(11), forced_label="REPEATED_NODE",
        min_hops=4, max_hops=4, max_sampling_attempts=1024,
    )
    final_hops = len(root["candidate_path"]["path_link_ids"])
    assert final_hops == 4
