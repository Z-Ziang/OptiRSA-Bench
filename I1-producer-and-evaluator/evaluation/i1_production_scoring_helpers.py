"""V2.1.3 production-mode helpers for I1.

The public production unit is one canonical truth mapped to one final prompt.  The
EASY/MEDIUM/HARD labels used by the historical pilot deliberately do not appear in
these helpers.  They remain an internal audit concern, not a public benchmark axis.
"""

from __future__ import annotations

from copy import deepcopy

from src.i1.difficulty import parse_controlled_prompt
from src.i1.validator import validate_i1_output
from src.i1.validators import validate_rewrite


_TASK_BY_INTENT = {
    "SINGLE": "I1-S",
    "CONCURRENT": "I1-C",
    "DYNAMIC": "I1-D",
}
_OBJECTIVE_CODES = (
    "MIN-HOP-COUNT",
    "MIN-FRAGMENTATION",
    "MIN-TOTAL-SLOT-USAGE",
    "MAX-ACCEPTED-REQUESTS",
    "MIN-EXTERNAL-FRAGMENTATION",
)


def _require_nonempty_string(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def normalized_prompt(prompt: str) -> str:
    """Return the comparison form used only for duplicate detection."""

    return " ".join(_require_nonempty_string(prompt, "prompt").split())


def build_formal_benchmark_case(
    case_id: str, llm_prompt: str, canonical_answer: dict
) -> dict:
    """Build the frozen public benchmark shape: exactly case_id/llm_prompt/answer."""

    _require_nonempty_string(case_id, "case_id")
    _require_nonempty_string(llm_prompt, "llm_prompt")
    if not isinstance(canonical_answer, dict):
        raise ValueError("canonical_answer must be an object")
    return {
        "case_id": case_id,
        "llm_prompt": llm_prompt,
        "answer": deepcopy(canonical_answer),
    }


def build_formal_evaluation_case(public_case: dict) -> dict:
    """Build the DUT-facing shape without answer/truth/difficulty leakage."""

    if not isinstance(public_case, dict) or set(public_case) != {
        "case_id",
        "llm_prompt",
        "answer",
    }:
        raise ValueError("public_case must have exactly case_id, llm_prompt and answer")
    return {"case_id": public_case["case_id"], "prompt": public_case["llm_prompt"]}


def validate_formal_rewrite(canonical_answer: dict, final_prompt: str) -> dict:
    """Validate a final production prompt with the independent semantic parser.

    This is the production analogue of the second-round difficulty validator.  It
    intentionally reports ``difficulty=None`` so callers cannot accidentally treat a
    language style as a scientific difficulty label.
    """

    if not isinstance(canonical_answer, dict):
        raise ValueError("canonical_answer must be an object")
    task_type = _TASK_BY_INTENT.get(canonical_answer.get("intent_type"))
    if task_type is None:
        raise ValueError("canonical_answer has unsupported intent_type")

    base = validate_rewrite(
        canonical_answer,
        final_prompt,
        semantic_parser=lambda prompt: parse_controlled_prompt(prompt, task_type),
    )
    errors = list(base["errors"])
    leaked_objective_codes = [
        code for code in _OBJECTIVE_CODES if isinstance(final_prompt, str) and code in final_prompt
    ]
    if leaked_objective_codes:
        errors.append(f"objective enum leakage: {leaked_objective_codes}")

    semantic_exact = base["semantic_roundtrip"] == "PASS"
    overall = (
        "PASS"
        if base["overall"] == "PASS" and semantic_exact and not leaked_objective_codes
        else "FAIL"
    )
    return {
        "difficulty": None,
        "schema": base["schema"],
        "literal_integrity": base["literal_integrity"],
        "request_mapping": base["request_mapping"],
        "objective_semantics": base["objective_semantics"],
        "semantic_roundtrip": base["semantic_roundtrip"],
        "semantic_exact_match": semantic_exact,
        "leakage_check": "PASS"
        if base["leakage_check"] == "PASS" and not leaked_objective_codes
        else "FAIL",
        "forbidden_patterns": "NOT_APPLICABLE",
        "overall": overall,
        "errors": errors,
    }


def validate_one_prompt_per_truth(records: list[dict]) -> dict:
    """Fail closed unless each truth and normalized final prompt is unique."""

    seen_truths: set[str] = set()
    seen_prompts: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("production record must be an object")
        truth_id = _require_nonempty_string(record.get("truth_id"), "truth_id")
        prompt = record.get("final_prompt")
        if truth_id in seen_truths:
            raise ValueError(f"one final prompt required per truth: duplicate truth_id {truth_id}")
        seen_truths.add(truth_id)
        normalized = normalized_prompt(prompt)
        previous_truth = seen_prompts.get(normalized)
        if previous_truth is not None:
            raise ValueError(
                "duplicate normalized prompt: "
                f"truths {previous_truth} and {truth_id}"
            )
        seen_prompts[normalized] = truth_id
    return {
        "valid": True,
        "truth_count": len(seen_truths),
        "final_prompt_count": len(seen_prompts),
        "normalized_duplicate_count": 0,
    }


def score_dual_metrics(expected_answer: dict, raw_content: str) -> dict:
    """Score raw DUT content while separating science from strict formatting.

    All parsing and semantic comparison comes from the canonical I1 validator.  No
    cleanup, extraction, or Truth-based repair is performed here.
    """

    validator_result = validate_i1_output(expected_answer, raw_content)
    semantic_exact = bool(validator_result["semantic_exact_match"])
    raw_format_valid = bool(validator_result["raw_format_valid"])
    final_case_pass = bool(validator_result["final_case_pass"])
    return {
        "semantic_exact_match": semantic_exact,
        "semantic_intent_accuracy": semantic_exact,
        "raw_format_valid": raw_format_valid,
        "strict_format_compliance": raw_format_valid,
        "final_case_pass": final_case_pass,
        "strict_case_pass_rate": final_case_pass,
        "validator_result": validator_result,
    }
