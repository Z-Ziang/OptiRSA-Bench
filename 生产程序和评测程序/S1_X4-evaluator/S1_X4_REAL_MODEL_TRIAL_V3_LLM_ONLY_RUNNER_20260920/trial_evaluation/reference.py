from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trial_evaluation.metrics import build_prefix_summary


def load_reference_prefix_summary(
    dataset_root: Path | str,
    *,
    task: str,
    topology_id: str,
    condition_id: str,
    step_count: int,
    policy_name: str = "KSP-FF",
) -> dict[str, Any] | None:
    path = (
        Path(dataset_root)
        / "reference"
        / task
        / topology_id
        / condition_id
        / "reference_trajectories"
        / f"{policy_name}.jsonl"
    )
    if not path.is_file():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = build_prefix_summary(rows[:step_count])
    summary["reference_scope"] = f"PREFIX_{step_count}"
    summary["reference_policy"] = policy_name
    return summary

