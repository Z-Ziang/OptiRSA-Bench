import json

import pytest

from trial.output_format import (
    OutputFormatError,
    apply_response_format,
    build_case_response_schema,
    build_preflight_response_schema,
    normalize_output_format_config,
    payload_forbidden_key_hits,
    response_format_for_case,
    validate_json_output,
)


def _root(task="G2", **extra):
    root = {
        "case_id": f"{task}_000001",
        "task_type": task,
        "nodes": [{"node_id": n} for n in range(4)],
        "path_cost_metric": "HOP_COUNT",
        "conversion": "EDGE_LIST_TO_ADJACENCY_LIST",
    }
    root.update(extra)
    return root


def test_json_object_and_schema_modes_are_explicit_and_validated():
    object_cfg = normalize_output_format_config({"mode": "json_object", "strict": True})
    assert response_format_for_case(_root(), object_cfg) == {"type": "json_object"}

    schema_cfg = normalize_output_format_config({"mode": "json_schema", "strict": True})
    response_format = response_format_for_case(_root(), schema_cfg)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert "answer" not in json.dumps(schema)
    assert "truth" not in json.dumps(schema)
    assert set(object_cfg) == {"mode", "strict", "preflight"}


def test_case_schema_is_task_specific_without_truth_values():
    g1 = build_case_response_schema(
        _root("G1", conversion="ADJACENCY_MATRIX_TO_EDGE_LIST")
    )
    g3 = build_case_response_schema(
        _root("G3", conversion=None, pairs=[{"pair_id": "pair_A"}, {"pair_id": "pair_B"}])
    )
    x1 = build_case_response_schema(_root("X1", conversion=None))
    assert g1["properties"]["representation_type"]["enum"] == ["EDGE_LIST"]
    assert "shortest_paths" in g3["required"]
    assert "path_node_ids" in x1["required"]
    assert "oracle" not in json.dumps({"g1": g1, "g3": g3, "x1": x1}).lower()


def test_preflight_schema_is_small_and_strict():
    schema = build_preflight_response_schema()
    assert schema == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }


def test_response_format_cannot_be_silently_overridden():
    cfg = normalize_output_format_config({"mode": "json_schema", "strict": True})
    with pytest.raises(OutputFormatError, match="response_format"):
        apply_response_format({"response_format": {"type": "json_object"}}, _root(), cfg)


def test_local_json_validation_distinguishes_parse_and_schema_errors():
    cfg = normalize_output_format_config({"mode": "json_schema", "strict": True})
    valid = validate_json_output('{"is_valid":true,"error_type":null}', _root(), cfg)
    assert valid["json_parse_valid"] is True
    assert valid["schema_valid"] is True

    invalid_json = validate_json_output("```json\n{}\n```", _root(), cfg)
    assert invalid_json["json_parse_valid"] is False
    assert invalid_json["schema_valid"] is False

    invalid_shape = validate_json_output('{"is_valid":true}', _root(), cfg)
    assert invalid_shape["json_parse_valid"] is True
    assert invalid_shape["schema_valid"] is False


def test_payload_boundary_scan_checks_nested_model_messages_and_results():
    payload = {
        "messages": [{"role": "assistant", "content": json.dumps({"truth": {}, "reference": {}})}],
    }
    hits = payload_forbidden_key_hits(payload)
    assert {hit["key"] for hit in hits} == {"truth", "reference"}

