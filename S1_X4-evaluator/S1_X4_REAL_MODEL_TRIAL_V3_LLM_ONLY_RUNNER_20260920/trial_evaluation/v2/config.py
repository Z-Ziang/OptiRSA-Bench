from __future__ import annotations

from typing import Any

from trial_evaluation.v2.action_schemas import action_schema


def build_profile(name: str, task: str) -> dict[str, Any]:
    upper = str(name).upper()
    if upper == "A":
        enable_thinking = False
        thinking_budget = None
    elif upper == "B":
        enable_thinking = True
        thinking_budget = 1024
    else:
        raise ValueError("profile must be A or B")
    return {
        "profile": upper,
        "provider": "siliconflow",
        "task_type": task,
        "model": "deepseek-ai/DeepSeek-V4-Flash",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "structured_output_mode": "JSON_SCHEMA",
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"{task.lower()}_action",
                "strict": True,
                "schema": action_schema(task),
            },
        },
        "enable_thinking": enable_thinking,
        "thinking_budget": thinking_budget,
        "reasoning_effort": None,
        "temperature": 0.0,
        "top_p": 1.0,
        # Keep the provider-facing name explicit in the resolved profile.  The
        # shared adapter consumes max_output_tokens, while max_tokens records
        # the exact Chat Completions request cap for auditability.
        "max_tokens": 512,
        "max_output_tokens": 512,
        "timeout_seconds": 60.0,
        "max_transport_retries": 5,
    }
