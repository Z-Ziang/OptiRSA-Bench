from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production.config import TopologySpec
from src.production.topology_input import TopologyInputError, load_and_build_topology


def _write_gabriel(path: Path) -> None:
    value = {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": 10}, {"id": 20}, {"id": 30}],
        "edges": [
            {"source": 10, "target": 20, "dist": 12.5},
            {"source": 20, "target": 30, "dist": 15.0},
            {"source": 10, "target": 30, "dist": 20.0},
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")


def test_gabriel_unknown_dist_is_not_published_as_length_km(tmp_path: Path) -> None:
    path = tmp_path / "7.json"
    _write_gabriel(path)
    artifacts = load_and_build_topology(TopologySpec("top_g300_7", path, "GABRIEL_JSON", None))
    assert artifacts.physical["source_type"] == "SYNTHETIC"
    assert [n["node_id"] for n in artifacts.physical["node_records"]] == [0, 1, 2]
    assert all("length_km" not in edge for edge in artifacts.physical["physical_link_records"])
    assert "average_physical_link_length_km" not in artifacts.metrics
    assert artifacts.private_mapping["source_distance_field"] == "dist"
    assert artifacts.private_mapping["source_distance_unit"] == "UNKNOWN"
    assert artifacts.metrics["physical_link_count"] == 3
    assert artifacts.metrics["directed_link_count"] == 6


def test_gabriel_self_loop_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    value = {"directed": False, "multigraph": False, "nodes": [{"id": 0}, {"id": 1}],
             "edges": [{"source": 0, "target": 0}, {"source": 0, "target": 1}]}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(TopologyInputError, match="self-loop"):
        load_and_build_topology(TopologySpec("top_bad", path, "GABRIEL_JSON", None))


def test_disconnected_input_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    value = {"directed": False, "multigraph": False, "nodes": [{"id": 0}, {"id": 1}, {"id": 2}],
             "edges": [{"source": 0, "target": 1}]}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(TopologyInputError, match="connected"):
        load_and_build_topology(TopologySpec("top_bad", path, "GABRIEL_JSON", None))


def test_canonical_physical_json_preserves_trusted_length(tmp_path: Path) -> None:
    path = tmp_path / "physical.json"
    value = {
        "topology_id": "ignored_source_id",
        "source_type": "REAL",
        "node_records": [{"node_id": 0}, {"node_id": 1}],
        "physical_link_records": [{"physical_link_id": 0, "node_u_id": 0, "node_v_id": 1, "length_km": 42.0}],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    artifacts = load_and_build_topology(TopologySpec("top_new", path, "CANONICAL_PHYSICAL_JSON", None))
    assert artifacts.physical["topology_id"] == "top_new"
    assert artifacts.physical["physical_link_records"][0]["length_km"] == 42.0
    assert artifacts.metrics["average_physical_link_length_km"] == 42.0
