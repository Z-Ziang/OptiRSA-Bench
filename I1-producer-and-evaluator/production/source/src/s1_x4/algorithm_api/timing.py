from __future__ import annotations

from typing import Any


def build_timing(
    *,
    load_time: int,
    compile_time: int,
    observation_build_time: int,
    per_step_solve_time: list[int],
    validation_time: int,
    state_commit_time: int,
    environment_time: int,
    end_to_end_time: int,
) -> dict[str, Any]:
    solve_times = [int(value) for value in per_step_solve_time]
    return {
        "unit": "ns",
        "load_time": int(load_time),
        "compile_time": int(compile_time),
        "observation_build_time": int(observation_build_time),
        "per_step_solve_time": solve_times,
        "total_solve_time": sum(solve_times),
        "validation_time": int(validation_time),
        "state_commit_time": int(state_commit_time),
        "environment_time": int(environment_time),
        "end_to_end_time": int(end_to_end_time),
    }
