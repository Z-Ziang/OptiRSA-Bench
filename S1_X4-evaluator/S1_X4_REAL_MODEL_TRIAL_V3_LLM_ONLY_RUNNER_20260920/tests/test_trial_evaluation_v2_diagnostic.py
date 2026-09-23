from __future__ import annotations

from tests.test_trial_evaluation_runner import _trial_dataset


def test_protocol_diagnostic_runs_both_llm_task_units_with_fake_provider(tmp_path):
    from trial_evaluation.providers.base import ModelConfig, ProviderResponse, Usage
    from trial_evaluation.v2.diagnostic import run_protocol_diagnostic

    _trial_dataset(tmp_path, "S1", length=2)
    dataset = _trial_dataset(tmp_path, "X4", length=2)

    class FakeProvider:
        def __init__(self, config):
            self.task = config["task_type"]
            self.config = ModelConfig(provider="fake", model="fake-v2", base_url="offline://fake", api_key_env="UNUSED")

        def complete(self, messages):
            text = (
                '{"decision":"REJECT","path_rank":null,"slot_start":null}'
                if self.task == "S1"
                else '{"decision":"REJECT","path_node_ids":[],"path_link_ids":[],"slot_start":null}'
            )
            return ProviderResponse("fake-v2", "fake-v2", text, Usage(input_tokens=1, output_tokens=1), 0.1, None, 0, "stop")

    result = run_protocol_diagnostic(
        dataset,
        tmp_path / "diagnostic",
        profiles=("A",),
        max_steps=1,
        topology_id="top_demo",
        condition_id="A_MEDIUM_MATCH",
        provider_factory=FakeProvider,
    )

    assert result["status"] == "PASS"
    profile = result["profiles"][0]
    assert profile["summary"]["planned_units"] == 2
    assert profile["summary"]["committed_steps"] == 2
    assert profile["summary"]["protocol_failure_attempts"] == 0
    assert profile["summary"]["infra_failure_attempts"] == 0
