from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_episode(path: Path | str) -> dict[str, Any]:
    """Load one canonical root Episode for evaluator use."""

    source = Path(path)
    obj = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("canonical Episode must be a JSON object")
    required = {
        "case_id",
        "task_type",
        "topology_id",
        "nodes",
        "directed_links",
        "slot_count",
        "initial_link_spectrum_states",
        "initial_existing_connections",
        "episode_length",
        "request_events",
    }
    missing = sorted(required - set(obj))
    if missing:
        raise ValueError(f"canonical Episode missing fields: {missing}")
    return obj


def load_episode_from_launcher(
    launcher_path: Path | str,
    evaluator_dataset_root: Path | str,
    expected_task: str | None = None,
):
    """Evaluator-facing loader for a public opaque Algorithm launcher."""

    from .resolver import resolve_algorithm_launcher

    return resolve_algorithm_launcher(launcher_path, evaluator_dataset_root, expected_task=expected_task)
