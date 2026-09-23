from __future__ import annotations

from typing import Any


def _fmt_nodes(nodes: list[int]) -> str:
    return "、".join(str(x) for x in nodes)


def _fmt_edge_list(edges: list[list[int]]) -> str:
    return "[\n" + ",\n".join(f"  [{a},{b}]" for a, b in edges) + "\n]"


def _fmt_adj(adj: dict[str, list[int]]) -> str:
    lines = []
    keys = list(adj.keys())
    for i, k in enumerate(keys):
        vals = ",".join(str(x) for x in adj[k])
        comma = "," if i < len(keys)-1 else ""
        lines.append(f'  "{k}": [{vals}]{comma}')
    return "{\n" + "\n".join(lines) + "\n}"


def _fmt_matrix(matrix: list[list[int]]) -> str:
    return "[\n" + ",\n".join("  [" + ",".join(str(x) for x in row) + "]" for row in matrix) + "\n]"


def _g1_prompt(root: dict[str, Any]) -> str:
    src = root["source_representation"]
    tgt = root["target_representation"]
    cn = {"EDGE_LIST": "边列表", "ADJACENCY_LIST": "邻接表", "ADJACENCY_MATRIX": "邻接矩阵"}
    lines = [f"请将下面的无向光网络拓扑从{cn[src]}转换为{cn[tgt]}。", ""]
    if src == "EDGE_LIST":
        if tgt == "ADJACENCY_MATRIX":
            lines.append("节点顺序：[" + ",".join(map(str, root["nodes"])) + "]。")
        else:
            lines.append("网络包含节点：" + _fmt_nodes(root["nodes"]) + "。")
        lines += ["", "当前边列表：", _fmt_edge_list(root["source_payload"])]
    elif src == "ADJACENCY_LIST":
        if tgt == "ADJACENCY_MATRIX":
            lines.append("节点顺序：[" + ",".join(map(str, root["nodes"])) + "]。")
        else:
            lines.append("网络包含节点：" + _fmt_nodes(root["nodes"]) + "。")
        lines += ["", "当前邻接表：", _fmt_adj(root["source_payload"])]
    else:
        lines.append("节点顺序：[" + ",".join(map(str, root["nodes"])) + "]。")
        lines += ["", "当前邻接矩阵：", _fmt_matrix(root["source_payload"])]
    if tgt == "EDGE_LIST":
        lines += ["", "请按照系统提示词规定的格式输出边列表。每条无向边只输出一次。"]
    elif tgt == "ADJACENCY_LIST":
        lines += ["", "请按照系统提示词规定的格式输出完整邻接表。"]
    else:
        lines += ["", "请按照给定节点顺序生成邻接矩阵，并按照系统提示词规定的格式输出。"]
    return "\n".join(lines)


def _directed_lines(root: dict[str, Any]) -> list[str]:
    metric = root.get("path_cost_metric")
    out = []
    for x in root["directed_links"]:
        line = f"有向链路{x['link_id']}：节点{x['source_node_id']} 指向 节点{x['destination_node_id']}"
        if metric == "TOTAL_LENGTH_KM":
            line += f"，长度{x['length_km']:g} km"
        out.append(line + "；")
    if out:
        out[-1] = out[-1][:-1] + "。"
    return out


def _g2_llm_prompt(root: dict[str, Any]) -> str:
    p = root["candidate_path"]
    return "\n".join([
        f"请判断下面的候选路径是否为当前有向光网络拓扑中，从节点{root['source_node_id']}到节点{root['destination_node_id']}的一条简单有向路径。",
        "", "当前网络包含节点：" + _fmt_nodes(root["nodes"]) + "。", "", "当前有向链路:",
        *_directed_lines(root), "", "候选路径：",
        f"源节点：{root['source_node_id']}；", f"目的节点：{root['destination_node_id']}；",
        "路径节点数组：[" + ",".join(map(str, p["path_node_ids"])) + "]；",
        "有向链路数组：[" + ",".join(map(str, p["path_link_ids"])) + "]。", "",
        "请按照系统提示词中的 FIRST_MATCH 顺序判断路径是否合规。"
    ])


def _g3_prompt(root: dict[str, Any]) -> str:
    metric_cn = "最小化路径总公里长度" if root["path_cost_metric"] == "TOTAL_LENGTH_KM" else "最小化路径跳数"
    a, b = root["pairs"]
    lines = [
        f"请在当前有向光网络拓扑中，分别求出两对源宿节点之间的最短路径，并判断两条最短路径是否共享至少一条完全相同的有向链路。最短路径指标为{metric_cn}。",
        "", "当前网络包含节点：" + _fmt_nodes(root["nodes"]) + "。"
    ]
    lines += ["", "当前有向链路：", *_directed_lines(root)]
    lines += ["", "两对源宿节点为：",
              f"pair_A：节点{a['source_node_id']} 到 节点{a['destination_node_id']}；",
              f"pair_B：节点{b['source_node_id']} 到 节点{b['destination_node_id']}。", "",
              "请分别输出 pair_A 和 pair_B 的最短路径，并判断两条最短路径是否共享有向链路。如果存在共享有向链路，请输出全部共享有向链路id(link_id)。"]
    return "\n".join(lines)


def _x1_prompt(root: dict[str, Any]) -> str:
    metric_cn = "最小化路径总公里长度" if root["path_cost_metric"] == "TOTAL_LENGTH_KM" else "最小化路径跳数"
    lines = [
        f"请在当前有向光网络拓扑中，寻找从节点{root['source_node_id']}到节点{root['destination_node_id']}的一条全局最短路径。最短路径指标为{metric_cn}。",
        "", "当前网络包含节点：" + _fmt_nodes(root["nodes"]) + "。"
    ]
    lines += ["", "当前有向链路：", *_directed_lines(root)]
    lines += ["", "请按照系统提示词规定的格式输出一条全局最短路径。"]
    return "\n".join(lines)


def render_llm_case(root: dict[str, Any]) -> dict[str, Any]:
    task = root["task_type"]
    if task == "G1": prompt = _g1_prompt(root)
    elif task == "G2": prompt = _g2_llm_prompt(root)
    elif task == "G3": prompt = _g3_prompt(root)
    elif task == "X1": prompt = _x1_prompt(root)
    else: raise ValueError(task)
    return {"case_id": root["case_id"], "prompt": prompt, "answer": root["answer"]}
