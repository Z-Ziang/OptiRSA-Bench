from __future__ import annotations

import json
from pathlib import Path

import pytest

from gx1.unified_schema import verify_unified_export

from stage2.audit import audit_stage2_dataset, compare_deterministic_trees
from stage2.canonical_km import audit_canonical_package
from stage2.teacher_demo import build_stage2_config, run_stage2_production


TASK_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = TASK_ROOT / "input_canonical"
PRODUCER_ROOT = TASK_ROOT / "producer_stage2_dev"
EXPECTED_TOPOLOGIES = {
    "topologybench_netrail",
    "topologybench_elibackbone",
    "topologybench_jpn48",
    "topologybench_conus75",
    "topohub_gabriel_125_0",
    "topohub_gabriel_175_2",
    "topohub_gabriel_250_3",
    "topohub_gabriel_375_3",
    "topohub_gabriel_450_9",
}


@pytest.mark.skipif(not CANONICAL_ROOT.exists(), reason="optional canonical-km fixture is not bundled")
def test_canonical_km_acceptance_is_exact_and_does_not_scale_again():
    result = audit_canonical_package(CANONICAL_ROOT)

    assert result["pass"] is True
    assert result["canonical_km_topology_baseline_accepted"] is True
    assert result["second_scaling_performed"] is False
    assert {row["topology_id"] for row in result["topologies"]} == EXPECTED_TOPOLOGIES
    assert all(row["connected"] for row in result["topologies"])
    assert all(row["bridge_count"] == 0 for row in result["topologies"])
    assert all(row["all_lengths_positive"] for row in result["topologies"])
    assert all(row["manifest_hash_match"] for row in result["topologies"])


def test_stage2_config_has_fixed_45_case_matrix_and_scientific_constraints():
    config = build_stage2_config(CANONICAL_ROOT, seed=20260913)

    assert config["case_counts"] == {"G1": 11, "G2": 11, "G3": 11, "X1": 12}
    assert set(config["topology_ids"]) == EXPECTED_TOPOLOGIES
    assert config["supplementary_cases"] == 9
    assert config["tasks"]["G2"]["label_schedule"].count("VALID") == 3
    assert all(
        config["tasks"]["G2"]["label_schedule"].count(label) == 2
        for label in ("WRONG_DIRECTION", "DISCONNECTED_PATH", "NODE_LINK_MISMATCH", "REPEATED_NODE")
    )
    assert set(config["tasks"]["G1"]["conversion_schedule"]) == {
        "EDGE_LIST_TO_ADJACENCY_LIST",
        "EDGE_LIST_TO_ADJACENCY_MATRIX",
        "ADJACENCY_LIST_TO_EDGE_LIST",
        "ADJACENCY_LIST_TO_ADJACENCY_MATRIX",
        "ADJACENCY_MATRIX_TO_EDGE_LIST",
        "ADJACENCY_MATRIX_TO_ADJACENCY_LIST",
    }


@pytest.mark.skipif(not CANONICAL_ROOT.exists(), reason="optional canonical-km fixture is not bundled")
def test_stage2_production_has_45_valid_cases_public_schema_and_teacher_views(tmp_path):
    output = tmp_path / "stage2"
    topology_audit = audit_canonical_package(CANONICAL_ROOT)
    result = run_stage2_production(CANONICAL_ROOT, output, seed=20260913)

    assert result["pass"] is True
    assert result["case_count"] == 45
    assert result["task_counts"] == {"G1": 11, "G2": 11, "G3": 11, "X1": 12}
    assert verify_unified_export(output)["valid"] is True

    audit = audit_stage2_dataset(output, PRODUCER_ROOT, topology_audit)
    assert audit["pass"] is True
    assert audit["case_count"] == 45
    assert audit["topology_case_counts"] == {topology_id: 5 for topology_id in sorted(EXPECTED_TOPOLOGIES)}
    assert audit["validator"]["pass_count"] == 45
    assert audit["leak_scan"]["checked_request_count"] == 45
    assert audit["leak_scan"]["pass"] is True
    assert len(list((output / "teacher_view").rglob("*_TEACHER_VIEW.md"))) == 45
    copied_topology_audit = audit_canonical_package(output / "canonical_topologies")
    assert copied_topology_audit["pass"] is True
    assert copied_topology_audit["second_scaling_performed"] is False


@pytest.mark.skipif(not CANONICAL_ROOT.exists(), reason="optional canonical-km fixture is not bundled")
def test_deterministic_stage2_outputs_have_identical_relative_hashes(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    run_stage2_production(CANONICAL_ROOT, first, seed=20260913)
    run_stage2_production(CANONICAL_ROOT, second, seed=20260913)

    comparison = compare_deterministic_trees(first, second)
    assert comparison["pass"] is True
    assert comparison["different_paths"] == []


@pytest.mark.skipif(not CANONICAL_ROOT.exists(), reason="optional canonical-km fixture is not bundled")
def test_public_cases_do_not_contain_private_top_level_fields(tmp_path):
    output = tmp_path / "stage2"
    run_stage2_production(CANONICAL_ROOT, output, seed=20260913)

    for path in sorted((output / "benchmark_case").rglob("case_*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        assert list(case) == ["case_id", "llm_prompt", "reference"]
    for path in sorted((output / "evaluation_case").rglob("case_*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        assert list(case) == ["case_id", "prompt"]
        assert "reference" not in case
