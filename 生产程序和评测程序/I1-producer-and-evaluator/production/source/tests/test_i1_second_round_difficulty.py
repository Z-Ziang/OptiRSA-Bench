from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from src.i1.difficulty import (
    DIFFICULTIES,
    build_pilot_truths,
    build_pilot_case,
    parse_controlled_prompt,
    validate_difficulty_variant,
)


ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "tests" / "fixtures" / "public_environment_gabriel10"


def _single_answer(objectives=None):
    return {
        "intent_type": "SINGLE",
        "source_node_id": 1,
        "destination_node_id": 6,
        "required_slots": 9,
        "objectives": objectives or ["MIN-FRAGMENTATION"],
    }


def _concurrent_answer():
    return {
        "intent_type": "CONCURRENT",
        "requests": [
            {"request_id": "req_001", "source_node_id": 3, "destination_node_id": 18, "required_slots": 5},
            {"request_id": "req_002", "source_node_id": 7, "destination_node_id": 15, "required_slots": 3},
        ],
        "objectives": ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
    }


def _dynamic_answer():
    return {
        "intent_type": "DYNAMIC",
        "request": {
            "request_id": "dyn_1",
            "source_node_id": 3,
            "destination_node_id": 18,
            "required_slots": 5,
            "arrival_time": 445.382981448571,
            "holding_time": 4.704381744198,
        },
        "objectives": ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"],
    }


def test_second_round_truth_pool_is_exactly_balanced_and_paired():
    truths = build_pilot_truths(ENV, seed=20260911)
    assert {task: len(rows) for task, rows in truths.items()} == {"I1-S": 7, "I1-C": 7, "I1-D": 7}
    for rows in truths.values():
        assert len({row["truth_id"] for row in rows}) == 7
        assert len({row["canonical_answer_sha256"] for row in rows}) == 7

    for row in [item for rows in truths.values() for item in rows]:
        prompts = {
            difficulty: row["base_prompt"].replace(
                "该请求需要", "这项业务需要"
            )
            for difficulty in DIFFICULTIES
        }
        cases = [
            build_pilot_case(row, difficulty, rewritten_prompt=prompts[difficulty])
            for difficulty in DIFFICULTIES
        ]
        assert [case["canonical_answer"] for case in cases] == [row["canonical_answer"]] * 3
        assert len({case["case_id"] for case in cases}) == 3


def test_single_objective_hard_rejects_residual_tie_break():
    answer = _single_answer()
    text = "首先为节点1到节点6建立业务，需要连续使用9个频谱槽位；若相同，再选择使全网频谱碎片最少的方案。"
    result = validate_difficulty_variant(answer, text, difficulty="HARD")
    assert result["overall"] == "FAIL"
    assert any("orphan" in error for error in result["errors"])


def test_two_objective_hard_requires_both_goals_and_order():
    answer = _single_answer(["MIN-HOP-COUNT", "MIN-FRAGMENTATION"])
    valid = "从节点1到节点6建立业务，需要连续使用9个频谱槽位；首先让传输路径经过的链路数量尽可能少，在此前提下让本次分配后全网剩余可用频谱保持连续，减少零散空闲区间。"
    missing = "从节点1到节点6建立业务，需要连续使用9个频谱槽位；首先让本次分配后全网剩余可用频谱保持连续，减少零散空闲区间。"
    swapped = "从节点1到节点6建立业务，需要连续使用9个频谱槽位；首先让本次分配后全网剩余可用频谱保持连续，减少零散空闲区间，在此前提下让传输路径经过的链路数量尽可能少。"
    assert validate_difficulty_variant(answer, valid, difficulty="HARD")["overall"] == "PASS"
    assert validate_difficulty_variant(answer, missing, difficulty="HARD")["overall"] == "FAIL"
    assert validate_difficulty_variant(answer, swapped, difficulty="HARD")["overall"] == "FAIL"


