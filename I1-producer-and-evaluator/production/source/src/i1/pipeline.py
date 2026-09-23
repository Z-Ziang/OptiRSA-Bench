from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from src.case_core.serialization_metrics import canonical_tokenizer_metadata
from src.i1.base_dataset import export_i1_base_dataset, verify_i1_base_dataset
from src.i1.config import load_i1_config
from src.i1.exporter import export_i1_dataset
from src.i1.renderer import render_base_prompt
from src.i1.rewrite import build_rewrite_client
from src.i1.source_loader import load_i1_sources
from src.i1.truth import build_concurrent_answer, build_dynamic_answer, build_single_answer
from src.i1.validators import validate_rewrite
from src.i1.version import I1_PRODUCER_VERSION

TASKS = ("I1-S", "I1-C", "I1-D")


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_obj(obj) -> str:
    return _sha_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _objective_for(profile_variants: list[list[str]], ordinal: int) -> list[str]:
    if not profile_variants:
        raise ValueError("no objective profile variants configured")
    return list(profile_variants[(ordinal - 1) % len(profile_variants)])


def _select(items, n, seed, allow_shortfall):
    if n > len(items) and not allow_shortfall:
        raise ValueError(f"requested {n} cases but only {len(items)} source items available")
    rows = list(items)
    random.Random(seed).shuffle(rows)
    return rows[: min(n, len(rows))]


def _expand_concurrent_sources(sources: dict, needed: int, seed: int) -> list[dict]:
    rows = list(sources["concurrent"])
    if len(rows) >= needed:
        return rows
    singles = list(sources["single"])
    rnd = random.Random(seed)
    rnd.shuffle(singles)
    existing = {tuple(r["request_id"] for r in x["requests"]) for x in rows}
    width = 4
    cursor = 0
    synthetic_idx = 1
    while len(rows) < needed and singles:
        if cursor + width > len(singles):
            rnd.shuffle(singles)
            cursor = 0
        group = singles[cursor : cursor + width]
        cursor += width
        if len(group) < width:
            break
        signature = tuple(r["request_id"] for r in group)
        if signature in existing:
            continue
        existing.add(signature)
        rows.append(
            {
                "request_set_id": f"i1_derived_reqset_{synthetic_idx:06d}",
                "requests": group,
            }
        )
        synthetic_idx += 1
        if synthetic_idx > needed * 20 + 100:
            break
    return rows


def _base_record(task: str, case_id: str, source_ref: str, answer: dict, cfg: dict) -> dict:
    base_prompt = render_base_prompt(answer)
    lineage = {
        "producer_version": I1_PRODUCER_VERSION,
        "producer_contract_version": "I1_PRODUCER_V2_1_3",
        "stage": "BASE_TEMPLATE",
        "source_ref": source_ref,
        "config_sha256": cfg["config_sha256"],
        "canonical_answer_sha256": _sha_obj(answer),
        "base_prompt_sha256": _sha_text(base_prompt),
    }
    return {
        "case_id": case_id,
        "source_ref": source_ref,
        "canonical_answer": answer,
        "base_prompt": base_prompt,
        "lineage": lineage,
    }


def _generate_base_records(cfg: dict, sources: dict) -> dict[str, list[dict]]:
    records = {task: [] for task in TASKS}
    counts = cfg["case_counts"]
    objectives = cfg["objective_profiles"]
    seed = int(cfg["seed"])
    allow_shortfall = bool(cfg.get("allow_shortfall", False))

    for i, request in enumerate(
        _select(sources["single"], counts.get("I1-S", 0), seed + 11, allow_shortfall), 1
    ):
        answer = build_single_answer(request, _objective_for(objectives["I1-S"], i))
        records["I1-S"].append(
            _base_record("I1-S", f"I1_S_{i:06d}", str(request["request_id"]), answer, cfg)
        )

    concurrent_sources = _expand_concurrent_sources(
        sources, counts.get("I1-C", 0), seed + 23
    )
    for i, row in enumerate(
        _select(concurrent_sources, counts.get("I1-C", 0), seed + 23, allow_shortfall), 1
    ):
        answer = build_concurrent_answer(row["requests"], _objective_for(objectives["I1-C"], i))
        records["I1-C"].append(
            _base_record("I1-C", f"I1_C_{i:06d}", str(row["request_set_id"]), answer, cfg)
        )

    for i, request in enumerate(
        _select(sources["dynamic"], counts.get("I1-D", 0), seed + 37, allow_shortfall), 1
    ):
        answer = build_dynamic_answer(request, _objective_for(objectives["I1-D"], i))
        source_ref = f"{request.get('request_sequence_id', 'seq')}::{request['request_id']}"
        records["I1-D"].append(
            _base_record("I1-D", f"I1_D_{i:06d}", source_ref, answer, cfg)
        )

    for task, rows in records.items():
        seen = set()
        for record in rows:
            digest = record["lineage"]["canonical_answer_sha256"]
            if digest in seen:
                raise ValueError(f"{task}: duplicate canonical answer")
            seen.add(digest)
    return records


