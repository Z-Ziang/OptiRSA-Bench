"""Independent verification for the clean compiled-Algorithm small batch."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
EXPECTED_BENCHMARK_KEYS = ("case_id", "instance", "llm_prompt", "reference")
NPZ_KEYS = {
    "format_version", "schema_version", "task_type", "case_id", "slot_count",
    "nodes", "link_ids", "edge_src", "edge_dst", "out_edges_offsets", "out_edges_values",
    "occupied_mask_words", "request_ids", "request_source_node_ids",
    "request_destination_node_ids", "request_required_slots",
    "fixed_path_node_offsets", "fixed_path_nodes", "fixed_path_link_offsets", "fixed_path_links",
    "candidate_request_offsets", "candidate_path_ranks", "candidate_path_node_offsets",
    "candidate_path_nodes", "candidate_path_link_offsets", "candidate_path_links",
}
FORBIDDEN_TEXT = ("reference", "oracle", "truth", "calibration", "provenance", "difficulty")
WINDOWS_INVALID = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _load_index(dataset: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (dataset / "case_index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _npz_text(path: Path) -> tuple[dict[str, np.ndarray], str]:
    chunks: list[str] = []
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
    if set(arrays) != NPZ_KEYS or len(arrays) != len(NPZ_KEYS):
        raise ValueError(f"NPZ key set mismatch: {path}")
    for name, array in arrays.items():
        if array.dtype.kind == "O":
            raise ValueError(f"object dtype in {path}:{name}")
        if array.dtype.kind == "S":
            chunks.append(b" ".join(bytes(item) for item in array.tolist()).decode("utf-8"))
    return arrays, " ".join(chunks).lower()


def _hash_manifest_ok(root: Path) -> bool:
    path = root / "SHA256SUMS.txt"
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        target = root / relative
        if not target.is_file() or _hash(target) != expected:
            return False
    return True


def verify(public_root: Path, production_root: Path, contracts_root: Path, report_path: Path) -> dict[str, Any]:
    from src.algorithm_api.compiled_npz import write_compiled_algorithm_case
    from src.algorithm_api.loader import compile_algorithm_input, load_compiled_algorithm_case
    from src.case_core.task_support import validate_required_slots_probabilities
    from src.five_task_orchestrator import verify_five_task_dataset

    public_root = public_root.resolve()
    production_root = production_root.resolve()
    contracts_root = contracts_root.resolve()
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    source_dataset_by_id: dict[str, Path] = {}
    production_result = _read_json(production_root / "FIVE_TASK_PRODUCTION_RESULT.json")
    topology_ids = sorted(str(key) for key in production_result.get("datasets", {}))
    if production_result.get("status") != "PASS" or len(topology_ids) != 9:
        errors.append("production result is not PASS for nine topologies")
    for topology_id in topology_ids:
        dataset = production_root / "datasets" / topology_id
        source_dataset_by_id[topology_id] = dataset
        try:
            for row in _load_index(dataset):
                source_by_id[str(row["case_id"])] = {"row": row, "dataset": dataset}
        except Exception as exc:
            errors.append(f"source index {topology_id}: {type(exc).__name__}: {exc}")

    expected_top = {"README.md", "benchmark_case", "evaluation_case", "SHA256SUMS.txt"}
    actual_top = {path.name for path in public_root.iterdir()} if public_root.is_dir() else set()
    if actual_top != expected_top:
        errors.append(f"public top-level mismatch: {sorted(actual_top)}")
    if not _hash_manifest_ok(public_root):
        errors.append("public SHA256SUMS verification failed")

    benchmark_root = public_root / "benchmark_case"
    evaluation_root = public_root / "evaluation_case"
    try:
        benchmark_tasks = {path.name for path in benchmark_root.iterdir() if path.is_dir()}
        evaluation_tasks = {path.name for path in evaluation_root.iterdir() if path.is_dir() and path.name != "algorithm_api"}
        if benchmark_tasks != set(TASKS) or evaluation_tasks != set(TASKS):
            errors.append("public task directory set mismatch")
    except OSError as exc:
        errors.append(f"public task directory scan: {exc}")

    api_dir = evaluation_root / "algorithm_api"
    if not (api_dir / "loader.py").is_file() or not (api_dir / "compiled_npz.py").is_file():
        errors.append("public Algorithm API is incomplete")

    with tempfile.TemporaryDirectory(prefix="compiled_batch_verify_") as temp_name:
        temp = Path(temp_name)
        for task in TASKS:
            task_benchmark = benchmark_root / task
            task_evaluation = evaluation_root / task
            for filename in ("llm_system_prompt.txt",):
                if not (task_benchmark / filename).is_file():
                    errors.append(f"missing public task file: {task}/{filename}")
            benchmark_cases = sorted((task_benchmark / "cases").glob("case_*.json")) if (task_benchmark / "cases").is_dir() else []
            npz_cases = sorted((task_evaluation / "algorithm").glob("case_*.npz")) if (task_evaluation / "algorithm").is_dir() else []
            llm_cases = sorted((task_evaluation / "llm").glob("case_*.json")) if (task_evaluation / "llm").is_dir() else []
            if not (len(benchmark_cases) == len(npz_cases) == len(llm_cases) == 9):
                errors.append(f"count mismatch for {task}")
            for benchmark_path in benchmark_cases:
                ordinal_name = benchmark_path.stem
                try:
                    benchmark = _read_json(benchmark_path)
                    if tuple(benchmark) != EXPECTED_BENCHMARK_KEYS:
                        raise ValueError("benchmark key order mismatch")
                    case_id = str(benchmark["case_id"])
                    instance = benchmark["instance"]
                    if "schema_version" in instance:
                        raise ValueError("public instance contains schema_version")
                    validate_required_slots_probabilities({"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25})
                    llm_path = task_evaluation / "llm" / f"{ordinal_name}.json"
                    npz_path = task_evaluation / "algorithm" / f"{ordinal_name}.npz"
                    llm = _read_json(llm_path)
                    if set(llm) != {"case_id", "prompt"}:
                        raise ValueError("evaluation JSON has fields other than case_id/prompt")
                    if llm["case_id"] != case_id:
                        raise ValueError("evaluation case_id mismatch")
                    if llm["prompt"] != benchmark["llm_prompt"]:
                        raise ValueError("prompt parity mismatch")
                    if any(token in json.dumps(llm, ensure_ascii=False).lower() for token in ("reference", "truth", "oracle")):
                        raise ValueError("LLM evaluation leakage")
                    arrays, payload = _npz_text(npz_path)
                    if any(token in payload for token in FORBIDDEN_TEXT):
                        raise ValueError("NPZ contains forbidden textual payload")
                    contract_path = contracts_root / task / "algorithm_contract.json"
                    compiled = load_compiled_algorithm_case(npz_path, contract_path=contract_path)
                    expected_compiled = compile_algorithm_input(instance, case_id=case_id, contract=_read_json(contract_path))
                    if compiled != expected_compiled:
                        raise ValueError("NPZ loader result differs from compiled benchmark input")
                    # The public JSON ranges and binary words must agree link by link.
                    link_states = {int(row["link_id"]): row["occupied_ranges"] for row in instance["link_spectrum_states"]}
                    link_ids = arrays["link_ids"].tolist()
                    words = arrays["occupied_mask_words"]
                    for link_id, row in zip(link_ids, words, strict=True):
                        actual_mask = sum(int(word) << (64 * index) for index, word in enumerate(row.tolist()))
                        expected_mask = 0
                        for start, end in link_states[int(link_id)]:
                            expected_mask |= sum(1 << slot for slot in range(int(start), int(end) + 1))
                        if actual_mask != expected_mask:
                            raise ValueError(f"spectrum bitset mismatch on link {link_id}")
                    first = temp / f"{task}_{ordinal_name}_first.npz"
                    second = temp / f"{task}_{ordinal_name}_second.npz"
                    write_compiled_algorithm_case(first, instance, case_id=case_id, contract=_read_json(contract_path))
                    write_compiled_algorithm_case(second, instance, case_id=case_id, contract=_read_json(contract_path))
                    if first.read_bytes() != second.read_bytes() or first.read_bytes() != npz_path.read_bytes():
                        raise ValueError("compiled NPZ is not byte-deterministic or not master-derived")
                    source = source_by_id.get(case_id)
                    if source is None:
                        raise ValueError("public case_id has no producer source record")
                    source_row = source["row"]
                    source_benchmark = source["dataset"] / source_row["benchmark_case_path"]
                    source_master = _read_json(source_benchmark)
                    if benchmark != source_master:
                        raise ValueError("public benchmark master differs from producer output")
                    records.append({"task": task, "case_id": case_id, "source_topology_id": source_row.get("topology_id"), "status": "PASS"})
                except Exception as exc:
                    errors.append(f"{task}/{ordinal_name}: {type(exc).__name__}: {exc}")

    replay_by_topology: dict[str, Any] = {}
    replay_count = 0
    for topology_id, dataset in source_dataset_by_id.items():
        replay = verify_five_task_dataset(dataset)
        replay_by_topology[topology_id] = replay
        replay_count += int(replay.get("reference_replay_pass_count", 0))
        if not replay.get("valid"):
            errors.extend(f"{topology_id}: {error}" for error in replay.get("errors", []))

    invalid_paths = []
    for path in public_root.rglob("*"):
        relative = path.relative_to(public_root)
        # Check individual Windows path components.  The public report uses
        # POSIX separators for portability; '/' is a separator, not an
        # invalid character inside a component.
        if any(WINDOWS_INVALID.search(component) for component in relative.parts):
            invalid_paths.append(relative.as_posix())
    if invalid_paths:
        errors.append(f"Windows-invalid public paths: {invalid_paths}")
    report = {
        "status": "PASS" if not errors and len(records) == 45 and replay_count == 45 else "FAIL",
        "topology_count": 9,
        "task_count": 5,
        "benchmark_case_count": len(records),
        "algorithm_npz_count": sum(len(list((evaluation_root / task / "algorithm").glob("case_*.npz"))) for task in TASKS),
        "llm_evaluation_count": sum(len(list((evaluation_root / task / "llm").glob("case_*.json"))) for task in TASKS),
        "algorithm_loader_pass_count": len(records),
        "json_npz_parity_pass_count": len(records),
        "llm_prompt_parity_pass_count": len(records),
        "reference_replay_pass_count": replay_count,
        "reference_replay_by_topology": replay_by_topology,
        "evaluation_no_reference_leakage": "PASS" if not errors else "CHECKED_WITH_ERRORS",
        "npz_allow_pickle_false_and_no_object_dtype": "PASS" if not errors else "CHECKED_WITH_ERRORS",
        "deterministic_compiler": "PASS" if not errors else "CHECKED_WITH_ERRORS",
        "windows_path_audit": "PASS" if not invalid_paths else "FAIL",
        "records": records,
        "errors": errors,
    }
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="verify a nine-topology compiled Algorithm dataset")
    parser.add_argument("--public-root", required=True)
    parser.add_argument("--production-root", required=True)
    parser.add_argument("--contracts-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = verify(Path(args.public_root), Path(args.production_root), Path(args.contracts_root), Path(args.report))
    print(json.dumps({key: report[key] for key in ("status", "benchmark_case_count", "algorithm_npz_count", "llm_evaluation_count", "reference_replay_pass_count")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
