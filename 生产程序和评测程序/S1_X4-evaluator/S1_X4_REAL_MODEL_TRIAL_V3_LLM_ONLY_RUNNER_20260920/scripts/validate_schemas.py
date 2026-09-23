#!/usr/bin/env python3
"""Validate JSON and JSONL files with JSON Schema Draft 2020-12.

The CLI can validate one schema/input pair, a manifest of file mappings, or an
expected-validity test suite. Reports preserve the input file, JSONL line,
instance JSON Pointer, schema JSON Pointer, validator keyword, failing field,
and human-readable message.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


def _pointer(parts: Iterable[Any]) -> str:
    escaped = []
    for part in parts:
        text = str(part).replace("~", "~0").replace("/", "~1")
        escaped.append(text)
    return "" if not escaped else "/" + "/".join(escaped)


def _failing_field(error: ValidationError) -> str | None:
    if error.path:
        return str(list(error.path)[-1])
    if error.validator == "required":
        # jsonschema's message is stable enough for diagnostics, but avoid
        # relying on it for validation logic.
        message = error.message
        if message.startswith("'") and "' is a required property" in message:
            return message.split("'", 2)[1]
    if error.validator == "additionalProperties":
        message = error.message
        marker = "('"
        if marker in message and "' was unexpected)" in message:
            return message.split(marker, 1)[1].split("'", 1)[0]
    return None


def _error_record(error: ValidationError, input_path: Path, line: int | None) -> dict[str, Any]:
    return {
        "file": str(input_path),
        "line": line,
        "instance_pointer": _pointer(error.absolute_path),
        "schema_pointer": _pointer(error.absolute_schema_path),
        "validator": error.validator,
        "failing_field": _failing_field(error),
        "message": error.message,
    }


def _parse_error_record(input_path: Path, message: str, line: int | None = None) -> dict[str, Any]:
    return {
        "file": str(input_path),
        "line": line,
        "instance_pointer": "",
        "schema_pointer": "",
        "validator": "json_parse",
        "failing_field": None,
        "message": message,
    }


def load_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read schema {schema_path}: {exc}") from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid Draft 2020-12 schema {schema_path}: {exc.message}") from exc
    return schema


def _iter_documents(input_path: Path) -> tuple[list[tuple[int | None, Any]], list[dict[str, Any]]]:
    documents: list[tuple[int | None, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    if input_path.suffix.lower() == ".jsonl":
        try:
            lines = input_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [], [_parse_error_record(input_path, str(exc))]
        for line_no, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            try:
                documents.append((line_no, json.loads(raw)))
            except json.JSONDecodeError as exc:
                parse_errors.append(
                    _parse_error_record(
                        input_path,
                        f"JSONL parse error at column {exc.colno}: {exc.msg}",
                        line=line_no,
                    )
                )
        return documents, parse_errors

    try:
        documents.append((None, json.loads(input_path.read_text(encoding="utf-8"))))
    except OSError as exc:
        parse_errors.append(_parse_error_record(input_path, str(exc)))
    except json.JSONDecodeError as exc:
        parse_errors.append(
            _parse_error_record(
                input_path,
                f"JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
        )
    return documents, parse_errors


def validate_file(schema_path: Path | str, input_path: Path | str) -> list[dict[str, Any]]:
    schema_path = Path(schema_path)
    input_path = Path(input_path)
    schema = load_schema(schema_path)
    validator = Draft202012Validator(schema)
    documents, errors = _iter_documents(input_path)
    for line_no, document in documents:
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
            errors.append(_error_record(error, input_path, line_no))
    return errors


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def run_suite(suite_path: Path | str) -> dict[str, Any]:
    suite_path = Path(suite_path).resolve()
    base = suite_path.parent
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for test in suite.get("tests", []):
        schema_path = _resolve(base, test["schema"])
        input_path = _resolve(base, test["file"])
        errors = validate_file(schema_path, input_path)
        actual_valid = not errors
        expected_valid = bool(test["expected_valid"])
        expectation_met = actual_valid == expected_valid
        results.append(
            {
                "name": test.get("name", input_path.name),
                "category": test.get("category"),
                "schema": str(schema_path),
                "file": str(input_path),
                "expected_valid": expected_valid,
                "actual_valid": actual_valid,
                "expectation_met": expectation_met,
                "error_count": len(errors),
                "errors": errors,
            }
        )
    passed = sum(1 for item in results if item["expectation_met"])
    return {
        "suite": str(suite_path),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
    }


def run_manifest(manifest_path: Path | str, input_root: Path | str | None = None) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(input_root).resolve() if input_root is not None else _resolve(base, manifest.get("input_root", "."))
    mappings = manifest.get("mappings", [])
    results: list[dict[str, Any]] = []
    for file_path in sorted(path for path in root.rglob("*") if path.suffix.lower() in {".json", ".jsonl"}):
        relative = file_path.relative_to(root).as_posix()
        matched = next((item for item in mappings if fnmatch.fnmatch(relative, item["pattern"])), None)
        if matched is None:
            continue
        schema_path = _resolve(base, matched["schema"])
        errors = validate_file(schema_path, file_path)
        results.append(
            {
                "file": str(file_path),
                "relative_file": relative,
                "schema": str(schema_path),
                "valid": not errors,
                "error_count": len(errors),
                "errors": errors,
            }
        )
    return {
        "manifest": str(manifest_path),
        "input_root": str(root),
        "summary": {
            "files": len(results),
            "valid": sum(1 for item in results if item["valid"]),
            "invalid": sum(1 for item in results if not item["valid"]),
            "errors": sum(item["error_count"] for item in results),
        },
        "results": results,
    }


def _write_report(report: dict[str, Any], report_path: Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path is None:
        print(text)
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
        print(report_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--schema", type=Path, help="Schema for one input file; requires --input")
    mode.add_argument("--suite", type=Path, help="Expected-validity test suite JSON")
    mode.add_argument("--manifest", type=Path, help="Glob-to-schema manifest JSON")
    parser.add_argument("--input", type=Path, help="JSON/JSONL file for --schema, or root for --manifest")
    parser.add_argument("--report", type=Path, help="Write JSON report to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.suite:
            report = run_suite(args.suite)
            exit_code = 0 if report["summary"]["failed"] == 0 else 1
        elif args.manifest:
            report = run_manifest(args.manifest, args.input)
            exit_code = 0 if report["summary"]["invalid"] == 0 else 1
        else:
            if args.input is None:
                raise ValueError("--schema requires --input")
            errors = validate_file(args.schema, args.input)
            report = {
                "schema": str(args.schema),
                "file": str(args.input),
                "valid": not errors,
                "error_count": len(errors),
                "errors": errors,
            }
            exit_code = 0 if not errors else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report = {"fatal_error": str(exc)}
        exit_code = 2
    _write_report(report, args.report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