def _finalize_record(base_record: dict, cfg: dict, client) -> dict:
    answer = base_record["canonical_answer"]
    base_prompt = base_record["base_prompt"]
    rewrite_cfg = cfg["rewrite"]
    enabled = bool(rewrite_cfg.get("enabled", False))
    max_attempts = int(rewrite_cfg.get("max_attempts", 3))
    final_prompt = None
    validation = None
    attempts = []

    if not enabled:
        final_prompt = base_prompt
        parser = lambda prompt: client.parse_intent(prompt, answer)
        validation = validate_rewrite(answer, final_prompt, semantic_parser=parser)
        attempts.append(
            {
                "attempt": 1,
                "mode": "identity",
                "status": validation["overall"],
                "rewritten_prompt": final_prompt,
            }
        )
    else:
        for attempt in range(1, max_attempts + 1):
            try:
                text = client.rewrite(base_prompt, answer)
                parser = lambda prompt, ans=answer: client.parse_intent(prompt, ans)
                candidate_validation = validate_rewrite(
                    answer, text, semantic_parser=parser
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": candidate_validation["overall"],
                        "rewritten_prompt": text,
                        "errors": candidate_validation["errors"],
                    }
                )
                if candidate_validation["overall"] == "PASS":
                    final_prompt = text
                    validation = candidate_validation
                    break
            except Exception as exc:
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        if final_prompt is None:
            raise RuntimeError(
                f"{base_record['case_id']}: rewrite failed after {max_attempts} attempts"
            )

    if validation is None or validation["overall"] != "PASS":
        raise RuntimeError(f"{base_record['case_id']}: rewrite validation failed")

    rewrite_meta = {
        "enabled": enabled,
        "mode": rewrite_cfg.get("mode", "identity"),
        "provider": rewrite_cfg.get("provider"),
        "model": rewrite_cfg.get("model"),
        "temperature": rewrite_cfg.get("temperature"),
        "max_attempts": max_attempts,
        "attempts": attempts,
    }
    lineage = dict(base_record["lineage"])
    lineage.update(
        {
            "producer_version": I1_PRODUCER_VERSION,
            "producer_contract_version": "I1_PRODUCER_V2_1_3",
            "stage": "FINAL_CASE",
            "rewrite_config_sha256": cfg["config_sha256"],
            "final_prompt_sha256": _sha_text(final_prompt),
            "rewrite_mode": rewrite_cfg.get("mode", "identity"),
            "rewrite_enabled": enabled,
            "rewrite_provider": rewrite_cfg.get("provider"),
            "rewrite_model": rewrite_cfg.get("model"),
        }
    )
    return {
        **base_record,
        "final_prompt": final_prompt,
        "rewrite": rewrite_meta,
        "validation": validation,
        "lineage": lineage,
    }


def derive_i1_base_dataset(
    environment_root: Path | str,
    config_path: Path | str,
    output_root: Path | str,
) -> dict:
    cfg = load_i1_config(config_path)
    if cfg.get("require_canonical_tokenizer", False):
        canonical_tokenizer_metadata()
    sources = load_i1_sources(environment_root)
    records = _generate_base_records(cfg, sources)
    return export_i1_base_dataset(
        output_root,
        records,
        contracts_root=Path(__file__).resolve().parents[2] / "contracts",
        production_metadata={
            "profile": cfg["profile"],
            "seed": int(cfg["seed"]),
            "config_sha256": cfg["config_sha256"],
        },
    )


def _load_base_records(base_dataset_root: Path | str) -> dict[str, list[dict]]:
    root = Path(base_dataset_root).resolve()
    report = verify_i1_base_dataset(root)
    if not report["valid"]:
        raise ValueError(f"invalid base dataset: {report['errors']}")
    rows = [
        json.loads(line)
        for line in (root / "base_case_index.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = {task: [] for task in TASKS}
    for row in rows:
        case = json.loads((root / row["base_case_path"]).read_text(encoding="utf-8"))
        internal = root / row["internal_case_dir"]
        lineage = json.loads((internal / "lineage.json").read_text(encoding="utf-8"))
        records[row["task_type"]].append(
            {
                "case_id": case["case_id"],
                "source_ref": row["source_ref"],
                "canonical_answer": case["answer"],
                "base_prompt": case["llm_prompt"],
                "lineage": lineage,
            }
        )
    return records


def rewrite_i1_base_dataset(
    base_dataset_root: Path | str,
    config_path: Path | str,
    output_root: Path | str,
    rewrite_client=None,
) -> dict:
    cfg = load_i1_config(config_path)
    if not cfg["rewrite"].get("enabled", False):
        raise ValueError("rewrite-base-cases requires rewrite.enabled=true")
    if cfg.get("require_canonical_tokenizer", False):
        canonical_tokenizer_metadata()
    base_records = _load_base_records(base_dataset_root)
    client = rewrite_client or build_rewrite_client(cfg)
    final_records = {
        task: [_finalize_record(record, cfg, client) for record in rows]
        for task, rows in base_records.items()
    }
    return export_i1_dataset(
        output_root,
        final_records,
        contracts_root=Path(__file__).resolve().parents[2] / "contracts",
        production_metadata={
            "profile": cfg["profile"],
            "seed": int(cfg["seed"]),
            "config_sha256": cfg["config_sha256"],
            "source_base_dataset": str(Path(base_dataset_root).resolve()),
        },
    )


def derive_i1_dataset(
    environment_root: Path | str,
    config_path: Path | str,
    output_root: Path | str,
    rewrite_client=None,
) -> dict:
    """Convenience one-step pipeline; explicit base→rewrite stages remain the formal workflow."""
    cfg = load_i1_config(config_path)
    if cfg.get("require_canonical_tokenizer", False):
        canonical_tokenizer_metadata()
    sources = load_i1_sources(environment_root)
    base_records = _generate_base_records(cfg, sources)
    client = rewrite_client or build_rewrite_client(cfg)
    final_records = {
        task: [_finalize_record(record, cfg, client) for record in rows]
        for task, rows in base_records.items()
    }
    return export_i1_dataset(
        output_root,
        final_records,
        contracts_root=Path(__file__).resolve().parents[2] / "contracts",
        production_metadata={
            "profile": cfg["profile"],
            "seed": int(cfg["seed"]),
            "config_sha256": cfg["config_sha256"],
        },
    )
