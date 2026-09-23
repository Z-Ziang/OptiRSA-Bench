from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production.config import ConfigurationError, FROZEN_SCIENTIFIC_PROFILE, load_production_config


def _config(tmp_path: Path, dynamic: dict) -> Path:
    topology = tmp_path / "topology.json"
    topology.write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    obj = {
        "schema_version": "PUBLIC_ENV_PRODUCTION_CONFIG_V1_0",
        "batch_id": "DYNAMIC_V220_TEST",
        "scientific_profile": dict(FROZEN_SCIENTIFIC_PROFILE),
        "resource_state_jobs": [
            {"job_id": "light", "policy": "KSP-FF", "load_band": "LIGHT", "seed": 101, "confirmation_seed": 201},
            {"job_id": "medium", "policy": "KSP-FF", "load_band": "MEDIUM", "seed": 102, "confirmation_seed": 202},
            {"job_id": "high", "policy": "KSP-FF", "load_band": "HIGH", "seed": 103, "confirmation_seed": 203},
            {"job_id": "pressure", "policy": "KSP-FF", "load_band": "HIGH_PRESSURE", "seed": 104, "confirmation_seed": 204, "diagnostic": True},
        ],
        "request_generation": {"seed": 301, "derivation_anchor_job_id": "medium"},
        "concurrent": {"enabled": False, "set_count": 0, "requests_per_set": 0, "seed": 401},
        "dynamic": dynamic,
        "execution": {"resume": False, "continue_on_failure": False},
        "topologies": [{"topology_id": "top_test", "source_path": str(topology), "source_type": "GABRIEL_JSON"}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_match_state_dynamic_config_names_non_diagnostic_anchors(tmp_path: Path) -> None:
    cfg = load_production_config(_config(tmp_path, {
        "enabled": True,
        "anchor_job_ids": ["light", "medium", "high"],
        "sequence_length": 128,
        "sequences_per_condition": 3,
        "arrival_rate_mode": "MATCH_STATE",
        "seed": 501,
    }))
    assert cfg.dynamic.anchor_job_ids == ("light", "medium", "high")
    assert cfg.dynamic.sequence_length == 128
    assert cfg.dynamic.sequences_per_condition == 3
    assert cfg.dynamic.arrival_rate_mode == "MATCH_STATE"
    assert cfg.dynamic.arrival_rate_multipliers == (1.0,)


def test_multiplier_dynamic_config_preserves_progressive_load_ratios(tmp_path: Path) -> None:
    cfg = load_production_config(_config(tmp_path, {
        "enabled": True,
        "anchor_job_ids": ["medium"],
        "sequence_length": 512,
        "sequences_per_condition": 2,
        "arrival_rate_mode": "MULTIPLIER_OF_STATE",
        "arrival_rate_multipliers": [0.8, 1.0, 1.2],
        "seed": 502,
    }))
    assert cfg.dynamic.arrival_rate_multipliers == (0.8, 1.0, 1.2)


def test_absolute_dynamic_rate_requires_explicit_nonstationary_opt_in(tmp_path: Path) -> None:
    path = _config(tmp_path, {
        "enabled": True,
        "anchor_job_ids": ["medium"],
        "sequence_length": 32,
        "sequences_per_condition": 1,
        "arrival_rate_mode": "ABSOLUTE",
        "arrival_rate_lambda": 0.5,
        "seed": 503,
    })
    with pytest.raises(ConfigurationError, match="allow_nonstationary_absolute_rate"):
        load_production_config(path)


def test_dynamic_anchor_cannot_reference_diagnostic_state(tmp_path: Path) -> None:
    path = _config(tmp_path, {
        "enabled": True,
        "anchor_job_ids": ["pressure"],
        "sequence_length": 32,
        "sequences_per_condition": 1,
        "arrival_rate_mode": "MATCH_STATE",
        "seed": 504,
    })
    with pytest.raises(ConfigurationError, match="non-diagnostic"):
        load_production_config(path)


def test_resolve_dynamic_conditions_uses_each_states_calibrated_lambda(tmp_path: Path) -> None:
    from src.production.dynamic import resolve_dynamic_conditions

    cfg = load_production_config(_config(tmp_path, {
        "enabled": True,
        "anchor_job_ids": ["light", "high"],
        "sequence_length": 64,
        "sequences_per_condition": 2,
        "arrival_rate_mode": "MULTIPLIER_OF_STATE",
        "arrival_rate_multipliers": [0.8, 1.2],
        "seed": 505,
    }))
    jobs = {j.job_id: j for j in cfg.resource_state_jobs}
    conditions = resolve_dynamic_conditions(cfg.dynamic, jobs, {"light": 10.0, "high": 30.0})
    assert [(c.anchor_job_id, c.arrival_rate_multiplier, c.arrival_rate_lambda, c.lambda_ratio) for c in conditions] == [
        ("light", 0.8, 8.0, 0.8),
        ("light", 1.2, 12.0, 1.2),
        ("high", 0.8, 24.0, 0.8),
        ("high", 1.2, 36.0, 1.2),
    ]


def _inject_generation_context(env: Path) -> None:
    seq_path = env / "requests/dynamic/seq_demo.json"
    seq = json.loads(seq_path.read_text(encoding="utf-8"))
    seq["generation_context"] = {
        "anchor_job_id": "medium",
        "initial_load_band": "MEDIUM",
        "state_arrival_rate_lambda": 20.0,
        "dynamic_arrival_rate_lambda": 24.0,
        "arrival_rate_mode": "MULTIPLIER_OF_STATE",
        "requested_arrival_rate_multiplier": 1.2,
        "lambda_ratio": 1.2,
    }
    seq_path.write_text(json.dumps(seq), encoding="utf-8")


def test_episode_internal_difficulty_context_is_preserved_but_not_rendered(tmp_path: Path) -> None:
    from tests.s1x4_test_utils import minimal_dynamic_environment
    from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
    from src.s1_x4.state_machine import DynamicEpisodeState
    from src.s1_x4.renderer import render_s1_step

    env = minimal_dynamic_environment(tmp_path, length=3)
    _inject_generation_context(env)
    index = load_dynamic_public_environment(env)
    episode = build_episode_definition(index, "bs_dynamic_demo", "S1", "S1_case_000001", k=3, pairing_id="pair")
    assert episode["initial_reference_time"] == 0.0
    assert episode["holding_time_rate_mu"] == pytest.approx(1 / 15)
    assert episode["difficulty_context"]["initial_load_band"] == "MEDIUM"
    assert episode["difficulty_context"]["lambda_ratio"] == pytest.approx(1.2)
    prompt = render_s1_step(episode, DynamicEpisodeState(episode).prepare_current_step(), "llm")
    assert "lambda_ratio" not in prompt
    assert "state_arrival_rate_lambda" not in prompt
    assert "MULTIPLIER_OF_STATE" not in prompt


def test_exported_features_record_initial_state_and_normalized_horizon(tmp_path: Path, monkeypatch) -> None:
    from tests.s1x4_test_utils import minimal_dynamic_environment
    import src.s1_x4.exporter as ex
    from src.s1_x4_pipeline import derive_s1x4_dataset

    monkeypatch.setattr(ex, "compute_serialization_metrics", lambda l: {
        "llm_prompt_char_count": len(l),
        "canonical_tokenizer": {"backend": "TEST", "encoding": "TEST", "package_version": "0"},
    })
    env = minimal_dynamic_environment(tmp_path, length=3)
    _inject_generation_context(env)
    cfg = tmp_path / "s1x4.json"
    cfg.write_text(json.dumps({"profile": "TEST", "case_count": 1, "allow_shortfall": False, "k_values": [3], "run_reference_panel": True}), encoding="utf-8")
    out = tmp_path / "dataset"
    derive_s1x4_dataset(env, cfg, out)
    features = json.loads((out / "internal/private/S1/S1_case_000001/features.json").read_text(encoding="utf-8"))
    d = features["difficulty"]
    assert d["initial_load_band"] == "MEDIUM"
    assert d["lambda_ratio"] == pytest.approx(1.2)
    assert d["initial_network_utilization"] > 0
    assert d["initial_network_efm"] is not None
    assert d["episode_time_span"] == pytest.approx(5.5)
    assert d["normalized_horizon"] == pytest.approx(5.5 / 15.0)
    assert d["node_count"] == 4
    assert d["directed_link_count"] == 10
    assert d["k_value"] == 3
    assert d["initial_candidate_action_count"] >= 0
    lineage = json.loads((out / "internal/private/S1/S1_case_000001/lineage.json").read_text(encoding="utf-8"))
    assert lineage["dynamic_generation_context"]["lambda_ratio"] == pytest.approx(1.2)
    public = json.loads((out / "benchmark_case/S1/cases/case_000001.json").read_text(encoding="utf-8"))
    assert "lambda_ratio" not in public["llm_prompt"]


def test_reference_difficulty_calibration_reports_prefix_spread_and_saturation(tmp_path: Path, monkeypatch) -> None:
    from tests.s1x4_test_utils import minimal_dynamic_environment
    import src.s1_x4.exporter as ex
    from src.s1_x4_pipeline import derive_s1x4_dataset
    from src.s1_x4.difficulty_calibration import build_difficulty_report

    monkeypatch.setattr(ex, "compute_serialization_metrics", lambda l: {
        "llm_prompt_char_count": len(l),
        "canonical_tokenizer": {"backend": "TEST", "encoding": "TEST", "package_version": "0"},
    })
    env = minimal_dynamic_environment(tmp_path, length=4)
    _inject_generation_context(env)
    cfg = tmp_path / "s1x4.json"
    cfg.write_text(json.dumps({"profile": "TEST", "case_count": 1, "allow_shortfall": False, "k_values": [3], "run_reference_panel": True}), encoding="utf-8")
    out = tmp_path / "dataset"
    derive_s1x4_dataset(env, cfg, out)
    report = build_difficulty_report(out, prefixes=(2, 4))
    assert report["schema_version"] == "S1X4_DIFFICULTY_CALIBRATION_V2_2_0"
    assert len(report["cases"]) == 2
    s1 = next(row for row in report["cases"] if row["task_type"] == "S1")
    assert s1["lambda_ratio"] == pytest.approx(1.2)
    assert s1["reference_policy_count"] == 6
    assert s1["node_count"] == 4
    assert s1["k_value"] == 3
    assert s1["reference_final_utilization_min"] is not None
    assert s1["reference_final_utilization_max"] is not None
    assert s1["reference_zero_action_fraction_max"] is not None
    assert s1["saturation_flag"] in {"ALL_ZERO_RBR", "ALL_ONE_RBR", "RBR_DISCRIMINATIVE", "UNIFORM_NONEXTREME_RBR"}
    prefix = next(row for row in report["prefixes"] if row["task_type"] == "S1" and row["prefix_h"] == 2)
    assert prefix["reference_rbr_spread"] >= 0
    assert prefix["reference_mean_efm_spread"] >= 0


def test_reference_trajectory_exposes_internal_load_evolution_diagnostics(tmp_path: Path) -> None:
    from tests.s1x4_test_utils import minimal_dynamic_environment
    from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
    from src.s1_x4.reference_algorithms import run_reference_panel

    env = minimal_dynamic_environment(tmp_path, length=3)
    _inject_generation_context(env)
    index = load_dynamic_public_environment(env)
    episode = build_episode_definition(index, "bs_dynamic_demo", "S1", "S1_case_000001", k=3, pairing_id="pair")
    result = run_reference_panel(episode)["policy_results"][0]
    assert result["initial_network_efm"] is not None
    assert result["final_network_efm"] is not None
    assert len(result["network_efm_series"]) == 3
    assert result["initial_network_utilization"] > 0
    assert result["final_network_utilization"] >= 0
    assert len(result["network_utilization_series"]) == 3
    first = result["trajectory"][0]
    assert "pre_decision_network_utilization" in first
    assert "post_decision_network_utilization" in first
    assert "active_connection_count_before_decision" in first
    assert "active_connection_count_after_decision" in first
    assert first["candidate_action_count"] >= 0


def test_calibration_cli_writes_machine_readable_outputs(tmp_path: Path, monkeypatch) -> None:
    from tests.s1x4_test_utils import minimal_dynamic_environment
    import src.s1_x4.exporter as ex
    from src.s1_x4_pipeline import derive_s1x4_dataset
    import benchmark_s1x4

    monkeypatch.setattr(ex, "compute_serialization_metrics", lambda l: {
        "llm_prompt_char_count": len(l),
        "canonical_tokenizer": {"backend": "TEST", "encoding": "TEST", "package_version": "0"},
    })
    env = minimal_dynamic_environment(tmp_path, length=4)
    _inject_generation_context(env)
    cfg = tmp_path / "s1x4.json"
    cfg.write_text(json.dumps({"profile": "TEST", "case_count": 1, "allow_shortfall": False, "k_values": [3], "run_reference_panel": True}), encoding="utf-8")
    dataset = tmp_path / "dataset"
    derive_s1x4_dataset(env, cfg, dataset)
    output = tmp_path / "calibration"
    assert benchmark_s1x4.main(["calibrate-difficulty", "--dataset", str(dataset), "--output", str(output), "--prefixes", "2,4"]) == 0
    assert (output / "difficulty_calibration.json").is_file()
    assert (output / "difficulty_cases.csv").is_file()
    assert (output / "difficulty_prefixes.csv").is_file()
