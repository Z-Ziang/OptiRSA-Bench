from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from gx1.production import produce_batch, verify_output_tree
from gx1.unified_schema import export_unified

from .canonical_km import (
    EXPECTED_TOPOLOGIES,
    audit_canonical_package,
    copy_canonical_package_assets,
    copy_lineage,
)
from .teacher_view import export_teacher_views


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _physical_dir(canonical_root: Path) -> Path:
    nested = Path(canonical_root) / "01_canonical_physical"
    return nested if nested.is_dir() else Path(canonical_root)


def build_stage2_config(canonical_root: Path, seed: int) -> dict[str, Any]:
    physical = _physical_dir(Path(canonical_root).resolve())
    topology_ids = [row["topology_id"] for row in EXPECTED_TOPOLOGIES]
    topology_paths = [str(physical / f"{topology_id}.json") for topology_id in topology_ids]

    g1_topology_schedule = [
        "topologybench_netrail",
        "topologybench_elibackbone",
        "topologybench_jpn48",
        "topologybench_conus75",
        "topohub_gabriel_125_0",
        "topohub_gabriel_175_2",
        "topohub_gabriel_250_3",
        "topohub_gabriel_375_3",
        "topohub_gabriel_450_9",
        "topologybench_netrail",
        "topologybench_elibackbone",
    ]
    g1_conversion_schedule = [
        "EDGE_LIST_TO_ADJACENCY_LIST",
        "EDGE_LIST_TO_ADJACENCY_MATRIX",
        "ADJACENCY_LIST_TO_EDGE_LIST",
        "ADJACENCY_LIST_TO_ADJACENCY_MATRIX",
        "EDGE_LIST_TO_ADJACENCY_LIST",
        "ADJACENCY_LIST_TO_EDGE_LIST",
        "EDGE_LIST_TO_ADJACENCY_LIST",
        "ADJACENCY_LIST_TO_EDGE_LIST",
        "EDGE_LIST_TO_ADJACENCY_LIST",
        "ADJACENCY_MATRIX_TO_EDGE_LIST",
        "ADJACENCY_MATRIX_TO_ADJACENCY_LIST",
    ]

    g2_topology_schedule = [
        "topologybench_netrail",
        "topologybench_elibackbone",
        "topologybench_jpn48",
        "topologybench_conus75",
        "topohub_gabriel_125_0",
        "topohub_gabriel_175_2",
        "topohub_gabriel_250_3",
        "topohub_gabriel_375_3",
        "topohub_gabriel_450_9",
        "topohub_gabriel_125_0",
        "topohub_gabriel_175_2",
    ]
    g2_label_schedule = [
        "VALID",
        "WRONG_DIRECTION",
        "DISCONNECTED_PATH",
        "NODE_LINK_MISMATCH",
        "REPEATED_NODE",
        "VALID",
        "WRONG_DIRECTION",
        "DISCONNECTED_PATH",
        "NODE_LINK_MISMATCH",
        "REPEATED_NODE",
        "VALID",
    ]

    g3_topology_schedule = [
        "topologybench_netrail",
        "topologybench_elibackbone",
        "topologybench_jpn48",
        "topologybench_conus75",
        "topohub_gabriel_125_0",
        "topohub_gabriel_175_2",
        "topohub_gabriel_250_3",
        "topohub_gabriel_375_3",
        "topohub_gabriel_450_9",
        "topologybench_jpn48",
        "topologybench_conus75",
    ]
    g3_metric_schedule = [
        "HOP_COUNT",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
    ]
    g3_shared_schedule = [True, False, True, False, True, False, True, False, True, False, False]

    x1_topology_schedule = [
        "topologybench_netrail",
        "topologybench_elibackbone",
        "topologybench_jpn48",
        "topologybench_conus75",
        "topohub_gabriel_125_0",
        "topohub_gabriel_175_2",
        "topohub_gabriel_250_3",
        "topohub_gabriel_375_3",
        "topohub_gabriel_450_9",
        "topohub_gabriel_250_3",
        "topohub_gabriel_375_3",
        "topohub_gabriel_450_9",
    ]
    x1_metric_schedule = [
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
        "HOP_COUNT",
        "TOTAL_LENGTH_KM",
    ]
    x1_multiplicity_schedule = [
        "UNIQUE",
        "UNIQUE",
        "MULTIPLE",
        "UNIQUE",
        "UNIQUE",
        "UNIQUE",
        "MULTIPLE",
        "UNIQUE",
        "MULTIPLE",
        "UNIQUE",
        "UNIQUE",
        "UNIQUE",
    ]

    return {
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_2",
        "batch_id": "GX1_TEACHER_DEMO_STAGE2_45CASES_CANONICAL_KM_20260913",
        "seed": int(seed),
        "topologies": topology_paths,
        "topology_ids": topology_ids,
        "case_counts": {"G1": 11, "G2": 11, "G3": 11, "X1": 12},
        "supplementary_cases": 9,
        "tasks": {
            "G1": {
                "topology_schedule": g1_topology_schedule,
                "conversion_schedule": g1_conversion_schedule,
                "max_sampling_attempts": 64,
            },
            "G2": {
                "topology_schedule": g2_topology_schedule,
                "label_schedule": g2_label_schedule,
                "hop_range_schedule": [[1, 20]] * 11,
                "max_sampling_attempts": 2048,
            },
            "G3": {
                "topology_schedule": g3_topology_schedule,
                "metric_schedule": g3_metric_schedule,
                "shared_schedule": g3_shared_schedule,
                "hop_range_schedule": [[1, 30]] * 11,
                "max_sampling_attempts": 2048,
            },
            "X1": {
                "topology_schedule": x1_topology_schedule,
                "metric_schedule": x1_metric_schedule,
                "multiplicity_schedule": x1_multiplicity_schedule,
                "hop_range_schedule": [[1, 30]] * 12,
                "max_sampling_attempts": 4096,
            },
        },
    }


