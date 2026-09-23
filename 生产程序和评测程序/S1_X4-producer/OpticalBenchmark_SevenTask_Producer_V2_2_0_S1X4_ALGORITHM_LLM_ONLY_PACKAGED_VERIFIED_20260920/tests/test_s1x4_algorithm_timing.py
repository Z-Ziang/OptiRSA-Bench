from __future__ import annotations

from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


class FakeTimer:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        self.value += 100
        return self.value


def _episode(tmp_path: Path) -> dict:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=2))
    return build_episode_definition(idx, "bs_dynamic_demo", "S1", "S1_case_000001", k=3, pairing_id="pair_timing")


def test_algorithm_runner_records_separate_solve_and_environment_timing(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.runner import run_algorithm_episode

    timer = FakeTimer()
    calls = []

    def algorithm(static, observation):
        calls.append((static, observation))
        if observation.feasible_actions.size:
            row = observation.feasible_actions[0]
            return {"decision": "ACCEPT", "path_rank": int(row[0]), "slot_start": int(row[1])}
        return {"decision": "REJECT", "path_rank": None, "slot_start": None}

    result = run_algorithm_episode(_episode(tmp_path), algorithm, timer=timer, output_dir=tmp_path / "run")
    timing = result["timing"]

    assert len(calls) == 2
    assert len(timing["per_step_solve_time"]) == 2
    assert timing["total_solve_time"] == sum(timing["per_step_solve_time"])
    assert timing["compile_time"] > 0
    assert timing["load_time"] == 0
    assert timing["validation_time"] > 0
    assert timing["state_commit_time"] > 0
    assert timing["environment_time"] > 0
    assert timing["end_to_end_time"] > timing["total_solve_time"]


def test_algorithm_runner_load_time_is_not_solve_time(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.runner import run_algorithm_episode

    episode = _episode(tmp_path)
    root = tmp_path / "root_case.json"
    root.write_text(__import__("json").dumps(episode), encoding="utf-8")

    def reject(_static, _observation):
        return {"decision": "REJECT", "path_rank": None, "slot_start": None}

    timing = run_algorithm_episode(root, reject, timer=FakeTimer())["timing"]
    assert timing["load_time"] > 0
    assert timing["total_solve_time"] == sum(timing["per_step_solve_time"])
