from __future__ import annotations


def test_capability_probe_records_exact_model_and_protocol_capabilities_without_secret(tmp_path):
    from trial_evaluation.providers.base import ProviderResponse, Usage
    from trial_evaluation.v2.capability_probe import run_capability_probe

    secret = "hidden-secret-value"
    calls = []

    class FakeProvider:
        def __init__(self, config):
            self.config = type("Config", (), {"model": config["model"]})()

        def complete(self, messages):
            calls.append({"messages": messages})
            return ProviderResponse(
                requested_model="deepseek-ai/DeepSeek-V4-Flash",
                response_model="deepseek-ai/DeepSeek-V4-Flash",
                text='{"decision":"REJECT","path_rank":null,"slot_start":null}',
                                usage=Usage(input_tokens=9, output_tokens=4, reasoning_tokens=2),
                latency_ms=3.0,
                provider_request_id="probe-1",
                retry_count=0,
                finish_reason="stop",
            )

    def fake_get_json(url, headers, timeout_seconds):
        assert url.endswith("/models?sub_type=chat")
        assert headers["Authorization"] == f"Bearer {secret}"
        return {"data": [{"id": "deepseek-ai/DeepSeek-V4-Flash"}]}

    result = run_capability_probe(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key_env": "SILICONFLOW_API_KEY",
        },
        api_key=secret,
        get_json=fake_get_json,
        provider_factory=lambda config: FakeProvider(config),
        output_path=tmp_path / "PROVIDER_CAPABILITY_PROBE.json",
    )

    assert result["exact_model_available"] is True
    assert result["capabilities"]["chat_completions"] is True
    assert result["capabilities"]["finish_reason"] is True
    assert result["capabilities"]["usage_prompt_tokens"] is True
    assert result["capabilities"]["usage_reasoning_tokens"] is True
    assert secret not in (tmp_path / "PROVIDER_CAPABILITY_PROBE.json").read_text(encoding="utf-8")
    assert len(calls) >= 1


def test_capability_probe_stops_before_post_when_exact_model_is_unavailable(tmp_path):
    from trial_evaluation.v2.capability_probe import run_capability_probe

    post_calls = []

    def fake_get_json(_url, _headers, _timeout_seconds):
        return {"data": [{"id": "other/model"}]}

    def provider_factory(_config):
        post_calls.append(True)
        raise AssertionError("POST probe must not run when exact model is absent")

    result = run_capability_probe(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key_env": "SILICONFLOW_API_KEY",
        },
        api_key="hidden-secret-value",
        get_json=fake_get_json,
        provider_factory=provider_factory,
        output_path=tmp_path / "PROVIDER_CAPABILITY_PROBE.json",
    )

    assert result["status"] == "MODEL_UNAVAILABLE"
    assert result["available_model_ids"] == ["other/model"]
    assert post_calls == []

