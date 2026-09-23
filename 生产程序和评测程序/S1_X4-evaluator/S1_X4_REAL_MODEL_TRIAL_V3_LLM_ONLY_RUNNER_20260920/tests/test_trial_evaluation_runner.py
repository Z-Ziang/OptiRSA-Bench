from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.s1x4_test_utils import minimal_dynamic_environment


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trial_dataset(tmp_path: Path, task: str, length: int = 3) -> Path:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path / "environment", length=length))
    episode = build_episode_definition(
        idx,
        "bs_dynamic_demo",
        task,
        f"{task}_top_demo_A_MEDIUM_MATCH",
        k=3 if task == "S1" else None,
        pairing_id="pair_demo",
    )
    root = tmp_path / "dataset"
    _write_json(root / "benchmark_case" / task / "episodes" / "top_demo" / "A_MEDIUM_MATCH.json", episode)
    (root / "evaluation_case" / task / "llm").mkdir(parents=True, exist_ok=True)
    (root / "evaluation_case" / task / "llm" / "system_prompt.txt").write_text(
        f"{task} LLM frozen system prompt\n", encoding="utf-8"
    )
    _write_json(
        root / "evaluation_case" / task / "llm" / "top_demo" / "A_MEDIUM_MATCH.json",
        {"case_id": episode["case_id"], "prompt": "current step only"},
    )
    return root


class _FakeProvider:
    def __init__(self, response_factory):
        from trial_evaluation.providers.base import ModelConfig

        self.response_factory = response_factory
        self.calls = []
        self.config = ModelConfig(
            provider="fake",
            model="fake-model",
            base_url="offline://fake",
            api_key_env="UNUSED_TEST_KEY",
        )

    def complete(self, messages):
        from trial_evaluation.providers.base import ProviderResponse, Usage

        self.calls.append({"messages": json.loads(json.dumps(messages))})
        return self.response_factory(len(self.calls), messages, ProviderResponse, Usage)


def _reject_response(_index, _messages, ProviderResponse, Usage):
    return ProviderResponse(
        requested_model="fake-model",
        response_model="fake-model",
        text='{"decision":"REJECT","path_rank":null,"slot_start":null}',
                usage=Usage(input_tokens=10, output_tokens=5),
        latency_ms=1.0,
        provider_request_id=None,
        retry_count=0,
    )


def test_llm_runner_uses_new_two_message_conversation_for_each_step_and_official_submission(tmp_path):
    from trial_evaluation.episodes import load_episode_bundle
    from trial_evaluation.runner import run_unit

    dataset = _trial_dataset(tmp_path, "S1", length=3)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    provider = _FakeProvider(_reject_response)

    result = run_unit(bundle, provider, tmp_path / "output", max_steps=3)

    assert result["status"] == "PASS"
    assert result["summary"]["step_count"] == 3
    assert result["summary"]["blocked_count"] == 3
    assert result["model"]["response_model"] == "fake-model"
    assert len(provider.calls) == 3
    assert all(len(call["messages"]) == 2 for call in provider.calls)
    assert all(call["messages"][0]["role"] == "system" for call in provider.calls)
    assert all(call["messages"][1]["role"] == "user" for call in provider.calls)
    assert all("reference" not in json.dumps(call).lower() for call in provider.calls)
    assert "dynreq_demo_000002" not in json.dumps(provider.calls[0])
    assert "dynreq_demo_000003" not in json.dumps(provider.calls[0])
    assert "dynreq_demo_000003" not in json.dumps(provider.calls[1])


def test_semantically_invalid_accept_is_submitted_once_and_not_retried(tmp_path):
    from trial_evaluation.episodes import load_episode_bundle
    from trial_evaluation.runner import run_unit

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")

    def invalid(_index, _messages, ProviderResponse, Usage):
        return ProviderResponse(
            requested_model="fake-model",
            response_model="fake-model",
            text='{"decision":"ACCEPT","path_rank":999,"slot_start":999}',
                        usage=Usage(input_tokens=10, output_tokens=4),
            latency_ms=1.0,
            provider_request_id=None,
            retry_count=0,
        )

    provider = _FakeProvider(invalid)
    result = run_unit(bundle, provider, tmp_path / "output", max_steps=2)

    assert result["status"] == "PASS"
    assert len(provider.calls) == 2
    assert result["summary"]["invalid_allocation_count"] == 2
    assert result["summary"]["blocked_count"] == 2


def test_resume_replays_completed_steps_without_calling_provider_again(tmp_path):
    from trial_evaluation.episodes import load_episode_bundle
    from trial_evaluation.runner import run_unit

    dataset = _trial_dataset(tmp_path, "S1", length=3)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    output = tmp_path / "output"
    first_provider = _FakeProvider(_reject_response)
    first = run_unit(bundle, first_provider, output, max_steps=1)
    second_provider = _FakeProvider(_reject_response)
    second = run_unit(bundle, second_provider, output, max_steps=3, resume=True)

    assert first["status"] == "PREFIX_COMPLETE"
    assert second["status"] == "PASS"
    assert len(first_provider.calls) == 1
    assert len(second_provider.calls) == 2
    assert second["summary"]["step_count"] == 3

