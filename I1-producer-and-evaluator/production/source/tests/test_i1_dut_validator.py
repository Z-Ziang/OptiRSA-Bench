from __future__ import annotations

from src.i1.validator import validate_i1_output


def _single_answer():
    return {
        "intent_type": "SINGLE",
        "source_node_id": 1,
        "destination_node_id": 6,
        "required_slots": 9,
        "objectives": ["MIN-FRAGMENTATION"],
    }


def test_strict_json_exact_semantics_is_full_pass():
    raw = '{"intent_type":"SINGLE","source_node_id":1,"destination_node_id":6,"required_slots":9,"objectives":["MIN-FRAGMENTATION"]}'
    result = validate_i1_output(_single_answer(), raw)
    assert result["raw_format_valid"] is True
    assert result["strict_json_parse_success"] is True
    assert result["semantic_json_parse_success"] is True
    assert result["schema_valid"] is True
    assert result["semantic_exact_match"] is True
    assert result["final_case_pass"] is True


def test_markdown_fence_is_format_fail_but_semantic_pass():
    raw = '''```json
{
  "intent_type": "SINGLE",
  "source_node_id": 1,
  "destination_node_id": 6,
  "required_slots": 9,
  "objectives": ["MIN-FRAGMENTATION"]
}
```'''
    result = validate_i1_output(_single_answer(), raw)
    assert result["raw_format_valid"] is False
    assert result["strict_json_parse_success"] is False
    assert result["semantic_json_parse_success"] is True
    assert result["semantic_parse_source"] == "MARKDOWN_FENCE_ONLY"
    assert result["schema_valid"] is True
    assert result["semantic_exact_match"] is True
    assert result["final_case_pass"] is False
    assert result["format_error_type"] == "MARKDOWN_CODE_FENCE"


def test_wrong_objective_is_semantic_fail_even_when_json_valid():
    raw = '{"intent_type":"SINGLE","source_node_id":1,"destination_node_id":6,"required_slots":9,"objectives":["MIN-HOP-COUNT","MIN-FRAGMENTATION"]}'
    result = validate_i1_output(_single_answer(), raw)
    assert result["raw_format_valid"] is True
    assert result["schema_valid"] is True
    assert result["objective_set_accuracy"] is False
    assert result["objective_order_accuracy"] is False
    assert result["semantic_exact_match"] is False
    assert result["final_case_pass"] is False


def test_concurrent_request_mapping_is_scored_separately():
    expected = {
        "intent_type": "CONCURRENT",
        "requests": [
            {"request_id":"req_001","source_node_id":3,"destination_node_id":18,"required_slots":5},
            {"request_id":"req_002","source_node_id":7,"destination_node_id":15,"required_slots":3},
        ],
        "objectives": ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
    }
    raw = '''{
      "intent_type":"CONCURRENT",
      "requests":[
        {"request_id":"req_001","source_node_id":7,"destination_node_id":15,"required_slots":3},
        {"request_id":"req_002","source_node_id":3,"destination_node_id":18,"required_slots":5}
      ],
      "objectives":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"]
    }'''
    result = validate_i1_output(expected, raw)
    assert result["field_results"]["request_count"] is True
    assert result["field_results"]["request_id"] is True
    assert result["field_results"]["request_mapping"] is False
    assert result["semantic_exact_match"] is False


def test_dynamic_time_fields_are_exactly_scored():
    expected = {
        "intent_type":"DYNAMIC",
        "request":{
            "request_id":"dyn_1","source_node_id":3,"destination_node_id":18,
            "required_slots":5,"arrival_time":445.382981448571,"holding_time":4.704381744198
        },
        "objectives":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"],
    }
    raw = '''{"intent_type":"DYNAMIC","request":{"request_id":"dyn_1","source_node_id":3,"destination_node_id":18,"required_slots":5,"arrival_time":445.382981448572,"holding_time":4.704381744198},"objectives":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]}'''
    result = validate_i1_output(expected, raw)
    assert result["field_results"]["arrival_time"] is False
    assert result["field_results"]["holding_time"] is True
    assert result["semantic_exact_match"] is False
