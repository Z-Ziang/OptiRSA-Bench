from __future__ import annotations

from collections import Counter
from statistics import fmean, median
from typing import Any, Iterable, Mapping


def build_v2_summary(records: Iterable[Mapping[str, Any]], attempts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    committed = [dict(row) for row in records if row.get("step_status") == "COMMITTED"]
    attempt_rows = [dict(row) for row in attempts]
    trajectories = [row["trajectory_record"] for row in committed if isinstance(row.get("trajectory_record"), Mapping)]
    blocked = sum(bool(row.get("blocked")) for row in trajectories)
    efm = [row.get("post_decision_network_efm") for row in trajectories if row.get("post_decision_network_efm") is not None]
    model_codes = Counter(
        code
        for row in committed
        for code in ([row.get("scientific_status")] + list(row.get("model_failure_codes", [])))
        if isinstance(code, str) and code.startswith("MODEL_")
    )
    infra = sum(1 for row in attempt_rows if str(row.get("infrastructure_status", "OK")) != "OK")
    # Infrastructure/runner stops use protocol_status=NOT_RUN.  They must not
    # be double-counted as protocol failures.
    protocol = sum(
        1
        for row in attempt_rows
        if str(row.get("protocol_status", "OK")) not in {"OK", "NOT_RUN"}
    )
    committed_steps = len(committed)
    attempts_count = len(attempt_rows)
    def total_usage(key: str) -> int | None:
        values = [row.get("api_usage", {}).get(key) for row in attempt_rows if isinstance(row.get("api_usage"), Mapping)]
        numeric = [int(value) for value in values if value is not None]
        return sum(numeric) if numeric else None

    latencies = [float(row.get("latency_ms")) for row in attempt_rows if row.get("latency_ms") is not None]
    latencies.sort()
    def percentile(percent: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, max(0, int(round((percent / 100.0) * (len(latencies) - 1)))))
        return latencies[index]

    return {
        "committed_steps": committed_steps,
        "blocked_count": blocked,
        "established_count": committed_steps - blocked,
        "submitted_reject_count": sum(row.get("decision") == "REJECT" for row in trajectories),
        "invalid_allocation_count": sum(row.get("decision") == "ACCEPT" and row.get("validation_error") is not None for row in trajectories),
        "scientific_rbr": blocked / committed_steps if committed_steps else None,
        "rbr": blocked / committed_steps if committed_steps else None,
        "network_efm_defined_step_count": len(efm),
        "mean_network_efm": fmean(efm) if efm else None,
        "final_network_efm": trajectories[-1].get("post_decision_network_efm") if trajectories else None,
        "scientific_trajectory_step_count": len(trajectories),
        "infra_failure_attempts": infra,
        "protocol_failure_attempts": protocol,
        "all_attempts": attempts_count,
        "all_attempts_failure_rate": (infra + protocol) / attempts_count if attempts_count else 0.0,
        "model_failure_counts": dict(sorted(model_codes.items())),
        "api_usage": {
            "api_requests": total_usage("api_requests"),
            "input_tokens": total_usage("input_tokens"),
            "output_tokens": total_usage("output_tokens"),
            "cached_tokens": total_usage("cached_tokens"),
            "reasoning_tokens": total_usage("reasoning_tokens"),
            "transport_retries": sum(int(row.get("retry_count", 0)) for row in attempt_rows),
            "latency_mean_ms": fmean(latencies) if latencies else None,
            "latency_p50_ms": median(latencies) if latencies else None,
            "latency_p95_ms": percentile(95),
            "latency_total_ms": sum(latencies) if latencies else 0.0,
        },
    }
