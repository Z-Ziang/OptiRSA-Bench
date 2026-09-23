from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
import time
from typing import Any

from .environment import AlgorithmEpisodeEnvironment
from .loader import load_episode
from .resolver import resolve_algorithm_launcher
from .timing import build_timing


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _solve(algorithm: Any, static_context: Any, observation: Any) -> Any:
    solver = getattr(algorithm, "solve", None)
    if solver is None:
        if not callable(algorithm):
            raise TypeError("algorithm must be callable or expose solve(static_context, observation)")
        solver = algorithm
    return solver(static_context, observation)


def _write_output(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "static_context.json", result["static_context"])
    _write_json(output_dir / "episode_metrics.json", result["summary"])
    _write_json(output_dir / "timing.json", result["timing"])
    _write_json(
        output_dir / "validation_summary.json",
        {
            "case_id": result["summary"]["case_id"],
            "task_type": result["summary"]["task_type"],
            "step_count": result["summary"]["step_count"],
            "completed": True,
        },
    )
    (output_dir / "trajectory.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in result["trajectory"]),
        encoding="utf-8",
    )
    (output_dir / "algorithm_observation_audit.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in result["algorithm_observation_audit"]
        ),
        encoding="utf-8",
    )
    files = sorted(path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha(path)}  {path.relative_to(output_dir).as_posix()}\n" for path in files),
        encoding="utf-8",
    )


def run_algorithm_episode(
    episode_or_path: Mapping[str, Any] | Path | str,
    algorithm: Any,
    *,
    output_dir: Path | str | None = None,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    """Evaluator-internal direct canonical Episode runner.

    Formal DUT execution must call :func:`run_algorithm_evaluation`, which
    resolves a public launcher through the evaluator-private registry first.
    """
    end_to_end_started = timer()
    load_time = 0
    if isinstance(episode_or_path, (str, Path)):
        load_started = timer()
        episode = load_episode(episode_or_path)
        load_time = timer() - load_started
    elif isinstance(episode_or_path, Mapping):
        episode = dict(episode_or_path)
    else:
        raise TypeError("episode_or_path must be a Mapping or a JSON path")

    compile_started = timer()
    environment = AlgorithmEpisodeEnvironment(episode, timer=timer)
    compile_time = timer() - compile_started
    observation = environment.reset()
    observation_build_time = environment.last_reset_observation_build_time
    static_context = environment.static_context
    observations = []
    trajectory = []
    solve_times: list[int] = []
    validation_time = 0
    state_commit_time = 0
    environment_time = 0

    while not environment.done:
        observations.append(observation.to_public_dict())
        solve_started = timer()
        decision = _solve(algorithm, static_context, observation)
        solve_time = timer() - solve_started
        solve_times.append(solve_time)
        step_result = environment.step(decision)
        trajectory.append(step_result.trajectory_record)
        validation_time += step_result.timing["validation_time"]
        state_commit_time += step_result.timing["state_commit_time"]
        observation_build_time += step_result.timing["observation_build_time"]
        environment_time += step_result.timing["environment_time"]
        observation = step_result.next_observation

    summary = environment.summary()
    timing = build_timing(
        load_time=load_time,
        compile_time=compile_time,
        observation_build_time=observation_build_time,
        per_step_solve_time=solve_times,
        validation_time=validation_time,
        state_commit_time=state_commit_time,
        environment_time=environment_time,
        end_to_end_time=timer() - end_to_end_started,
    )
    result = {
        "static_context": static_context.to_public_dict(),
        "summary": summary,
        "trajectory": trajectory,
        "timing": timing,
        "algorithm_observation_audit": observations,
    }
    if output_dir is not None:
        _write_output(Path(output_dir).resolve(), result)
    return result


def run_algorithm_benchmark(
    run_config_or_generation_spec: Path | str | Mapping[str, Any],
    algorithm: Any,
    *,
    task_type: str | None = None,
    dataset_root: Path | str | None = None,
    output_dir: Path | str | None = None,
    timer: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    """Run the formal Algorithm benchmark from a harness run config.

    The run config and materialized Episode are resolved by the harness. Only
    the existing static context and current compiled observation cross the
    callback boundary; the callback never receives the resolver or Episode.
    """

    from .run_config import resolve_run_config, run_config_for_spec

    if isinstance(run_config_or_generation_spec, Mapping) and "generation_spec_id" in run_config_or_generation_spec:
        if dataset_root is None:
            raise ValueError("dataset_root is required for a generation-spec mapping")
        spec = dict(run_config_or_generation_spec)
        if task_type is None:
            raise ValueError("task_type is required for a generation-spec mapping")
        harness_input: Mapping[str, Any] = run_config_for_spec(spec, task_type=task_type)
    else:
        harness_input = run_config_or_generation_spec
    resolved = resolve_run_config(harness_input, dataset_root=dataset_root, task_type=task_type)
    result = run_algorithm_episode(
        resolved.episode,
        algorithm,
        output_dir=output_dir,
        timer=timer,
    )
    result["algorithm_interface"] = "RUN_CONFIG_ENVIRONMENT"
    result["run_config"] = {
        "task_type": resolved.config["task_type"],
        "topology_id": resolved.config["topology_id"],
        "condition_id": resolved.config["condition_id"],
        "generation_spec_id": resolved.generation_spec["generation_spec_id"],
    }
    return result


def run_algorithm_evaluation(
    launcher_path: Path | str,
    evaluator_dataset_root: Path | str,
    algorithm: Any,
    *,
    output_dir: Path | str | None = None,
    timer: Callable[[], int] = time.perf_counter_ns,
    expected_task: str | None = None,
) -> dict[str, Any]:
    """Run one formal Algorithm evaluation from a public V1.1 launcher.

    The resolver is the only component that handles the evaluator-private
    canonical root. The Algorithm callback receives only the public static
    context and current observation through the existing episode loop.
    """

    resolved = resolve_algorithm_launcher(
        launcher_path,
        evaluator_dataset_root,
        expected_task=expected_task,
    )
    result = run_algorithm_episode(
        resolved.episode,
        algorithm,
        output_dir=output_dir,
        timer=timer,
    )
    result["public_launcher"] = {
        "schema_version": "S1_X4_ALGORITHM_EVALUATION_CASE_V1_1",
        "case_id": resolved.case_id,
        "task_type": resolved.task_type,
        "opaque_case_handle": resolved.opaque_case_handle,
    }
    return result
