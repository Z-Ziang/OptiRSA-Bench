"""Fail-closed audit for the active I1 V2.1.3 source/examples interface."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.i1.version import I1_PRODUCER_VERSION

TASKS = ("I1-S", "I1-C", "I1-D")
ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/(?:mnt|home|Users|tmp)/)")
SECRET_RE = re.compile(r"(?:Bearer\s+[A-Za-z0-9._-]{12,}|sk-[A-Za-z0-9]{12,})")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(schema_path: Path, value, label: str, errors: list[str]) -> None:
    try:
        Draft202012Validator(_read_json(schema_path)).validate(value)
    except Exception as exc:
        errors.append(f"{label}: {type(exc).__name__}: {exc}")


def run_active_audit(root: Path | str) -> dict:
    root = Path(root).resolve()
    errors: list[str] = []
    benchmark_count = 0
    evaluation_count = 0
    mapping_count = 0
    old_benchmark_count = 0
    benchmark_schema_count = 0
    evaluation_schema_count = 0
    example_root = root / "examples" / "i1_representative"

    for task in TASKS:
        benchmark_schema = root / "contracts" / task / "schemas" / "benchmark_case.schema.json"
        evaluation_schema = root / "contracts" / task / "schemas" / "evaluation_case.schema.json"
        try:
            b_schema = _read_json(benchmark_schema)
            e_schema = _read_json(evaluation_schema)
            if b_schema.get("required") != ["case_id", "llm_prompt", "answer"]:
                errors.append(f"{task}: active benchmark schema required mismatch")
            if e_schema.get("required") != ["case_id", "prompt"]:
                errors.append(f"{task}: active evaluation schema required mismatch")
            if b_schema.get("additionalProperties") is not False:
                errors.append(f"{task}: benchmark schema is not closed")
            if e_schema.get("additionalProperties") is not False:
                errors.append(f"{task}: evaluation schema is not closed")
            benchmark_schema_count += 1
            evaluation_schema_count += 1
        except Exception as exc:
            errors.append(f"{task}: schema read failure: {type(exc).__name__}: {exc}")

        benchmark_dir = example_root / "benchmark_case" / task / "cases"
        evaluation_dir = example_root / "evaluation_case" / task / "cases"
        benchmark_cases = sorted(benchmark_dir.glob("*.json"))
        evaluation_cases = sorted(evaluation_dir.glob("*.json"))
        if len(benchmark_cases) != len(evaluation_cases):
            errors.append(f"{task}: benchmark/evaluation count mismatch")
        for benchmark_path in benchmark_cases:
            benchmark_count += 1
            try:
                benchmark = _read_json(benchmark_path)
                if set(benchmark) != {"case_id", "llm_prompt", "answer"}:
                    errors.append(f"{benchmark_path.relative_to(root)}: not current benchmark envelope")
                    if set(benchmark) == {"case_id", "prompt", "answer"}:
                        old_benchmark_count += 1
                else:
                    _validate(benchmark_schema, benchmark, str(benchmark_path.relative_to(root)), errors)
            except Exception as exc:
                errors.append(f"{benchmark_path.relative_to(root)}: invalid JSON: {type(exc).__name__}: {exc}")
        for evaluation_path in evaluation_cases:
            evaluation_count += 1
            try:
                evaluation = _read_json(evaluation_path)
                if set(evaluation) != {"case_id", "prompt"}:
                    errors.append(f"{evaluation_path.relative_to(root)}: not current evaluation envelope")
                else:
                    _validate(evaluation_schema, evaluation, str(evaluation_path.relative_to(root)), errors)
                benchmark_path = example_root / "benchmark_case" / task / "cases" / evaluation_path.name
                benchmark = _read_json(benchmark_path)
                if evaluation.get("case_id") != benchmark.get("case_id"):
                    errors.append(f"{evaluation_path.relative_to(root)}: case_id mismatch")
                if evaluation.get("prompt") != benchmark.get("llm_prompt"):
                    errors.append(f"{evaluation_path.relative_to(root)}: prompt is not exact benchmark.llm_prompt")
                else:
                    mapping_count += 1
            except Exception as exc:
                errors.append(f"{evaluation_path.relative_to(root)}: invalid JSON: {type(exc).__name__}: {exc}")

    source_files = []
    for path in sorted((root / "src" / "i1").rglob("*.py")):
        source_files.append(path)
    source_files += [root / "benchmark_i1.py", root / "scripts" / "i1_v2_1_3_production.py"]
    forbidden_fallbacks = []
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"get\(\s*[\"']llm_prompt[\"']\s*,[^\n]*[\"']prompt[\"']", text):
            forbidden_fallbacks.append(str(path.relative_to(root)))
    if forbidden_fallbacks:
        errors.append(f"active legacy benchmark fallback: {forbidden_fallbacks}")

    version_file = (root / "I1_VERSION").read_text(encoding="utf-8").strip()
    if version_file != I1_PRODUCER_VERSION:
        errors.append(f"I1_VERSION mismatch: {version_file!r} != {I1_PRODUCER_VERSION!r}")

    secret_hits = []
    path_hits = []
    scoped_roots = [
        root / "src" / "i1",
        root / "benchmark_i1.py",
        root / "scripts" / "i1_active_audit.py",
        root / "scripts" / "i1_v2_1_3_production.py",
        root / "configs" / "i1_representative.json",
        root / "configs" / "i1_small_batch.json",
        root / "configs" / "i1_config.schema.json",
        root / "configs" / "i1_llm_rewrite_template.json",
        root / "configs" / "i1_v2_1_3_preproduction.json",
        root / "contracts" / "I1-S",
        root / "contracts" / "I1-C",
        root / "contracts" / "I1-D",
        root / "contracts" / "I1",
        root / "examples" / "i1_representative",
        root / "README.md",
        root / "QUICKSTART.md",
        root / "DIRECTORY_MAP.md",
        root / "I1_CASE_ENVELOPE_FORMAT.md",
        root / "I1_VERSION",
        root / "docs" / "08_I1_生产与改写说明.md",
        root / "docs" / "I1_AUTHORITY_NOTES.md",
    ]
    scoped_files = []
    for scoped_root in scoped_roots:
        if scoped_root.is_file():
            scoped_files.append(scoped_root)
        elif scoped_root.is_dir():
            scoped_files.extend(p for p in scoped_root.rglob("*") if p.is_file())
    for path in sorted(set(scoped_files)):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SECRET_RE.search(text):
            secret_hits.append(str(path.relative_to(root)))
        if ABSOLUTE_PATH_RE.search(text):
            path_hits.append(str(path.relative_to(root)))
    if secret_hits:
        errors.append(f"secret-like values found: {secret_hits}")
    if path_hits:
        errors.append(f"absolute local paths found: {path_hits}")

    return {
        "valid": not errors,
        "producer_version": I1_PRODUCER_VERSION,
        "benchmark_case_count": benchmark_count,
        "evaluation_case_count": evaluation_count,
        "evaluation_prompt_exact_mapping_count": mapping_count,
        "active_old_benchmark_prompt_count": old_benchmark_count,
        "benchmark_schema_count": benchmark_schema_count,
        "evaluation_schema_count": evaluation_schema_count,
        "forbidden_active_fallback_files": forbidden_fallbacks,
        "secret_hit_files": secret_hits,
        "absolute_path_hit_files": path_hits,
        "errors": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit active I1 V2.1.3 envelope and examples")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_active_audit(args.root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
