from __future__ import annotations

import hashlib
import json
from pathlib import Path
from random import Random
from typing import Any

from . import __version__
from .common import GenerationError, derive_seed, weighted_choice, write_json
from .contracts import contract_bundle, system_prompt
from .g1 import generate_g1_case
from .g2 import generate_g2_case
from .g3 import generate_g3_case
from .renderers import render_llm_case
from .topology import Topology, load_topology
from .validators import validate_dut_output
from .x1 import generate_x1_case


class ConfigError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    p = Path(path).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema_version") not in {"GX1_PRODUCTION_CONFIG_V2_0", "GX1_PRODUCTION_CONFIG_V2_1", "GX1_PRODUCTION_CONFIG_V2_2"}:
        raise ConfigError("schema_version 必须为 GX1_PRODUCTION_CONFIG_V2_0、GX1_PRODUCTION_CONFIG_V2_1 或 GX1_PRODUCTION_CONFIG_V2_2")
    if not isinstance(data.get("batch_id"), str) or not data["batch_id"]:
        raise ConfigError("batch_id 必须为非空字符串")
    if not isinstance(data.get("seed"), int):
        raise ConfigError("seed 必须为整数")
    if not isinstance(data.get("topologies"), list) or not data["topologies"]:
        raise ConfigError("topologies 必须为非空数组")
    counts = data.get("case_counts")
    if not isinstance(counts, dict) or set(counts) != {"G1", "G2", "G3", "X1"}:
        raise ConfigError("case_counts 必须且只能包含 G1/G2/G3/X1")
    for task, n in counts.items():
        if not isinstance(n, int) or n < 0:
            raise ConfigError(f"{task} case_count 必须为非负整数")
    if not isinstance(data.get("tasks"), dict):
        raise ConfigError("tasks 配置缺失")
    return data, p


def _resolve_topology_paths(config: dict[str, Any], cfg_path: Path) -> list[Path]:
    out = []
    for raw in config["topologies"]:
        p = Path(raw)
        if not p.is_absolute():
            p = (cfg_path.parent / p).resolve()
        if not p.exists():
            raise ConfigError(f"拓扑文件不存在: {p}")
        out.append(p)
    return out


def _choose_topology(
    rng: Random,
    topologies: list[Topology],
    require_lengths: bool = False,
    forced_topology_id: str | None = None,
) -> Topology:
    eligible = [t for t in topologies if (t.has_complete_lengths or not require_lengths)]
    if forced_topology_id is not None:
        eligible = [t for t in eligible if t.topology_id == forced_topology_id]
        if not eligible:
            known = ", ".join(t.topology_id for t in topologies)
            raise GenerationError(f"指定拓扑 {forced_topology_id} 不可用；已加载拓扑: {known}")
    if not eligible:
        raise GenerationError("没有满足 length_km 要求的输入拓扑")
    return rng.choice(eligible)


def _scheduled_value(settings: dict[str, Any], key: str, case_index: int, default: Any = None) -> Any:
    schedule = settings.get(key)
    if not schedule:
        return default
    return schedule[(case_index - 1) % len(schedule)]


def _hop_range(settings: dict[str, Any], case_index: int, default_min: int, default_max: int) -> tuple[int, int]:
    scheduled = _scheduled_value(settings, "hop_range_schedule", case_index)
    if scheduled is None:
        lo, hi = int(settings.get("min_hops", default_min)), int(settings.get("max_hops", default_max))
    else:
        if not isinstance(scheduled, list) or len(scheduled) != 2:
            raise ConfigError("hop_range_schedule 每项必须为 [min_hops,max_hops]")
        lo, hi = int(scheduled[0]), int(scheduled[1])
    if lo < 1 or hi < lo:
        raise ConfigError(f"非法跳数范围: [{lo},{hi}]")
    return lo, hi


def _task_rng(seed: int, task: str) -> Random:
    return Random(derive_seed(seed, task))


