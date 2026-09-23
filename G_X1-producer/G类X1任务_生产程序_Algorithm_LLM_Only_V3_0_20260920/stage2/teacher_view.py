from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical_km import EXPECTED_BY_ID


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _configuration_summary(root: dict[str, Any]) -> list[str]:
    task = root["task_type"]
    rows = [
        f"- topology_id：`{root.get('topology_id')}`",
        f"- 节点数：{len(root.get('nodes', []))}",
        f"- 物理链路数：{len(root.get('undirected_edges', [])) if task == 'G1' else len(root.get('directed_links', [])) // 2}",
    ]
    if task == "G1":
        rows.extend([
            f"- conversion：`{root.get('conversion')}`",
            f"- source_representation：`{root.get('source_representation')}`",
            f"- target_representation：`{root.get('target_representation')}`",
        ])
    elif task == "G2":
        rows.extend([
            f"- oracle_label：`{root.get('oracle_label')}`",
            f"- candidate_hop_count：{len(root.get('candidate_path', {}).get('path_link_ids', []))}",
        ])
    elif task == "G3":
        rows.extend([
            f"- path_cost_metric：`{root.get('path_cost_metric')}`",
            f"- pair_A_hop_count：{root.get('answer', {}).get('shortest_paths', [{}])[0].get('hop_count')}",
            f"- pair_B_hop_count：{root.get('answer', {}).get('shortest_paths', [{}, {}])[1].get('hop_count')}",
            f"- has_shared_directed_link：{root.get('answer', {}).get('has_shared_directed_link')}",
            f"- shared_link_ids：`{root.get('answer', {}).get('shared_link_ids')}`",
        ])
    elif task == "X1":
        rows.extend([
            f"- path_cost_metric：`{root.get('path_cost_metric')}`",
            f"- shortest_path_multiplicity：{root.get('shortest_path_multiplicity')}",
            f"- optimal_path_hop_count：{root.get('answer', {}).get('hop_count')}",
            f"- optimal_cost：{root.get('optimal_cost')}",
        ])
    return rows


def _topology_summary(topology_id: str, topology_audit: dict[str, Any]) -> list[str]:
    row = next((item for item in topology_audit.get("topologies", []) if item.get("topology_id") == topology_id), None)
    expected = EXPECTED_BY_ID.get(topology_id, {})
    if row is None:
        row = expected
    return [
        f"- topology_id：`{topology_id}`",
        f"- display_name：{row.get('display_name', expected.get('display_name', topology_id))}",
        f"- source_family：`{row.get('source_family', expected.get('source_family'))}`",
        f"- scale_bin：`{row.get('scale_bin', expected.get('scale_bin'))}`（拓扑规模区间，不是难度标签）",
        f"- nodes：{row.get('node_count')}",
        f"- physical links：{row.get('physical_link_count')}",
        f"- mean_length_km：{row.get('mean_length_km')}",
        f"- total_length_km_eligible：{row.get('total_length_km_eligible')}",
    ]


def _case_record(public_manifest: dict[str, Any], task: str, case_id: str) -> dict[str, str]:
    for item in public_manifest.get("cases", []):
        if item.get("task_type") == task and item.get("case_id") == case_id:
            return item
    raise ValueError(f"unified manifest missing {task}/{case_id}")


def export_teacher_views(dataset_root: Path, internal_root: Path, topology_audit: dict[str, Any]) -> dict[str, Any]:
    dataset_root = Path(dataset_root).resolve()
    internal_root = Path(internal_root).resolve()
    public_manifest = _read_json(dataset_root / "manifest.json")
    view_paths: list[str] = []
    for record in sorted(public_manifest.get("cases", []), key=lambda item: (item["task_type"], item["case_id"])):
        task = record["task_type"]
        case_id = record["case_id"]
        benchmark_path = dataset_root / record["benchmark_case"]
        benchmark = _read_json(benchmark_path)
        root_path = internal_root / "cases" / task / case_id / "root_case.json"
        root = _read_json(root_path)
        task_dir = dataset_root / "evaluation_case" / task
        llm_system = (task_dir / "llm_system_prompt.txt").read_text(encoding="utf-8")
        view = "\n".join([
            f"# {case_id}",
            "",
            f"## Task：{task}",
            "",
            "## 拓扑与配置",
            "",
            *_topology_summary(root["topology_id"], topology_audit),
            *_configuration_summary(root),
            "",
            "## LLM system prompt",
            "",
            "```text",
            llm_system.rstrip("\n"),
            "```",
            "",
            "## benchmark_case（正式三字段）",
            "",
            "```json",
            _pretty(benchmark).rstrip("\n"),
            "```",
            "",
            "## LLM 实际测试输入",
            "",
            "`llm_system_prompt.txt` + `evaluation_case/<TASK>/llm/<CASE>.json.prompt`",
            "",
            "## Algorithm 评测输入",
            "",
            "`internal_evidence/<TASK>/<CASE>/root_case.json` + canonical Validator",
            "",
            "## Reference",
            "",
            "以下 reference 仅用于公开参考、canonical Validator 和离线评测，不发送给 DUT。",
            "",
            "```json",
            _pretty(benchmark["reference"]).rstrip("\n"),
            "```",
            "",
            "Teacher Demo 视图不包含模型成绩；正式机器 Case 仍以 public unified schema 为准。",
            "",
        ])
        target = dataset_root / "teacher_view" / task / f"{case_id}_TEACHER_VIEW.md"
        _write_text(target, view)
        view_paths.append(str(target.relative_to(dataset_root)).replace("\\", "/"))
    return {"pass": len(view_paths) == int(public_manifest.get("case_count", -1)), "count": len(view_paths), "paths": view_paths}
