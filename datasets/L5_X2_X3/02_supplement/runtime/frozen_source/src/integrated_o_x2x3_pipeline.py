from __future__ import annotations

from pathlib import Path

from src.five_task_orchestrator import (
    derive_five_task_dataset,
    produce_environment_and_five_tasks,
    verify_five_task_dataset,
)


def derive_integrated_dataset(environment_root: str | Path, o_config_path: str | Path, x_config_path: str | Path, output_root: str | Path) -> dict:
    """Compatibility wrapper for the process-isolated five-task derivation."""
    return derive_five_task_dataset(environment_root, o_config_path, x_config_path, output_root)


def verify_integrated_dataset(dataset_root: str | Path) -> dict:
    return verify_five_task_dataset(dataset_root)


def produce_environment_and_integrated(environment_config: str | Path, o_config_path: str | Path, x_config_path: str | Path, output_root: str | Path) -> dict:
    return produce_environment_and_five_tasks(environment_config, o_config_path, x_config_path, output_root)
