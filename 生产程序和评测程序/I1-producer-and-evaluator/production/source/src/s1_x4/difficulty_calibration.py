"""Reference-only difficulty diagnostics for S1/X4 dynamic datasets.

This module does not assign permanent Easy/Medium/Hard labels. It exposes the
observable dimensions needed to calibrate those labels empirically.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _spread(values: Iterable[float | None]) -> tuple[float | None, float | None, float | None]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None, None, None
    lo, hi = min(vals), max(vals)
    return lo, hi, hi - lo


def _saturation(rbr_values: list[float]) -> str:
    if rbr_values and max(rbr_values) == 0.0:
        return "ALL_ZERO_RBR"
    if rbr_values and min(rbr_values) == 1.0:
        return "ALL_ONE_RBR"
    if rbr_values and max(rbr_values) - min(rbr_values) > 0:
        return "RBR_DISCRIMINATIVE"
    return "UNIFORM_NONEXTREME_RBR"


def _prefix_metrics(trajectory: list[dict], h: int) -> tuple[float, float | None]:
    rows = trajectory[:h]
    blocked = sum(bool(x.get("blocked")) for x in rows)
    efm = [x.get("post_decision_network_efm") for x in rows if x.get("post_decision_network_efm") is not None]
    return blocked / h, (sum(float(v) for v in efm) / len(efm) if efm else None)


def build_difficulty_report(dataset_root: str | Path, *, prefixes: tuple[int, ...] = (32, 128, 512)) -> dict:
    root = Path(dataset_root).resolve()
    cases: list[dict] = []
    prefix_rows: list[dict] = []
    for root_path in sorted((root / "internal/cases").glob("*/*/root_case.json")):
        ep = _read_json(root_path)
        task = str(ep["task_type"])
        case_id = str(ep["case_id"])
        private = root / "internal/private" / task / case_id
        features = _read_json(private / "features.json")
        ref = _read_json(private / "reference_output.json")
        policies = list(ref.get("policy_results", []))
        rbr = [float(x["rbr"]) for x in policies if x.get("rbr") is not None]
        efm = [x.get("mean_network_efm") for x in policies]
        rlo, rhi, rspread = _spread(rbr)
        elo, ehi, espread = _spread(efm)
        d = dict(features.get("difficulty") or {})
        trajectory_files = sorted((private / "reference_trajectories").glob("*.jsonl"))
        trajectories = {p.stem: _read_jsonl(p) for p in trajectory_files}
        final_utilization = [tr[-1].get("post_decision_network_utilization") for tr in trajectories.values() if tr]
        fulo, fuhi, fuspread = _spread(final_utilization)
        zero_action_fractions = []
        for tr in trajectories.values():
            counts = [x.get("candidate_action_count") for x in tr if x.get("candidate_action_count") is not None]
            if counts:
                zero_action_fractions.append(sum(int(x) == 0 for x in counts) / len(counts))
        zalo, zahi, zaspread = _spread(zero_action_fractions)
        cases.append({
            "task_type": task,
            "case_id": case_id,
            "pairing_id": ep.get("pairing_id"),
            "topology_id": ep.get("topology_id"),
            "resource_state_id": ep.get("resource_state_id"),
            "initial_load_band": d.get("initial_load_band"),
            "state_arrival_rate_lambda": d.get("state_arrival_rate_lambda"),
            "dynamic_arrival_rate_lambda": d.get("dynamic_arrival_rate_lambda"),
            "lambda_ratio": d.get("lambda_ratio"),
            "episode_length": int(ep["episode_length"]),
            "episode_time_span": d.get("episode_time_span"),
            "normalized_horizon": d.get("normalized_horizon"),
            "initial_network_utilization": d.get("initial_network_utilization"),
            "initial_network_efm": d.get("initial_network_efm"),
            "node_count": d.get("node_count"),
            "directed_link_count": d.get("directed_link_count"),
            "k_value": d.get("k_value"),
            "initial_candidate_action_count": d.get("initial_candidate_action_count"),
            "llm_prompt_token_count": (features.get("initial_serialization_metrics") or {}).get("llm_prompt_token_count"),
            "reference_policy_count": len(policies),
            "reference_rbr_min": rlo,
            "reference_rbr_max": rhi,
            "reference_rbr_spread": rspread,
            "reference_mean_efm_min": elo,
            "reference_mean_efm_max": ehi,
            "reference_mean_efm_spread": espread,
            "reference_final_utilization_min": fulo,
            "reference_final_utilization_max": fuhi,
            "reference_final_utilization_spread": fuspread,
            "reference_zero_action_fraction_min": zalo,
            "reference_zero_action_fraction_max": zahi,
            "reference_zero_action_fraction_spread": zaspread,
            "saturation_flag": _saturation(rbr),
        })
        for h in sorted(set(int(x) for x in prefixes if int(x) > 0 and int(x) <= int(ep["episode_length"]))):
            prefix_rbr: list[float] = []
            prefix_efm: list[float | None] = []
            for trajectory in trajectories.values():
                rr, ee = _prefix_metrics(trajectory, h)
                prefix_rbr.append(rr)
                prefix_efm.append(ee)
            rlo2, rhi2, rspread2 = _spread(prefix_rbr)
            elo2, ehi2, espread2 = _spread(prefix_efm)
            prefix_rows.append({
                "task_type": task,
                "case_id": case_id,
                "pairing_id": ep.get("pairing_id"),
                "prefix_h": h,
                "reference_policy_count": len(trajectories),
                "reference_rbr_min": rlo2,
                "reference_rbr_max": rhi2,
                "reference_rbr_spread": rspread2,
                "reference_mean_efm_min": elo2,
                "reference_mean_efm_max": ehi2,
                "reference_mean_efm_spread": espread2,
                "saturation_flag": _saturation(prefix_rbr),
            })
    return {
        "schema_version": "S1X4_DIFFICULTY_CALIBRATION_V2_2_0",
        "dataset_root": str(root),
        "case_count": len(cases),
        "cases": cases,
        "prefixes": prefix_rows,
    }


def write_difficulty_report(dataset_root: str | Path, output_dir: str | Path, *, prefixes: tuple[int, ...] = (32, 128, 512)) -> dict:
    report = build_difficulty_report(dataset_root, prefixes=prefixes)
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "difficulty_calibration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for key, filename in (("cases", "difficulty_cases.csv"), ("prefixes", "difficulty_prefixes.csv")):
        rows = report[key]
        if not rows:
            (out / filename).write_text("", encoding="utf-8")
            continue
        fields = list(rows[0])
        with (out / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return report
