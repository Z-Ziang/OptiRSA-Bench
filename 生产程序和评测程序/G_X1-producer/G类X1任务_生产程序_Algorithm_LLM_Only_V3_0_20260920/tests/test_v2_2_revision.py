import json
def test_g2_wrong_direction_prompt_is_reverse_edge_only():
    from gx1.contracts import system_prompt

    prompt = system_prompt("G2")
    assert "u → v" in prompt and "v → u" in prompt
    assert "12 → 11" in prompt or "u → x" in prompt
    assert "14 → 13" in prompt or "x → v" in prompt


def test_g2_classifier_does_not_expand_wrong_direction_to_endpoint_mismatch():
    from gx1.g2 import classify_g2

    def root(source, destination):
        return {
            "directed_links": [
                {"link_id": 0, "source_node_id": source, "destination_node_id": destination},
            ],
            "candidate_path": {"path_node_ids": [12, 13], "path_link_ids": [0]},
        }

    reverse = root(13, 12)
    assert classify_g2(reverse) == "WRONG_DIRECTION"
    assert classify_g2(root(12, 11)) == "NODE_LINK_MISMATCH"
    assert classify_g2(root(14, 13)) == "NODE_LINK_MISMATCH"


def test_v22_config_is_accepted_and_x1_multiple_has_private_evidence(tmp_path, weighted_topology_file):
    from gx1.production import produce_batch, verify_output_tree

    cfg = tmp_path / "v22.json"
    cfg.write_text(json.dumps({
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_2",
        "batch_id": "V22_TEST",
        "seed": 20260912,
        "topologies": [str(weighted_topology_file)],
        "case_counts": {"G1": 0, "G2": 0, "G3": 0, "X1": 1},
        "tasks": {"G1": {}, "G2": {}, "G3": {}, "X1": {
            "metric_schedule": ["HOP_COUNT"],
            "multiplicity_schedule": ["MULTIPLE"],
            "min_hops": 1,
            "max_hops": 6,
        }},
    }), encoding="utf-8")
    out = tmp_path / "out"
    produce_batch(cfg, out)
    assert verify_output_tree(out)["valid"] is True
    root = json.loads((out / "cases" / "X1" / "X1_000001" / "root_case.json").read_text(encoding="utf-8"))
    evidence = root["oracle_evidence"]
    assert evidence["shortest_path_multiplicity"] > 1
    assert len(evidence["optimal_paths"]) >= 2
    assert all("path_node_ids" in p and "path_link_ids" in p and "cost" in p for p in evidence["optimal_paths"])


def test_x1_validator_accepts_another_evidenced_optimal_path(tmp_path, weighted_topology_file):
    from gx1.production import produce_batch
    from gx1.validators import validate_dut_output

    cfg = tmp_path / "v22.json"
    cfg.write_text(json.dumps({
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_2",
        "batch_id": "V22_X1_ALT",
        "seed": 1,
        "topologies": [str(weighted_topology_file)],
        "case_counts": {"G1": 0, "G2": 0, "G3": 0, "X1": 1},
        "tasks": {"G1": {}, "G2": {}, "G3": {}, "X1": {"metric_schedule": ["HOP_COUNT"], "multiplicity_schedule": ["MULTIPLE"], "min_hops": 1, "max_hops": 6}},
    }), encoding="utf-8")
    out = tmp_path / "out"
    produce_batch(cfg, out)
    case = out / "cases" / "X1" / "X1_000001"
    root = json.loads((case / "root_case.json").read_text(encoding="utf-8"))
    alternate = next(p for p in root["oracle_evidence"]["optimal_paths"] if p["path_link_ids"] != root["answer"]["path_link_ids"])
    answer = {"path_node_ids": alternate["path_node_ids"], "path_link_ids": alternate["path_link_ids"], "hop_count": len(alternate["path_link_ids"])}
    assert validate_dut_output(root, json.dumps(answer))['valid'] is True
