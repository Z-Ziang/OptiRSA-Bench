"""Public structured Algorithm input API for the five O/X2/X3 tasks."""

from .compiled_npz import NPZ_FORMAT_VERSION, NPZ_KEYS, write_compiled_algorithm_case
from .loader import compile_algorithm_input, load_algorithm_case, load_compiled_algorithm_case
from .types import CompiledAlgorithmCase, CompiledLink, CompiledPath, CompiledRequest

__all__ = [
    "CompiledAlgorithmCase",
    "CompiledLink",
    "CompiledPath",
    "CompiledRequest",
    "compile_algorithm_input",
    "load_algorithm_case",
    "load_compiled_algorithm_case",
    "write_compiled_algorithm_case",
    "NPZ_FORMAT_VERSION",
    "NPZ_KEYS",
]
