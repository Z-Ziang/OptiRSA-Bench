from __future__ import annotations

import json
from pathlib import Path

from src.multi_topology.simulation import LoadSearchProtocol
from src.production.batch import run_batch
from src.production.config import FROZEN_SCIENTIFIC_PROFILE, load_production_config


def _write_cycle(path: Path, n: int, chord: bool) -> None:
    edges = [{"source": i, "target": (i + 1) % n, "dist": 1.0} for i in range(n)]
    if chord:
        edges.append({"source": 0, "target": n // 2, "dist": 1.5})
    path.write_text(json.dumps({
        "directed": False, "multigraph": False,
        "nodes": [{"id": i} for i in range(n)], "edges": edges,
    }), encoding="utf-8")


def test_batch_runner_uses_same_single_topology_pipeline_and_promotes_only_passed_units(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write_cycle(a, 8, False)
    _write_cycle(b, 9, True)
    cfg = {
        "schema_version": "PUBLIC_ENV_PRODUCTION_CONFIG_V1_0", "batch_id": "TEST_BATCH",
        "scientific_profile": FROZEN_SCIENTIFIC_PROFILE,
        "resource_state_jobs": [{"job_id": "anchor", "policy": "KSP-FF", "load_band": "MEDIUM", "seed": 11, "confirmation_seed": 12}],
        "request_generation": {"seed": 21, "derivation_anchor_job_id": "anchor"},
        "concurrent": {"enabled": False, "set_count": 0, "requests_per_set": 0, "seed": 31},
        "dynamic": {"enabled": False, "sequence_count": 0, "sequence_length": 0, "arrival_rate_lambda": 0.0, "seed": 41},
        "execution": {"resume": True, "continue_on_failure": True},
        "topologies": [
            {"topology_id": "top_a", "source_path": str(a), "source_type": "GABRIEL_JSON"},
            {"topology_id": "top_b", "source_path": str(b), "source_type": "GABRIEL_JSON"},
        ],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    config = load_production_config(path)
    protocol = LoadSearchProtocol(
        warmup_min_requests=80, warmup_min_time_factor=0.2,
        observation_min_requests=120, observation_min_time_factor=0.2,
        utilization_stability_tolerance=0.20, blocking_stability_tolerance=0.20,
        sample_interval_requests=10, max_coarse_expansions=6, max_fine_rounds=4,
    )
    result = run_batch(config, tmp_path / "batch_out", protocol=protocol)
    assert result["status"] == "PASS"
    assert result["passed_topology_count"] == 2
    assert (tmp_path / "batch_out/units/top_a/reports/UNIT_ACCEPTANCE.json").is_file()
    assert (tmp_path / "batch_out/units/top_b/reports/UNIT_ACCEPTANCE.json").is_file()
    assert (tmp_path / "batch_out/reports/BATCH_ACCEPTANCE.json").is_file()
    assert (tmp_path / "batch_out/SHA256SUMS.txt").is_file()
