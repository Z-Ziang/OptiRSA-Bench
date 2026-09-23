from __future__ import annotations

from typing import Any, Callable, Mapping

from trial_evaluation.providers.base import ModelConfig
from trial_evaluation.providers.openai_compatible import OpenAICompatibleProvider, Transport


def create_siliconflow_provider(
    raw_config: Mapping[str, Any],
    *,
    transport: Transport | None = None,
    sleep: Callable[[float], None] | None = None,
) -> OpenAICompatibleProvider:
    config = ModelConfig.from_mapping(raw_config)
    if config.provider != "siliconflow":
        raise ValueError("SiliconFlow factory requires provider=siliconflow")
    kwargs: dict[str, Any] = {"transport": transport}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return OpenAICompatibleProvider(config, **kwargs)
