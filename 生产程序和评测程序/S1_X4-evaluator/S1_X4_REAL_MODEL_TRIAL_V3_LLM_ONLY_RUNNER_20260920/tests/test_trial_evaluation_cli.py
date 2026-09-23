from __future__ import annotations

import json

from tests.test_trial_evaluation_runner import _trial_dataset
from tests.test_trial_evaluation_runner import _write_json
from tests.s1x4_test_utils import minimal_dynamic_environment


def _paired_trial_dataset(tmp_path):
    root = _trial_dataset(tmp_path, "S1", length=2)
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path / "environment", length=2))
    episode = build_episode_definition(
        idx,
        "bs_dynamic_demo",
        "X4",
        "X4_top_demo_A_MEDIUM_MATCH",
        k=None,
        pairing_id="pair_demo",
    )
    _write_json(root / "benchmark_case" / "X4" / "episodes" / "top_demo" / "A_MEDIUM_MATCH.json", episode)
    (root / "evaluation_case" / "X4" / "llm").mkdir(parents=True, exist_ok=True)
    (root / "evaluation_case" / "X4" / "llm" / "system_prompt.txt").write_text(
        "X4 llm frozen system prompt\n", encoding="utf-8"
    )
    _write_json(
        root / "evaluation_case" / "X4" / "llm" / "top_demo" / "A_MEDIUM_MATCH.json",
        {"case_id": episode["case_id"], "prompt": "current step only"},
    )
    return root


def _models_config(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "provider": "deepseek",
                        "model": "deepseek-flash",
                        "base_url": "https://api.deepseek.com",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cli_run_is_dry_run_without_execute(tmp_path, capsys):
    from trial_evaluation.cli import main

    dataset = _trial_dataset(tmp_path, "S1", length=1)
    code = main(
        [
            "run",
            "--phase",
            "smoke",
            "--model",
            "deepseek-flash",
            "--dataset",
            str(dataset),
            "--models-config",
            str(_models_config(tmp_path)),
            "--output",
            str(tmp_path / "output"),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["status"] == "DRY_RUN"
    assert result["phase"] == "PHASE1_SMOKE"
    assert result["unit_count"] == 2


def test_cli_request_output_limit_is_recorded_separately_from_budget_limit(tmp_path, capsys):
    from trial_evaluation.cli import main

    dataset = _trial_dataset(tmp_path, "S1", length=1)
    code = main(
        [
            "run",
            "--phase",
            "smoke",
            "--model",
            "deepseek-flash",
            "--dataset",
            str(dataset),
            "--models-config",
            str(_models_config(tmp_path)),
            "--request-max-output-tokens",
            "1024",
            "--max-output-tokens",
            "100000",
            "--output",
            str(tmp_path / "output"),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    resolved = json.loads((tmp_path / "output" / "CONFIG" / "trial_eval_models.resolved.json").read_text(encoding="utf-8"))
    assert code == 0
    assert result["status"] == "DRY_RUN"
    assert resolved["max_output_tokens"] == 1024
    assert resolved["budget_max_output_tokens"] == 100000


def test_cli_execute_without_key_is_explicitly_not_run(monkeypatch, tmp_path, capsys):
    from trial_evaluation.cli import main

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    dataset = _trial_dataset(tmp_path, "S1", length=1)
    code = main(
        [
            "run",
            "--phase",
            "smoke",
            "--model",
            "deepseek-flash",
            "--execute",
            "--dataset",
            str(dataset),
            "--models-config",
            str(_models_config(tmp_path)),
            "--output",
            str(tmp_path / "output"),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["status"] == "NOT_RUN_NO_KEY"
    assert result["real_api_execution"] == "NOT_RUN_NO_KEY"


def test_cli_doctor_reports_provider_ready_without_exposing_key(monkeypatch, capsys):
    from trial_evaluation.cli import main

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-test-key")
    code = main(["doctor"])
    captured = capsys.readouterr().out
    result = json.loads(captured)
    assert code == 0
    assert result["valid"] is True
    assert result["deepseek_provider_ready"] is True
    assert "secret-test-key" not in captured


def test_offline_gate_runs_fake_llm_without_external_provider(tmp_path):
    from trial_evaluation.offline import run_offline_gate

    dataset = _paired_trial_dataset(tmp_path)
    result = run_offline_gate(dataset, tmp_path / "offline", max_steps=2)
    assert result["status"] == "PASS"
    assert result["fake_llm_steps"] >= 2
    assert result["no_reference_in_decision_loop"] is True
    assert result["checkpoint_resume"] is True
    rerun = run_offline_gate(dataset, tmp_path / "offline", max_steps=2)
    assert rerun["status"] == "PASS"
