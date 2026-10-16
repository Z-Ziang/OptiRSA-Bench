from __future__ import annotations

import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

from src.algorithm_api.loader import compile_algorithm_input, load_compiled_algorithm_case
from src.case_core.task_support import validate_required_slots_probabilities
from src.tasks.o1.validator import validate_o1_output
from src.tasks.o2_s.validator import validate_o2s_output
from src.tasks.o2_c.validator import validate_o2c_output

_VALIDATORS = {"O1": validate_o1_output, "O2-S": validate_o2s_output, "O2-C": validate_o2c_output}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_check(schema_path: Path, obj: dict) -> None:
    schema = _read(schema_path)
    errs = list(Draft202012Validator(schema).iter_errors(obj))
    if errs:
        raise ValueError(errs[0].message)
    if "required_slots_probabilities" in obj:
        validate_required_slots_probabilities(obj["required_slots_probabilities"])


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_rows(root: Path) -> list[dict]:
    p = root / "case_index.jsonl"
    if not p.is_file():
        raise ValueError("missing case_index.jsonl")
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_dataset(dataset_root: Path | str, *, contracts_root: Path | str | None = None) -> dict:
    root = Path(dataset_root).resolve()
    contracts = Path(contracts_root).resolve() if contracts_root else root / "internal" / "contracts"
    errors: list[str] = []
    count = 0
    replay = 0
    if not root.is_dir():
        return {"valid": False, "case_count": 0, "reference_replay_pass_count": 0, "errors": [f"dataset not found: {root}"]}
    try:
        rows = _index_rows(root)
    except Exception as exc:
        rows = []
        errors.append(f"index: {type(exc).__name__}: {exc}")
    for row in rows:
        task = str(row.get("task_type"))
        if task not in _VALIDATORS:
            continue
        cid = str(row.get("case_id"))
        count += 1
        try:
            benchmark = _read(root / row["benchmark_case_path"])
            algorithm_path = root / row["algorithm_evaluation_path"]
            if algorithm_path.suffix.lower() != ".npz":
                raise ValueError("five-task Algorithm evaluation must be an NPZ file")
            formal_algorithm_input = int(benchmark["instance"].get("slot_count", 0)) == 320
            compiled = load_compiled_algorithm_case(
                algorithm_path,
                contract_path=contracts / task / "algorithm_contract.json" if formal_algorithm_input else None,
                use_default_contract=formal_algorithm_input,
            )
            llm = _read(root / row["llm_evaluation_path"])
            case_dir = root / row["internal_case_dir"]
            private_dir = root / row["internal_private_dir"]
            root_case = _read(case_dir / "root_case.json")
            algorithm = _read(case_dir / "algorithm_case.json")
            truth = _read(private_dir / "private_truth.json")
            reference = _read(private_dir / "reference_output.json")
            for name, obj in (("root_case", root_case), ("algorithm_case", algorithm), ("benchmark_case", benchmark), ("llm_case", llm)):
                _schema_check(contracts / task / "schemas" / f"{name}.schema.json", obj)
            _schema_check(contracts / task / "schemas" / "algorithm_input.schema.json", benchmark["instance"])
            _schema_check(contracts / task / "output_schema.json", benchmark["reference"])
            _schema_check(contracts / task / "schemas/private_truth.schema.json", truth)
            if any(obj["case_id"] != cid for obj in (benchmark, llm, root_case, algorithm, truth)) or compiled.case_id != cid:
                raise ValueError("case_id mismatch across exported views")
            if benchmark["llm_prompt"] != llm["prompt"]:
                raise ValueError("benchmark llm_prompt != evaluation llm prompt")
            if benchmark["reference"] != reference:
                raise ValueError("benchmark reference != internal reference_output")
            expected_compiled = compile_algorithm_input(
                benchmark["instance"],
                case_id=cid,
                contract=json.loads((contracts / task / "algorithm_contract.json").read_text(encoding="utf-8")) if formal_algorithm_input else None,
            )
            if compiled != expected_compiled or compiled.task_type != task:
                raise ValueError("Algorithm loader case identity mismatch")
            if set(llm) != {"case_id", "prompt"}:
                raise ValueError("evaluation case must contain id + prompt only")
            result = _VALIDATORS[task](root_case, truth, reference)
            if not result["valid"]:
                raise ValueError("reference replay failed Validator: " + str(result["errors"]))
            if task in ("O2-S", "O2-C") and reference.get("decision") == "ACCEPT" and not result.get("lexicographic_optimal"):
                raise ValueError("reference does not attain both new O2 objective levels")
            metric_name = "feasible_decision_accuracy" if task == "O2-S" else "joint_feasible_decision_accuracy"
            if result["metrics"].get(metric_name) != 1:
                raise ValueError("reference replay feasible-decision metric != 1")
            gap = result["metrics"].get("wufr_gap")
            if reference.get("decision") == "ACCEPT" and (gap is None or abs(float(gap)) > 1e-12):
                raise ValueError("reference replay wufr_gap != 0")
            replay += 1
        except Exception as exc:
            errors.append(f"{task}/{cid}: {type(exc).__name__}: {exc}")
    hash_path = root / "SHA256SUMS.txt"
    if hash_path.is_file():
        for line in hash_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, rel = line.split("  ", 1)
            p = root / rel
            if not p.is_file() or _hash(p) != expected:
                errors.append(f"SHA256 mismatch: {rel}")
    else:
        errors.append("missing SHA256SUMS.txt")
    return {"valid": not errors, "case_count": count, "reference_replay_pass_count": replay, "errors": errors}