def _generate_root(task: str, case_id: str, case_index: int, rng: Random, topologies: list[Topology], settings: dict[str, Any]) -> dict[str, Any]:
    forced_topology_id = _scheduled_value(settings, "topology_schedule", case_index)
    if task == "G1":
        topo = _choose_topology(rng, topologies, forced_topology_id=forced_topology_id)
        schedule = settings.get("conversion_schedule")
        if schedule:
            conversion = schedule[(case_index - 1) % len(schedule)]
        else:
            weights = dict(settings.get("conversion_weights", {"EDGE_LIST_TO_ADJACENCY_LIST": 1}))
            if len(topo.nodes) > 100:
                allowed_large = {"EDGE_LIST_TO_ADJACENCY_LIST", "ADJACENCY_LIST_TO_EDGE_LIST"}
                weights = {k: v for k, v in weights.items() if k in allowed_large}
            conversion = weighted_choice(rng, weights)
        return generate_g1_case(topo, case_id, rng, forced_conversion=conversion)

    if task == "G2":
        schedule = settings.get("label_schedule")
        label = schedule[(case_index - 1) % len(schedule)] if schedule else weighted_choice(rng, settings.get("label_weights", {"VALID": 1}))
        min_hops, max_hops = _hop_range(settings, case_index, 2, 8)
        topo = _choose_topology(rng, topologies, forced_topology_id=forced_topology_id)
        return generate_g2_case(
            topo, case_id, rng, forced_label=label,
            min_hops=min_hops, max_hops=max_hops,
            max_sampling_attempts=int(settings.get("max_sampling_attempts", 256)),
        )

    if task in {"G3", "X1"}:
        metric_schedule = settings.get("metric_schedule")
        metric = metric_schedule[(case_index - 1) % len(metric_schedule)] if metric_schedule else weighted_choice(rng, settings.get("metric_weights", {"HOP_COUNT": 1}))
        require_lengths = metric == "TOTAL_LENGTH_KM"
        min_hops, max_hops = _hop_range(settings, case_index, 1, 20)
        if forced_topology_id is not None:
            eligible = [_choose_topology(rng, topologies, require_lengths=require_lengths, forced_topology_id=forced_topology_id)]
        else:
            eligible = [t for t in topologies if (t.has_complete_lengths or not require_lengths)]
            if not eligible:
                raise GenerationError(f"{task} 请求 {metric}，但没有完整 length_km 拓扑")
            rng.shuffle(eligible)
        errors = []
        for topo in eligible:
            try:
                if task == "G3":
                    shared_schedule = settings.get("shared_schedule")
                    if shared_schedule:
                        shared = bool(shared_schedule[(case_index - 1) % len(shared_schedule)])
                    else:
                        shared_key = weighted_choice(rng, settings.get("shared_weights", {"true": 1, "false": 1}))
                        shared = str(shared_key).lower() == "true"
                    return generate_g3_case(
                        topo, case_id, rng, forced_metric=metric, forced_shared=shared,
                        min_hops=min_hops, max_hops=max_hops,
                        max_sampling_attempts=int(settings.get("max_sampling_attempts", 512)),
                    )
                multiplicity = _scheduled_value(settings, "multiplicity_schedule", case_index)
                return generate_x1_case(
                    topo, case_id, rng, forced_metric=metric, forced_multiplicity=multiplicity,
                    min_hops=min_hops, max_hops=max_hops,
                    max_sampling_attempts=int(settings.get("max_sampling_attempts", 256)),
                )
            except GenerationError as exc:
                errors.append(f"{topo.topology_id}: {exc}")
        raise GenerationError("; ".join(errors))
    raise ConfigError(f"未知任务: {task}")


def _truth_from_root(root: dict[str, Any]) -> dict[str, Any]:
    task = root["task_type"]
    truth: dict[str, Any] = {"case_id": root["case_id"], "task_type": task, "answer": root["answer"]}
    if task == "G2":
        truth["oracle_label"] = root["oracle_label"]
    elif task == "G3":
        truth["oracle_shortest_paths"] = root["oracle_shortest_paths"]
    elif task == "X1":
        truth["optimal_cost"] = root["optimal_cost"]
        truth["shortest_path_multiplicity"] = root["shortest_path_multiplicity"]
        if "oracle_evidence" in root:
            truth["oracle_evidence"] = root["oracle_evidence"]
    return truth


