from __future__ import annotations

from statistics import fmean
from typing import Any, Iterable, Mapping


def build_prefix_summary(trajectory: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize only records already accepted by the official dynamic session."""

    rows = [dict(row) for row in trajectory]
    efm_values = [row.get("post_decision_network_efm") for row in rows if row.get("post_decision_network_efm") is not None]
    blocked = sum(bool(row.get("blocked")) for row in rows)
    result: dict[str, Any] = {
        "step_count": len(rows),
        "established_count": len(rows) - blocked,
        "blocked_count": blocked,
        "submitted_reject_count": sum(row.get("decision") == "REJECT" for row in rows),
        "invalid_allocation_count": sum(
            row.get("decision") == "ACCEPT" and row.get("validation_error") is not None for row in rows
        ),
        "format_error_count": sum(row.get("decision") is None for row in rows),
        "rbr": blocked / len(rows) if rows else None,
        "network_efm_defined_step_count": len(efm_values),
        "network_efm_series": [row.get("post_decision_network_efm") for row in rows],
        "mean_network_efm": fmean(efm_values) if efm_values else None,
        "final_network_efm": rows[-1].get("post_decision_network_efm") if rows else None,
    }
    return result

