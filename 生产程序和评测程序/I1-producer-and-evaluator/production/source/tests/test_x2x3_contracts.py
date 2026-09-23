import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_x2x3_contracts_expose_algorithm_and_llm_only():
    for task in ("X2", "X3"):
        base = ROOT / "contracts" / task
        llm = (base / "llm_system_prompt.txt").read_text(encoding="utf-8")
        assert "320" in llm and "JSON" in llm
        llm_schema = _read(base / "schemas/llm_case.schema.json")
        assert set(llm_schema["properties"]) == {"case_id", "prompt"}
        benchmark = _read(base / "schemas/benchmark_case.schema.json")
        expected = ["case_id", "instance", "llm_prompt", "reference"]
        assert benchmark["required"] == expected
        assert list(benchmark["properties"]) == expected


def test_x2x3_output_schemas_remain_scientifically_unchanged():
    x2 = _read(ROOT / "contracts/X2/output_schema.json")
    assert set(x2["properties"]) == {"decision", "path_node_ids", "path_link_ids", "slot_start"}
    x3 = _read(ROOT / "contracts/X3/output_schema.json")
    assert set(x3["properties"]) == {"decision", "allocations"}
    assert set(x3["properties"]["allocations"]["items"]["properties"]) == {
        "request_id", "path_node_ids", "path_link_ids", "slot_start"
    }
