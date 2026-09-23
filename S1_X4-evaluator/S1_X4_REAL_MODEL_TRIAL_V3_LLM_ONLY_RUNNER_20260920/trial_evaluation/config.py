from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from trial_evaluation.providers.base import ModelConfig


class BudgetStop(RuntimeError):
    pass


class BudgetGuard:
    def __init__(
        self,
        *,
        max_api_calls: int | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_wall_time_minutes: float | None = None,
    ) -> None:
        self.max_api_calls = max_api_calls
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.max_wall_time_minutes = max_wall_time_minutes
        self._started = time.monotonic()
        self.api_requests = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def before_request(self) -> None:
        if self.max_api_calls is not None and self.api_requests >= self.max_api_calls:
            raise BudgetStop("max_api_calls")
        if self.max_wall_time_minutes is not None:
            elapsed_minutes = (time.monotonic() - self._started) / 60.0
            if elapsed_minutes >= self.max_wall_time_minutes:
                raise BudgetStop("max_wall_time_minutes")
        if self.max_input_tokens is not None and self.input_tokens >= self.max_input_tokens:
            raise BudgetStop("max_input_tokens")
        if self.max_output_tokens is not None and self.output_tokens >= self.max_output_tokens:
            raise BudgetStop("max_output_tokens")

    def account(self, *, api_calls: int = 1, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
        self.api_requests += int(api_calls)
        if input_tokens is not None:
            self.input_tokens += int(input_tokens)
        if output_tokens is not None:
            self.output_tokens += int(output_tokens)

    def snapshot(self) -> dict[str, Any]:
        return {
            "api_requests": self.api_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "max_api_calls": self.max_api_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_wall_time_minutes": self.max_wall_time_minutes,
            "elapsed_seconds": time.monotonic() - self._started,
        }


@dataclass(frozen=True)
class PhasePlan:
    name: str
    max_steps: int
    topologies: tuple[str, ...]
    conditions: tuple[str, ...]
    tasks: tuple[str, ...] = ("S1", "X4")
    modalities: tuple[str, ...] = ("llm",)

    def unit_count(self) -> int:
        return len(self.topologies) * len(self.conditions) * len(self.tasks) * len(self.modalities)


def build_phase_plan(phase: str) -> PhasePlan:
    if phase in {"smoke", "phase1", "phase_1"}:
        return PhasePlan("PHASE1_SMOKE", 8, ("topologybench_netrail",), ("A_MEDIUM_MATCH",))
    if phase in {"pilot", "phase2", "phase_2"}:
        return PhasePlan(
            "PHASE2_REPRESENTATIVE_PILOT",
            64,
            ("topologybench_netrail", "topologybench_conus75", "topohub_gabriel_450_9"),
            ("A_MEDIUM_MATCH", "B_HIGH_MATCH", "C_HIGH_X1P2"),
        )
    if phase in {"h512_representative", "phase3", "phase_3"}:
        return PhasePlan(
            "PHASE3_H512_REPRESENTATIVE",
            512,
            ("topologybench_netrail", "topologybench_conus75", "topohub_gabriel_450_9"),
            ("A_MEDIUM_MATCH", "B_HIGH_MATCH", "C_HIGH_X1P2"),
        )
    if phase in {"full", "phase4", "phase_4"}:
        return PhasePlan("PHASE4_FULL_MATRIX", 512, tuple(), tuple())
    raise ValueError(f"unknown trial phase: {phase}")


def load_model_catalog(path: Path | str) -> list[ModelConfig]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or not isinstance(raw.get("models"), list) or not raw["models"]:
        raise ValueError("model config must contain a non-empty models list")
    return [ModelConfig.from_mapping(item) for item in raw["models"]]
