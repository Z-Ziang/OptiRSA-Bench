import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_o_family_contracts_expose_algorithm_and_llm_only():
    for task in ("O1", "O2-S", "O2-C"):
        base = ROOT / "contracts" / task
        llm = (base / "llm_system_prompt.txt").read_text(encoding="utf-8")
        assert "JSON" in llm and "320" in llm and "频谱碎片程度" in llm
        benchmark = load_json(base / "schemas" / "benchmark_case.schema.json")
        expected = ["case_id", "instance", "llm_prompt", "reference"]
        assert benchmark["required"] == expected
        assert list(benchmark["properties"]) == expected


def test_output_schemas_are_strict_and_match_frozen_public_outputs():
    expected = {
        "O1": {"decision", "allocations"},
        "O2-S": {"decision", "path_rank", "slot_start"},
        "O2-C": {"decision", "allocations"},
    }
    for task, fields in expected.items():
        schema = load_json(ROOT / "contracts" / task / "output_schema.json")
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == fields


def test_task_contracts_keep_scientific_rules():
    o1 = load_json(ROOT / "contracts/O1/task_contract.json")
    o2s = load_json(ROOT / "contracts/O2-S/task_contract.json")
    o2c = load_json(ROOT / "contracts/O2-C/task_contract.json")
    assert o1["batch_semantics"] == "ALL_OR_NOTHING"
    assert o2c["batch_semantics"] == "ALL_OR_NOTHING"
    assert o2s["path_rank_base"] == 1
    assert o2c["path_rank_base"] == 1
    assert o2s["formal_candidate_path_k"] == [2, 3, 5]
    assert o2c["formal_candidate_path_k"] == [2, 3, 5]
    assert o1["metrics"] == ["joint_feasible_decision_accuracy", "wufr_gap"]
    assert o2s["metrics"] == ["feasible_decision_accuracy", "wufr_gap"]
    assert o2c["metrics"] == ["joint_feasible_decision_accuracy", "wufr_gap"]


def test_structured_views_and_llm_schema_remain_available():
    for task in ("O1", "O2-S", "O2-C"):
        for view in ("root_case", "algorithm_case"):
            schema = load_json(ROOT / f"contracts/{task}/schemas/{view}.schema.json")
            assert "required_slots_probabilities" in schema["properties"]
            assert "required_slots_probabilities" in schema["required"]
        schema = load_json(ROOT / f"contracts/{task}/schemas/llm_case.schema.json")
        assert set(schema["properties"]) == {"case_id", "prompt"}
        assert schema["required"] == ["case_id", "prompt"]
