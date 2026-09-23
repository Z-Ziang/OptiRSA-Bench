from __future__ import annotations

import json
import http.client
import os
import time
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trial_evaluation.providers.base import (
    ModelConfig,
    ModelProvider,
    ProviderError,
    ProviderResponse,
    TransportProviderError,
    Usage,
)


@dataclass(frozen=True)
class HTTPResponse:
    status_code: int
    payload: dict[str, Any]
    headers: Mapping[str, str]


Transport = Callable[[str, dict[str, Any], dict[str, str], float], HTTPResponse]


def _redact_message(value: object) -> str:
    text = str(value)
    if "Bearer " in text:
        text = text.split("Bearer ", 1)[0] + "Bearer [REDACTED]"
    return text[:500]


def _default_transport(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: float) -> HTTPResponse:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - URL is an explicit model config
            body = response.read()
            parsed = json.loads(body.decode("utf-8"))
            return HTTPResponse(int(response.status), parsed, dict(response.headers.items()))
    except HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = {"error": {"message": body.decode("utf-8", errors="replace")[:500]}}
        return HTTPResponse(int(exc.code), parsed, dict(exc.headers.items()))
    except (TimeoutError, ConnectionError, URLError, OSError, http.client.HTTPException) as exc:
        raise TransportProviderError(f"transport error: {_redact_message(exc)}") from exc


def _error_message(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping):
        return _redact_message(error.get("message", error))
    return _redact_message(error or payload)


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, 60.0))


def _content_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts) or None
    return str(content)


def _parse_response(config: ModelConfig, response: HTTPResponse, *, latency_ms: float, retry_count: int) -> ProviderResponse:
    if not isinstance(response.payload, Mapping):
        raise ProviderError("provider response payload must be an object")
    choices = response.payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderError("provider response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ProviderError("provider response choice has no message")
    usage_raw = response.payload.get("usage")
    if not isinstance(usage_raw, Mapping):
        usage_raw = {}
    details = usage_raw.get("prompt_tokens_details") or usage_raw.get("input_tokens_details") or {}
    completion_details = usage_raw.get("completion_tokens_details") or usage_raw.get("output_tokens_details") or {}
    cached = usage_raw.get("cached_tokens")
    if cached is None and isinstance(details, Mapping):
        cached = details.get("cached_tokens")
    return ProviderResponse(
        requested_model=config.model,
        response_model=(str(response.payload["model"]) if response.payload.get("model") is not None else None),
        text=_content_text(message.get("content")),
        usage=Usage(
            input_tokens=(int(usage_raw["prompt_tokens"]) if usage_raw.get("prompt_tokens") is not None else (int(usage_raw["input_tokens"]) if usage_raw.get("input_tokens") is not None else None)),
            output_tokens=(int(usage_raw["completion_tokens"]) if usage_raw.get("completion_tokens") is not None else (int(usage_raw["output_tokens"]) if usage_raw.get("output_tokens") is not None else None)),
            cached_tokens=(int(cached) if cached is not None else None),
            reasoning_tokens=(
                int(usage_raw["reasoning_tokens"])
                if usage_raw.get("reasoning_tokens") is not None
                else (int(completion_details["reasoning_tokens"]) if isinstance(completion_details, Mapping) and completion_details.get("reasoning_tokens") is not None else None)
            ),
        ),
        latency_ms=float(latency_ms),
        provider_request_id=(str(response.payload["id"]) if response.payload.get("id") is not None else None),
        retry_count=int(retry_count),
        finish_reason=(str(choices[0]["finish_reason"]) if choices[0].get("finish_reason") is not None else None),
    )


class OpenAICompatibleProvider(ModelProvider):
    """LLM Chat Completions adapter with bounded transport retries."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport = transport or _default_transport
        self._sleep = sleep

    def _payload(self, messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [dict(message) for message in messages],
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_output_tokens,
        }
        if self.config.response_format is not None:
            payload["response_format"] = dict(self.config.response_format)
        if self.config.reasoning_effort is not None:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if self.config.enable_thinking is not None:
            payload["enable_thinking"] = self.config.enable_thinking
        if self.config.thinking_budget is not None:
            payload["thinking_budget"] = self.config.thinking_budget
        return payload

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> ProviderResponse:
        key = os.environ.get(self.config.api_key_env)
        if not key:
            raise ProviderError(f"missing API key environment variable: {self.config.api_key_env}")
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload = self._payload(messages)
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        retry_count = 0
        while True:
            started = perf_counter()
            try:
                response = self._transport(url, payload, headers, self.config.timeout_seconds)
            except ProviderError as exc:
                exc.retry_count = retry_count
                if not exc.retryable or retry_count >= self.config.max_transport_retries:
                    raise
                delay = exc.retry_after_seconds if exc.retry_after_seconds is not None else min(2.0**retry_count, 30.0)
            else:
                if 200 <= int(response.status_code) < 300:
                    return _parse_response(
                        self.config,
                        response,
                        latency_ms=(perf_counter() - started) * 1000.0,
                        retry_count=retry_count,
                    )
                status = int(response.status_code)
                retryable = status == 429 or 500 <= status <= 599
                if not retryable or retry_count >= self.config.max_transport_retries:
                    raise ProviderError(
                        f"HTTP {status}: {_error_message(response.payload)}",
                        status_code=status,
                        retryable=retryable,
                        retry_after_seconds=_retry_after(response.headers),
                        retry_count=retry_count,
                    )
                delay = _retry_after(response.headers)
                if delay is None:
                    delay = min(2.0**retry_count, 30.0)
            self._sleep(max(0.0, float(delay)))
            retry_count += 1
