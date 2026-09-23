from __future__ import annotations

from typing import Any, Mapping, Sequence

from trial_evaluation.config import BudgetGuard
from trial_evaluation.providers.base import ModelProvider, ProviderResponse


def _account_response(budget: BudgetGuard, response: ProviderResponse) -> None:
    budget.account(
        api_calls=1 + int(response.retry_count),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def call_model(
    provider: ModelProvider,
    budget: BudgetGuard,
    messages: Sequence[Mapping[str, Any]],
) -> ProviderResponse:
    budget.before_request()
    response = provider.complete(messages)
    _account_response(budget, response)
    return response


def run_llm_step(
    *,
    provider: ModelProvider,
    budget: BudgetGuard,
    system_prompt: str,
    step_prompt: str,
) -> dict[str, Any]:
    response = call_model(
        provider,
        budget,
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": step_prompt}],
    )
    output = response.text or ""
    return {
        "submission": output,
        "raw_model_output": output,
        "provider_responses": [response.to_dict()],
        "api_usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cached_tokens": response.usage.cached_tokens,
            "api_requests": 1 + int(response.retry_count),
        },
        "latency_ms": response.latency_ms,
        "retry_count": response.retry_count,
    }
