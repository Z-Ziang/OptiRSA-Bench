"""Official structured Algorithm interface for dynamic S1/X4 Episodes."""

from .compiler import compile_observation, compile_spectrum, compile_static_context
from .run_config import load_run_config, resolve_run_config
from .runner import run_algorithm_benchmark
from .types import (
    AlgorithmObservation,
    AlgorithmStaticContext,
    CandidatePath,
    CompiledSpectrum,
    CompiledTopology,
)

__all__ = [
    "AlgorithmObservation",
    "AlgorithmStaticContext",
    "CandidatePath",
    "CompiledSpectrum",
    "CompiledTopology",
    "compile_observation",
    "compile_spectrum",
    "compile_static_context",
    "load_run_config",
    "resolve_run_config",
    "run_algorithm_benchmark",
]
