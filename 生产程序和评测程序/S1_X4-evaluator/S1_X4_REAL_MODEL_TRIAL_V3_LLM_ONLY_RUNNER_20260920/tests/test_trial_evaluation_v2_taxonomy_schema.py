from __future__ import annotations


def test_action_schema_has_only_official_s1_and_x4_fields():
    from trial_evaluation.v2.action_schemas import action_schema

    s1 = action_schema("S1")
    x4 = action_schema("X4")
    assert s1["oneOf"][0]["required"] == ["decision", "path_rank", "slot_start"]
    assert set(s1["oneOf"][0]["properties"]) == {"decision", "path_rank", "slot_start"}
    assert set(x4["oneOf"][0]["properties"]) == {"decision", "path_node_ids", "path_link_ids", "slot_start"}
    assert "candidate_actions" not in str(s1)
    assert "reference" not in str(x4).lower()


def test_parser_accepts_schema_valid_s1_reject_and_x4_accept():
    from trial_evaluation.v2.structured_output import StructuredActionParser

    s1 = StructuredActionParser("S1").parse(
        '{"decision":"REJECT","path_rank":null,"slot_start":null}',
        finish_reason="stop",
    )
    x4 = StructuredActionParser("X4").parse(
        '{"decision":"ACCEPT","path_node_ids":[1,2],"path_link_ids":[7],"slot_start":3}',
        finish_reason="stop",
    )
    assert s1.protocol_status == "OK"
    assert s1.action["decision"] == "REJECT"
    assert x4.protocol_status == "OK"
    assert x4.action["slot_start"] == 3


def test_parser_classifies_non_decision_output_without_repairing_text():
    from trial_evaluation.v2.structured_output import StructuredActionParser

    cases = [
        ("", "PROTOCOL_EMPTY_OUTPUT"),
        ("{\"decision\":", "PROTOCOL_INVALID_JSON"),
        ("Here is the action: {\"decision\":\"REJECT\"}", "PROTOCOL_EXTRA_TEXT"),
        ("```json\n{\"decision\":\"REJECT\"}\n```", "PROTOCOL_EXTRA_TEXT"),
    ]
    for text, expected in cases:
        result = StructuredActionParser("S1").parse(text, finish_reason="stop")
        assert result.protocol_status == "PROTOCOL_FAILURE"
        assert result.code == expected
        assert result.action is None


def test_parser_classifies_truncation_before_json_parsing_and_schema_violation():
    from trial_evaluation.v2.structured_output import StructuredActionParser

    truncated = StructuredActionParser("X4").parse("", finish_reason="length")
    extra_field = StructuredActionParser("S1").parse(
        '{"decision":"REJECT","path_rank":null,"slot_start":null,"extra":1}',
        finish_reason="stop",
    )
    assert truncated.code == "PROTOCOL_TRUNCATED"
    assert extra_field.code == "PROTOCOL_SCHEMA_VIOLATION"
