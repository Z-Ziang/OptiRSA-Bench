from __future__ import annotations

import json

PRIVATE_TOKENS = (
    "private_truth", "reference_output", "optimal_wufr", "feasible_slot_starts",
    "feasible_action_count", "feasible_candidate_path_count", "joint_feasibility_status",
)


def assert_no_private_leak(public_obj: dict) -> None:
    text = json.dumps(public_obj, ensure_ascii=False, sort_keys=True)
    lowered = text.lower()
    for token in PRIVATE_TOKENS:
        if token.lower() in lowered:
            raise ValueError(f"private field leaked into public projection: {token}")
