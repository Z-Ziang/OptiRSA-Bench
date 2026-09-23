"""Public unified benchmark/evaluation schema projection.

The module deliberately treats the existing root_case files as the scientific
source of truth.  It creates a release-layer projection and never edits the
source tree or changes the canonical Validator.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .common import canonical_json
from .contracts import unified_system_prompt
from .renderers import render_llm_case


TASKS = ("G1", "G2", "G3", "X1")
BENCHMARK_KEYS = ("case_id", "llm_prompt", "reference")
EVALUATION_KEYS = ("case_id", "prompt")
FORBIDDEN_REQUEST_KEYS = frozenset({"answer", "truth", "oracle", "private_truth", "reference"})

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


class UnifiedSchemaError(ValueError):
    """Raised when a source case or unified export is structurally invalid."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - message is useful to callers
        raise UnifiedSchemaError(f"无法读取 JSON: {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip("\n") + "\n", encoding="utf-8")


def _task_sort_key(task: str) -> tuple[int, str]:
    try:
        return TASKS.index(task), task
    except ValueError:
        return len(TASKS), task


def _validate_root(root: dict[str, Any], expected_task: str | None = None) -> None:
    if not isinstance(root, dict):
        raise UnifiedSchemaError("root_case 必须是 JSON object")
    task = root.get("task_type")
    if task not in TASKS:
        raise UnifiedSchemaError(f"root_case task_type 非法: {task!r}")
    if expected_task is not None and task != expected_task:
        raise UnifiedSchemaError(f"root_case task_type 不匹配: expected={expected_task}, actual={task}")
    if not isinstance(root.get("case_id"), str) or not root["case_id"]:
        raise UnifiedSchemaError("root_case 缺少非空 case_id")
    if not isinstance(root.get("answer"), dict):
        raise UnifiedSchemaError(f"{root['case_id']} 缺少 object answer")


def discover_scientific_cases(source_dir: str | Path) -> list[tuple[str, Path, dict[str, Any]]]:
    """Discover `(task, root_path, root_case)` records deterministically.

    Supported inputs are a V2.x producer output (`manifest.json` plus
    `cases/<TASK>/<CASE_ID>/root_case.json`) and the Stage 1 regression layout
    (`02_INTERNAL_EVIDENCE/<TASK>/root_case.json`).
    """

    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise UnifiedSchemaError(f"source_dir 不存在或不是目录: {source}")

    records: list[tuple[str, Path, dict[str, Any]]] = []
    manifest_path = source / "manifest.json"
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        raw_cases = manifest.get("cases") if isinstance(manifest, dict) else None
        if not isinstance(raw_cases, list):
            raise UnifiedSchemaError(f"manifest cases 缺失: {manifest_path}")
        for record in raw_cases:
            if not isinstance(record, dict):
                raise UnifiedSchemaError(f"manifest case record 非法: {manifest_path}")
            task = record.get("task_type")
            case_id = record.get("case_id")
            if task not in TASKS or not isinstance(case_id, str) or not case_id:
                raise UnifiedSchemaError(f"manifest case record 缺少 task_type/case_id: {record}")
            root_path = source / "cases" / task / case_id / "root_case.json"
            if not root_path.exists():
                raise UnifiedSchemaError(f"manifest 引用的 root_case 不存在: {root_path}")
            root = _read_json(root_path)
            _validate_root(root, task)
            if root["case_id"] != case_id:
                raise UnifiedSchemaError(f"manifest/root case_id 不一致: {case_id}")
            records.append((task, root_path, root))
    else:
        for task in TASKS:
            stage1_path = source / "02_INTERNAL_EVIDENCE" / task / "root_case.json"
            producer_roots = sorted((source / "cases" / task).glob("*/root_case.json"))
            candidates = [stage1_path] if stage1_path.exists() else producer_roots
            for root_path in candidates:
                root = _read_json(root_path)
                _validate_root(root, task)
                records.append((task, root_path, root))

    if not records:
        raise UnifiedSchemaError(
            "未发现支持的 scientific root_case；需要 manifest.json/cases 或 02_INTERNAL_EVIDENCE"
        )
    records.sort(key=lambda item: (_task_sort_key(item[0]), item[2]["case_id"]))
    return records


def project_reference(root: dict[str, Any]) -> dict[str, Any]:
    """Project the existing canonical answer into the public reference field."""

    _validate_root(root)
    return copy.deepcopy(root["answer"])


def build_benchmark_case(root: dict[str, Any]) -> dict[str, Any]:
    """Build a public case with exactly three top-level fields."""

    _validate_root(root)
    llm = render_llm_case(root)
    case = {
        "case_id": root["case_id"],
        "llm_prompt": llm["prompt"],
        "reference": project_reference(root),
    }
    errors = validate_public_case_schema(case, "benchmark")
    if errors:
        raise UnifiedSchemaError(f"public benchmark_case 非法: {errors}")
    return case


def build_evaluation_case(case_id: str, prompt: str) -> dict[str, str]:
    case = {"case_id": case_id, "prompt": prompt}
    errors = validate_public_case_schema(case, "evaluation")
    if errors:
        raise UnifiedSchemaError(f"public evaluation_case 非法: {errors}")
    return case


def validate_public_case_schema(value: Any, kind: str) -> list[str]:
    """Validate the stable, dependency-free structural subset of the schemas."""

    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{kind}: value must be an object"]
    if kind == "benchmark":
        expected = BENCHMARK_KEYS
        if set(value.keys()) != set(expected) or len(value) != len(expected):
            errors.append(f"benchmark keys must be exactly {list(expected)}")
        if not isinstance(value.get("case_id"), str) or not value.get("case_id"):
            errors.append("benchmark.case_id must be a non-empty string")
        for key in ("llm_prompt",):
            if not isinstance(value.get(key), str):
                errors.append(f"benchmark.{key} must be a string")
        if not isinstance(value.get("reference"), dict):
            errors.append("benchmark.reference must be an object")
    elif kind == "evaluation":
        expected = EVALUATION_KEYS
        if set(value.keys()) != set(expected) or len(value) != len(expected):
            errors.append(f"evaluation keys must be exactly {list(expected)}")
        if not isinstance(value.get("case_id"), str) or not value.get("case_id"):
            errors.append("evaluation.case_id must be a non-empty string")
        if not isinstance(value.get("prompt"), str):
            errors.append("evaluation.prompt must be a string")
    else:
        errors.append(f"unknown public schema kind: {kind}")
    return errors


def forbidden_field_hits(value: Any, path: str = "$") -> list[str]:
    """Return paths where a private field name occurs as an object key."""

    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_REQUEST_KEYS:
                hits.append(child_path)
            hits.extend(forbidden_field_hits(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(forbidden_field_hits(child, f"{path}[{index}]"))
    return hits


def _schema_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _read_json(_SCHEMA_DIR / "benchmark_case.schema.json"),
        _read_json(_SCHEMA_DIR / "evaluation_case.schema.json"),
    )


def _jsonschema_errors(schema: dict[str, Any], value: Any) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    validator = jsonschema.Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(value), key=str)]


