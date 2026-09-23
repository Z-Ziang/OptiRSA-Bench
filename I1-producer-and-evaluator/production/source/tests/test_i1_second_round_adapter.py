from __future__ import annotations

import json

from src.i1.rewrite import IdentityRewriteClient, OpenAICompatibleRewriteClient


def test_identity_adapter_exposes_raw_response_contract_for_audit():
    client = IdentityRewriteClient()
    text, raw = client.rewrite_with_raw("基础文本", {"intent_type": "SINGLE"}, difficulty="EASY")
    assert text == "基础文本"
    assert raw is None


def test_openai_compatible_adapter_records_raw_rewrite_and_explicit_generation_parameters(monkeypatch):
    client = OpenAICompatibleRewriteClient(
        base_url="https://example.invalid/v1",
        api_key_env="TEST_KEY",
        model="rewrite-model",
        temperature=0.5,
        top_p=0.9,
        max_tokens=321,
    )
    observed = {}

    def fake_chat(system, user, temperature, *, top_p=None, max_tokens=None):
        observed.update({"system": system, "user": user, "temperature": temperature, "top_p": top_p, "max_tokens": max_tokens})
        return '{"rewritten_prompt":"从节点1到节点6建立业务，需要连续使用9个频谱槽位。"}'

    monkeypatch.setattr(client, "_chat", fake_chat)
    text, raw = client.rewrite_with_raw(
        "从节点1到节点6建立业务，需要连续使用9个频谱槽位。",
        {"intent_type": "SINGLE"},
        difficulty="MEDIUM",
    )
    assert text.startswith("从节点1到节点6")
    assert json.loads(raw)["rewritten_prompt"] == text
    assert observed["temperature"] == 0.5
    assert observed["top_p"] == 0.9
    assert observed["max_tokens"] == 321
    assert "MEDIUM" in observed["user"]


def test_openai_compatible_rewrite_can_disable_reasoning_for_json_rewrite(monkeypatch):
    client = OpenAICompatibleRewriteClient(
        base_url="https://example.invalid/v1",
        api_key_env="TEST_KEY",
        model="rewrite-model",
        enable_thinking=False,
    )
    observed = {}

    def fake_urlopen(request, timeout):
        observed.update(json.loads(request.data.decode("utf-8")))
        raise AssertionError("network must be mocked by the test harness")

    monkeypatch.setattr("src.i1.rewrite.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("TEST_KEY", "redacted-test-key")
    try:
        client._chat("system", "user", 0.0)
    except AssertionError:
        pass
    assert observed["enable_thinking"] is False


def test_openai_compatible_rewrite_records_formal_style_without_difficulty_label(monkeypatch):
    client = OpenAICompatibleRewriteClient(
        base_url="https://example.invalid/v1",
        api_key_env="TEST_KEY",
        model="rewrite-model",
    )
    observed = {}

    def fake_chat(system, user, temperature, *, top_p=None, max_tokens=None):
        observed["user"] = user
        return '{"rewritten_prompt":"从节点0到节点4建立业务，需要连续使用5个频谱槽位。"}'

    monkeypatch.setattr(client, "_chat", fake_chat)
    client.rewrite_with_raw(
        "从节点0到节点4建立业务，需要连续使用5个频谱槽位。",
        {"intent_type": "SINGLE"},
        rewrite_style="NATURAL",
    )

    assert "表达风格：NATURAL" in observed["user"]
    assert "难度等级" not in observed["user"]


def test_pilot_chat_payload_can_disable_reasoning_without_logging_the_key(monkeypatch):
    import scripts.i1_second_round_pilot as pilot

    observed = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"{}"}}],"usage":{}}'

    def fake_urlopen(request, timeout):
        observed.update(json.loads(request.data.decode("utf-8")))
        assert "redacted-test-key" not in request.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr(pilot.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "redacted-test-key")
    result = pilot.api_chat(
        base_url="https://example.invalid/v1",
        model="dut-model",
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "case"}],
        temperature=0.0,
        top_p=1.0,
        max_tokens=128,
        timeout_seconds=1.0,
        enable_thinking=False,
    )
    assert result["api_success"] is True
    assert observed["enable_thinking"] is False
