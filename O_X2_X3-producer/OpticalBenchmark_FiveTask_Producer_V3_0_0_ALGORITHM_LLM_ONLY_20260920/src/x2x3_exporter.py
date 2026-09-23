from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.dataset_layout import prepare_task_layout, write_case_layout, write_json
from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.serialization_metrics import compute_serialization_metrics

_TASKS = ("X2", "X3")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(path: Path, obj, label: str) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    errs = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errs:
        raise ValueError(f"{label} schema violation: {errs[0].message}")


def export_x2x3_dataset(output_root, bundles_by_task, *, contracts_root, production_metadata, strict_frozen_interface: bool = True):
    root = Path(output_root).resolve()
    contracts = Path(contracts_root).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    index = []
    counts = {}
    replay = []
    for task in _TASKS:
        bundles = sorted(bundles_by_task.get(task, []), key=lambda b: str(b["root_case"]["case_id"]))
        counts[task] = len(bundles)
        if bundles:
            prepare_task_layout(root, task, contracts)
        for ordinal, b in enumerate(bundles, start=1):
            cid = str(b["root_case"]["case_id"])
            if b["algorithm_case"].get("case_id") != cid or b["private_truth"].get("case_id") != cid:
                raise ValueError(f"case_id mismatch {cid}")
            instance = project_algorithm_input(task, b["algorithm_case"])
            views = build_benchmark_views(
                b["root_case"],
                b["reference_output"],
                strict_frozen_interface=strict_frozen_interface,
                instance=instance,
            )
            public = {"root_case": b["root_case"], "algorithm_case": b["algorithm_case"], **views}
            for name in ("root_case", "algorithm_case", "benchmark_case", "llm_case"):
                _validate(contracts / task / "schemas" / f"{name}.schema.json", public[name], f"{task}/{cid}/{name}")
            _validate(contracts / task / "schemas" / "algorithm_input.schema.json", instance, f"{task}/{cid}/instance")
            _validate(contracts / task / "output_schema.json", public["benchmark_case"]["reference"], f"{task}/{cid}/benchmark_case.reference")
            _validate(contracts / task / "schemas/private_truth.schema.json", b["private_truth"], f"{task}/{cid}/private_truth")
            features = dict(b["features"])
            features.pop("serialized_char_count_llm", None)
            features["serialization_metrics"] = compute_serialization_metrics(
                public["benchmark_case"]["llm_prompt"]
            )
            private = {**b, "features": features}
            algorithm_contract = (
                json.loads((contracts / task / "algorithm_contract.json").read_text(encoding="utf-8"))
                if strict_frozen_interface else None
            )
            paths = write_case_layout(
                root, task, ordinal, public, private,
                include_algorithm_view=True,
                algorithm_contract=algorithm_contract,
            )
            index.append({"case_id": cid, "task_type": task, "topology_id": b["root_case"]["topology_id"], "resource_state_id": b["root_case"]["resource_state_id"], "features": features, **paths})
            replay.append({"task_type": task, "case_id": cid, "valid": bool(b["validation"]["valid"]), "metrics": b["validation"]["metrics"], "errors": b["validation"]["errors"]})
    index.sort(key=lambda x: (x["task_type"], x["case_id"]))
    (root / "case_index.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in index), encoding="utf-8")
    summary = {"schema_version": "X2X3_PRODUCTION_SUMMARY_V3_0", "case_count": len(index), "task_counts": counts, "production_metadata": production_metadata, "benchmark_interface": "DUAL_VIEW_ALGORITHM_LLM_V1_0_COMPILED_NPZ"}
    write_json(root / "production_summary.json", summary, sort_keys=True)
    write_json(root / "reports/REFERENCE_REPLAY_SUMMARY.json", {"schema_version": "X2X3_REFERENCE_REPLAY_SUMMARY_V2_1", "case_count": len(replay), "reference_replay_pass_count": sum(bool(r["valid"]) for r in replay), "reference_replay_fail_count": sum(not bool(r["valid"]) for r in replay), "cases": replay}, sort_keys=True)
    files = []
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name not in {"RUN_MANIFEST.json", "SHA256SUMS.txt"}):
        files.append({"path": p.relative_to(root).as_posix(), "size_bytes": p.stat().st_size, "sha256": _hash(p)})
    write_json(root / "RUN_MANIFEST.json", {"schema_version": "X2X3_RUN_MANIFEST_V2_1", "file_count": len(files), "files": files}, sort_keys=True)
    lines = [f"{_hash(p)}  {p.relative_to(root).as_posix()}" for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name != "SHA256SUMS.txt")]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
