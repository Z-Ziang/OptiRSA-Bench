from pathlib import Path

from scripts.i1_active_audit import run_active_audit


def test_active_i1_examples_use_llm_prompt_and_exact_evaluation_projection():
    root = Path(__file__).resolve().parents[1]
    report = run_active_audit(root)
    assert report["valid"], report["errors"]
    assert report["benchmark_case_count"] == 6
    assert report["evaluation_case_count"] == 6
    assert report["evaluation_prompt_exact_mapping_count"] == 6
    assert report["active_old_benchmark_prompt_count"] == 0
