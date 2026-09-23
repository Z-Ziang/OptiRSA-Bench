from __future__ import annotations


def test_protocol_profiles_are_explicit_and_task_schema_specific():
    from trial_evaluation.v2.config import build_profile

    a = build_profile("A", "S1")
    b = build_profile("B", "X4")
    assert a["enable_thinking"] is False
    assert a["thinking_budget"] is None
    assert a["structured_output_mode"] == "JSON_SCHEMA"
    assert a["max_tokens"] in {256, 512}
    assert b["enable_thinking"] is True
    assert b["thinking_budget"] == 1024
    assert b["response_format"]["json_schema"]["name"] == "x4_action"
    assert b["response_format"]["json_schema"]["strict"] is True


def test_v2_offline_gate_exercises_non_commit_paths(tmp_path):
    from tests.test_trial_evaluation_runner import _trial_dataset
    from trial_evaluation.v2.offline import run_v2_offline_gate

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    result = run_v2_offline_gate(dataset, tmp_path / "offline", max_steps=1)
    assert result["status"] == "PASS"
    assert result["infra_failure_probe"] is True
    assert result["protocol_failure_probe"] is True
    assert result["resume_same_step_probe"] is True
    assert result["scientific_reject_probe"] is True


def test_v2_cli_doctor_is_read_only_and_reports_key_presence_without_value(monkeypatch, capsys):
    from trial_evaluation.v2.cli import main

    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key-not-output")
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert '"siliconflow_key_present": true' in output.lower()
    assert "test-key-not-output" not in output
