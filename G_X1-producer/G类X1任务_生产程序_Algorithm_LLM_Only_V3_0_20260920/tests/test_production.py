import json
from pathlib import Path

from gx1.production import produce_batch, verify_output_tree


def make_config(path, topology_path):
    config = {
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_0",
        "batch_id": "TEST_BATCH",
        "seed": 20260909,
        "topologies": [str(topology_path)],
        "case_counts": {"G1": 2, "G2": 2, "G3": 2, "X1": 2},
        "tasks": {
            "G1": {"conversion_weights": {"EDGE_LIST_TO_ADJACENCY_LIST": 1}},
            "G2": {"label_weights": {"VALID": 1, "WRONG_DIRECTION": 1}, "min_hops": 2, "max_hops": 5},
            "G3": {"metric_weights": {"HOP_COUNT": 1, "TOTAL_LENGTH_KM": 1}, "shared_weights": {"true": 1, "false": 1}, "min_hops": 1, "max_hops": 6},
            "X1": {"metric_weights": {"HOP_COUNT": 1, "TOTAL_LENGTH_KM": 1}, "min_hops": 1, "max_hops": 6},
        },
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def test_batch_production_is_deterministic_and_complete(tmp_path, weighted_topology_file):
    cfg = tmp_path / "cfg.json"
    make_config(cfg, weighted_topology_file)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    m1 = produce_batch(cfg, out1)
    m2 = produce_batch(cfg, out2)
    assert m1["case_counts"] == {"G1": 2, "G2": 2, "G3": 2, "X1": 2}
    files1 = sorted(p.relative_to(out1) for p in out1.rglob("*") if p.is_file())
    files2 = sorted(p.relative_to(out2) for p in out2.rglob("*") if p.is_file())
    assert files1 == files2
    for rel in files1:
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes()
    assert verify_output_tree(out1)["valid"] is True


def test_each_case_directory_contains_llm_algorithm_evidence(tmp_path, weighted_topology_file):
    cfg = tmp_path / "cfg.json"
    make_config(cfg, weighted_topology_file)
    out = tmp_path / "out"
    produce_batch(cfg, out)
    case_dirs = [p for p in out.glob("cases/*/*") if p.is_dir()]
    assert len(case_dirs) == 8
    for d in case_dirs:
        names = {p.name for p in d.iterdir()}
        assert names == {
            "root_case.json", "llm_case.json", "truth.json", "validation_metadata.json",
            "actual_llm_request.json",
        }
        llm = json.loads((d / "llm_case.json").read_text(encoding="utf-8"))
        assert "answer" in llm
        # Actual request payloads are not stored with answer embedded.
        actual_llm = json.loads((d / "actual_llm_request.json").read_text(encoding="utf-8"))
        serialized = json.dumps(actual_llm).lower()
        assert '"answer"' not in serialized and '"truth"' not in serialized and '"oracle' not in serialized
    for task in ["G1", "G2", "G3", "X1"]:
        contract_names = {p.name for p in (out / "contracts" / task).iterdir()}
        assert contract_names == {"system_prompt_llm.txt"}

def test_exact_schedules_control_small_batch_strata(tmp_path, weighted_topology_file):
    cfg = tmp_path / "scheduled.json"
    config = {
        "schema_version": "GX1_PRODUCTION_CONFIG_V2_0",
        "batch_id": "SCHEDULED",
        "seed": 9,
        "topologies": [str(weighted_topology_file)],
        "case_counts": {"G1": 6, "G2": 5, "G3": 4, "X1": 2},
        "tasks": {
            "G1": {"conversion_schedule": [
                "EDGE_LIST_TO_ADJACENCY_LIST", "EDGE_LIST_TO_ADJACENCY_MATRIX",
                "ADJACENCY_LIST_TO_EDGE_LIST", "ADJACENCY_LIST_TO_ADJACENCY_MATRIX",
                "ADJACENCY_MATRIX_TO_EDGE_LIST", "ADJACENCY_MATRIX_TO_ADJACENCY_LIST"]},
            "G2": {"label_schedule": ["VALID", "WRONG_DIRECTION", "DISCONNECTED_PATH", "NODE_LINK_MISMATCH", "REPEATED_NODE"], "min_hops": 2, "max_hops": 6},
            "G3": {"metric_schedule": ["HOP_COUNT", "HOP_COUNT", "TOTAL_LENGTH_KM", "TOTAL_LENGTH_KM"], "shared_schedule": [True, False, True, False], "min_hops": 1, "max_hops": 6},
            "X1": {"metric_schedule": ["HOP_COUNT", "TOTAL_LENGTH_KM"], "min_hops": 1, "max_hops": 6}
        }
    }
    cfg.write_text(json.dumps(config), encoding="utf-8")
    out = tmp_path / "scheduled_out"
    produce_batch(cfg, out)
    def roots(task):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out/"cases"/task).glob("*/root_case.json"))]
    assert [r["conversion"] for r in roots("G1")] == config["tasks"]["G1"]["conversion_schedule"]
    assert [r["oracle_label"] for r in roots("G2")] == config["tasks"]["G2"]["label_schedule"]
    assert [r["path_cost_metric"] for r in roots("G3")] == config["tasks"]["G3"]["metric_schedule"]
    assert [r["answer"]["has_shared_directed_link"] for r in roots("G3")] == config["tasks"]["G3"]["shared_schedule"]
    assert [r["path_cost_metric"] for r in roots("X1")] == config["tasks"]["X1"]["metric_schedule"]
