from __future__ import annotations

import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

from src.algorithm_api.loader import compile_algorithm_input, load_compiled_algorithm_case
from src.tasks.x2.validator import validate_x2_output
from src.tasks.x3.validator import validate_x3_output

_VAL = {"X2": validate_x2_output, "X3": validate_x3_output}


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(path: Path, obj) -> None:
    errs = list(Draft202012Validator(_read(path)).iter_errors(obj))
    if errs:
        raise ValueError(errs[0].message)


def verify_x2x3_dataset(dataset_root, *, contracts_root=None):
    root = Path(dataset_root).resolve()
    contracts = Path(contracts_root).resolve() if contracts_root else root / "internal" / "contracts"
    errors = []
    count = 0
    replay = 0
    if not root.is_dir():
        return {"valid": False, "case_count": 0, "reference_replay_pass_count": 0, "errors": [f"dataset not found: {root}"]}
    index_path = root / "case_index.jsonl"
    if not index_path.is_file():
        return {"valid": False, "case_count": 0, "reference_replay_pass_count": 0, "errors": ["missing case_index.jsonl"]}
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        task = str(row.get("task_type"))
        if task not in _VAL:
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
                _schema(contracts / task / "schemas" / f"{name}.schema.json", obj)
            _schema(contracts / task / "schemas" / "algorithm_input.schema.json", benchmark["instance"])
            _schema(contracts / task / "output_schema.json", benchmark["reference"])
            _schema(contracts / task / "schemas/private_truth.schema.json", truth)
            if any(obj["case_id"] != cid for obj in (benchmark, llm, root_case, algorithm, truth)) or compiled.case_id != cid:
                raise ValueError("case_id mismatch across exported views")
            if benchmark["llm_prompt"] != llm["prompt"]:
                raise ValueError("benchmark/evaluation prompt mismatch")
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
            result = _VAL[task](root_case, truth, reference)
            metric = "feasible_decision_accuracy" if task == "X2" else "joint_feasible_decision_accuracy"
            if result["metrics"].get(metric) != 1:
                raise ValueError("reference decision replay != 1")
            primary = "hop_gap" if task == "X2" else "delta_tso_gap"
            if reference["decision"] == "ACCEPT" and result["metrics"].get(primary) != 0:
                raise ValueError(f"reference {primary} != 0")
            if reference["decision"] == "ACCEPT" and abs(float(result["metrics"].get("wufr_gap") or 0.0)) > 1e-12:
                raise ValueError("reference wufr_gap != 0")
            replay += 1
        except Exception as exc:
            errors.append(f"{task}/{cid}: {type(exc).__name__}: {exc}")
    hp = root / "SHA256SUMS.txt"
    if hp.is_file():
        for line in hp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            exp, rel = line.split("  ", 1)
            p = root / rel
            if not p.is_file() or _hash(p) != exp:
                errors.append(f"SHA256 mismatch: {rel}")
    else:
        errors.append("missing SHA256SUMS.txt")
    return {"valid": not errors, "case_count": count, "reference_replay_pass_count": replay, "errors": errors}