def _validate_private_x1_evidence(root: dict[str, Any]) -> list[str]:
    """Validate private MULTIPLE evidence using the unchanged public Validator."""
    if root.get("task_type") != "X1" or int(root.get("shortest_path_multiplicity", 1)) <= 1:
        return []
    evidence = root.get("oracle_evidence")
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["X1 MULTIPLE missing oracle_evidence"]
    if float(evidence.get("optimal_cost", float("nan"))) != float(root["optimal_cost"]):
        errors.append("X1 evidence optimal_cost mismatch")
    if int(evidence.get("shortest_path_multiplicity", -1)) != int(root["shortest_path_multiplicity"]):
        errors.append("X1 evidence multiplicity mismatch")
    paths = evidence.get("optimal_paths")
    if not isinstance(paths, list) or len(paths) < 2:
        return errors + ["X1 MULTIPLE evidence must contain at least two paths"]
    distinct = {tuple(p.get("path_link_ids", [])) for p in paths if isinstance(p, dict)}
    if len(distinct) < 2:
        errors.append("X1 MULTIPLE evidence paths are not distinct")
    for index, path in enumerate(paths[:2]):
        if not isinstance(path, dict):
            errors.append(f"X1 evidence path {index} is not an object")
            continue
        candidate: dict[str, Any] = {
            "path_node_ids": path.get("path_node_ids"),
            "path_link_ids": path.get("path_link_ids"),
            "hop_count": path.get("hop_count"),
        }
        if root["path_cost_metric"] == "TOTAL_LENGTH_KM":
            candidate["total_length_km"] = path.get("cost")
        validation = validate_dut_output(root, json.dumps(candidate, ensure_ascii=False))
        if not validation.get("valid"):
            errors.append(f"X1 evidence path {index} fails Validator: {validation}")
        if not isinstance(path.get("cost"), (int, float)):
            errors.append(f"X1 evidence path {index} missing numeric cost")
    return errors


def _actual_request(root: dict[str, Any], llm_case: dict[str, Any]) -> dict[str, Any]:
    task = root["task_type"]
    llm = {
        "case_id": root["case_id"],
        "messages": [
            {"role": "system", "content": system_prompt(task)},
            {"role": "user", "content": llm_case["prompt"]},
        ],
    }
    return llm