def _save_public_config(output: Path, config: dict[str, Any]) -> None:
    normalized = copy.deepcopy(config)
    normalized["topologies"] = [f"../canonical_topologies/01_canonical_physical/{Path(path).name}" for path in config["topologies"]]
    _write_json(output / "audit" / "production_config.json", normalized)


def _copy_internal_evidence(legacy_root: Path, dataset_root: Path) -> int:
    count = 0
    (dataset_root / "audit").mkdir(parents=True, exist_ok=True)
    for case_dir in sorted((legacy_root / "cases").glob("*/*")):
        if not case_dir.is_dir():
            continue
        relative = case_dir.relative_to(legacy_root / "cases")
        destination = dataset_root / "internal_evidence" / relative
        destination.mkdir(parents=True, exist_ok=True)
        for source in sorted(case_dir.iterdir()):
            if source.is_file():
                shutil.copyfile(source, destination / source.name)
        if (destination / "root_case.json").exists():
            count += 1
    shutil.copyfile(legacy_root / "manifest.json", dataset_root / "audit" / "legacy_manifest.json")
    return count


def _write_lineage_and_commands(output: Path, canonical_root: Path, config: dict[str, Any], package_audit: dict[str, Any]) -> None:
    _write_json(
        output / "audit" / "seed_and_lineage.json",
        {
            "seed": config["seed"],
            "batch_id": config["batch_id"],
            "producer_mode": "EXISTING_UNIFIED_PRODUCER_WRAPPED_BY_STAGE2_ORCHESTRATOR",
            "canonical_input_mode": "DIRECT_SUPPLIED_CANONICAL_PHYSICAL_JSON",
            "canonical_package_root": str(Path(canonical_root).resolve()),
            "canonical_package_acceptance": {
                "pass": package_audit["pass"],
                "second_scaling_performed": False,
                "source_mode": package_audit["source_mode"],
            },
        },
    )
    commands = "\n".join([
        "# GX1 Teacher Demo Stage 2 Canonical-km reproduction",
        "# All commands are local; no model API is called.",
        "python -m stage2.run_stage2 --canonical-root <CANONICAL_PACKAGE_OR_PHYSICAL_DIR> --output <DATASET_DIR> --seed 20260913",
        "python -m gx1.cli --verify-unified <DATASET_DIR>",
        "python -m pytest -q --basetemp <WRITABLE_TEMP_DIR>",
        "",
    ])
    (output / "audit" / "reproduction_commands.md").write_text(commands, encoding="utf-8", newline="\n")


