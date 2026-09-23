from __future__ import annotations

from copy import deepcopy
from typing import Iterable

SUPPORTED_TASKS = {"O1", "O2-S", "O2-C", "X2", "X3"}


def _compact_array(values: Iterable[int]) -> str:
    return "[" + ",".join(str(int(x)) for x in values) + "]"


def _free_ranges(bits: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for i, bit in enumerate(bits):
        free = int(bit) == 1
        if free and start is None:
            start = i
        elif not free and start is not None:
            ranges.append((start, i - 1))
            start = None
    if start is not None:
        ranges.append((start, len(bits) - 1))
    return ranges


def _validate_frozen_interface(root: dict, strict_frozen_interface: bool) -> None:
    if strict_frozen_interface and int(root.get("slot_count", -1)) != 320:
        raise ValueError("slot_count must be 320 for frozen natural-language interface")
    if str(root.get("task_type")) not in SUPPORTED_TASKS:
        raise ValueError(f"unsupported task_type: {root.get('task_type')}")


def _network_text(root: dict, *, strict_frozen_interface: bool) -> str:
    nodes = sorted(int(x) for x in root["nodes"])
    if not nodes:
        raise ValueError("nodes must be non-empty")
    links = {int(x["link_id"]): x for x in root["directed_links"]}
    states = {int(x["link_id"]): x for x in root["link_spectrum_states"]}
    if set(links) != set(states):
        raise ValueError("directed_links and link_spectrum_states link_id sets must match")
    lines = [
        "2.当前网络有向链路及频谱资源状态：",
        "",
        f"网络节点编号范围：{nodes[0]}～{nodes[-1]}，共{len(nodes)}个节点。",
        "",
    ]
    for link_id in sorted(links):
        link = links[link_id]
        bits = list(states[link_id]["slot_availability"])
        if strict_frozen_interface and len(bits) != 320:
            raise ValueError("slot_count must be 320 for frozen natural-language interface")
        ranges = _free_ranges(bits)
        rendered = ",".join(f"[{a},{b}]" for a, b in ranges) if ranges else "无"
        lines.append(
            f"有向链路{link_id}：{int(link['source_node_id'])}→{int(link['destination_node_id'])}；空闲槽位区间：{rendered}。"
        )
    return "\n".join(lines)


def _candidate_path_lines(paths: list[dict]) -> list[str]:
    out: list[str] = []
    for p in sorted(paths, key=lambda x: int(x.get("path_rank", x.get("rank", 0)))):
        rank = int(p.get("path_rank", p.get("rank")))
        out.append(
            f"候选路径{rank}：路径编号path_rank为{rank}，路径节点数组{_compact_array(p['path_node_ids'])}，有向链路数组{_compact_array(p['path_link_ids'])}。"
        )
    return out


def _llm_intent_o1(root: dict) -> str:
    lines = ["1.业务请求意图：", "", "请同时为以下业务请求建立业务连接：", ""]
    for req in root["requests"]:
        fixed = req["fixed_path"]
        lines.append(
            f"业务请求{req['request_id']}：请为节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 建立一项业务，需要连续使用 {int(req['required_slots'])} 个频谱槽位。该业务请求的固定传输路径为：路径节点数组{_compact_array(fixed['path_node_ids'])}，有向链路数组{_compact_array(fixed['path_link_ids'])}。"
        )
        lines.append("")
    lines.append("请你做出决策，优先输出资源分配后全网碎片化程度最低的资源分配方案。")
    return "\n".join(lines)


def _llm_intent_o2s(root: dict) -> str:
    req = root["request"]
    lines = [
        "1.业务请求意图：",
        "",
        f"请为节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 建立一项业务，需要连续使用 {int(req['required_slots'])} 个频谱槽位。请从给定的候选传输路径中选择资源分配方案，优先选择资源分配后全网碎片化程度最低的方案。",
        "",
        "该业务请求可以使用以下候选传输路径：",
    ]
    lines.extend(_candidate_path_lines(root["candidate_paths"]))
    return "\n".join(lines)


def _llm_intent_o2c(root: dict) -> str:
    lines = ["1.业务请求意图：", "", "请同时为以下业务请求建立业务连接："]
    for req in root["requests"]:
        lines.extend([
            f"业务请求{req['request_id']}：请为节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 建立一项业务，需要连续使用 {int(req['required_slots'])} 个频谱槽位。",
            "该业务请求可以使用以下候选传输路径：",
        ])
        lines.extend(_candidate_path_lines(req["candidate_paths"]))
        lines.append("")
    lines.append("请你优先选择资源分配后全网碎片化程度最低的方案。")
    return "\n".join(lines)


def _llm_intent_x2(root: dict) -> str:
    req = root["request"]
    return (
        f"1.业务请求意图：请为节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 建立一项业务，需要连续使用 {int(req['required_slots'])} 个频谱槽位。"
        "分配优先选择最小化路径跳数的方案，跳数相同时，优先选择资源分配后全网碎片化程度最低的方案。"
    )


def _llm_intent_x3(root: dict) -> str:
    lines = ["1.业务请求意图：", "", "请同时为以下业务请求建立业务连接："]
    for req in root["requests"]:
        lines.append(
            f"业务请求{req['request_id']}：请为节点 {int(req['source_node_id'])} 到节点 {int(req['destination_node_id'])} 建立一项业务，需要连续使用 {int(req['required_slots'])} 个频谱槽位。"
        )
    lines.extend(["", "分配优先选择最小化总槽位数的方案，总槽位数相同时，优先选择资源分配后全网碎片程度最低的方案。"])
    return "\n".join(lines)


_LLM_INTENT_RENDERERS = {
    "O1": _llm_intent_o1,
    "O2-S": _llm_intent_o2s,
    "O2-C": _llm_intent_o2c,
    "X2": _llm_intent_x2,
    "X3": _llm_intent_x3,
}
def render_llm_prompt(root_case: dict, *, strict_frozen_interface: bool = True) -> str:
    _validate_frozen_interface(root_case, strict_frozen_interface)
    task = str(root_case["task_type"])
    return "\n\n".join(
        (
            _LLM_INTENT_RENDERERS[task](root_case),
            _network_text(root_case, strict_frozen_interface=strict_frozen_interface),
        )
    )


def render_benchmark_prompt(root_case: dict, *, strict_frozen_interface: bool = True) -> str:
    """Compatibility alias for the LLM endpoint prompt."""
    return render_llm_prompt(root_case, strict_frozen_interface=strict_frozen_interface)


def build_benchmark_views(
    root_case: dict,
    reference_output: dict,
    *,
    strict_frozen_interface: bool = True,
    instance: dict | None = None,
) -> dict:
    llm_prompt = render_llm_prompt(root_case, strict_frozen_interface=strict_frozen_interface)
    case_id = str(root_case["case_id"])
    benchmark_case = {"case_id": case_id}
    if instance is not None:
        benchmark_case["instance"] = deepcopy(instance)
    benchmark_case["llm_prompt"] = llm_prompt
    benchmark_case["reference"] = deepcopy(reference_output)
    return {
        "benchmark_case": benchmark_case,
        "llm_case": {"case_id": case_id, "prompt": llm_prompt},
    }
