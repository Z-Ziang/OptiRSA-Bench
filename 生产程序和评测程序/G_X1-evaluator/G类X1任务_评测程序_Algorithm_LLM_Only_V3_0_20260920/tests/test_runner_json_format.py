import json
from pathlib import Path


def _opts():
    return {
        "temperature": 0.0,
        "max_tokens": 256,
        "case_timeout_seconds": 10.0,
        "request_timeout_seconds": 2.0,
        "request_hard_timeout_seconds": 2.0,
        "retries": 1,
        "backoff_seconds": 0.0,
        "output_format": {"mode": "json_schema", "strict": True, "preflight": True},
    }


def _write_llm_case(tmp_path: Path):
    case_dir = tmp_path / "G2_000001"
    case_dir.mkdir()
    root = {
        "case_id": "G2_000001",
        "task_type": "G2",
        "nodes": [0, 1],
        "path_cost_metric": "HOP_COUNT",
    }
    request = {"messages": [{"role": "user", "content": "classify this public case"}]}
    (case_dir / "root_case.json").write_text(json.dumps(root), encoding="utf-8")
    (case_dir / "actual_llm_request.json").write_text(json.dumps(request), encoding="utf-8")
    return case_dir


def test_llm_case_persists_exact_payload_with_case_json_schema(tmp_path, monkeypatch):
    import trial.run_openai_compatible_trial as mod

    seen = []

    def fake_post(*args, **kwargs):
        seen.append(args[2])
        return {"choices": [{"message": {"content": '{"is_valid":true,"error_type":null}'}}]}

    monkeypatch.setattr(mod, "_post_for_case", fake_post)
    case_dir = _write_llm_case(tmp_path)
    output_dir = tmp_path / "result"
    result = mod.run_one_llm_case(
        case_dir,
        "test-model",
        "http://example",
        "secret-not-written",
        _opts(),
        {},
        output_dir=output_dir,
        output_format_config=_opts()["output_format"],
    )

    assert result["model_output"] == '{"is_valid":true,"error_type":null}'
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    persisted = json.loads((output_dir / "actual_model_request.json").read_text(encoding="utf-8"))
    assert persisted == seen[0]
    assert "Authorization" not in json.dumps(persisted)
    audit = json.loads((output_dir / "request_boundary_audit.json").read_text(encoding="utf-8"))
    assert audit["passed"] is True


def test_preflight_uses_structured_json_prompt_and_response_format(monkeypatch):
    import trial.run_openai_compatible_trial as mod

    seen = []

    def fake_post(*args, **kwargs):
        seen.append(args[2])
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    monkeypatch.setattr(mod, "_post_chat_hard_timeout", fake_post)
    result = mod.run_llm_preflight(
        "http://example",
        "key",
        "model",
        request_timeout_seconds=1,
        request_hard_timeout_seconds=1,
        retries=1,
        backoff_seconds=0,
        case_timeout_seconds=5,
        extra_body={},
        output_format_config={"mode": "json_object", "strict": True},
    )
    assert result["supported"] is True
    assert "JSON object" in seen[0]["messages"][0]["content"]
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_old_direct_case_call_without_format_config_stays_unmodified(tmp_path, monkeypatch):
    import trial.run_openai_compatible_trial as mod

    seen = []
    monkeypatch.setattr(
        mod,
        "_post_for_case",
        lambda *args, **kwargs: seen.append(args[2]) or {"choices": [{"message": {"content": "{}"}}]},
    )
    case_dir = _write_llm_case(tmp_path)
    mod.run_one_llm_case(
        case_dir,
        "test-model",
        "http://example",
        "key",
        {**_opts(), "output_format": {"mode": "off"}},
        {},
    )
    assert "response_format" not in seen[0]


def test_failure_artifacts_always_include_empty_model_output_file(tmp_path):
    import trial.run_openai_compatible_trial as mod

    target = tmp_path / "failed_case"
    target.mkdir()
    mod._write_failure_artifacts(target, {"valid": False, "reason": "READ_TIMEOUT"}, "read timeout")

    output = target / "model_output.txt"
    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""


def test_summary_counts_only_formally_attempted_case_requests():
    import trial.run_openai_compatible_trial as mod

    rows = [
        {"task": "G1", "api_attempted": False, "api_success": False},
        {"task": "G2", "api_attempted": True, "api_success": True},
    ]
    summary = mod._summary(rows, "test-model", {}, {"supported": False})

    assert summary["api_attempted"] == 1
