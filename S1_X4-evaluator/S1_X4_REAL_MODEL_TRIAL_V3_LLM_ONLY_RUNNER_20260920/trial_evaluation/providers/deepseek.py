from __future__ import annotations

from typing import Any, Callable, Mapping

from trial_evaluation.providers.base import ModelConfig
from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider, Transport


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def create_deepseek_provider(
    raw_config: Mapping[str, Any],
    *,
    transport: Transport | None = None,
    sleep: Callable[[float], None] | None = None,
) -> OpenAICompatibleProvider:
    config_data = dict(raw_config)
    config_data.setdefault("provider", "deepseek")
    config_data.setdefault("base_url", DEFAULT_DEEPSEEK_BASE_URL)
    config_data.setdefault("api_key_env", "DEEPSEEK_API_KEY")
    config = ModelConfig.from_mapping(config_data)
    if config.provider != "deepseek":
        raise ValueError(f"DeepSeek factory received provider={config.provider!r}")
    kwargs: dict[str, Any] = {"transport": transport}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return OpenAICompatibleProvider(config, **kwargs)

