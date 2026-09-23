import json

import pytest

from src.i1.production import (
    build_formal_benchmark_case,
    build_formal_evaluation_case,
    score_dual_metrics,
    validate_formal_rewrite,
    validate_one_prompt_per_truth,
)
from src.i1.renderer import render_base_prompt


def _single_answer(objectives=None):
    return {
        "intent_type": "SINGLE",
        "source_node_id": 0,
        "destination_node_id": 4,
        "required_slots": 5,
        "objectives": objectives or ["MIN-FRAGMENTATION"],
    }


def test_formal_public_and_evaluation_cases_have_frozen_shapes_without_difficulty():
    answer = _single_answer()
    public = build_formal_benchmark_case(
        "I1_S_000001", render_base_prompt(answer), answer
    )
    evaluation = build_formal_evaluation_case(public)

    assert set(public) == {"case_id", "llm_prompt", "answer"}
    assert set(evaluation) == {"case_id", "prompt"}
    assert "difficulty" not in public
    assert "difficulty" not in evaluation
    assert evaluation["prompt"] == public["llm_prompt"]


def test_formal_rewrite_uses_semantic_gate_without_difficulty_label():
    answer = _single_answer(["MIN-HOP-COUNT", "MIN-FRAGMENTATION"])
    result = validate_formal_rewrite(answer, render_base_prompt(answer))

    assert result["overall"] == "PASS"
    assert result["semantic_roundtrip"] == "PASS"
    assert result["difficulty"] is None


def test_formal_rewrite_accepts_equivalent_natural_hop_ordering():
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 4,
        "destination_node_id": 8,
        "required_slots": 2,
        "objectives": ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"],
    }
    prompt = (
        "在节点4和节点8之间建立一条业务连接，该连接需要占用连续的2个频谱槽位。"
        "资源分配时，优先选择跳数最少的路径；若跳数相同，则优先选择使全网频谱碎片程度最低的分配方案。"
    )

    result = validate_formal_rewrite(answer, prompt)

    assert result["overall"] == "PASS"


def test_formal_rewrite_accepts_equivalent_total_slot_usage_wording():
    answer = {
        "intent_type": "CONCURRENT",
        "requests": [
            {
                "request_id": "req_a",
                "source_node_id": 1,
                "destination_node_id": 2,
                "required_slots": 3,
            },
            {
                "request_id": "req_b",
                "source_node_id": 2,
                "destination_node_id": 3,
                "required_slots": 5,
            },
        ],
        "objectives": ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
    }
    prompt = (
        "请同时为以下业务请求建立连接：req_a从节点1到节点2，需要连续使用3个频谱槽位；"
        "req_b从节点2到节点3，需要连续使用5个频谱槽位。"
        "在进行联合资源分配时，优先选择总槽位使用数最少的方案；"
        "若总槽位使用数相同，则优先选择全网频谱碎片程度最低的方案。"
    )

    result = validate_formal_rewrite(answer, prompt)

    assert result["overall"] == "PASS"


def test_one_truth_must_map_to_one_unique_prompt():
    records = [
        {"truth_id": "t1", "final_prompt": "同一条请求"},
        {"truth_id": "t1", "final_prompt": "另一条表达"},
    ]

    with pytest.raises(ValueError, match="one final prompt"):
        validate_one_prompt_per_truth(records)


def test_normalized_final_prompts_must_not_duplicate():
    records = [
        {"truth_id": "t1", "final_prompt": "请建立业务连接。"},
        {"truth_id": "t2", "final_prompt": "  请建立业务连接。  "},
    ]

    with pytest.raises(ValueError, match="duplicate normalized prompt"):
        validate_one_prompt_per_truth(records)


def test_dual_metrics_keep_semantic_success_separate_from_strict_format():
    answer = _single_answer()
    raw = "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"

    metrics = score_dual_metrics(answer, raw)

    assert metrics["semantic_exact_match"] is True
    assert metrics["semantic_intent_accuracy"] is True
    assert metrics["raw_format_valid"] is False
    assert metrics["strict_format_compliance"] is False
    assert metrics["final_case_pass"] is False
    assert metrics["strict_case_pass_rate"] is False
    assert metrics["validator_result"]["semantic_parse_source"] == "MARKDOWN_FENCE_ONLY"


def test_v213_cli_exposes_formal_preproduction_mode():
    from benchmark_i1 import parser

    assert "preproduction-dry-run" in parser().format_help()


def test_preproduction_source_pool_is_fail_closed_for_dynamic_shortfall():
    from pathlib import Path

    from scripts.i1_v2_1_3_production import build_preproduction_base_records

    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "configs" / "i1_v2_1_3_preproduction.json").read_text(encoding="utf-8")
    )
    records, pool = build_preproduction_base_records(
        root / "tests" / "fixtures" / "public_environment_gabriel10",
        config,
        "test-config-sha256",
    )

    assert {task: len(records[task]) for task in ("I1-S", "I1-C", "I1-D")} == {
        "I1-S": 90,
        "I1-C": 100,
        "I1-D": 20,
    }
    assert pool["shortfall_case_counts"] == {"I1-S": 10, "I1-C": 0, "I1-D": 80}
    assert "no synthetic time/request pairing" in pool["capacity_notes"]["I1-D"]


def test_formal_rewrite_prompt_protects_objective_scope_words():
    from scripts.i1_v2_1_3_production import PRODUCTION_REWRITE_SYSTEM_PROMPT

    assert "范围词" in PRODUCTION_REWRITE_SYSTEM_PROMPT
    assert "全网" in PRODUCTION_REWRITE_SYSTEM_PROMPT
    assert "网络外部" in PRODUCTION_REWRITE_SYSTEM_PROMPT
