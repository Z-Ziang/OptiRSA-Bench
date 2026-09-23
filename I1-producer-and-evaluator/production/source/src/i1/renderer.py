from __future__ import annotations


def _fmt_num(x) -> str:
    if isinstance(x, int):
        return str(x)
    return str(float(x))


def _objective_text(objectives: list[str], intent_type: str) -> str:
    key = tuple(objectives)
    table = {
        ("MIN-HOP-COUNT", "MIN-FRAGMENTATION"):
            "资源分配时，优先选择路径跳数最少的方案；当路径跳数相同时，优先选择资源分配后全网频谱碎片程度最低的方案。",
        ("MIN-FRAGMENTATION",):
            ("联合资源分配时，优先选择资源分配后全网频谱碎片程度最低的方案。" if intent_type == "CONCURRENT"
             else "资源分配时，优先选择资源分配后全网频谱碎片程度最低的方案。"),
        ("MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"):
            "联合资源分配时，优先选择全部业务请求占用总槽位数最少的方案；总槽位数相同时，优先选择资源分配后全网频谱碎片程度最低的方案。",
        ("MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"):
            "在整条动态业务请求序列中，首要目标是尽量提高成功建立的业务请求数量；在此前提下，再尽量降低网络外部频谱碎片程度。",
    }
    if key not in table:
        raise ValueError(f"no frozen natural-language objective template for {key}")
    return table[key]


def render_base_prompt(answer: dict) -> str:
    kind = answer["intent_type"]
    if kind == "SINGLE":
        head = (
            f"请为节点{answer['source_node_id']}到节点{answer['destination_node_id']}建立一项业务连接，"
            f"该业务请求需要连续使用{answer['required_slots']}个频谱槽位。"
        )
        return head + _objective_text(answer["objectives"], kind)
    if kind == "CONCURRENT":
        lines = ["请同时为以下业务请求建立业务连接："]
        for r in answer["requests"]:
            lines.append(
                f"业务请求{r['request_id']}：请为节点{r['source_node_id']}到节点{r['destination_node_id']}建立一项业务，"
                f"需要连续使用{r['required_slots']}个频谱槽位。"
            )
        lines.append(_objective_text(answer["objectives"], kind))
        return "\n".join(lines)
    if kind == "DYNAMIC":
        r = answer["request"]
        return (
            f"当前时刻为{_fmt_num(r['arrival_time'])}。请为业务请求{r['request_id']}建立一项从节点{r['source_node_id']}到节点{r['destination_node_id']}的业务连接，"
            f"该请求需要连续使用{r['required_slots']}个频谱槽位，业务连接持续时长为{_fmt_num(r['holding_time'])}。"
            + _objective_text(answer["objectives"], kind)
        )
    raise ValueError(f"unknown intent_type: {kind}")
