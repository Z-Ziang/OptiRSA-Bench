from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LLM_PROMPTS = {
    "S1": "e0cbb0a844eef28d45c4c1d85c8bebdac1b8b6b7a196263b9f5f702c54cfa797",
    "X4": "8dbb48faa3a99f185fb9b58f2dba3d0e217459a00752ca52fc67d5ab47847afe",
}


def test_s1x4_contracts_and_llm_prompts_are_available() -> None:
    for task, expected in EXPECTED_LLM_PROMPTS.items():
        contract = ROOT / "contracts" / task
        assert hashlib.sha256((contract / "llm_system_prompt.txt").read_bytes()).hexdigest() == expected
        assert (contract / "output_schema.json").is_file()
        assert (contract / "schemas" / "algorithm_runtime_contract.json").is_file()


def test_s1x4_export_produces_llm_cases_and_algorithm_launchers(tmp_path, monkeypatch) -> None:
    import src.s1_x4.exporter as exporter
    from src.s1_x4.dataset_validator import verify_s1x4_dataset
    from src.s1_x4_pipeline import derive_s1x4_dataset

    monkeypatch.setattr(
        exporter,
        "compute_serialization_metrics",
        lambda prompt: {"llm_prompt_char_count": len(prompt), "canonical_tokenizer": {"backend": "TEST", "encoding": "TEST", "package_version": "0"}},
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"profile": "TEST", "case_count": 1, "allow_shortfall": False, "k_values": [3], "run_reference_panel": True}), encoding="utf-8")
    output = tmp_path / "dataset"
    derive_s1x4_dataset(minimal_dynamic_environment(tmp_path, length=3), config, output)

    for task in ("S1", "X4"):
        benchmark = json.loads((output / "benchmark_case" / task / "cases" / "case_000001.json").read_text(encoding="utf-8"))
        assert set(benchmark) == {"case_id", "llm_prompt", "reference"}
        llm = json.loads((output / "evaluation_case" / task / "llm" / "case_000001.json").read_text(encoding="utf-8"))
        assert llm == {"case_id": benchmark["case_id"], "prompt": benchmark["llm_prompt"]}
        assert (output / "evaluation_case" / task / "algorithm" / "case_000001.json").is_file()
    assert verify_s1x4_dataset(output)["valid"] is True
