from __future__ import annotations

import json

from tests.test_trial_evaluation_runner import _trial_dataset


class ProviderSequence:
    def __init__(self, responses):
        from trial_evaluation.providers.base import ModelConfig

        self.responses = list(responses)
        self.calls = 0
        self.config = ModelConfig(
            provider="fake",
            model="fake-v2",
            base_url="offline://fake",
            api_key_env="UNUSED",
            max_output_tokens=256,
        )

    def complete(self, messages):
        from trial_evaluation.providers.base import ProviderResponse

        self.calls += 1
        response = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(response, BaseException):
            raise response
        return response


def _response(text, *, finish_reason="stop"):
    from trial_evaluation.providers.base import ProviderResponse, Usage

    return ProviderResponse(
        requested_model="fake-v2",
        response_model="fake-v2",
        text=text,
                usage=Usage(input_tokens=2, output_tokens=2),
        latency_ms=1.0,
        provider_request_id=None,
        retry_count=0,
        finish_reason=finish_reason,
    )


def test_balance_failure_does_not_commit_or_enter_rbr(tmp_path):
    from trial_evaluation.providers.base import ProviderError
    from trial_evaluation.v2.runner import run_v2_unit
    from trial_evaluation.episodes import load_episode_bundle

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    provider = ProviderSequence([ProviderError("balance", status_code=402)])

    result = run_v2_unit(bundle, provider, tmp_path / "output", max_steps=1)

    assert result["status"] == "BALANCE_STOP"
    assert result["summary"]["committed_steps"] == 0
    assert result["summary"]["scientific_rbr"] is None
    assert result["summary"]["infra_failure_attempts"] == 1
    assert not list((tmp_path / "output" / "CHECKPOINTS").rglob("steps.jsonl"))


def test_protocol_failure_does_not_commit_or_advance_session(tmp_path):
    from trial_evaluation.v2.runner import run_v2_unit
    from trial_evaluation.episodes import load_episode_bundle

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    provider = ProviderSequence([_response("explanation only")])

    result = run_v2_unit(bundle, provider, tmp_path / "output", max_steps=1)

    assert result["status"] == "PROTOCOL_STOP"
    assert result["summary"]["committed_steps"] == 0
    assert result["summary"]["protocol_failure_attempts"] == 1
    attempts = list((tmp_path / "output" / "ATTEMPTS").rglob("attempts.jsonl"))
    assert len(attempts) == 1
    assert json.loads(attempts[0].read_text(encoding="utf-8").splitlines()[0])["step_status"] == "NOT_COMMITTED"


def test_valid_reject_is_committed_and_counted_as_model_failure(tmp_path):
    from trial_evaluation.v2.runner import run_v2_unit
    from trial_evaluation.episodes import load_episode_bundle

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    provider = ProviderSequence([_response('{"decision":"REJECT","path_rank":null,"slot_start":null}')])

    result = run_v2_unit(bundle, provider, tmp_path / "output", max_steps=1)

    assert result["status"] == "PREFIX_COMPLETE"
    assert result["summary"]["committed_steps"] == 1
    assert result["summary"]["blocked_count"] == 1
    assert result["summary"]["scientific_rbr"] == 1.0
    assert result["summary"]["model_failure_counts"]["MODEL_REJECT"] == 1


def test_semantic_infeasible_accept_is_committed_but_classified_as_model_failure(tmp_path):
    from trial_evaluation.v2.runner import run_v2_unit
    from trial_evaluation.episodes import load_episode_bundle

    dataset = _trial_dataset(tmp_path, "S1", length=1)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    provider = ProviderSequence([_response('{"decision":"ACCEPT","path_rank":999,"slot_start":999}')])

    result = run_v2_unit(bundle, provider, tmp_path / "output", max_steps=1)

    assert result["summary"]["committed_steps"] == 1
    assert result["summary"]["model_failure_counts"]["MODEL_INFEASIBLE_ACCEPT"] == 1
    assert result["summary"]["blocked_count"] == 1


def test_resume_after_protocol_stop_replays_no_step_and_commits_same_step(tmp_path):
    from trial_evaluation.v2.runner import run_v2_unit
    from trial_evaluation.episodes import load_episode_bundle

    dataset = _trial_dataset(tmp_path, "S1", length=2)
    bundle = load_episode_bundle(dataset, task="S1", modality="llm", topology_id="top_demo", condition_id="A_MEDIUM_MATCH")
    output = tmp_path / "output"
    first = run_v2_unit(bundle, ProviderSequence([_response("not-json")]), output, max_steps=1)
    second_provider = ProviderSequence([_response('{"decision":"REJECT","path_rank":null,"slot_start":null}')])
    second = run_v2_unit(bundle, second_provider, output, max_steps=1, resume=True)

    assert first["status"] == "PROTOCOL_STOP"
    assert second["status"] == "PREFIX_COMPLETE"
    assert second["summary"]["committed_steps"] == 1
    assert second["summary"]["protocol_failure_attempts"] == 1
    assert second_provider.calls == 1
