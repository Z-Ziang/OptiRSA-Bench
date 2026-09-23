from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    step_index: int
    step_status: str
    infrastructure_status: str
    protocol_status: str
    scientific_status: str | None
    code: str | None
    raw_model_output: str | None = None
    validation: dict[str, Any] | None = None
    trajectory_record: dict[str, Any] | None = None
    provider_responses: list[dict[str, Any]] = field(default_factory=list)
    api_usage: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    model_failure_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_status": self.step_status,
            "infrastructure_status": self.infrastructure_status,
            "protocol_status": self.protocol_status,
            "scientific_status": self.scientific_status,
            "code": self.code,
            "raw_model_output": self.raw_model_output,
            "validation": self.validation,
            "trajectory_record": self.trajectory_record,
            "provider_responses": self.provider_responses,
            "api_usage": self.api_usage,
            "errors": self.errors,
            "model_failure_codes": self.model_failure_codes,
        }
