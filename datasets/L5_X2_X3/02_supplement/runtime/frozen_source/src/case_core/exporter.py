from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from jsonschema import Draft202012Validator

from src.case_core.algorithm_projection import project_algorithm_input
from src.case_core.dataset_layout import prepare_task_layout, write_case_layout, write_json
from src.case_core.natural_language_renderer import build_benchmark_views
from src.case_core.serialization_metrics import compute_serialization_metrics
from src.case_core.task_support import validate_required_slots_probabilities

_TASKS = ("O1", "O2-S", "O2-C")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(schema_path: Path, obj: Any, label: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        raise ValueError(f"{label} schema violation: {errors[0].message}")
    if isinstance(obj, dict) and "required_slots_probabilities" in obj:
        validate_required_slots_probabilities(obj["required_slots_probabilities"])


def _export_bundle_views(bundle: dict, *, strict_frozen_interface: bool) -> dict:
    instance = project_algorithm_input(bundle["root_case"]["task_type"], bundle["algorithm_case"])
    views = build_benchmark_views(
        bundle["root_case"],
        bundle["reference_output"],
        strict_frozen_interface=strict_frozen_interface,
        instance=instance,
        language="en",
    )
    return {"root_case": bundle["root_case"], "algorithm_case": bundle["algorithm_case"], **views}


def _finalize(root: Path, summary: dict, replay_rows: list[dict], replay_schema: str, manifest_schema: str) -> None:
    write_json(root / "production_summary.json", summary, sort_keys=True)
    write_json(root / "reports" / "REFERENCE_REPLAY_SUMMARY.json", {
        "schema_version": replay_schema,
        "case_count": len(replay_rows),
        "reference_replay_pass_count": sum(bool(r["valid"]) for r in replay_rows),
        "reference_replay_fail_count": sum(not bool(r["valid"]) for r in replay_rows),
        "cases": replay_rows,
    }, sort_keys=True)
    files = []
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name not in {"RUN_MANIFEST.json", "SHA256SUMS.txt"}):
        files.append({"path": p.relative_to(root).as_posix(), "size_bytes": p.stat().st_size, "sha256": _hash(p)})
    write_json(root / "RUN_MANIFEST.json", {"schema_version": manifest_schema, "file_count": len(files), "files": files}, sort_keys=True)
    lines = [f"{_hash(p)}  {p.relative_to(root).as_posix()}" for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name != "SHA256SUMS.txt")]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_dataset(output_root: Path | str, bundles_by_task: dict[str, list[dict]], *, contracts_root: Path | str, production_metadata: dict, strict_frozen_interface: bool = True) -> dict:
    root = Path(output_root).resolve()
    contracts = Path(contracts_root).resolve()
    if root.exists():
        raise FileExistsError("export target already exists: " + str(root))
    root.mkdir(parents=True)
    index: list[dict] = []
    counts: dict[str, int] = {}
    replay_rows: list[dict] = []
    for task in _TASKS:
        bundles = sorted(bundles_by_task.get(task, []), key=lambda b: str(b["root_case"]["case_id"]))
        counts[task] = len(bundles)
        if bundles:
            prepare_task_layout(root, task, contracts)
        for ordinal, bundle in enumerate(bundles, start=1):
            cid = str(bundle["root_case"]["case_id"])
            if bundle["algorithm_case"].get("case_id") != cid or bundle["private_truth"].get("case_id") != cid:
                raise ValueError(f"case_id mismatch in bundle {cid}")
            public = _export_bundle_views(bundle, strict_frozen_interface=strict_frozen_interface)
            zh_views = build_benchmark_views(
                bundle["root_case"],
                bundle["reference_output"],
                strict_frozen_interface=strict_frozen_interface,
                instance=public["benchmark_case"]["instance"],
                language="zh",
            )
            public_zh = {"root_case": bundle["root_case"], "algorithm_case": bundle["algorithm_case"], **zh_views}
            for name in ("root_case", "algorithm_case", "benchmark_case", "llm_case"):
                _validate(contracts / task / "schemas" / f"{name}.schema.json", public[name], f"{task}/{cid}/{name}")
                _validate(contracts / task / "schemas" / f"{name}.schema.json", public_zh[name], f"{task}/{cid}/{name}/zh")
            instance = public["benchmark_case"]["instance"]
            _validate(contracts / task / "schemas" / "algorithm_input.schema.json", instance, f"{task}/{cid}/instance")
            _validate(contracts / task / "output_schema.json", public["benchmark_case"]["reference"], f"{task}/{cid}/benchmark_case.reference")
            _validate(contracts / task / "schemas/private_truth.schema.json", bundle["private_truth"], f"{task}/{cid}/private_truth")
            features = dict(bundle["features"])
            features.pop("serialized_char_count_llm", None)
            features["serialization_metrics"] = compute_serialization_metrics(
                public["benchmark_case"]["llm_prompt"]
            )
            private = {**bundle, "features": features}
            algorithm_contract = (
                json.loads((contracts / task / "algorithm_contract.json").read_text(encoding="utf-8"))
                if strict_frozen_interface else None
            )
            paths = write_case_layout(
                root, task, ordinal, public, private,
                include_algorithm_view=True,
                algorithm_contract=algorithm_contract,
                public_zh=public_zh,
            )
            index.append({"case_id": cid, "task_type": task, "topology_id": bundle["root_case"]["topology_id"], "resource_state_id": bundle["root_case"]["resource_state_id"], "features": features, **paths})
            replay_rows.append({"task_type": task, "case_id": cid, "valid": bool(bundle["validation"]["valid"]), "metrics": bundle["validation"]["metrics"], "errors": bundle["validation"]["errors"]})
    index.sort(key=lambda x: (x["task_type"], x["case_id"]))
    (root / "case_index.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in index), encoding="utf-8")
    summary = {"schema_version": "O_FAMILY_PRODUCTION_SUMMARY_V3_0", "case_count": len(index), "task_counts": counts, "production_metadata": production_metadata, "benchmark_interface": "DUAL_VIEW_ALGORITHM_LLM_V1_0_COMPILED_NPZ"}
    _finalize(root, summary, replay_rows, "O_FAMILY_REFERENCE_REPLAY_SUMMARY_V2_1", "O_FAMILY_RUN_MANIFEST_V2_1")
    return summary
