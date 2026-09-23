from __future__ import annotations

import json

import pytest


def _base_root(task: str) -> dict:
    free = [1] * 320
    for i in range(4, 7):
        free[i] = 0
    none_free = [0] * 320
    links = [
        {"link_id": 2, "source_node_id": 1, "destination_node_id": 2},
        {"link_id": 1, "source_node_id": 1, "destination_node_id": 0},
        {"link_id": 0, "source_node_id": 0, "destination_node_id": 1},
    ]
    common = {
        "case_id": f"{task.replace('-', '')}_TEST",
        "task_type": task,
        "topology_id": "top_test",
        "resource_state_id": "rs_test",
        "nodes": [2, 0, 1],
        "directed_links": links,
        "slot_count": 320,
        "link_spectrum_states": [
            {"link_id": 2, "slot_availability": none_free},
            {"link_id": 0, "slot_availability": free},
            {"link_id": 1, "slot_availability": [1] * 320},
        ],
        "required_slots_probabilities": {"2": .25, "3": .25, "5": .25, "9": .25},
    }
    if task == "O1":
        common["requests"] = [
            {"request_id": "req_001", "source_node_id": 0, "destination_node_id": 2, "required_slots": 5,
             "fixed_path": {"path_node_ids": [0, 1, 2], "path_link_ids": [0, 2]}},
            {"request_id": "req_002", "source_node_id": 1, "destination_node_id": 2, "required_slots": 3,
             "fixed_path": {"path_node_ids": [1, 2], "path_link_ids": [2]}},
        ]
    elif task == "O2-S":
        common["request"] = {"request_id": "req_001", "source_node_id": 0, "destination_node_id": 2, "required_slots": 5}
        common["candidate_paths"] = [
            {"path_rank": 1, "path_node_ids": [0, 1, 2], "path_link_ids": [0, 2]},
            {"path_rank": 2, "path_node_ids": [0, 2], "path_link_ids": [9]},
        ]
    elif task == "O2-C":
        common["requests"] = [
            {"request_id": "req_001", "source_node_id": 0, "destination_node_id": 2, "required_slots": 5,
             "candidate_paths": [{"path_rank": 1, "path_node_ids": [0, 1, 2], "path_link_ids": [0, 2]}]},
            {"request_id": "req_002", "source_node_id": 1, "destination_node_id": 2, "required_slots": 3,
             "candidate_paths": [{"path_rank": 1, "path_node_ids": [1, 2], "path_link_ids": [2]}]},
        ]
    elif task == "X2":
        common["request"] = {"request_id": "req_001", "source_node_id": 0, "destination_node_id": 2, "required_slots": 5}
    elif task == "X3":
        common["requests"] = [
            {"request_id": "req_001", "source_node_id": 0, "destination_node_id": 2, "required_slots": 5},
            {"request_id": "req_002", "source_node_id": 1, "destination_node_id": 2, "required_slots": 3},
        ]
    return common


def test_llm_renderer_uses_merged_compact_lossless_network_section():
    from src.case_core.natural_language_renderer import render_llm_prompt

    prompt = render_llm_prompt(_base_root("X2"))
    assert prompt.startswith(
        "1.业务请求意图：请为节点 0 到节点 2 建立一项业务，需要连续使用 5 个频谱槽位。"
        "分配优先选择最小化路径跳数的方案，跳数相同时，优先选择资源分配后全网碎片化程度最低的方案。"
    )
    assert "2.当前网络有向链路及频谱资源状态：" in prompt
    assert "网络节点编号范围：0～2，共3个节点。" in prompt
    line0 = "有向链路0：0→1；空闲槽位区间：[0,3],[7,319]。"
    line1 = "有向链路1：1→0；空闲槽位区间：[0,319]。"
    line2 = "有向链路2：1→2；空闲槽位区间：无。"
    assert line0 in prompt and line1 in prompt and line2 in prompt
    assert prompt.index(line0) < prompt.index(line1) < prompt.index(line2)
    assert "当前网络有向拓扑" not in prompt
    assert "3.当前每条有向链路的频谱资源状态" not in prompt


def test_task_specific_llm_business_intent_wording_is_frozen():
    from src.case_core.natural_language_renderer import render_llm_prompt

    o1 = render_llm_prompt(_base_root("O1"))
    assert "该业务请求的固定传输路径为：路径节点数组[0,1,2]，有向链路数组[0,2]。" in o1
    assert "请你做出决策，优先输出资源分配后全网碎片化程度最低的资源分配方案。" in o1

    o2s = render_llm_prompt(_base_root("O2-S"))
    assert "请从给定的候选传输路径中选择资源分配方案，优先选择资源分配后全网碎片化程度最低的方案。" in o2s
    assert "候选路径1：路径编号path_rank为1，路径节点数组[0,1,2]，有向链路数组[0,2]。" in o2s

    o2c = render_llm_prompt(_base_root("O2-C"))
    assert "请同时为以下业务请求建立业务连接：" in o2c
    assert "请你优先选择资源分配后全网碎片化程度最低的方案。" in o2c

    x3 = render_llm_prompt(_base_root("X3"))
    assert "分配优先选择最小化总槽位数的方案，总槽位数相同时，优先选择资源分配后全网碎片程度最低的方案。" in x3


def test_renderer_rejects_non_320_slot_case():
    from src.case_core.natural_language_renderer import render_llm_prompt

    root = _base_root("X2")
    root["slot_count"] = 80
    with pytest.raises(ValueError, match="slot_count must be 320"):
        render_llm_prompt(root)


def test_benchmark_runtime_views_keep_reference_out_of_llm_input():
    from src.case_core.natural_language_renderer import build_benchmark_views

    root = _base_root("X2")
    reference = {"decision": "ACCEPT", "path_node_ids": [0, 1, 2], "path_link_ids": [0, 2], "slot_start": 10}
    views = build_benchmark_views(root, reference)
    assert views["benchmark_case"] == {
        "case_id": "X2_TEST",
        "llm_prompt": views["llm_case"]["prompt"],
        "reference": reference,
    }
    assert views["llm_case"] == {"case_id": "X2_TEST", "prompt": views["benchmark_case"]["llm_prompt"]}
    assert set(views) == {"benchmark_case", "llm_case"}
    assert "reference" not in json.dumps(views["llm_case"], ensure_ascii=False)