def _write_stage2_readme(output: Path) -> None:
    text = "\n".join([
        "# GX1 Teacher Demo Stage 2 — Canonical-km 45 Case",
        "",
        "本包是 G1/G2/G3/X1 Teacher Demo 的代表性展示数据集，不是正式 Benchmark 难度数据集。",
        "",
        "本次直接消费交接包提供的 9 张 `01_canonical_physical/*.json`；未建立第二套拓扑归一化流程，未进行二次缩放。",
        "Algorithm+LLM public schema：benchmark_case 严格三字段，evaluation_case 严格两字段。",
        "",
        "固定结构：G1=11、G2=11、G3=11、X1=12，共 45 Case；每张冻结拓扑恰好 5 Case。",
        "Teacher View 可以同时查看 LLM system prompt、公开 Case、Algorithm 输入说明和 reference；reference 仅用于公开参考与离线验证，不发送给 DUT。",
        "",
        "9 个规模区间表示拓扑规模覆盖，不等于 Easy/Medium/Hard 难度标签。正式难度配置由并行试评线决定。",
        "",
        "本轮没有调用任何模型 API。",
        "",
    ])
    (output / "README_FIRST.md").write_text(text, encoding="utf-8", newline="\n")


def _write_tree_sha256sums(output: Path) -> None:
    output = Path(output)
    lines: list[str] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        lines.append(f"{_sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run_stage2_production(canonical_root: Path, output_dir: Path, seed: int = 20260913) -> dict[str, Any]:
    canonical_root = Path(canonical_root).resolve()
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Stage 2 output must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    package_audit = audit_canonical_package(canonical_root)
    if not package_audit["pass"]:
        raise RuntimeError(f"canonical-km acceptance failed: {package_audit['errors']}")

    config = build_stage2_config(canonical_root, seed)
    runtime_config = output.parent / f"{output.name}_runtime_config.json"
    _write_json(runtime_config, config)
    legacy_root = output.parent / f"{output.name}_legacy_internal"
    if legacy_root.exists():
        raise ValueError(f"legacy output already exists: {legacy_root}")
    manifest = produce_batch(runtime_config, legacy_root)
    legacy_verification = verify_output_tree(legacy_root)
    if not legacy_verification.get("valid"):
        raise RuntimeError(f"legacy Producer verification failed: {legacy_verification}")
    public_verification = export_unified(legacy_root, output)
    if not public_verification.get("valid"):
        raise RuntimeError(f"Unified export verification failed: {public_verification}")

    _copy_internal_evidence(legacy_root, output)
    copy_canonical_package_assets(canonical_root, output / "canonical_topologies")
    copy_lineage(canonical_root, output / "topology_lineage")
    _save_public_config(output, config)
    _write_lineage_and_commands(output, canonical_root, config, package_audit)
    _write_json(output / "audit" / "canonical_topology_acceptance.json", package_audit)
    export_teacher_views(output, legacy_root, package_audit)
    _write_stage2_readme(output)

    from .audit import audit_stage2_dataset, write_audit_documents

    dataset_audit = audit_stage2_dataset(output, Path(__file__).resolve().parents[1], package_audit)
    write_audit_documents(output, package_audit, dataset_audit)
    _write_tree_sha256sums(output)
    return {
        "pass": bool(dataset_audit.get("pass")),
        "case_count": int(manifest.get("case_counts", {}).get("G1", 0))
        + int(manifest.get("case_counts", {}).get("G2", 0))
        + int(manifest.get("case_counts", {}).get("G3", 0))
        + int(manifest.get("case_counts", {}).get("X1", 0)),
        "task_counts": manifest.get("case_counts", {}),
        "dataset_audit": dataset_audit,
        "legacy_verification": legacy_verification,
        "public_verification": public_verification,
    }
