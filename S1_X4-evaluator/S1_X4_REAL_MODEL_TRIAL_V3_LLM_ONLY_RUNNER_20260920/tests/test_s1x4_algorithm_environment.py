from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _episode(tmp_path: Path, task: str = "S1") -> dict:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=3))
    return build_episode_definition(
        idx,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3 if task == "S1" else None,
        pairing_id="pair_environment",
    )


def test_algorithm_environment_module_is_present() -> None:
    assert importlib.util.find_spec("src.s1_x4.algorithm_api.environment") is not None


def test_s1_environment_reuses_state_machine_and_exposes_only_current_observation(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.environment import AlgorithmEpisodeEnvironment
    from src.s1_x4.state_machine import DynamicEpisodeState
    from src.s1_x4.validators import validate_s1_response

    episode = _episode(tmp_path, "S1")
    env = AlgorithmEpisodeEnvironment(episode)
    assert not hasattr(env, "episode")
    assert not hasattr(env, "state")

    observation = env.reset()
    direct = DynamicEpisodeState(episode)
    direct_records = []
    while not env.done:
        assert observation.request["request_id"] == direct.prepare_current_step()["request"]["request_id"]
        assert observation.request["request_id"] not in {
            event["request_id"] for event in episode["request_events"][observation.step_index :]
        }
        if observation.feasible_actions.size:
            row = observation.feasible_actions[0]
            response = {"decision": "ACCEPT", "path_rank": int(row[0]), "slot_start": int(row[1])}
        else:
            response = {"decision": "REJECT", "path_rank": None, "slot_start": None}
        direct_ctx = direct.prepare_current_step()
        direct_validation = validate_s1_response(response, direct_ctx)
        direct_records.append(direct.commit_step(direct_validation))
        result = env.step(response)
        assert result.trajectory_record == direct_records[-1]
        observation = result.next_observation

    assert env.summary() == {
        "case_id": episode["case_id"],
        "task_type": "S1",
        "step_count": 3,
        "established_count": sum(bool(x["established"]) for x in direct_records),
        "blocked_count": sum(bool(x["blocked"]) for x in direct_records),
        "submitted_reject_count": sum(x["decision"] == "REJECT" for x in direct_records),
        "invalid_allocation_count": sum(
            x["decision"] == "ACCEPT" and x["validation_error"] is not None for x in direct_records
        ),
        "format_error_count": sum(x["decision"] is None for x in direct_records),
        "rbr": sum(bool(x["blocked"]) for x in direct_records) / 3,
        "network_efm_defined_step_count": sum(
            x["post_decision_network_efm"] is not None for x in direct_records
        ),
        "network_efm_series": [x["post_decision_network_efm"] for x in direct_records],
        "mean_network_efm": env.summary()["mean_network_efm"],
        "final_network_efm": direct_records[-1]["post_decision_network_efm"],
    }


def test_x4_environment_has_no_candidate_oracle(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.environment import AlgorithmEpisodeEnvironment

    env = AlgorithmEpisodeEnvironment(_episode(tmp_path, "X4"))
    observation = env.reset()
    public = observation.to_public_dict()
    assert "candidate_paths" not in public
    assert "feasible_actions" not in public


def test_environment_can_reset_to_a_fresh_episode(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.environment import AlgorithmEpisodeEnvironment

    env = AlgorithmEpisodeEnvironment(_episode(tmp_path, "S1"))
    first = env.reset()
    assert first.step_index == 1
    observation = first
    while not env.done:
        if observation.feasible_actions.size:
            row = observation.feasible_actions[0]
            response = {"decision": "ACCEPT", "path_rank": int(row[0]), "slot_start": int(row[1])}
        else:
            response = {"decision": "REJECT", "path_rank": None, "slot_start": None}
        result = env.step(response)
        if result.next_observation is None:
            break
        observation = result.next_observation
    second = env.reset()
    assert second.step_index == 1
    assert second.request["request_id"] == first.request["request_id"]