def test_concurrent_request_mapping_is_not_reduced_to_literal_presence():
    answer = _concurrent_answer()
    text = "同时处理req_001和req_002：req_001从节点7到节点15，需要连续使用3个频谱槽位；req_002从节点3到节点18，需要连续使用5个频谱槽位。优先减少所有并发业务合计占用的频谱槽位规模，再降低全网频谱碎片化程度。"
    result = validate_difficulty_variant(answer, text, difficulty="HARD")
    assert result["overall"] == "FAIL"
    assert result["semantic_roundtrip"] == "FAIL"


def test_dynamic_time_fields_are_not_tolerated_or_swapped():
    answer = _dynamic_answer()
    valid = "仿真时钟在445.382981448571时接收dyn_1，请从节点3到节点18建立业务，连续使用5个频谱槽位；若建立，持续占用资源4.704381744198。整条序列首先尽量提高成功建立的业务请求数量，在此前提下尽量降低网络外部频谱碎片。"
    swapped = "仿真时钟在4.704381744198时接收dyn_1，请从节点3到节点18建立业务，连续使用5个频谱槽位；若建立，持续占用资源445.382981448571。整条序列首先尽量提高成功建立的业务请求数量，在此前提下尽量降低网络外部频谱碎片。"
    changed = valid.replace("445.382981448571", "445.382981448572")
    assert validate_difficulty_variant(answer, valid, difficulty="HARD")["overall"] == "PASS"
    assert validate_difficulty_variant(answer, swapped, difficulty="HARD")["overall"] == "FAIL"
    assert validate_difficulty_variant(answer, changed, difficulty="HARD")["overall"] == "FAIL"


def test_hard_rejects_answer_leakage_vague_reference_and_extra_semantics():
    answer = _single_answer()
    text = "请从节点1到节点6建立业务，需要连续使用9个频谱槽位；该请求的 source_node_id 应为1，优先降低全网频谱碎片，并使用候选路径P1。"
    result = validate_difficulty_variant(answer, text, difficulty="HARD")
    assert result["overall"] == "FAIL"
    assert result["leakage_check"] == "FAIL" or result["forbidden_patterns"] == "FAIL"


def test_invalid_variant_cannot_be_promoted_to_pilot_case():
    answer = _single_answer()
    invalid = "节点1到节点6，9个槽位；若相同，再优化频谱。"
    with pytest.raises(ValueError, match="rewrite validation"):
        build_pilot_case(
            {
                "truth_id": "I1_S_000001",
                "task_type": "I1-S",
                "canonical_answer": answer,
                "base_prompt": invalid,
                "source_ref": "test",
                "canonical_answer_sha256": "test",
            },
            "HARD",
            rewritten_prompt=invalid,
        )


def test_parse_controlled_prompt_does_not_accept_extra_fields():
    answer = _single_answer(["MIN-HOP-COUNT", "MIN-FRAGMENTATION"])
    text = "从节点1到节点6建立业务，需要连续使用9个频谱槽位；首先减少路径经过的链路数量，在此前提下减少全网频谱碎片。"
    parsed = parse_controlled_prompt(text, "I1-S")
    assert parsed == answer


def test_semantic_gate_accepts_observed_natural_objective_and_pair_paraphrases():
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 0,
        "destination_node_id": 1,
        "required_slots": 5,
        "objectives": ["MIN-FRAGMENTATION"],
    }
    observed_model_variant = (
        "请为从节点0发往节点1的业务请求分配资源，该请求需占用5个连续频谱槽位。"
        "在制定分配方案时，应优先确保分配完成后全网的频谱碎片程度最低。"
    )
    assert validate_difficulty_variant(answer, observed_model_variant, difficulty="MEDIUM")["overall"] == "PASS"


