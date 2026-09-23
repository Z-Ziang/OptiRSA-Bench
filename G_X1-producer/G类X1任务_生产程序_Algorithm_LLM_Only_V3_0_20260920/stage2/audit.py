from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from gx1.unified_schema import assemble_unified_request, forbidden_field_hits, verify_unified_export
from gx1.validators import validate_dut_output

from .canonical_km import EXPECTED_BY_ID, EXPECTED_TOPOLOGIES, sha256_file


TASKS = ("G1", "G2", "G3", "X1")
FORBIDDEN_REQUEST_KEYS = {"answer", "truth", "oracle", "private_truth", "reference"}
G1_DIRECTIONS = {
    "EDGE_LIST_TO_ADJACENCY_LIST",
    "EDGE_LIST_TO_ADJACENCY_MATRIX",
    "ADJACENCY_LIST_TO_EDGE_LIST",
    "ADJACENCY_LIST_TO_ADJACENCY_MATRIX",
    "ADJACENCY_MATRIX_TO_EDGE_LIST",
    "ADJACENCY_MATRIX_TO_ADJACENCY_LIST",
}
G2_LABELS = ("VALID", "WRONG_DIRECTION", "DISCONNECTED_PATH", "NODE_LINK_MISMATCH", "REPEATED_NODE")
G3_COMBINATIONS = {
    ("HOP_COUNT", True),
    ("HOP_COUNT", False),
    ("TOTAL_LENGTH_KM", True),
    ("TOTAL_LENGTH_KM", False),
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _csv_write(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _configuration_summary(root: dict[str, Any]) -> str:
    task = root["task_type"]
    if task == "G1":
        return root.get("conversion", "")
    if task == "G2":
        return f"label={root.get('oracle_label')};candidate_hops={len(root.get('candidate_path', {}).get('path_link_ids', []))}"
    if task == "G3":
        answers = root.get("answer", {}).get("shortest_paths", [])
        hops = ",".join(str(item.get("hop_count")) for item in answers)
        return f"metric={root.get('path_cost_metric')};shared={root.get('answer', {}).get('has_shared_directed_link')};pair_hops={hops}"
    return f"metric={root.get('path_cost_metric')};multiplicity={'MULTIPLE' if int(root.get('shortest_path_multiplicity', 1)) > 1 else 'UNIQUE'};hops={root.get('answer', {}).get('hop_count')}"


def _path_hop_summary(root: dict[str, Any]) -> str:
    task = root["task_type"]
    if task == "G2":
        return str(len(root.get("candidate_path", {}).get("path_link_ids", [])))
    if task == "G3":
        return ",".join(str(item.get("hop_count")) for item in root.get("answer", {}).get("shortest_paths", []))
    if task == "X1":
        return str(root.get("answer", {}).get("hop_count", ""))
    return ""


def _x1_evidence_validation(root: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    if root["task_type"] != "X1" or int(root.get("shortest_path_multiplicity", 1)) <= 1:
        return True, []
    evidence = root.get("oracle_evidence")
    if not isinstance(evidence, dict):
        return False, [{"index": None, "valid": False, "reason": "missing oracle_evidence"}]
    rows: list[dict[str, Any]] = []
    paths = evidence.get("optimal_paths")
    if not isinstance(paths, list) or len(paths) < 2:
        return False, [{"index": None, "valid": False, "reason": "fewer than two optimal paths"}]
    for index, path in enumerate(paths[:2]):
        candidate: dict[str, Any] = {
            "path_node_ids": path.get("path_node_ids"),
            "path_link_ids": path.get("path_link_ids"),
            "hop_count": path.get("hop_count"),
        }
        if root["path_cost_metric"] == "TOTAL_LENGTH_KM":
            candidate["total_length_km"] = path.get("cost")
        validation = validate_dut_output(root, json.dumps(candidate, ensure_ascii=False))
        rows.append({"index": index, "valid": bool(validation.get("valid")), "validation": validation})
    distinct = {tuple(path.get("path_link_ids", [])) for path in paths[:2] if isinstance(path, dict)}
    return all(row["valid"] for row in rows) and len(distinct) >= 2, rows


def _validate_internal_cases(dataset_root: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for record in sorted(manifest.get("cases", []), key=lambda item: (item["task_type"], item["case_id"])):
        task = record["task_type"]
        case_id = record["case_id"]
        root_path = dataset_root / "internal_evidence" / task / case_id / "root_case.json"
        if not root_path.exists():
            errors.append(f"{task}/{case_id}: root_case missing")
            continue
        root = _read_json(root_path)
        validation = validate_dut_output(root, json.dumps(root.get("answer"), ensure_ascii=False))
        evidence_pass, evidence_rows = _x1_evidence_validation(root)
        passed = bool(validation.get("valid")) and evidence_pass
        if not passed:
            errors.append(f"{task}/{case_id}: canonical Validator failed: {validation}; evidence={evidence_rows}")
        rows.append({
            "task": task,
            "case_id": case_id,
            "topology_id": root.get("topology_id"),
            "root_validator": validation,
            "x1_evidence": evidence_rows,
            "pass": passed,
        })
    return rows, errors


def _request_key_hits(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if key_text in FORBIDDEN_REQUEST_KEYS:
                hits.append(child_path)
            hits.extend(_request_key_hits(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_request_key_hits(child, f"{path}[{index}]"))
    return hits


def _scan_public_requests(dataset_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    literal_forbidden_word_mentions: list[dict[str, Any]] = []
    for record in sorted(manifest.get("cases", []), key=lambda item: (item["task_type"], item["case_id"])):
        task = record["task_type"]
        case_id = record["case_id"]
        for track in ("llm",):
            request = assemble_unified_request(dataset_root, task, case_id)
            key_hits = _request_key_hits(request)
            recursive_hits = forbidden_field_hits(request)
            serialized = json.dumps(request, ensure_ascii=False).lower()
            value_hits = [token for token in ("\"answer\"", "\"truth\"", "\"oracle\"", "\"private_truth\"", "\"reference\"") if token in serialized]
            literal_hits = [token for token in FORBIDDEN_REQUEST_KEYS if token in serialized]
            frozen_contract_mentions = False
            unexpected_literal_hits = [] if frozen_contract_mentions else literal_hits
            if literal_hits:
                literal_forbidden_word_mentions.append({
                    "task": task,
                    "case_id": case_id,
                    "track": track,
                    "tokens": sorted(literal_hits),
                    "classification": "FROZEN_SYSTEM_PROMPT_CONTRACT_WORDING" if frozen_contract_mentions else "UNEXPECTED_LITERAL_TOKEN",
                })
            pass_flag = not key_hits and not recursive_hits and not value_hits and not unexpected_literal_hits
            checks.append({
                "task": task,
                "case_id": case_id,
                "track": track,
                "key_hits": key_hits,
                "recursive_key_hits": recursive_hits,
                "serialized_forbidden_key_tokens": value_hits,
                "literal_forbidden_word_hits": sorted(literal_hits),
                "unexpected_literal_word_hits": sorted(unexpected_literal_hits),
                "pass": pass_flag,
            })
    return {
        "forbidden_field_names": sorted(FORBIDDEN_REQUEST_KEYS),
        "checked_request_count": len(checks),
        "pass_count": sum(1 for check in checks if check["pass"]),
        "fail_count": sum(1 for check in checks if not check["pass"]),
        "pass": len(checks) == 45 and all(check["pass"] for check in checks),
        "structural_field_scan": {
            "pass": len(checks) == 45 and all(
                not check["key_hits"] and not check["recursive_key_hits"] and not check["serialized_forbidden_key_tokens"]
                for check in checks
            ),
            "checked_request_count": len(checks),
        },
        "literal_forbidden_word_mentions": literal_forbidden_word_mentions,
        "literal_scan": {
            "pass": not any(check["unexpected_literal_word_hits"] for check in checks),
            "frozen_contract_wording_exception_count": sum(
                1 for item in literal_forbidden_word_mentions if item["classification"] == "FROZEN_SYSTEM_PROMPT_CONTRACT_WORDING"
            ),
            "unexpected_literal_token_count": sum(len(check["unexpected_literal_word_hits"]) for check in checks),
        },
        "checks": checks,
    }


def _case_rows(dataset_root: Path, manifest: dict[str, Any], topology_audit: dict[str, Any], validator_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topo_by_id = {item["topology_id"]: item for item in topology_audit.get("topologies", [])}
    validator_by_id = {item["case_id"]: item for item in validator_rows}
    rows: list[dict[str, Any]] = []
    for record in sorted(manifest.get("cases", []), key=lambda item: (item["task_type"], item["case_id"])):
        task, case_id = record["task_type"], record["case_id"]
        root = _read_json(dataset_root / "internal_evidence" / task / case_id / "root_case.json")
        topo = topo_by_id.get(root.get("topology_id"), EXPECTED_BY_ID.get(root.get("topology_id"), {}))
        g3_metric = root.get("path_cost_metric") if task == "G3" else ""
        g3_shared = root.get("answer", {}).get("has_shared_directed_link") if task == "G3" else ""
        x1_metric = root.get("path_cost_metric") if task == "X1" else ""
        x1_multiplicity = ("MULTIPLE" if int(root.get("shortest_path_multiplicity", 1)) > 1 else "UNIQUE") if task == "X1" else ""
        rows.append({
            "case_id": case_id,
            "task": task,
            "topology_id": root.get("topology_id"),
            "display_name": topo.get("display_name", root.get("topology_id")),
            "source_family": topo.get("source_family", ""),
            "scale_bin": topo.get("scale_bin", ""),
            "node_count": topo.get("node_count", len(root.get("nodes", []))),
            "physical_link_count": topo.get("physical_link_count", len(root.get("undirected_edges", [])) if task == "G1" else len(root.get("directed_links", [])) // 2),
            "mean_length_km": topo.get("mean_length_km", ""),
            "km_eligible": topo.get("total_length_km_eligible", ""),
            "configuration_summary": _configuration_summary(root),
            "g1_conversion": root.get("conversion", "") if task == "G1" else "",
            "g2_label": root.get("oracle_label", "") if task == "G2" else "",
            "g3_metric": g3_metric,
            "g3_shared": g3_shared,
            "x1_metric": x1_metric,
            "x1_multiplicity": x1_multiplicity,
            "path_hops_summary": _path_hop_summary(root),
            "benchmark_case_path": record.get("benchmark_case", ""),
            "evaluation_llm_path": record.get("evaluation_llm_case", ""),
            "teacher_view_path": f"teacher_view/{task}/{case_id}_TEACHER_VIEW.md",
            "validator_pass": validator_by_id.get(case_id, {}).get("pass", False),
            "substitution_reason": root.get("generation_metadata", {}).get("substitution_reason", ""),
        })
    return rows


def _coverage(topology_audit: dict[str, Any], case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    task_counts = {task: sum(1 for row in case_rows if row["task"] == task) for task in TASKS}
    topology_counts = {topology_id: sum(1 for row in case_rows if row["topology_id"] == topology_id) for topology_id in sorted(EXPECTED_BY_ID)}
    mandatory_cells = {f"{topology_id}::{task}" for topology_id in EXPECTED_BY_ID for task in TASKS}
    actual_cells = {f"{row['topology_id']}::{row['task']}" for row in case_rows}

    g1_rows = [row for row in case_rows if row["task"] == "G1"]
    g1_small_directions = sorted({row["g1_conversion"] for row in g1_rows if int(row["node_count"]) <= 100})
    g1_large_matrix = [row["case_id"] for row in g1_rows if int(row["node_count"]) > 100 and "MATRIX" in row["g1_conversion"]]
    g2_counts = {label: sum(1 for row in case_rows if row["task"] == "G2" and row["g2_label"] == label) for label in G2_LABELS}
    g3_combos = {f"{row['g3_metric']}::{str(row['g3_shared']).lower()}" for row in case_rows if row["task"] == "G3"}
    g3_length_gabriel = [row["case_id"] for row in case_rows if row["task"] == "G3" and row["g3_metric"] == "TOTAL_LENGTH_KM" and row["source_family"] == "TopoHub_Gabriel_controlled"]
    g3_length_large = [row["case_id"] for row in case_rows if row["task"] == "G3" and row["g3_metric"] == "TOTAL_LENGTH_KM" and int(row["node_count"]) >= 250]
    x1_combos: dict[str, int] = {}
    for row in case_rows:
        if row["task"] == "X1":
            key = f"{row['x1_metric']}::{row['x1_multiplicity']}"
            x1_combos[key] = x1_combos.get(key, 0) + 1
    x1_multiple = [row["case_id"] for row in case_rows if row["task"] == "X1" and row["x1_multiplicity"] == "MULTIPLE"]
    x1_length_multiple = [row["case_id"] for row in case_rows if row["task"] == "X1" and row["x1_metric"] == "TOTAL_LENGTH_KM" and row["x1_multiplicity"] == "MULTIPLE"]
    if x1_length_multiple:
        length_multiple_status = "FOUND"
    else:
        length_multiple_status = "NO_GENUINE_TOTAL_LENGTH_KM_MULTIPLE_FOUND_IN_FROZEN_CANONICAL_9_TOPOLOGIES"

    expected_task_counts = {"G1": 11, "G2": 11, "G3": 11, "X1": 12}
    expected_g2_counts = {"VALID": 3, "WRONG_DIRECTION": 2, "DISCONNECTED_PATH": 2, "NODE_LINK_MISMATCH": 2, "REPEATED_NODE": 2}
    result = {
        "case_count": len(case_rows),
        "task_counts": task_counts,
        "expected_task_counts": expected_task_counts,
        "task_counts_pass": task_counts == expected_task_counts,
        "topology_case_counts": topology_counts,
        "each_topology_exactly_five": all(count == 5 for count in topology_counts.values()),
        "mandatory_topology_task_cells": {
            "expected_count": len(mandatory_cells),
            "actual_count": len(actual_cells),
            "missing": sorted(mandatory_cells - actual_cells),
            "extra": sorted(actual_cells - mandatory_cells),
            "pass": actual_cells == mandatory_cells,
        },
        "g1": {
            "small_topology_directions": g1_small_directions,
            "required_directions": sorted(G1_DIRECTIONS),
            "all_six_directions_present": set(g1_small_directions) == G1_DIRECTIONS,
            "large_topology_matrix_cases": g1_large_matrix,
            "large_topology_matrix_forbidden_pass": not g1_large_matrix,
        },
        "g2": {
            "label_counts": g2_counts,
            "expected_label_counts": expected_g2_counts,
            "five_label_coverage_pass": set(label for label, count in g2_counts.items() if count > 0) == set(G2_LABELS),
            "target_distribution_pass": g2_counts == expected_g2_counts,
        },
        "g3": {
            "metric_shared_combinations": sorted(g3_combos),
            "required_metric_shared_combinations": sorted(f"{metric}::{str(shared).lower()}" for metric, shared in G3_COMBINATIONS),
            "all_metric_shared_combinations_present": {f"{metric}::{str(shared).lower()}" for metric, shared in G3_COMBINATIONS}.issubset(g3_combos),
            "total_length_gabriel_case_count": len(g3_length_gabriel),
            "total_length_gabriel_case_ids": g3_length_gabriel,
            "total_length_n_ge_250_case_count": len(g3_length_large),
            "total_length_n_ge_250_case_ids": g3_length_large,
            "large_length_coverage_pass": len(g3_length_gabriel) >= 3 and len(g3_length_large) >= 2,
        },
        "x1": {
            "metric_multiplicity_counts": dict(sorted(x1_combos.items())),
            "genuine_multiple_case_count": len(x1_multiple),
            "genuine_multiple_case_ids": x1_multiple,
            "total_length_multiple_case_count": len(x1_length_multiple),
            "total_length_multiple_case_ids": x1_length_multiple,
            "total_length_multiple_status": length_multiple_status,
            "both_metrics_present": {row["x1_metric"] for row in case_rows if row["task"] == "X1"} == {"HOP_COUNT", "TOTAL_LENGTH_KM"},
            "unique_present": any(row["x1_multiplicity"] == "UNIQUE" for row in case_rows if row["task"] == "X1"),
            "multiple_present": bool(x1_multiple),
            "large_length_case_count": sum(1 for row in case_rows if row["task"] == "X1" and row["x1_metric"] == "TOTAL_LENGTH_KM" and int(row["node_count"]) >= 250),
            "large_length_coverage_pass": any(row["task"] == "X1" and row["x1_metric"] == "TOTAL_LENGTH_KM" and int(row["node_count"]) >= 250 for row in case_rows),
        },
    }
    result["pass"] = bool(
        result["case_count"] == 45
        and result["task_counts_pass"]
        and result["each_topology_exactly_five"]
        and result["mandatory_topology_task_cells"]["pass"]
        and result["g1"]["all_six_directions_present"]
        and result["g1"]["large_topology_matrix_forbidden_pass"]
        and result["g2"]["target_distribution_pass"]
        and result["g3"]["all_metric_shared_combinations_present"]
        and result["g3"]["large_length_coverage_pass"]
        and result["x1"]["both_metrics_present"]
        and result["x1"]["unique_present"]
        and result["x1"]["multiple_present"]
        and result["x1"]["large_length_coverage_pass"]
    )
    return result


def audit_stage2_dataset(dataset_root: Path, producer_root: Path, topology_audit: dict[str, Any]) -> dict[str, Any]:
    dataset_root = Path(dataset_root).resolve()
    errors: list[str] = []
    try:
        manifest = _read_json(dataset_root / "manifest.json")
    except Exception as exc:
        return {"pass": False, "errors": [f"manifest parse failed: {exc}"]}
    public_verification = verify_unified_export(dataset_root)
    if not public_verification.get("valid"):
        errors.extend(f"public unified: {error}" for error in public_verification.get("errors", []))
    validator_rows, validator_errors = _validate_internal_cases(dataset_root, manifest)
    errors.extend(validator_errors)
    case_rows = _case_rows(dataset_root, manifest, topology_audit, validator_rows)
    coverage = _coverage(topology_audit, case_rows)
    if not coverage["pass"]:
        errors.append("coverage audit failed")
    leak_scan = _scan_public_requests(dataset_root, manifest)
    if not leak_scan["pass"]:
        errors.append("public request leak scan failed")
    view_count = len(list((dataset_root / "teacher_view").rglob("*_TEACHER_VIEW.md")))
    if view_count != 45:
        errors.append(f"Teacher View count is {view_count}, expected 45")
    result = {
        "pass": not errors,
        "errors": errors,
        "producer_root": str(Path(producer_root).resolve()),
        "case_count": len(case_rows),
        "task_counts": coverage.get("task_counts", {}),
        "topology_case_counts": coverage.get("topology_case_counts", {}),
        "public_verification": public_verification,
        "validator": {
            "checked_count": len(validator_rows),
            "pass_count": sum(1 for row in validator_rows if row["pass"]),
            "fail_count": sum(1 for row in validator_rows if not row["pass"]),
            "pass": len(validator_rows) == 45 and all(row["pass"] for row in validator_rows),
            "cases": validator_rows,
        },
        "leak_scan": leak_scan,
        "teacher_view": {"count": view_count, "pass": view_count == 45},
        "coverage": coverage,
        "case_rows": case_rows,
    }
    result["pass"] = bool(result["pass"] and result["validator"]["pass"] and result["leak_scan"]["pass"] and result["teacher_view"]["pass"])
    return result


def _canonical_audit_markdown(topology_audit: dict[str, Any]) -> str:
    lines = [
        "# Canonical-km Topology Acceptance Audit",
        "",
        "本轮直接消费供应包中的 `01_canonical_physical/*.json`；未建立第二套归一化或公里缩放流程。",
        "",
        f"- CANONICAL_KM_TOPOLOGY_BASELINE_ACCEPTED：`{topology_audit.get('canonical_km_topology_baseline_accepted')}`",
        f"- canonical physical topology count：{topology_audit.get('actual_topology_count')}/9",
        f"- second scaling performed：`{topology_audit.get('second_scaling_performed')}`",
        f"- package SHA/CRC checks：`{topology_audit.get('zip_audits', {})}`",
        f"- package hash manifest：`{topology_audit.get('package_hash_manifest', {}).get('pass')}`",
        "",
        "| topology_id | nodes | links | connected | bridges | edge connectivity | mean km | min km | max km | km eligible | length method |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in topology_audit.get("topologies", []):
        lines.append(
            f"| {row.get('topology_id')} | {row.get('node_count')} | {row.get('physical_link_count')} | {row.get('connected')} | {row.get('bridge_count')} | {row.get('edge_connectivity')} | {row.get('mean_length_km')} | {row.get('min_length_km')} | {row.get('max_length_km')} | {row.get('total_length_km_eligible')} | {row.get('length_method')} |"
        )
    lines.extend([
        "",
        "Gabriel topology 的 raw `dist` 只作为 provenance/geometry proxy；canonical `length_km` 继承供应包已验证的 geometry-to-km preprocessing，本轮没有再次缩放或重算。",
        "",
    ])
    return "\n".join(lines)


def write_audit_documents(dataset_root: Path, topology_audit: dict[str, Any], dataset_audit: dict[str, Any]) -> None:
    dataset_root = Path(dataset_root)
    audit_dir = dataset_root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    _write_json(audit_dir / "COVERAGE_AUDIT.json", dataset_audit.get("coverage", {}))
    _write_json(dataset_root / "GX1_TEACHER_DEMO_STAGE2_COVERAGE_AUDIT.json", dataset_audit.get("coverage", {}))
    _write_json(audit_dir / "validation_summary.json", dataset_audit.get("validator", {}))
    _write_json(audit_dir / "leak_scan.json", dataset_audit.get("leak_scan", {}))
    _write_json(audit_dir / "dataset_audit.json", dataset_audit)
    _write_json(dataset_root / "00_CANONICAL_TOPOLOGY_ACCEPTANCE_AUDIT.json", topology_audit)
    (dataset_root / "00_CANONICAL_TOPOLOGY_ACCEPTANCE_AUDIT.md").write_text(_canonical_audit_markdown(topology_audit), encoding="utf-8", newline="\n")
    _csv_write(
        audit_dir / "CASE_INDEX.csv",
        [
            "case_id", "task", "topology_id", "display_name", "source_family", "scale_bin",
            "node_count", "physical_link_count", "mean_length_km", "km_eligible", "configuration_summary",
            "g1_conversion", "g2_label", "g3_metric", "g3_shared", "x1_metric", "x1_multiplicity",
            "path_hops_summary", "benchmark_case_path", "evaluation_llm_path",
            "teacher_view_path", "validator_pass", "substitution_reason",
        ],
        dataset_audit.get("case_rows", []),
    )
    topology_rows = []
    for row in topology_audit.get("topologies", []):
        topology_rows.append({
            "topology_id": row.get("topology_id"),
            "display_name": row.get("display_name"),
            "source_family": row.get("source_family"),
            "scale_bin": row.get("scale_bin"),
            "node_count": row.get("node_count"),
            "physical_link_count": row.get("physical_link_count"),
            "mean_length_km": row.get("mean_length_km"),
            "min_length_km": row.get("min_length_km"),
            "max_length_km": row.get("max_length_km"),
            "connected": row.get("connected"),
            "bridge_count": row.get("bridge_count"),
            "edge_connectivity": row.get("edge_connectivity"),
            "total_length_km_eligible": row.get("total_length_km_eligible"),
            "length_method": row.get("length_method"),
            "sha256": row.get("sha256"),
        })
    _csv_write(
        audit_dir / "TOPOLOGY_INDEX.csv",
        [
            "topology_id", "display_name", "source_family", "scale_bin", "node_count", "physical_link_count",
            "mean_length_km", "min_length_km", "max_length_km", "connected", "bridge_count", "edge_connectivity",
            "total_length_km_eligible", "length_method", "sha256",
        ],
        topology_rows,
    )
    coverage = dataset_audit.get("coverage", {})
    configuration_rows = [
        {"dimension": "total", "configuration": "case_count", "count": coverage.get("case_count"), "pass": coverage.get("case_count") == 45, "detail": "固定总数"},
        {"dimension": "task", "configuration": "G1/G2/G3/X1", "count": json.dumps(coverage.get("task_counts", {}), ensure_ascii=False), "pass": coverage.get("task_counts_pass"), "detail": "目标 11/11/11/12"},
        {"dimension": "topology", "configuration": "each topology exactly five", "count": json.dumps(coverage.get("topology_case_counts", {}), ensure_ascii=False), "pass": coverage.get("each_topology_exactly_five"), "detail": "9×5"},
        {"dimension": "G1", "configuration": "six directions on N<=100", "count": len(coverage.get("g1", {}).get("small_topology_directions", [])), "pass": coverage.get("g1", {}).get("all_six_directions_present"), "detail": json.dumps(coverage.get("g1", {}), ensure_ascii=False)},
        {"dimension": "G2", "configuration": "five labels", "count": json.dumps(coverage.get("g2", {}).get("label_counts", {}), ensure_ascii=False), "pass": coverage.get("g2", {}).get("target_distribution_pass"), "detail": "VALID=3; other labels=2"},
        {"dimension": "G3", "configuration": "metric×shared", "count": len(coverage.get("g3", {}).get("metric_shared_combinations", [])), "pass": coverage.get("g3", {}).get("all_metric_shared_combinations_present"), "detail": json.dumps(coverage.get("g3", {}), ensure_ascii=False)},
        {"dimension": "X1", "configuration": "metric×multiplicity", "count": json.dumps(coverage.get("x1", {}).get("metric_multiplicity_counts", {}), ensure_ascii=False), "pass": coverage.get("x1", {}).get("both_metrics_present") and coverage.get("x1", {}).get("unique_present") and coverage.get("x1", {}).get("multiple_present"), "detail": coverage.get("x1", {}).get("total_length_multiple_status")},
    ]
    _csv_write(audit_dir / "CONFIGURATION_COVERAGE.csv", ["dimension", "configuration", "count", "pass", "detail"], configuration_rows)
    matrix_rows = []
    for topology in sorted(EXPECTED_BY_ID):
        matrix_rows.append({"topology_id": topology, **{task: sum(1 for row in dataset_audit.get("case_rows", []) if row["topology_id"] == topology and row["task"] == task) for task in TASKS}, "total": sum(1 for row in dataset_audit.get("case_rows", []) if row["topology_id"] == topology)})
    _csv_write(audit_dir / "9_TOPOLOGY_4_TASK_MATRIX.csv", ["topology_id", *TASKS, "total"], matrix_rows)


def compare_deterministic_trees(first: Path, second: Path) -> dict[str, Any]:
    first = Path(first).resolve()
    second = Path(second).resolve()

    def hashes(root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)).replace("\\", "/"): sha256_file(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    a, b = hashes(first), hashes(second)
    paths = sorted(set(a) | set(b))
    different = [path for path in paths if a.get(path) != b.get(path)]
    return {
        "pass": not different and set(a) == set(b),
        "file_count_a": len(a),
        "file_count_b": len(b),
        "different_paths": different,
        "missing_in_a": sorted(set(b) - set(a)),
        "missing_in_b": sorted(set(a) - set(b)),
    }
