from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

_ENDPOINT_CONTRACT_FILES = ("llm_system_prompt.txt",)
_ALGORITHM_VIEW_TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
_ALGORITHM_PUBLIC_FILES = ("algorithm_contract.json", "output_schema.json")
_ALGORITHM_SCHEMA_FILES = ("algorithm_input.schema.json", "algorithm_evaluation_case.schema.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, obj: Any, *, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n", encoding="utf-8")


def prepare_task_layout(output_root: Path, task: str, contracts_root: Path) -> None:
    src = contracts_root / task
    internal_contract = output_root / "internal" / "contracts" / task
    if internal_contract.exists():
        shutil.rmtree(internal_contract)
    shutil.copytree(src, internal_contract)
    if task in _ALGORITHM_VIEW_TASKS:
        api_source = _PROJECT_ROOT / "src" / "algorithm_api"
        api_destination = output_root / "algorithm_api"
        if not api_destination.exists():
            shutil.copytree(api_source, api_destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for base in (output_root / "benchmark_case" / task, output_root / "evaluation_case" / task):
        base.mkdir(parents=True, exist_ok=True)
        for name in _ENDPOINT_CONTRACT_FILES:
            shutil.copy2(src / name, base / name)
        if task in _ALGORITHM_VIEW_TASKS:
            for name in _ALGORITHM_PUBLIC_FILES:
                shutil.copy2(src / name, base / name)
            for name in _ALGORITHM_SCHEMA_FILES:
                shutil.copy2(src / "schemas" / name, base / name)


def case_filename(ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError("case ordinal must be >= 1")
    return f"case_{ordinal:06d}.json"


def algorithm_case_filename(ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError("case ordinal must be >= 1")
    return f"case_{ordinal:06d}.npz"


def write_case_layout(
    output_root: Path,
    task: str,
    ordinal: int,
    public: dict,
    bundle_private: dict,
    *,
    include_algorithm_view: bool = False,
    algorithm_contract: dict[str, Any] | None = None,
) -> dict[str, str]:
    name = case_filename(ordinal)
    algorithm_name = algorithm_case_filename(ordinal)
    cid = str(public["benchmark_case"]["case_id"])
    benchmark_path = output_root / "benchmark_case" / task / "cases" / name
    llm_path = output_root / "evaluation_case" / task / "llm" / name
    algorithm_path = output_root / "evaluation_case" / task / "algorithm" / algorithm_name
    write_json(benchmark_path, public["benchmark_case"])
    write_json(llm_path, public["llm_case"])
    if include_algorithm_view:
        instance = public["benchmark_case"].get("instance")
        if not isinstance(instance, dict):
            raise ValueError("Algorithm evaluation view requires benchmark_case.instance")
        from src.algorithm_api.compiled_npz import write_compiled_algorithm_case

        write_compiled_algorithm_case(
            algorithm_path,
            instance,
            case_id=cid,
            contract=algorithm_contract,
        )

    internal_case = output_root / "internal" / "cases" / task / cid
    write_json(internal_case / "root_case.json", public["root_case"], sort_keys=True)
    write_json(internal_case / "algorithm_case.json", public["algorithm_case"], sort_keys=True)
    internal_private = output_root / "internal" / "private" / task / cid
    for key in ("private_truth", "reference_output", "validation", "features", "lineage"):
        write_json(internal_private / f"{key}.json", bundle_private[key], sort_keys=True)

    return {
        "benchmark_case_path": benchmark_path.relative_to(output_root).as_posix(),
        **({"algorithm_evaluation_path": algorithm_path.relative_to(output_root).as_posix()} if include_algorithm_view else {}),
        "llm_evaluation_path": llm_path.relative_to(output_root).as_posix(),
        "internal_case_dir": internal_case.relative_to(output_root).as_posix(),
        "internal_private_dir": internal_private.relative_to(output_root).as_posix(),
    }
