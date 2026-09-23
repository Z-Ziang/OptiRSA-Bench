from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.s1_x4.algorithm_api.compiler import compile_observation, compile_static_context
from src.s1_x4.algorithm_api.types import AlgorithmObservation, AlgorithmStaticContext


def build_static_context(episode: Mapping[str, Any]) -> AlgorithmStaticContext:
    """Compile only the static public topology view of a canonical Episode."""

    return compile_static_context(episode)


def project_current_step(context: Mapping[str, Any]) -> AlgorithmObservation:
    """Project one prepared DynamicEpisodeState context into a public observation."""

    return compile_observation(context)
