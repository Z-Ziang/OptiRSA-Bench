from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    temperature: float = 0.0
    top_p: float = 1.0
    max_output_tokens: int = 256
    timeout_seconds: float = 60.0
    max_transport_retries: int = 5
    response_format: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    structured_output_mode: str = "NONE"
    enable_thinking: bool | None = None
    thinking_budget: int | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ModelConfig":
        required = ("provider", "model", "base_url", "api_key_env")
        missing = [key for key in required if not isinstance(raw.get(key), str) or not raw[key]]
        if missing:
            raise ValueError(f"model config missing required fields: {missing}")
        config = cls(
            provider=str(raw["provider"]),
            model=str(raw["model"]),
            base_url=str(raw["base_url"]).rstrip("/"),
            api_key_env=str(raw["api_key_env"]),
            temperature=float(raw.get("temperature", 0.0)),
            top_p=float(raw.get("top_p", 1.0)),
            max_output_tokens=int(raw.get("max_output_tokens", raw.get("max_tokens", 256))),
            timeout_seconds=float(raw.get("timeout_seconds", 60.0)),
            max_transport_retries=int(raw.get("max_transport_retries", 5)),
            response_format=(dict(raw["response_format"]) if raw.get("response_format") is not None else None),
            reasoning_effort=(str(raw["reasoning_effort"]) if raw.get("reasoning_effort") is not None else None),
            structured_output_mode=str(raw.get("structured_output_mode", "NONE")),
            enable_thinking=(bool(raw["enable_thinking"]) if raw.get("enable_thinking") is not None else None),
            thinking_budget=(int(raw["thinking_budget"]) if raw.get("thinking_budget") is not None else None),
        )
        if config.temperature < 0 or config.top_p <= 0 or config.max_output_tokens <= 0:
            raise ValueError("temperature/top_p/max_output_tokens must be positive-or-zero valid values")
        if config.timeout_seconds <= 0 or config.max_transport_retries < 0:
            raise ValueError("timeout_seconds must be positive and max_transport_retries non-negative")
        if config.thinking_budget is not None and config.thinking_budget <= 0:
            raise ValueError("thinking_budget must be positive when provided")
        return config

    def to_public_dict(self) -> dict[str, Any]:
        """Return resolved request parameters without credentials."""

        return asdict(self)


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderResponse:
    requested_model: str
    response_model: str | None
    text: str | None
    usage: Usage
    latency_ms: float
    provider_request_id: str | None
    retry_count: int
    finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["usage"] = self.usage.to_dict()
        return data


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        retry_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.retry_count = int(retry_count)


class TransportProviderError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ModelProvider:
    """Small provider protocol implemented without coupling the evaluator to an SDK."""

    config: ModelConfig

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> ProviderResponse:
        raise NotImplementedError
