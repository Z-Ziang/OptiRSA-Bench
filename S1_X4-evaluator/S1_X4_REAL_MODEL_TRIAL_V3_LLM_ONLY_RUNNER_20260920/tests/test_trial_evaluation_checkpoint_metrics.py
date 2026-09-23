from __future__ import annotations

import json
import time

import pytest


def _trajectory():
    return [
        {
            "step_index": 1,
            "decision": "ACCEPT",
            "blocked": False,
            "validation_error": None,
            "post_decision_network_efm": 0.2,
        },
        {
            "step_index": 2,
            "decision": "REJECT",
            "blocked": True,
            "validation_error": None,
            "post_decision_network_efm": 0.4,
        },
        {
            "step_index": 3,
            "decision": "ACCEPT",
            "blocked": True,
            "validation_error": "action is not in the public feasible action set",
            "post_decision_network_efm": None,
        },
        {
            "step_index": 4,
            "decision": None,
            "blocked": True,
            "validation_error": "invalid JSON",
            "post_decision_network_efm": 0.6,
        },
    ]


def test_build_prefix_summary_uses_official_trajectory_fields():
    from trial_evaluation.metrics import build_prefix_summary

    result = build_prefix_summary(_trajectory())

    assert result["step_count"] == 4
    assert result["established_count"] == 1
    assert result["blocked_count"] == 3
    assert result["submitted_reject_count"] == 1
    assert result["invalid_allocation_count"] == 1
    assert result["format_error_count"] == 1
    assert result["rbr"] == 0.75
    assert result["network_efm_defined_step_count"] == 3
    assert result["mean_network_efm"] == pytest.approx(0.4)
    assert result["final_network_efm"] == 0.6


def test_checkpoint_store_writes_atomic_contiguous_records_and_resumes_next_step(tmp_path):
    from trial_evaluation.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / "unit")
    store.append({"step_index": 1, "submission": '{"decision":"REJECT"}'})
    store.append({"step_index": 2, "submission": '{"decision":"REJECT"}'})

    assert [row["step_index"] for row in store.load()] == [1, 2]
    assert store.next_step_index() == 3
    assert (tmp_path / "unit" / "steps.jsonl").is_file()
    with pytest.raises(ValueError, match="contiguous"):
        store.append({"step_index": 4, "submission": "{}"})


def test_checkpoint_store_rejects_duplicate_step_without_overwriting_existing_record(tmp_path):
    from trial_evaluation.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / "unit")
    first = {"step_index": 1, "submission": "first"}
    store.append(first)
    with pytest.raises(ValueError, match="duplicate"):
        store.append({"step_index": 1, "submission": "second"})
    assert store.load() == [first]


def test_budget_guard_stops_before_next_api_call():
    from trial_evaluation.config import BudgetGuard, BudgetStop

    guard = BudgetGuard(max_api_calls=2, max_input_tokens=20, max_output_tokens=20)
    guard.before_request()
    guard.account(api_calls=1, input_tokens=8, output_tokens=4)
    guard.before_request()
    guard.account(api_calls=1, input_tokens=8, output_tokens=4)
    with pytest.raises(BudgetStop, match="max_api_calls"):
        guard.before_request()
    assert guard.snapshot()["api_requests"] == 2
    assert guard.snapshot()["input_tokens"] == 16


def test_budget_guard_stops_when_wall_clock_cap_is_reached(monkeypatch):
    from trial_evaluation.config import BudgetGuard, BudgetStop

    now = iter([100.0, 100.0, 101.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(now))
    guard = BudgetGuard(max_wall_time_minutes=1 / 60)
    guard.before_request()
    with pytest.raises(BudgetStop, match="max_wall_time_minutes"):
        guard.before_request()


def test_secret_scan_and_redaction_never_return_secret_value():
    from trial_evaluation.security import redact_text, scan_for_secrets

    secret = "sk-secret-value"
    text = f"Authorization: Bearer {secret}; key={secret}"
    redacted = redact_text(text, secrets=[secret])
    result = scan_for_secrets([redacted], secrets=[secret])
    assert result["passed"] is True
    assert secret not in redacted
    assert scan_for_secrets([text], secrets=[secret])["passed"] is False

