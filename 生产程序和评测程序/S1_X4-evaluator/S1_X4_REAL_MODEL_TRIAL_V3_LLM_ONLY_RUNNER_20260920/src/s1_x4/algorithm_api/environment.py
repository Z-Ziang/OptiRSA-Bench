from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from statistics import fmean
import time
from collections.abc import Callable, Mapping
from typing import Any

from src.s1_x4.algorithm_api.compiler import compile_static_context
from src.s1_x4.algorithm_api.types import AlgorithmObservation, AlgorithmStaticContext
from src.s1_x4.public_projection import project_current_step
from src.s1_x4.state_machine import DynamicEpisodeState
from src.s1_x4.validators import validate_s1_response, validate_x4_response


@dataclass(frozen=True)
class AlgorithmStepResult:
    validation: dict[str, Any]
    trajectory_record: dict[str, Any]
    next_observation: AlgorithmObservation | None
    done: bool
    timing: dict[str, int]


class AlgorithmEpisodeEnvironment:
    """Thin public Algorithm adapter around the single S1/X4 state machine."""

    def __init__(self, episode: Mapping[str, Any], *, timer: Callable[[], int] = time.perf_counter_ns):
        self._episode = deepcopy(dict(episode))
        self._static_context = compile_static_context(self._episode)
        self._timer = timer
        self._state: DynamicEpisodeState | None = None
        self._current_context: dict[str, Any] | None = None
        self._current_observation: AlgorithmObservation | None = None
        self._last_reset_observation_build_time = 0

    @property
    def static_context(self) -> AlgorithmStaticContext:
        return self._static_context

    @property
    def done(self) -> bool:
        return self._state is not None and self._state.finished

    @property
    def last_reset_observation_build_time(self) -> int:
        return self._last_reset_observation_build_time

    def reset(self) -> AlgorithmObservation:
        self._state = DynamicEpisodeState(deepcopy(self._episode))
        context = self._state.prepare_current_step()
        started = self._timer()
        observation = project_current_step(context)
        finished = self._timer()
        self._last_reset_observation_build_time = finished - started
        self._current_context = context
        self._current_observation = observation
        return observation

    def step(self, decision: Mapping[str, Any] | str) -> AlgorithmStepResult:
        if self._state is None or self._current_context is None or self._current_observation is None:
            raise RuntimeError("reset() must be called before step()")
        if self.done:
            raise RuntimeError("episode finished")
        environment_started = self._timer()
        validation_started = self._timer()
        validation = self._validate(decision, self._current_context)
        validation_finished = self._timer()
        commit_started = self._timer()
        record = self._state.commit_step(validation)
        commit_finished = self._timer()

        next_observation: AlgorithmObservation | None = None
        observation_build_time = 0
        if not self._state.finished:
            next_context = self._state.prepare_current_step()
            observation_started = self._timer()
            next_observation = project_current_step(next_context)
            observation_build_time = self._timer() - observation_started
            self._current_context = next_context
            self._current_observation = next_observation
        else:
            self._current_context = None
            self._current_observation = None
        environment_finished = self._timer()
        return AlgorithmStepResult(
            validation=validation,
            trajectory_record=record,
            next_observation=next_observation,
            done=self._state.finished,
            timing={
                "validation_time": validation_finished - validation_started,
                "state_commit_time": commit_finished - commit_started,
                "observation_build_time": observation_build_time,
                "environment_time": environment_finished - environment_started,
            },
        )

    def _validate(self, decision: Mapping[str, Any] | str, context: dict[str, Any]) -> dict[str, Any]:
        if isinstance(decision, str):
            try:
                decision = json.loads(decision)
            except Exception as exc:
                return {"valid": False, "decision": None, "error": f"invalid JSON: {exc}"}
        task = self._episode["task_type"]
        return (
            validate_s1_response(decision, context)
            if task == "S1"
            else validate_x4_response(decision, context)
        )

    def summary(self) -> dict[str, Any]:
        if self._state is None or not self._state.finished:
            raise RuntimeError("episode not finished")
        trajectory = self._state.trajectory
        h = len(trajectory)
        blocked = sum(bool(row["blocked"]) for row in trajectory)
        values = [
            row["post_decision_network_efm"]
            for row in trajectory
            if row["post_decision_network_efm"] is not None
        ]
        return {
            "case_id": self._episode["case_id"],
            "task_type": self._episode["task_type"],
            "step_count": h,
            "established_count": h - blocked,
            "blocked_count": blocked,
            "submitted_reject_count": sum(row.get("decision") == "REJECT" for row in trajectory),
            "invalid_allocation_count": sum(
                row.get("decision") == "ACCEPT" and row.get("validation_error") is not None
                for row in trajectory
            ),
            "format_error_count": sum(row.get("decision") is None for row in trajectory),
            "rbr": blocked / h if h else None,
            "network_efm_defined_step_count": len(values),
            "network_efm_series": [row["post_decision_network_efm"] for row in trajectory],
            "mean_network_efm": fmean(values) if values else None,
            "final_network_efm": trajectory[-1]["post_decision_network_efm"] if trajectory else None,
        }
