from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production.config import (
    ConfigurationError,
    FROZEN_SCIENTIFIC_PROFILE,
    OFFICIAL_POLICY_TO_ENGINE_ID,
    load_production_config,
)


def _base_config(tmp_path: Path) -> Path:
    raw_topology = tmp_path / "topology.json"
    raw_topology.write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    cfg = {
        "schema_version": "PUBLIC_ENV_PRODUCTION_CONFIG_V1_0",
        "batch_id": "BATCH_TEST_001",
        "scientific_profile": dict(FROZEN_SCIENTIFIC_PROFILE),
        "resource_state_jobs": [
            {
                "job_id": "kspff_medium_seed01",
                "policy": "KSP-FF",
                "load_band": "MEDIUM",
                "seed": 1001,
                "confirmation_seed": 9001,
            }
        ],
        "request_generation": {
            "seed": 2001,
            "derivation_anchor_job_id": "kspff_medium_seed01",
        },
        "concurrent": {
            "enabled": True,
            "set_count": 3,
            "requests_per_set": 4,
            "seed": 3001,
        },
        "dynamic": {
            "enabled": True,
            "sequence_count": 1,
            "sequence_length": 20,
            "arrival_rate_lambda": 10.0,
            "seed": 4001,
        },
        "execution": {"resume": True, "continue_on_failure": True},
        "topologies": [
            {
                "topology_id": "top_test_001",
                "source_path": str(raw_topology),
                "source_type": "GABRIEL_JSON",
            }
        ],
    }
    path = tmp_path / "batch_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def test_load_config_maps_official_policy_without_exposing_internal_name(tmp_path: Path) -> None:
    config = load_production_config(_base_config(tmp_path))
    job = config.resource_state_jobs[0]
    assert job.policy == "KSP-FF"
    assert job.engine_policy_id == OFFICIAL_POLICY_TO_ENGINE_ID["KSP-FF"]
    assert config.scientific_profile.candidate_path_k == 5
    assert config.scientific_profile.slot_count == 320


def test_frozen_scientific_parameter_cannot_be_changed(tmp_path: Path) -> None:
    path = _base_config(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["scientific_profile"]["candidate_path_k"] = 3
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="candidate_path_k"):
        load_production_config(path)


def test_out_of_scope_policy_is_rejected(tmp_path: Path) -> None:
    path = _base_config(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["resource_state_jobs"][0]["policy"] = "KSP-PFA"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="policy"):
        load_production_config(path)


def test_high_pressure_requires_explicit_diagnostic_flag(tmp_path: Path) -> None:
    path = _base_config(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["resource_state_jobs"][0]["load_band"] = "HIGH_PRESSURE"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="HIGH_PRESSURE"):
        load_production_config(path)


def test_anchor_job_must_exist_and_be_kspff_medium(tmp_path: Path) -> None:
    path = _base_config(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["resource_state_jobs"][0]["load_band"] = "HIGH"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="derivation anchor"):
        load_production_config(path)


def test_duplicate_job_ids_are_rejected(tmp_path: Path) -> None:
    path = _base_config(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["resource_state_jobs"].append(dict(value["resource_state_jobs"][0]))
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate resource_state job_id"):
        load_production_config(path)
