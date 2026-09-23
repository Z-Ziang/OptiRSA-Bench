from __future__ import annotations

import json


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return 200

    def read(self):
        return json.dumps(
            {
                "id": "test-response",
                "choices": [
                    {
                        "message": {"content": "{\"intent_type\":\"SINGLE\"}"},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode("utf-8")


def test_i1_api_request_includes_json_mode_response_format_without_prompt_leakage(monkeypatch):
    import scripts.i1_second_round_pilot as runner

    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key-that-must-not-be-recorded")
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)

    result = runner.api_chat(
        base_url="https://api.example.test/v1",
        model="test/model",
        messages=[
            {"role": "system", "content": "只输出一个 JSON 对象。"},
            {"role": "user", "content": "case prompt"},
        ],
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
        timeout_seconds=10.0,
        enable_thinking=False,
        response_format={"type": "json_object"},
    )

    assert result["api_success"] is True
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][1]["content"] == "case prompt"
    assert "test-key-that-must-not-be-recorded" not in json.dumps(captured["body"])


def test_i1_api_request_omits_response_format_when_not_requested(monkeypatch):
    import scripts.i1_second_round_pilot as runner

    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)

    runner.api_chat(
        base_url="https://api.example.test/v1",
        model="test/model",
        messages=[{"role": "user", "content": "case prompt"}],
        temperature=0.0,
        top_p=1.0,
        max_tokens=512,
        timeout_seconds=10.0,
    )

    assert "response_format" not in captured["body"]