def test_single_hard_allows_unique_current_request_reference():
    answer = {
        "intent_type": "SINGLE",
        "source_node_id": 2,
        "destination_node_id": 8,
        "required_slots": 2,
        "objectives": ["MIN-FRAGMENTATION"],
    }
    text = (
        "请为从节点2发往节点8的业务请求建立连接，该请求需要连续使用2个频谱槽位；"
        "首要目标是确保分配完成后全网频谱碎片程度降至最低。"
    )
    assert validate_difficulty_variant(answer, text, difficulty="HARD")["overall"] == "PASS"


def test_concurrent_gate_accepts_spaced_nodes_and_connective_pair_language():
    answer = _concurrent_answer()
    text = (
        "同步建立两项业务连接：req_001由节点 3 连接至节点 18，占用5个连续频谱槽位；"
        "req_002从节点 7 通达节点 15，占用3个连续频谱槽位。"
        "优先让所有并发业务合计占用的频谱槽位规模尽可能小，在此基础上降低全网频谱碎片化程度。"
    )
    result = validate_difficulty_variant(answer, text, difficulty="MEDIUM")
    assert result["overall"] == "PASS"


def test_single_gate_accepts_source_and_destination_labels_with_explicit_connector():
    answer = _single_answer(["MIN-FRAGMENTATION"])
    text = (
        "本次任务为源节点1至目的节点6建立业务连接，需要连续占用9个频谱槽位；"
        "在资源分配决策中，首要目标是确保分配完成后全网频谱碎片程度达到最低。"
    )
    assert validate_difficulty_variant(answer, text, difficulty="HARD")["overall"] == "PASS"


def test_dynamic_gate_accepts_directional_pair_and_request_count_synonyms():
    answer = _dynamic_answer()
    text = (
        "当前系统时刻为445.382981448571，业务请求dyn_1需要从节点3出发前往节点18建立连接，"
        "需要连续占用5个频谱槽位且持续时长为4.704381744198。"
        "针对该动态请求序列，首要目标是最大化成功建立的业务请求总数，"
        "其次需最小化网络外部频谱碎片程度。"
    )
    assert validate_difficulty_variant(answer, text, difficulty="HARD")["overall"] == "PASS"


def test_field_accuracy_is_profile_scoped(tmp_path):
    from scripts.i1_second_round_pilot import aggregate_scores

    field_sets = {
        "I1-S": {"intent_type", "source_node_id", "destination_node_id", "required_slots"},
        "I1-C": {"intent_type", "request_count", "request_id", "source_node_id", "destination_node_id", "required_slots", "request_mapping"},
        "I1-D": {"intent_type", "request_id", "source_node_id", "destination_node_id", "required_slots", "arrival_time", "holding_time"},
    }
    rows = []
    cases = []
    for index, (task, fields) in enumerate(field_sets.items(), start=1):
        case_id = f"{task.replace('-', '_')}_{index:06d}_EASY"
        truth_id = f"truth_{index}"
        rows.append({
            "case_id": case_id,
            "truth_id": truth_id,
            "task_type": task,
            "difficulty": "EASY",
            "model": "test/model",
            "api_success": True,
            "json_parse_success": True,
            "validator_result": {
                "semantic_exact_match": True,
                "final_case_pass": True,
                "raw_format_valid": True,
                "schema_valid": True,
                "field_results": {field: True for field in fields},
                "objective_set_accuracy": True,
                "objective_order_accuracy": True,
            },
        })
        cases.append({"case_id": case_id, "truth_id": truth_id, "task_type": task, "difficulty": "EASY", "rewritten_prompt": "prompt", "canonical_answer": {}})
        metadata_dir = tmp_path / "TRIAL_INTERNAL_EVIDENCE" / "test_model" / case_id
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "api_metadata.json").write_text(json.dumps({"attempts": [{}]}), encoding="utf-8")

    aggregate_scores(tmp_path, rows, cases, [{"model": "test/model", "tier": 1}])
    grouped = {}
    with (tmp_path / "tables" / "field_accuracy.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(row["profile"], set()).add(row["field"])
    assert grouped == field_sets