def _task_contract_file(task: str) -> str:
    return unified_system_prompt(task)


def _case_filename(index: int) -> str:
    return f"case_{index:06d}.json"


def export_unified(source_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Export a source dataset into the public unified layout.

    The destination must be empty or absent.  Refusing to merge into an old
    output prevents stale cases from silently surviving a deterministic export.
    """

    records = discover_scientific_cases(source_dir)
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise UnifiedSchemaError(f"output_dir 必须为空: {output}")
    output.mkdir(parents=True, exist_ok=True)

    benchmark_schema, evaluation_schema = _schema_documents()
    _write_json(output / "schemas" / "benchmark_case.schema.json", benchmark_schema)
    _write_json(output / "schemas" / "evaluation_case.schema.json", evaluation_schema)

    task_counts = {task: 0 for task in TASKS}
    manifest_cases: list[dict[str, Any]] = []
    for task in TASKS:
        task_records = [item for item in records if item[0] == task]
        llm_system = _task_contract_file(task)
        benchmark_task_dir = output / "benchmark_case" / task
        evaluation_task_dir = output / "evaluation_case" / task
        for task_dir in (benchmark_task_dir, evaluation_task_dir):
            _write_text(task_dir / "llm_system_prompt.txt", llm_system)

        for index, (_, _root_path, root) in enumerate(task_records, start=1):
            public_case = build_benchmark_case(root)
            benchmark_path = benchmark_task_dir / "cases" / _case_filename(index)
            llm_path = evaluation_task_dir / "llm" / _case_filename(index)
            _write_json(benchmark_path, public_case)
            _write_json(llm_path, build_evaluation_case(root["case_id"], public_case["llm_prompt"]))
            task_counts[task] += 1
            manifest_cases.append({
                "task_type": task,
                "case_id": root["case_id"],
                "benchmark_case": str(benchmark_path.relative_to(output)).replace("\\", "/"),
                "evaluation_llm_case": str(llm_path.relative_to(output)).replace("\\", "/"),
            })

    manifest = {
        "schema_version": "GX1_ALGORITHM_LLM_ONLY_MANIFEST_V1_0",
        "schema_kind": "PUBLIC_ALGORITHM_LLM_ONLY",
        "source_mode": "V2_PRODUCER_OUTPUT" if (Path(source_dir) / "manifest.json").exists() else "STAGE1_INTERNAL_EVIDENCE",
        "task_counts": task_counts,
        "case_count": sum(task_counts.values()),
        "cases": manifest_cases,
    }
    _write_json(output / "manifest.json", manifest)
    verification = verify_unified_export(output)
    if not verification["valid"]:
        raise UnifiedSchemaError(f"unified export verification failed: {verification['errors']}")
    return verification


def _manifest_case_map(output: Path) -> dict[tuple[str, str], dict[str, Any]]:
    manifest = _read_json(output / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        raise UnifiedSchemaError("unified manifest 缺少 cases")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in manifest["cases"]:
        if not isinstance(item, dict):
            raise UnifiedSchemaError("unified manifest case record 非法")
        key = (str(item.get("task_type")), str(item.get("case_id")))
        if key in result:
            raise UnifiedSchemaError(f"unified manifest case 重复: {key}")
        result[key] = item
    return result


def verify_unified_export(output_dir: str | Path) -> dict[str, Any]:
    """Verify a public Algorithm+LLM export and its LLM request boundary."""

    output = Path(output_dir).resolve()
    errors: list[str] = []
    task_counts = {task: 0 for task in TASKS}
    try:
        benchmark_schema = _read_json(output / "schemas" / "benchmark_case.schema.json")
        evaluation_schema = _read_json(output / "schemas" / "evaluation_case.schema.json")
        manifest = _read_json(output / "manifest.json")
        case_map = _manifest_case_map(output)
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)], "case_count": 0, "task_counts": task_counts}

    if manifest.get("schema_version") != "GX1_ALGORITHM_LLM_ONLY_MANIFEST_V1_0":
        errors.append("manifest schema_version mismatch")
    expected_cases = set(case_map)
    seen_cases: set[tuple[str, str]] = set()

    for task in TASKS:
        benchmark_task_dir = output / "benchmark_case" / task
        evaluation_task_dir = output / "evaluation_case" / task
        required_task_files = [
            benchmark_task_dir / "llm_system_prompt.txt",
            evaluation_task_dir / "llm_system_prompt.txt",
        ]
        for path in required_task_files:
            if not path.exists():
                errors.append(f"missing task-level file: {path.relative_to(output)}")
        if any(not path.exists() for path in required_task_files):
            continue
        expected_llm = _task_contract_file(task)
        actual_llm = (benchmark_task_dir / "llm_system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
        if actual_llm != expected_llm.rstrip("\n"):
            errors.append(f"{task}: benchmark llm_system_prompt mismatch")
        evaluation_llm_system = (evaluation_task_dir / "llm_system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")
        if evaluation_llm_system != expected_llm.rstrip("\n"):
            errors.append(f"{task}: evaluation llm_system_prompt mismatch")

        for key, record in sorted(case_map.items(), key=lambda item: (_task_sort_key(item[0][0]), item[0][1])):
            record_task, case_id = key
            if record_task != task:
                continue
            seen_cases.add(key)
            task_counts[task] += 1
            benchmark_path = output / record["benchmark_case"]
            llm_path = output / record["evaluation_llm_case"]
            for path in (benchmark_path, llm_path):
                if not path.exists():
                    errors.append(f"{task}/{case_id}: missing {path.relative_to(output)}")
            if any(not path.exists() for path in (benchmark_path, llm_path)):
                continue
            benchmark = _read_json(benchmark_path)
            llm_eval = _read_json(llm_path)
            errors.extend(f"{task}/{case_id}: {error}" for error in validate_public_case_schema(benchmark, "benchmark"))
            errors.extend(f"{task}/{case_id}: {error}" for error in validate_public_case_schema(llm_eval, "evaluation"))
            errors.extend(f"{task}/{case_id}: benchmark schema: {error}" for error in _jsonschema_errors(benchmark_schema, benchmark))
            errors.extend(f"{task}/{case_id}: llm evaluation schema: {error}" for error in _jsonschema_errors(evaluation_schema, llm_eval))
            if benchmark.get("case_id") != case_id or llm_eval.get("case_id") != case_id:
                errors.append(f"{task}/{case_id}: case_id mismatch")
            if llm_eval.get("prompt") != benchmark.get("llm_prompt"):
                errors.append(f"{task}/{case_id}: LLM projection mismatch")

    if seen_cases != expected_cases:
        errors.append(f"manifest cases not represented exactly: missing={sorted(expected_cases - seen_cases)}, extra={sorted(seen_cases - expected_cases)}")
    if manifest.get("case_count") != len(expected_cases):
        errors.append("manifest case_count mismatch")
    if manifest.get("task_counts") != task_counts:
        errors.append(f"manifest task_counts mismatch: expected={task_counts}, actual={manifest.get('task_counts')}")
    return {
        "valid": not errors,
        "errors": errors,
        "case_count": len(expected_cases),
        "task_counts": task_counts,
        "schema_validation": "jsonschema" if _has_jsonschema() else "built_in_exact_keys",
    }


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _find_case_paths(output: Path, task: str, case_id: str) -> tuple[Path, Path]:
    manifest = _read_json(output / "manifest.json")
    for record in manifest.get("cases", []):
        if record.get("task_type") == task and record.get("case_id") == case_id:
            return (
                output / record["benchmark_case"],
                output / record["evaluation_llm_case"],
            )
    raise UnifiedSchemaError(f"unified case not found: {task}/{case_id}")


def assemble_unified_request(
    unified_dir: str | Path, task: str, case_id: str
) -> dict[str, Any]:
    """Assemble the exact public LLM request boundary for one case."""

    if task not in TASKS:
        raise UnifiedSchemaError(f"unknown task: {task}")
    output = Path(unified_dir).resolve()
    benchmark_path, llm_path = _find_case_paths(output, task, case_id)
    task_dir = output / "evaluation_case" / task
    eval_case = _read_json(llm_path)
    request: dict[str, Any] = {
        "case_id": case_id,
        "messages": [
            {"role": "system", "content": (task_dir / "llm_system_prompt.txt").read_text(encoding="utf-8").rstrip("\n")},
            {"role": "user", "content": eval_case["prompt"]},
        ],
    }
    hits = forbidden_field_hits(request)
    if hits:
        raise UnifiedSchemaError(f"unified DUT request contains forbidden fields: {hits}")
    # Keep the lookup explicit so a future refactor cannot accidentally use
    # the benchmark object/reference to assemble the request.
    if not benchmark_path.exists():
        raise UnifiedSchemaError(f"benchmark case missing: {benchmark_path}")
    return request
