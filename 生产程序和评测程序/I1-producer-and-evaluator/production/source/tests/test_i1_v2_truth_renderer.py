from __future__ import annotations
from src.i1.truth import build_single_answer, build_concurrent_answer, build_dynamic_answer
from src.i1.renderer import render_base_prompt


def test_single_truth_and_prompt_match_reviewed_contract():
    req = {"request_id":"req_001","source_node_id":3,"destination_node_id":18,"required_slots":5}
    ans = build_single_answer(req, ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"])
    assert ans == {
        "intent_type":"SINGLE",
        "source_node_id":3,
        "destination_node_id":18,
        "required_slots":5,
        "objectives":["MIN-HOP-COUNT","MIN-FRAGMENTATION"],
    }
    prompt = render_base_prompt(ans)
    assert "节点3到节点18" in prompt
    assert "5个频谱槽位" in prompt
    assert "路径跳数最少" in prompt
    assert "全网频谱碎片程度最低" in prompt


def test_concurrent_truth_preserves_request_mapping_and_order():
    reqs = [
        {"request_id":"req_001","source_node_id":3,"destination_node_id":18,"required_slots":5},
        {"request_id":"req_002","source_node_id":7,"destination_node_id":15,"required_slots":3},
    ]
    ans = build_concurrent_answer(reqs, ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"])
    assert [r["request_id"] for r in ans["requests"]] == ["req_001","req_002"]
    assert ans["requests"][1]["destination_node_id"] == 15
    prompt = render_base_prompt(ans)
    assert prompt.index("req_001") < prompt.index("req_002")
    assert "总槽位数最少" in prompt


def test_dynamic_truth_keeps_arrival_holding_and_omits_release_order():
    req = {"request_id":"req_000057","source_node_id":3,"destination_node_id":18,"required_slots":5,"arrival_time":86.42,"holding_time":12.70}
    ans = build_dynamic_answer(req, ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"])
    assert ans["request"]["arrival_time"] == 86.42
    assert ans["request"]["holding_time"] == 12.70
    assert "release_time" not in ans["request"]
    assert "arrival_order" not in ans["request"]
    prompt = render_base_prompt(ans)
    assert "当前时刻为86.42" in prompt
    assert "持续时长为12.7" in prompt


def test_dynamic_renderer_preserves_full_numeric_value_without_rounding():
    req = {"request_id":"dynreq_1","source_node_id":9,"destination_node_id":1,"required_slots":2,"arrival_time":445.382981448571,"holding_time":4.704381744198}
    ans = build_dynamic_answer(req, ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"])
    prompt = render_base_prompt(ans)
    assert "445.382981448571" in prompt
    assert "4.704381744198" in prompt


def test_concurrent_fragmentation_only_prompt_uses_joint_allocation_wording():
    reqs = [
        {"request_id":"req_001","source_node_id":3,"destination_node_id":18,"required_slots":5},
        {"request_id":"req_002","source_node_id":7,"destination_node_id":15,"required_slots":3},
    ]
    ans = build_concurrent_answer(reqs, ["MIN-FRAGMENTATION"])
    prompt = render_base_prompt(ans)
    assert "联合资源分配时" in prompt
