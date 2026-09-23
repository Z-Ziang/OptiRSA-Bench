from __future__ import annotations

import json

import pytest

from trial_evaluation.providers.openai_compatible import HTTPResponse


TEST_KEY = "silicon" + "-test-key"


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, headers, timeout_seconds):
        self.calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout_seconds})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _ok_response(payload=None, *, finish_reason="stop"):
    return HTTPResponse(
        200,
        payload or {
            "id": "sf-1",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "choices": [{"finish_reason": finish_reason, "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "completion_tokens_details": {"reasoning_tokens": 3}},
        },
        {},
    )


def test_siliconflow_factory_forwards_structured_and_thinking_config(monkeypatch):
    from trial_evaluation.providers.siliconflow import create_siliconflow_provider

    monkeypatch.setenv("SILICONFLOW_API_KEY", TEST_KEY)
    transport = FakeTransport([_ok_response()])
    provider = create_siliconflow_provider(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key_env": "SILICONFLOW_API_KEY",
            "structured_output_mode": "JSON_SCHEMA",
            "response_format": {"type": "json_schema", "json_schema": {"name": "s1_action", "strict": True, "schema": {}}},
            "enable_thinking": False,
            "max_output_tokens": 256,
        },
        transport=transport,
    )

    result = provider.complete([{"role": "user", "content": "step"}])

    assert result.response_model == "deepseek-ai/DeepSeek-V4-Flash"
    assert result.usage.reasoning_tokens == 3
    assert transport.calls[0]["url"] == "https://api.siliconflow.cn/v1/chat/completions"
    assert transport.calls[0]["payload"]["response_format"]["type"] == "json_schema"
    assert transport.calls[0]["payload"]["enable_thinking"] is False
    assert transport.calls[0]["payload"]["max_tokens"] == 256
    assert "Authorization" not in json.dumps(result.to_dict())


def test_siliconflow_402_is_balance_failure_without_retry(monkeypatch):
    from trial_evaluation.providers.base import ProviderError
    from trial_evaluation.providers.siliconflow import create_siliconflow_provider

    monkeypatch.setenv("SILICONFLOW_API_KEY", TEST_KEY)
    transport = FakeTransport([HTTPResponse(402, {"error": {"message": "Insufficient Balance"}}, {})])
    provider = create_siliconflow_provider(
        {
            "provider": "siliconflow",
            "model": "deepseek-ai/DeepSeek-V4-Flash",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key_env": "SILICONFLOW_API_KEY",
        },
        transport=transport,
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.complete([])
    assert excinfo.value.status_code == 402
    assert excinfo.value.retryable is False
    assert len(transport.calls) == 1


def test_model_list_parser_requires_exact_requested_model():
    from trial_evaluation.v2.capability_probe import parse_chat_model_ids, require_exact_model

    ids = parse_chat_model_ids({"data": [{"id": "deepseek-ai/DeepSeek-V4-Flash"}, {"id": "other/chat"}]})
    assert ids == ["deepseek-ai/DeepSeek-V4-Flash", "other/chat"]
    assert require_exact_model(ids, "deepseek-ai/DeepSeek-V4-Flash") is True
    with pytest.raises(ValueError, match="not available"):
        require_exact_model(["other/chat"], "deepseek-ai/DeepSeek-V4-Flash")