def produce_batch(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    config, cfg_path = _load_config(config_path)
    topo_paths = _resolve_topology_paths(config, cfg_path)
    topologies = [load_topology(p) for p in topo_paths]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Freeze task-level contracts into every production output for replayability.
    for task in ["G1", "G2", "G3", "X1"]:
        bundle = contract_bundle(task)
        task_dir = out / "contracts" / task
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "system_prompt_llm.txt").write_text(bundle["llm_system_prompt"] + "\n", encoding="utf-8")

    manifest_cases: list[dict[str, Any]] = []
    for task in ["G1", "G2", "G3", "X1"]:
        rng = _task_rng(config["seed"], task)
        settings = config["tasks"].get(task, {})
        count = int(config["case_counts"][task])
        for idx in range(1, count + 1):
            case_id = f"{task}_{idx:06d}"
            root = _generate_root(task, case_id, idx, rng, topologies, settings)
            root["generation_metadata"] = {
                "batch_id": config["batch_id"],
                "global_seed": config["seed"],
                "task_seed": derive_seed(config["seed"], task),
                "case_index": idx,
                "topology_node_count": len(root.get("nodes", [])),
                "topology_physical_edge_count": len(root.get("undirected_edges", [])) if task == "G1" else len(root.get("directed_links", [])) // 2,
            }
            if settings.get("hop_range_schedule"):
                root["generation_metadata"]["requested_hop_range"] = list(_hop_range(settings, idx, 1, 20))
            if settings.get("difficulty_schedule"):
                root["generation_metadata"]["requested_difficulty"] = _scheduled_value(settings, "difficulty_schedule", idx)
            if task == "X1" and settings.get("multiplicity_schedule"):
                root["generation_metadata"]["requested_multiplicity"] = _scheduled_value(settings, "multiplicity_schedule", idx)
            if task == "G2":
                root["generation_metadata"]["effective_candidate_hop_count"] = len(root["candidate_path"]["path_link_ids"])
            elif task == "G3":
                root["generation_metadata"]["effective_shortest_path_hop_counts"] = [
                    int(x["hop_count"]) for x in root["answer"]["shortest_paths"]
                ]
            elif task == "X1":
                root["generation_metadata"]["effective_shortest_path_hop_count"] = int(root["answer"]["hop_count"])
                if "oracle_evidence" in root:
                    root["generation_metadata"]["private_oracle_evidence_path_count"] = len(root["oracle_evidence"].get("optimal_paths", []))
            llm = render_llm_case(root)
            actual_llm = _actual_request(root, llm)
            self_validation = validate_dut_output(root, json.dumps(root["answer"], ensure_ascii=False))
            if not self_validation["valid"]:
                raise GenerationError(f"生产答案未通过 Validator: {case_id}: {self_validation}")
            evidence_errors = _validate_private_x1_evidence(root)
            if evidence_errors:
                raise GenerationError(f"X1 私有最优路径证据未通过 Validator: {case_id}: {evidence_errors}")
            d = out / "cases" / task / case_id
            d.mkdir(parents=True, exist_ok=True)
            write_json(d / "root_case.json", root)
            write_json(d / "llm_case.json", llm)
            write_json(d / "truth.json", _truth_from_root(root))
            write_json(d / "validation_metadata.json", {"case_id": case_id, "production_self_check": self_validation})
            write_json(d / "actual_llm_request.json", actual_llm)
            manifest_cases.append({
                "case_id": case_id,
                "task_type": task,
                "topology_id": root["topology_id"],
            })

    manifest = {
        "schema_version": "GX1_PRODUCTION_MANIFEST_V3_0_ALGORITHM_LLM_ONLY",
        "producer_version": __version__,
        "config_schema_version": config["schema_version"],
        "batch_id": config["batch_id"],
        "seed": config["seed"],
        "case_counts": {task: int(config["case_counts"][task]) for task in ["G1", "G2", "G3", "X1"]},
        "topology_ids": [t.topology_id for t in topologies],
        "cases": manifest_cases,
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def _contains_forbidden_key(obj: Any) -> bool:
    forbidden = {"answer", "truth", "oracle", "private_truth", "reference"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in forbidden:
                return True
            if _contains_forbidden_key(v):
                return True
    elif isinstance(obj, list):
        return any(_contains_forbidden_key(x) for x in obj)
    return False


def verify_output_tree(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    errors: list[str] = []
    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        return {"valid": False, "errors": ["manifest.json missing"]}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"valid": False, "errors": [f"manifest parse: {exc}"]}
    for rec in manifest.get("cases", []):
        d = out / "cases" / rec["task_type"] / rec["case_id"]
        needed = ["root_case.json", "llm_case.json", "truth.json", "validation_metadata.json", "actual_llm_request.json"]
        for name in needed:
            if not (d / name).exists():
                errors.append(f"{rec['case_id']}: missing {name}")
        if any(not (d / name).exists() for name in needed):
            continue
        root = json.loads((d / "root_case.json").read_text(encoding="utf-8"))
        llm = json.loads((d / "llm_case.json").read_text(encoding="utf-8"))
        actual_llm = json.loads((d / "actual_llm_request.json").read_text(encoding="utf-8"))
        if root.get("case_id") != rec["case_id"] or llm.get("case_id") != rec["case_id"]:
            errors.append(f"{rec['case_id']}: case_id mismatch")
        if _contains_forbidden_key(actual_llm):
            errors.append(f"{rec['case_id']}: actual request leaks private answer/truth fields")
        evidence_errors = _validate_private_x1_evidence(root)
        errors.extend(f"{rec['case_id']}: {error_text}" for error_text in evidence_errors)
        result = validate_dut_output(root, json.dumps(llm.get("answer"), ensure_ascii=False))
        if not result.get("valid"):
            errors.append(f"{rec['case_id']}: llm answer fails validator: {result}")
    return {"valid": not errors, "errors": errors, "case_count": len(manifest.get("cases", []))}


def doctor() -> dict[str, Any]:
    import sys
    checks = {
        "python_version": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 10),
        "producer_version": __version__,
        "tasks": ["G1", "G2", "G3", "X1"],
        "tracks": ["algorithm", "llm"],
    }
    checks["valid"] = bool(checks["python_ok"])
    return checks
