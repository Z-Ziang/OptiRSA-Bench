from __future__ import annotations

import json
import http.client

import pytest
from trial_evaluation.providers.base import ModelConfig


FAKE_API_TOKEN = "secret" + "-test-key"


def _config():
    return ModelConfig(
        provider="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        api_key_env="TRIAL_TEST_KEY",
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=128,
        timeout_seconds=3.0,
        max_transport_retries=5,
    )


class _FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload, headers, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _response(status_code, payload, headers=None):
    from trial_evaluation.providers.openai_compatible import HTTPResponse

    return HTTPResponse(status_code=status_code, payload=payload, headers=headers or {})


def test_openai_compatible_parser_normalizes_structured_content_usage_and_identity(monkeypatch):
    from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setenv("TRIAL_TEST_KEY", FAKE_API_TOKEN)
    transport = _FakeTransport(
        [
            _response(
                200,
                {
                    "id": "req_123",
                    "model": "deepseek-flash-20260917",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": '{"decision":"REJECT"}',
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 101,
                        "completion_tokens": 17,
                        "prompt_tokens_details": {"cached_tokens": 7},
                    },
                },
            )
        ]
    )
    provider = OpenAICompatibleProvider(_config(), transport=transport, sleep=lambda _: None)

    result = provider.complete(
        [{"role": "system", "content": "system"}, {"role": "user", "content": "step"}],
    )

    assert result.requested_model == "deepseek-flash"
    assert result.response_model == "deepseek-flash-20260917"
    assert result.provider_request_id == "req_123"
    assert result.text == '{"decision":"REJECT"}'
    assert result.usage.input_tokens == 101
    assert result.usage.output_tokens == 17
    assert result.usage.cached_tokens == 7
    assert result.retry_count == 0
    assert transport.calls[0]["payload"]["model"] == "deepseek-flash"
    assert "Authorization" not in json.dumps(result.to_dict())
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer " + FAKE_API_TOKEN


def test_openai_compatible_retries_transient_http_errors_and_records_retry_count(monkeypatch):
    from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setenv("TRIAL_TEST_KEY", FAKE_API_TOKEN)
    transport = _FakeTransport(
        [
            _response(429, {"error": {"message": "rate limited"}}, {"Retry-After": "0"}),
            _response(503, {"error": {"message": "temporary"}}),
            _response(
                200,
                {
                    "id": "req_ok",
                    "model": "deepseek-flash",
                    "choices": [{"message": {"content": '{"decision":"REJECT"}'}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                },
            ),
        ]
    )
    sleeps = []
    provider = OpenAICompatibleProvider(_config(), transport=transport, sleep=sleeps.append)

    result = provider.complete([])

    assert result.text == '{"decision":"REJECT"}'
    assert result.retry_count == 2
    assert len(transport.calls) == 3
    assert len(sleeps) == 2


def test_openai_compatible_does_not_retry_non_transient_http_error(monkeypatch):
    from trial_evaluation.providers.base import ProviderError
    from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setenv("TRIAL_TEST_KEY", FAKE_API_TOKEN)
    transport = _FakeTransport([_response(400, {"error": {"message": "bad request"}})])
    provider = OpenAICompatibleProvider(_config(), transport=transport, sleep=lambda _: None)

    with pytest.raises(ProviderError, match="400"):
        provider.complete([])
    assert len(transport.calls) == 1


def test_deepseek_factory_preserves_requested_model_and_endpoint(monkeypatch):
    from trial_evaluation.providers.deepseek import create_deepseek_provider

    monkeypatch.setenv("TRIAL_TEST_KEY", FAKE_API_TOKEN)
    transport = _FakeTransport(
        [
            _response(
                200,
                {
                    "id": "req_ok",
                    "model": "deepseek-flash",
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {},
                },
            )
        ]
    )
    provider = create_deepseek_provider(
        {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com",
            "api_key_env": "TRIAL_TEST_KEY",
        },
        transport=transport,
    )
    result = provider.complete([])
    assert result.requested_model == "deepseek-flash"
    assert transport.calls[0]["url"] == "https://api.deepseek.com/chat/completions"


def test_reasoning_effort_is_explicitly_forwarded_without_changing_messages(monkeypatch):
    from trial_evaluation.providers.base import ModelConfig
    from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setenv("TRIAL_TEST_KEY", FAKE_API_TOKEN)
    transport = _FakeTransport(
        [
            _response(
                200,
                {
                    "id": "req_reasoning",
                    "model": "deepseek-flash",
                    "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        ]
    )
    config = ModelConfig(
        provider="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        api_key_env="TRIAL_TEST_KEY",
        reasoning_effort="minimal",
    )
    provider = OpenAICompatibleProvider(config, transport=transport, sleep=lambda _: None)
    messages = [{"role": "user", "content": "step"}]

    provider.complete(messages)

    assert transport.calls[0]["payload"]["reasoning_effort"] == "minimal"
    assert transport.calls[0]["payload"]["messages"] == messages


def test_model_config_loads_reasoning_effort_from_external_mapping():
    from trial_evaluation.providers.base import ModelConfig

    config = ModelConfig.from_mapping(
        {
            "provider": "deepseek",
            "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY",
            "reasoning_effort": "minimal",
        }
    )

    assert config.reasoning_effort == "minimal"


def test_default_transport_classifies_incomplete_read_as_retryable(monkeypatch):
    from trial_evaluation.providers.base import TransportProviderError
    from trial_evaluation.providers import openai_compatible

    def broken_urlopen(*_args, **_kwargs):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(openai_compatible, "urlopen", broken_urlopen)

    with pytest.raises(TransportProviderError):
        openai_compatible._default_transport(
            "https://api.deepseek.com/chat/completions",
            {},
            {},
            1.0,
        )
