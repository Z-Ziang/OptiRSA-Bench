"""Assemble the clean public five-task dataset from verified production units.

The assembler copies producer-emitted public artifacts only.  It never edits a
case payload, regenerates prompts, or creates an Algorithm input independently
of its benchmark master.  Per-task filenames are renumbered in canonical
topology order so the public tree remains compact while case IDs remain the
stable identity inside each JSON/NPZ artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import numpy as np


TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
PUBLIC_TASK_FILES = ("llm_system_prompt.txt",)
EXPECTED_BENCHMARK_KEYS = ("case_id", "instance", "llm_prompt", "reference")
EXPECTED_EVAL_KEYS = {"case_id", "prompt"}
NPZ_KEYS = {
    "format_version", "schema_version", "task_type", "case_id", "slot_count",
    "nodes", "link_ids", "edge_src", "edge_dst", "out_edges_offsets", "out_edges_values",
    "occupied_mask_words", "request_ids", "request_source_node_ids",
    "request_destination_node_ids", "request_required_slots",
    "fixed_path_node_offsets", "fixed_path_nodes", "fixed_path_link_offsets", "fixed_path_links",
    "candidate_request_offsets", "candidate_path_ranks", "candidate_path_node_offsets",
    "candidate_path_nodes", "candidate_path_link_offsets", "candidate_path_links",
}
FORBIDDEN_NPZ_TEXT = ("reference", "oracle", "truth", "calibration", "provenance", "difficulty")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _write_hashes(root: Path) -> list[dict[str, Any]]:
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    lines = [f"{_sha256(path)}  {path.relative_to(root).as_posix()}" for path in files]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [
        {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in files
    ]


def _copy_same(source: Path, destination: Path, expected: bytes | None = None) -> bytes:
    if not source.is_file():
        raise ValueError(f"missing producer artifact: {source}")
    data = source.read_bytes()
    if expected is not None and data != expected:
        raise ValueError(f"task-level public contract differs across topology units: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def _npz_text_payload(path: Path) -> str:
    chunks: list[str] = []
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != NPZ_KEYS or len(archive.files) != len(NPZ_KEYS):
            raise ValueError(f"NPZ key set mismatch: {path}")
        for name in archive.files:
            value = np.asarray(archive[name])
            if value.dtype.kind == "O":
                raise ValueError(f"NPZ object dtype is forbidden: {path}:{name}")
            if value.dtype.kind == "S":
                chunks.append(b" ".join(bytes(item) for item in value.tolist()).decode("utf-8"))
    return " ".join(chunks).lower()


def _load_topology_order(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path)
    rows = value.get("topologies")
    if not isinstance(rows, list) or len(rows) != 9:
        raise ValueError("topology selection manifest must contain exactly nine topologies")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("topology_id"), str):
            raise ValueError("topology selection manifest has an invalid row")
        topology_id = row["topology_id"]
        if topology_id in seen:
            raise ValueError(f"duplicate topology_id: {topology_id}")
        seen.add(topology_id)
        result.append(row)
    return result


def _index_rows(dataset: Path) -> list[dict[str, Any]]:
    path = dataset / "case_index.jsonl"
    if not path.is_file():
        raise ValueError(f"missing producer case index: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_readme(root: Path, case_count: int) -> None:
    text = f"""# O/X2/X3 representative small-batch dataset

本示例数据集包含五类静态光网络优化任务：O1、O2-S、O2-C、X2、X3。
当前批次使用 9 张 canonical topology，每类任务每张拓扑 1 条 Case，共 {case_count} 条 Case。

## 文件关系

`benchmark_case/<TASK>/cases/` 保存每条 Case 的 canonical master，包含：

- `case_id`
- `llm_prompt`
- `instance`
- `reference`

`evaluation_case/` 保存无答案评测输入：

- `algorithm/`：由 canonical `benchmark_case.instance` 确定性编译得到的 `.npz`；
- `llm/`：`{{"case_id", "prompt"}}` JSON；

Algorithm NPZ 使用 `numpy.load(path, allow_pickle=False)` 加载，不含 object dtype、pickle、reference、oracle 或 private truth。NPZ 内的 `schema_version` 是编译容器元数据；公开 JSON 的 `instance` 不重复保存该字段。

## Algorithm 加载

```python
from evaluation_case.algorithm_api.loader import load_compiled_algorithm_case
case = load_compiled_algorithm_case("evaluation_case/X2/algorithm/case_000001.npz")
answer = algorithm.solve(case)
```

NPZ 加载和对象构造应计入 `dataset_load_time_ms`；`solve_time_ms` 从 `CompiledAlgorithmCase` 构造完成后开始，不包含数据集编译和文件 I/O。

各任务目录中的 `llm_system_prompt.txt` 是对应任务的公共输入合同。LLM evaluation JSON 不包含 reference。

