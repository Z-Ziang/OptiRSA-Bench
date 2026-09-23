from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping


def load_unit_summaries(root: Path | str) -> list[dict[str, Any]]:
    base = Path(root)
    rows = []
    for path in sorted((base / "UNITS").glob("*/unit_summary.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))


def write_phase_reports(root: Path | str, *, report_dir: Path | str, report_title: str) -> dict[str, Any]:
    root_path = Path(root)
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    summaries = load_unit_summaries(root_path)
    model_rows = []
    api_rows = []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in summaries:
        summary = item.get("summary", {})
        model = item.get("model", {})
        model_name = model.get("requested_model")
        model_rows.append(
            {
                "model": model_name,
                "provider": model.get("provider"),
                "task_type": item.get("task_type"),
                "modality": item.get("modality"),
                "topology_id": item.get("topology_id"),
                "condition_id": item.get("condition_id"),
                "case_id": item.get("case_id"),
                "evaluation_scope": item.get("evaluation_scope"),
                "steps_completed": summary.get("step_count"),
                "established_count": summary.get("established_count"),
                "blocked_count": summary.get("blocked_count"),
                "rbr": summary.get("rbr"),
                "mean_network_efm": summary.get("mean_network_efm"),
                "final_network_efm": summary.get("final_network_efm"),
                "reject_count": summary.get("submitted_reject_count"),
                "format_error_count": summary.get("format_error_count"),
                "invalid_allocation_count": summary.get("invalid_allocation_count"),
                "status": item.get("status"),
            }
        )
        api = dict(item.get("api_usage", {}))
        api.update({"model": model_name, "task_type": item.get("task_type"), "modality": item.get("modality"), "case_id": item.get("case_id")})
        api_rows.append(api)
        groups[(str(model_name), str(item.get("task_type")), str(item.get("modality")))].append(model_rows[-1])

    _write_csv(
        report_path / "MODEL_CASE_RESULTS.csv",
        model_rows,
        [
            "model", "provider", "task_type", "modality", "topology_id", "condition_id", "case_id",
            "evaluation_scope", "steps_completed", "established_count", "blocked_count", "rbr",
            "mean_network_efm", "final_network_efm", "reject_count", "format_error_count",
            "invalid_allocation_count", "status",
        ],
    )
    _write_csv(report_path / "API_USAGE.csv", api_rows, ["model", "task_type", "modality", "case_id", "api_requests", "input_tokens", "output_tokens", "cached_tokens", "transport_retries", "latency_mean_ms", "latency_total_ms"])
    aggregate_rows = []
    for key, rows in sorted(groups.items()):
        numeric = lambda field: [float(row[field]) for row in rows if row.get(field) is not None]
        aggregate_rows.append(
            {
                "model": key[0],
                "task_type": key[1],
                "modality": key[2],
                "unit_count": len(rows),
                "steps_completed": sum(int(row.get("steps_completed") or 0) for row in rows),
                "established_count": sum(int(row.get("established_count") or 0) for row in rows),
                "blocked_count": sum(int(row.get("blocked_count") or 0) for row in rows),
                "rbr": (sum(int(row.get("blocked_count") or 0) for row in rows) / sum(int(row.get("steps_completed") or 0) for row in rows)) if sum(int(row.get("steps_completed") or 0) for row in rows) else None,
                "mean_network_efm": fmean(numeric("mean_network_efm")) if numeric("mean_network_efm") else None,
                "final_network_efm": fmean(numeric("final_network_efm")) if numeric("final_network_efm") else None,
            }
        )
    _write_csv(report_path / "AGGREGATE_RESULTS.csv", aggregate_rows, ["model", "task_type", "modality", "unit_count", "steps_completed", "established_count", "blocked_count", "rbr", "mean_network_efm", "final_network_efm"])
    return {"unit_count": len(summaries), "model_case_rows": len(model_rows), "aggregate_rows": len(aggregate_rows)}


def write_phase_markdown(path: Path | str, *, title: str, execution_status: str, scope: str, max_steps: int, summaries: list[Mapping[str, Any]]) -> None:
    lines = [
        f"# {title}",
        "",
        f"执行状态：`{execution_status}`",
        f"评测范围：`{scope}`，每个 Episode 最多 `{max_steps}` Steps。",
        "",
        "本报告只统计已经通过官方 DynamicEpisodeSession 提交的轨迹记录。Prefix 指标与 H=512 Reference 按相同步数描述性对照，不能解释为完整 Episode 成绩。",
        "",
        "| Task | Modality | Topology | Condition | Steps | RBR | Mean Network EFM | Format/Invalid | Status |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in summaries:
        metric = item.get("summary", {})
        invalid = int(metric.get("format_error_count") or 0) + int(metric.get("invalid_allocation_count") or 0)
        lines.append(
            f"| {item.get('task_type')} | {item.get('modality')} | {item.get('topology_id')} | {item.get('condition_id')} | {metric.get('step_count')} | {metric.get('rbr')} | {metric.get('mean_network_efm')} | {invalid} | {item.get('status')} |"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
