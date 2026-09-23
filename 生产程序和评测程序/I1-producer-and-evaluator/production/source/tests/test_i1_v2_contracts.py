from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_i1_public_case_contract_is_llm_only_prompt_answer():
    for task in ("I1-S", "I1-C", "I1-D"):
        schema = json.loads((ROOT / "contracts" / task / "schemas" / "benchmark_case.schema.json").read_text(encoding="utf-8"))
        assert schema["required"] == ["case_id", "llm_prompt", "answer"]
        assert schema["additionalProperties"] is False
        assert "llm_prompt" in schema["properties"]
        assert "prompt" not in schema["properties"]


def test_i1_evaluation_case_is_id_plus_prompt_only():
    for task in ("I1-S", "I1-C", "I1-D"):
        schema = json.loads((ROOT / "contracts" / task / "schemas" / "evaluation_case.schema.json").read_text(encoding="utf-8"))
        assert schema["required"] == ["case_id", "prompt"]
        assert schema["additionalProperties"] is False
        assert "answer" not in schema["properties"]


def test_i1_task_prompts_are_available():
    for task in ("I1-S", "I1-C", "I1-D"):
        assert (ROOT / "contracts" / task / "llm_system_prompt.txt").is_file()


def test_i1_cli_exposes_explicit_base_and_rewrite_stages():
    from benchmark_i1 import parser
    p = parser()
    help_text = p.format_help()
    # argparse top-level help does not list subparser help bodies, but choices are rendered.
    assert "derive-base-cases" in help_text
    assert "verify-base-dataset" in help_text
    assert "rewrite-base-cases" in help_text
