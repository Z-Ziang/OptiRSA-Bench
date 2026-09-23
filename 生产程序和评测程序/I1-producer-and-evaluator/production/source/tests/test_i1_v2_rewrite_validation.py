from __future__ import annotations
from src.i1.validators import validate_rewrite


def _ans():
    return {
        "intent_type":"CONCURRENT",
        "requests":[
            {"request_id":"req_001","source_node_id":3,"destination_node_id":18,"required_slots":5},
            {"request_id":"req_002","source_node_id":7,"destination_node_id":15,"required_slots":3},
        ],
        "objectives":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"],
    }


def test_valid_rewrite_passes_with_roundtrip_parser():
    text = "请同时建立两项业务：req_001从节点3到节点18，需要连续5个频谱槽位；req_002从节点7到节点15，需要连续3个频谱槽位。优先使总槽位数最少，在此基础上再使全网频谱碎片程度最低。"
    result = validate_rewrite(_ans(), text, semantic_parser=lambda _: _ans())
    assert result["overall"] == "PASS"


def test_swapped_concurrent_mapping_fails_even_if_all_literals_exist():
    text = "请同时建立两项业务：req_001从节点7到节点15，需要连续3个频谱槽位；req_002从节点3到节点18，需要连续5个频谱槽位。优先使总槽位数最少，在此基础上再使全网频谱碎片程度最低。"
    result = validate_rewrite(_ans(), text, semantic_parser=lambda _: {
        **_ans(),
        "requests":[_ans()["requests"][1], _ans()["requests"][0]],
    })
    assert result["overall"] == "FAIL"
    assert result["semantic_roundtrip"] == "FAIL"


def test_dynamic_roundtrip_rejects_even_small_time_change():
    answer = {
        "intent_type":"DYNAMIC",
        "request":{
            "request_id":"dyn_1","source_node_id":3,"destination_node_id":18,"required_slots":5,
            "arrival_time":445.382981448571,"holding_time":4.704381744198
        },
        "objectives":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]
    }
    text = "当前时刻为445.382981448571。请为业务请求dyn_1建立从节点3到节点18的业务连接，需要连续使用5个频谱槽位，持续时长为4.704381744198。应尽量提高成功建立业务请求数量，并降低网络外部频谱碎片程度。"
    parsed = {
        **answer,
        "request": {**answer["request"], "arrival_time": 445.382981448572}
    }
    result = validate_rewrite(answer, text, semantic_parser=lambda _: parsed)
    assert result["semantic_roundtrip"] == "FAIL"
    assert result["overall"] == "FAIL"


def test_single_objective_rejects_orphan_tiebreak_language_even_if_parser_echoes_truth():
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 1,
        "destination_node_id": 6,
        "required_slots": 9,
        "objectives": ["MIN-FRAGMENTATION"],
    }
    text = "首先，为节点1和节点6之间建立一条业务连接；该连接需要占用连续的9个频谱槽位。若相同，再考虑资源分配方案，优先选择使全网频谱碎片程度最低的方案。"
    result = validate_rewrite(answer, text, semantic_parser=lambda _: answer)
    assert result["objective_semantics"] == "FAIL"
    assert result["overall"] == "FAIL"
    assert any("orphan objective-priority language" in e for e in result["errors"])


def test_single_objective_allows_plain_single_goal_language():
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 1,
        "destination_node_id": 6,
        "required_slots": 9,
        "objectives": ["MIN-FRAGMENTATION"],
    }
    text = "请从节点1到节点6建立业务连接，需要连续使用9个频谱槽位；资源分配时优先选择使全网频谱碎片程度最低的方案。"
    result = validate_rewrite(answer, text, semantic_parser=lambda _: answer)
    assert result["objective_semantics"] == "PASS"
    assert result["overall"] == "PASS"
