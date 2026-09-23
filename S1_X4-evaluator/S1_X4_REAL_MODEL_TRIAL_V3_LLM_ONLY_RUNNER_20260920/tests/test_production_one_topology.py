from __future__ import annotations

import json
from pathlib import Path

from src.multi_topology.simulation import LoadSearchProtocol
from src.production.config import FROZEN_SCIENTIFIC_PROFILE, load_production_config
from src.production.one_topology import run_one_topology


def _config(tmp_path: Path) -> Path:
    topology = tmp_path / "tiny.json"
    # Cycle: connected, no bridges, enough route alternatives for K<=5 tests.
    topology.write_text(json.dumps({
        "directed": False, "multigraph": False,
        "nodes": [{"id": i} for i in range(8)],
        "edges": [{"source": i, "target": (i + 1) % 8, "dist": 1.0} for i in range(8)],
    }), encoding="utf-8")
    cfg = {
        "schema_version": "PUBLIC_ENV_PRODUCTION_CONFIG_V1_0",
        "batch_id": "TEST_ONE",
        "scientific_profile": FROZEN_SCIENTIFIC_PROFILE,
        "resource_state_jobs": [
            {"job_id": "anchor", "policy": "KSP-FF", "load_band": "MEDIUM", "seed": 11, "confirmation_seed": 12},
        ],
        "request_generation": {"seed": 21, "derivation_anchor_job_id": "anchor"},
        "concurrent": {"enabled": True, "set_count": 2, "requests_per_set": 3, "seed": 31},
        "dynamic": {"enabled": True, "anchor_job_ids": ["anchor"], "sequence_length": 5, "sequences_per_condition": 1, "arrival_rate_mode": "MATCH_STATE", "seed": 41},
        "execution": {"resume": True, "continue_on_failure": True},
        "topologies": [{"topology_id": "top_tiny", "source_path": str(topology), "source_type": "GABRIEL_JSON"}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def _tiny_protocol() -> LoadSearchProtocol:
    return LoadSearchProtocol(
        warmup_min_requests=120, warmup_min_time_factor=0.2,
        observation_min_requests=180, observation_min_time_factor=0.2,
        initial_observation_blocks=2, max_observation_blocks=4,
        utilization_stability_tolerance=0.20, blocking_stability_tolerance=0.20,
        sample_interval_requests=10, max_coarse_expansions=6, max_fine_rounds=4,
    )


def test_single_topology_runner_writes_full_valid_environment(tmp_path: Path) -> None:
    config = load_production_config(_config(tmp_path))
    out = tmp_path / "out"
    result = run_one_topology(config, config.topologies[0], out, protocol=_tiny_protocol())
    assert result["status"] == "PASS"
    env = out / "public_environment"
    assert (env / "topologies/physical/top_tiny.json").is_file()
    assert (env / "states/spectrum/rs_tiny_anchor.json").is_file()
    assert (env / "requests/single/requests_top_tiny.jsonl").is_file()
    assert (env / "requests/derivation/derivations_top_tiny.jsonl").is_file()
    assert (out / "reports/SCHEMA_AUDIT.json").is_file()
    assert (out / "reports/CROSS_FILE_AUDIT.json").is_file()
    assert (out / "MANIFEST.json").is_file()
    assert (out / "SHA256SUMS.txt").is_file()
    summary = json.loads((out / "reports/UNIT_ACCEPTANCE.json").read_text(encoding="utf-8"))
    assert summary["schema_pass"] is True
    assert summary["cross_file_validation_pass"] is True
    assert summary["state_reconstruction_pass"] is True
    assert summary["dynamic_replay_pass"] is True


def test_dynamic_sequence_matches_calibrated_anchor_load_and_records_context(tmp_path: Path) -> None:
    config = load_production_config(_config(tmp_path))
    out = tmp_path / "out_dynamic"
    run_one_topology(config, config.topologies[0], out, protocol=_tiny_protocol())
    env = out / "public_environment"
    state_cfg = json.loads((env / "configs/genconf_tiny_state_anchor.json").read_text(encoding="utf-8"))
    state_lambda = state_cfg["parameter_values"]["selected_arrival_rate_lambda"]
    sequences = list((env / "requests/dynamic").glob("*.json"))
    assert len(sequences) == 1
    sequence = json.loads(sequences[0].read_text(encoding="utf-8"))
    assert sequence["arrival_rate_lambda"] == state_lambda
    assert sequence["generation_context"] == {
        "anchor_job_id": "anchor",
        "initial_load_band": "MEDIUM",
        "state_arrival_rate_lambda": state_lambda,
        "dynamic_arrival_rate_lambda": state_lambda,
        "arrival_rate_mode": "MATCH_STATE",
        "requested_arrival_rate_multiplier": 1.0,
        "lambda_ratio": 1.0,
    }
    dynamic_scenarios = [json.loads(p.read_text(encoding="utf-8")) for p in (env / "scenarios").glob("*.json")]
    dynamic_scenarios = [x for x in dynamic_scenarios if x["request_data_type"] == "DYNAMIC"]
    assert len(dynamic_scenarios) == 1
    assert dynamic_scenarios[0]["resource_state_id"] == "rs_tiny_anchor"
    assert dynamic_scenarios[0]["initial_existing_connection_set_id"] == "icset_tiny_anchor"
