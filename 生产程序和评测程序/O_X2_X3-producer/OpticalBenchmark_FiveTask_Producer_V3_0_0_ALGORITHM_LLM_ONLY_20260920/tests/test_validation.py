import copy
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.scenario_assembly.core import assemble_scenarios
from src.pipeline import run_pipeline
from src.validation.core import validate_base_scenario, validate_environment, validate_path


def indexes():
    return {
        "topology_id": "top_0001", "resource_state_id": "rs_0001",
        "initial_existing_connection_set_id": "icset_0001",
        "single_request_id": "req_0001", "concurrent_request_set_id": "reqset_0001",
        "dynamic_request_sequence_id": "seq_0001",
    }


def test_scenario_assembly_covers_four_types_and_pairs_state_ids():
    scenes = assemble_scenarios(indexes())
    assert [s["request_data_type"] for s in scenes] == ["NONE", "SINGLE", "CONCURRENT", "DYNAMIC"]
    assert "resource_state_id" not in scenes[0]
    assert all(("resource_state_id" in s) == ("initial_existing_connection_set_id" in s) for s in scenes)


def test_path_validation_rejects_wrong_direction_and_discontinuity():
    directed = {0: {"source_node_id": 0, "destination_node_id": 1},
                1: {"source_node_id": 2, "destination_node_id": 1}}
    with pytest.raises(ValueError, match="continuity"):
        validate_path(0, 1, [1], directed)
    with pytest.raises(ValueError, match="continuity"):
        validate_path(0, 1, [0, 1], directed)


def test_base_scenario_rejects_unpaired_state_and_wrong_type():
    scene = {"base_scenario_id":"b","topology_id":"t","resource_state_id":"r",
             "request_data_type":"NONE"}
    with pytest.raises(ValueError, match="paired"):
        validate_base_scenario(scene, {}, {}, {}, {}, {})
    scene = {"base_scenario_id":"b","topology_id":"t","request_data_type":"SINGLE",
             "request_data_id":"set"}
    with pytest.raises(ValueError, match="request"):
        validate_base_scenario(scene, {}, {}, {}, {"set":{}}, {})


@pytest.mark.parametrize("fixture", [
    "release_time.json", "required_slots_4.json", "initial_resource_state_id.json",
    "initial_existing_connection_set_id.json",
])
def test_destructive_dynamic_fields_are_schema_rejected(fixture):
    input_root=Path(__file__).resolve().parents[1]
    schema=json.loads((input_root/"schemas/dynamic_request_sequence.schema.json").read_text(encoding="utf-8"))
    instance=json.loads((input_root/"examples/invalid/dynamic_request_sequence"/fixture).read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(instance))


def test_destructive_wrong_directed_mapping_and_state_reconstruction_are_detected(tmp_path):
    input_root=Path(__file__).resolve().parents[1]
    good=tmp_path/"good"; run_pipeline(input_root,good)
    wrong_map=tmp_path/"wrong_map"; shutil.copytree(good,wrong_map)
    p=wrong_map/"public_environment/topologies/directed/top_0001.json"
    data=json.loads(p.read_text(encoding="utf-8")); data["directed_link_records"][0]["destination_node_id"]=13
    p.write_text(json.dumps(data),encoding="utf-8")
    assert not validate_environment(wrong_map/"public_environment")["pass"]
    wrong_state=tmp_path/"wrong_state"; shutil.copytree(good,wrong_state)
    p=wrong_state/"public_environment/states/spectrum/rs_0001.json"
    data=json.loads(p.read_text(encoding="utf-8")); data["link_spectrum_states"][0]["slot_availability"][0]^=1
    p.write_text(json.dumps(data),encoding="utf-8")
    result=validate_environment(wrong_state/"public_environment")
    assert result["state_reconstruction_pass"] is False
