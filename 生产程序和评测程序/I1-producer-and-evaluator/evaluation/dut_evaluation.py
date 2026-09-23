from __future__ import annotations

import json
from pathlib import Path

from src.tasks.o1.validator import validate_o1_output
from src.tasks.o2_s.validator import validate_o2s_output
from src.tasks.o2_c.validator import validate_o2c_output
from src.tasks.x2.validator import validate_x2_output
from src.tasks.x3.validator import validate_x3_output
from src.i1.validator import validate_i1_output

_I1_TASKS = {"I1-S", "I1-C", "I1-D"}

_VALIDATORS = {
    "O1": validate_o1_output,
    "O2-S": validate_o2s_output,
    "O2-C": validate_o2c_output,
    "X2": validate_x2_output,
    "X3": validate_x3_output,
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _find_case(dataset_root: Path, task: str, case_id: str) -> dict:
    index = dataset_root / "case_index.jsonl"
    if not index.is_file():
        raise FileNotFoundError(f"missing case_index.jsonl: {index}")
    matches = []
    for line in index.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("task_type")) == task and str(row.get("case_id")) == case_id:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one index row for {task}/{case_id}, found {len(matches)}")
    return matches[0]


def validate_dut_response(dataset_root: str | Path, task: str, case_id: str, response_path: str | Path) -> dict:
    task = str(task)
    case_id = str(case_id)
    if task not in _VALIDATORS and task not in _I1_TASKS:
        raise ValueError(f"unsupported task: {task}")
    root = Path(dataset_root).resolve()
    row = _find_case(root, task, case_id)
    case_dir = root / row["internal_case_dir"]

    if task in _I1_TASKS:
        answer = _read_json(case_dir / "canonical_answer.json")
        raw_output = Path(response_path).resolve().read_text(encoding="utf-8")
        validated = validate_i1_output(answer, raw_output)
        return {
            "task_type": task,
            "case_id": case_id,
            "valid": bool(validated["final_case_pass"]),
            "errors": list(validated.get("errors", [])),
            "metrics": {
                "raw_format_compliance": int(bool(validated["raw_format_valid"])),
                "schema_accuracy": int(bool(validated["schema_valid"])),
                "semantic_intent_accuracy": int(bool(validated["semantic_exact_match"])),
                "objective_set_accuracy": int(bool(validated["objective_set_accuracy"])),
                "objective_order_accuracy": int(bool(validated["objective_order_accuracy"])),
                "final_case_accuracy": int(bool(validated["final_case_pass"])),
            },
            "field_results": dict(validated.get("field_results", {})),
            "format_error_type": validated.get("format_error_type"),
            "semantic_parse_source": validated.get("semantic_parse_source"),
        }

    private_dir = root / row["internal_private_dir"]
    root_case = _read_json(case_dir / "root_case.json")
    truth = _read_json(private_dir / "private_truth.json")
    output = _read_json(Path(response_path).resolve())
    validated = _VALIDATORS[task](root_case, truth, output)
    result = {
        "task_type": task,
        "case_id": case_id,
        "valid": bool(validated.get("valid")),
        "errors": list(validated.get("errors", [])),
        "metrics": dict(validated.get("metrics", {})),
    }
    for key in ("submitted_wufr", "submitted_hop_count", "submitted_delta_tso"):
        if key in validated:
            result[key] = validated[key]
    return result