本批次用于代表性格式和接口展示，不表示 Easy、Medium、Hard、Challenge 四档难度已经冻结。
"""
    (root / "README.md").write_text(text, encoding="utf-8")


def assemble(production_root: Path, output_root: Path, topology_manifest: Path, report_path: Path) -> dict[str, Any]:
    production_root = production_root.resolve()
    output_root = output_root.resolve()
    topology_rows = _load_topology_order(topology_manifest.resolve())
    result_file = production_root / "FIVE_TASK_PRODUCTION_RESULT.json"
    if not result_file.is_file():
        raise ValueError(f"missing production result: {result_file}")
    result = _read_json(result_file)
    if result.get("status") != "PASS" or int(result.get("topology_count", 0)) != 9:
        raise ValueError("production result is not a PASS for nine topologies")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    case_records: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    task_file_bytes: dict[tuple[str, str], bytes] = {}
    api_source: Path | None = None
    for topology_ordinal, topology_row in enumerate(topology_rows, start=1):
        topology_id = str(topology_row["topology_id"])
        dataset = production_root / "datasets" / topology_id
        if not dataset.is_dir():
            raise ValueError(f"missing topology dataset: {dataset}")
        rows = _index_rows(dataset)
        by_task = {str(row.get("task_type")): row for row in rows}
        if set(by_task) != set(TASKS) or len(rows) != len(TASKS):
            raise ValueError(f"topology {topology_id} must contain exactly one Case for each task")
        for task in TASKS:
            row = by_task[task]
            case_id = str(row["case_id"])
            if case_id in seen_case_ids:
                raise ValueError(f"case_id is not globally unique: {case_id}")
            seen_case_ids.add(case_id)
            benchmark_source = dataset / row["benchmark_case_path"]
            llm_source = dataset / row["llm_evaluation_path"]
            algorithm_source = dataset / row["algorithm_evaluation_path"]
            benchmark = _read_json(benchmark_source)
            if tuple(benchmark) != EXPECTED_BENCHMARK_KEYS:
                raise ValueError(f"benchmark master field order mismatch: {benchmark_source}")
            if benchmark.get("case_id") != case_id:
                raise ValueError(f"benchmark case_id mismatch: {benchmark_source}")
            instance = benchmark.get("instance")
            if not isinstance(instance, dict) or "schema_version" in instance:
                raise ValueError(f"public instance must omit schema_version: {benchmark_source}")
            llm = _read_json(llm_source)
            if set(llm) != EXPECTED_EVAL_KEYS:
                raise ValueError(f"evaluation JSON must contain only case_id and prompt: {task}/{case_id}")
            if llm["case_id"] != case_id:
                raise ValueError(f"evaluation case_id mismatch: {task}/{case_id}")
            if llm["prompt"] != benchmark["llm_prompt"]:
                raise ValueError(f"evaluation prompt parity failure: {task}/{case_id}")
            if "reference" in llm:
                raise ValueError(f"evaluation reference leakage: {task}/{case_id}")
            payload = _npz_text_payload(algorithm_source)
            if any(token in payload for token in FORBIDDEN_NPZ_TEXT):
                raise ValueError(f"NPZ forbidden text payload: {task}/{case_id}")
            target_name = f"case_{topology_ordinal:06d}"
            benchmark_target = output_root / "benchmark_case" / task / "cases" / f"{target_name}.json"
            llm_target = output_root / "evaluation_case" / task / "llm" / f"{target_name}.json"
            algorithm_target = output_root / "evaluation_case" / task / "algorithm" / f"{target_name}.npz"
            _copy_same(benchmark_source, benchmark_target)
            _copy_same(llm_source, llm_target)
            _copy_same(algorithm_source, algorithm_target)
            for filename in PUBLIC_TASK_FILES:
                source = dataset / "benchmark_case" / task / filename
                key = (task, filename)
                expected = task_file_bytes.get(key)
                task_file_bytes[key] = _copy_same(source, output_root / "benchmark_case" / task / filename, expected)
            case_records.append({
                "public_ordinal": topology_ordinal,
                "task": task,
                "case_id": case_id,
                "topology_id": topology_id,
                "benchmark_case": benchmark_target.relative_to(output_root).as_posix(),
                "algorithm_npz": algorithm_target.relative_to(output_root).as_posix(),
                "llm_evaluation": llm_target.relative_to(output_root).as_posix(),
            })
        candidate_api = dataset / "algorithm_api"
        if api_source is None:
            api_source = candidate_api
        elif not candidate_api.is_dir():
            raise ValueError(f"missing Algorithm API in {dataset}")
    if api_source is None or not api_source.is_dir():
        raise ValueError("missing producer Algorithm API")
    shutil.copytree(api_source, output_root / "evaluation_case" / "algorithm_api", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _write_readme(output_root, len(case_records))
    file_records = _write_hashes(output_root)
    audit = {
        "status": "PASS",
        "dataset_root": str(output_root),
        "topology_count": len(topology_rows),
        "task_count": len(TASKS),
        "benchmark_case_count": len(case_records),
        "algorithm_npz_count": len(list((output_root / "evaluation_case").glob("*/algorithm/*.npz"))),
        "llm_evaluation_count": len(list((output_root / "evaluation_case").glob("*/llm/*.json"))),
        "case_records": case_records,
        "file_count": len(file_records),
        "files": file_records,
    }
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="assemble the clean nine-topology five-task Dataset")
    parser.add_argument("--production-root", required=True)
    parser.add_argument("--topology-manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    audit = assemble(Path(args.production_root), Path(args.output), Path(args.topology_manifest), Path(args.report))
    print(json.dumps({key: audit[key] for key in ("status", "topology_count", "benchmark_case_count", "algorithm_npz_count", "llm_evaluation_count")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
