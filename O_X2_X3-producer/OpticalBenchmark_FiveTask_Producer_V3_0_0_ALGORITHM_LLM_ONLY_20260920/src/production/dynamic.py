"""Dynamic production conditions coupled to calibrated resource-state load."""
from __future__ import annotations

from dataclasses import dataclass

from src.production.config import DynamicConfig, ResourceStateJob


@dataclass(frozen=True)
class DynamicCondition:
    anchor_job_id: str
    initial_load_band: str
    state_arrival_rate_lambda: float
    arrival_rate_mode: str
    arrival_rate_multiplier: float | None
    arrival_rate_lambda: float
    lambda_ratio: float


def resolve_dynamic_conditions(
    config: DynamicConfig,
    jobs_by_id: dict[str, ResourceStateJob],
    selected_state_lambdas: dict[str, float],
) -> list[DynamicCondition]:
    if not config.enabled:
        return []
    result: list[DynamicCondition] = []
    for anchor_job_id in config.anchor_job_ids:
        job = jobs_by_id[anchor_job_id]
        state_lambda = float(selected_state_lambdas[anchor_job_id])
        if state_lambda <= 0:
            raise ValueError(f"state calibrated lambda must be >0 for {anchor_job_id}")
        if config.arrival_rate_mode == "MATCH_STATE":
            requested = [(1.0, state_lambda)]
        elif config.arrival_rate_mode == "MULTIPLIER_OF_STATE":
            requested = [(float(m), state_lambda * float(m)) for m in config.arrival_rate_multipliers]
        elif config.arrival_rate_mode == "ABSOLUTE":
            assert config.arrival_rate_lambda is not None
            requested = [(None, float(config.arrival_rate_lambda))]
        else:
            raise ValueError(f"unsupported arrival_rate_mode: {config.arrival_rate_mode}")
        for multiplier, dynamic_lambda in requested:
            result.append(DynamicCondition(
                anchor_job_id=anchor_job_id,
                initial_load_band=job.load_band,
                state_arrival_rate_lambda=state_lambda,
                arrival_rate_mode=config.arrival_rate_mode,
                arrival_rate_multiplier=multiplier,
                arrival_rate_lambda=dynamic_lambda,
                lambda_ratio=dynamic_lambda / state_lambda,
            ))
    return result
