from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from src.numeric import json_ready


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(json_ready(value), ensure_ascii=False, separators=(",", ":")) + "\n"
                            for value in values), encoding="utf-8")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(json_ready(rows))


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and values[order[end]] == values[order[position]]:
            end += 1
        average_rank = (position + end - 1) / 2 + 1
        for index in order[position:end]:
            ranks[index] = average_rank
        position = end
    return ranks


def correlation_matrix(rows: list[dict], fields: list[str], method: str) -> list[dict]:
    result = []
    for left in fields:
        item = {"metric": left}
        for right in fields:
            pairs = [(float(row[left]), float(row[right])) for row in rows
                     if row.get(left) is not None and row.get(right) is not None]
            if len(pairs) < 2:
                value = None
            else:
                x = [pair[0] for pair in pairs]
                y = [pair[1] for pair in pairs]
                if method.upper() == "SPEARMAN":
                    x, y = _rank(x), _rank(y)
                value = None if np.std(x) == 0 or np.std(y) == 0 else float(np.corrcoef(x, y)[0, 1])
            item[right] = value
        result.append(item)
    return result


def numeric_summary(rows: list[dict], fields: list[str]) -> list[dict]:
    result = []
    for field in fields:
        values = sorted(float(row[field]) for row in rows if row.get(field) is not None)
        if not values:
            result.append({"metric": field, "count": 0, "missing_count": len(rows)})
            continue
        q1 = float(np.percentile(values, 25, method="linear"))
        q3 = float(np.percentile(values, 75, method="linear"))
        result.append({"metric": field, "count": len(values), "missing_count": len(rows)-len(values),
                       "minimum": min(values), "maximum": max(values), "median": median(values),
                       "q1": q1, "q3": q3, "iqr": q3-q1})
    return result


def high_correlation_pairs(matrix: list[dict], fields: list[str], threshold: float) -> list[dict]:
    result = []
    by_metric = {row["metric"]: row for row in matrix}
    for i, left in enumerate(fields):
        for right in fields[i+1:]:
            value = by_metric[left].get(right)
            if value is not None and abs(value) >= threshold:
                result.append({"metric_a": left, "metric_b": right, "correlation": value})
    return result

