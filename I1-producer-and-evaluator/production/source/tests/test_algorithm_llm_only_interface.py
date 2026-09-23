from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")


@pytest.mark.parametrize("task", TASKS)
def test_task_contracts_publish_llm_and_algorithm_inputs(task: str) -> None:
    contract = ROOT / "contracts" / task
    assert (contract / "llm_system_prompt.txt").is_file()
    assert (contract / "algorithm_contract.json").is_file()
    assert (contract / "output_schema.json").is_file()
    assert (contract / "schemas" / "algorithm_input.schema.json").is_file()
    assert (contract / "schemas" / "llm_case.schema.json").is_file()
    schema = json.loads((contract / "schemas" / "benchmark_case.schema.json").read_text(encoding="utf-8"))
    assert schema["required"] == ["case_id", "instance", "llm_prompt", "reference"]
    assert set(schema["properties"]) == set(schema["required"])
