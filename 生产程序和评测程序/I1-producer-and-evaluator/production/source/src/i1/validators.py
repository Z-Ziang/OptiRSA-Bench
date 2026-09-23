from __future__ import annotations
import json, re
from copy import deepcopy

_MACHINE_FIELD_NAMES = (
    "intent_type", "source_node_id", "destination_node_id", "required_slots",
    "objectives", "arrival_time", "holding_time"
)


def _normalize(obj):
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_normalize(x) for x in obj]
    return obj


def _request_literal_groups(answer: dict):
    if answer["intent_type"] == "SINGLE":
        return [{k: answer[k] for k in ("source_node_id","destination_node_id","required_slots")}]
    if answer["intent_type"] == "CONCURRENT":
        return answer["requests"]
    return [answer["request"]]


def _literal_integrity(answer: dict, text: str) -> tuple[bool, list[str]]:
    errors=[]
    if answer["intent_type"] == "CONCURRENT":
        for r in answer["requests"]:
            for key in ("request_id","source_node_id","destination_node_id","required_slots"):
                if str(r[key]) not in text:
                    errors.append(f"missing literal {key}={r[key]}")
    elif answer["intent_type"] == "DYNAMIC":
        r=answer["request"]
        for key in ("request_id","source_node_id","destination_node_id","required_slots"):
            if str(r[key]) not in text: errors.append(f"missing literal {key}={r[key]}")
        # Numeric spellings can lose trailing zeros but not value.
        for key in ("arrival_time","holding_time"):
            candidates={str(r[key]), format(float(r[key]), ".12g")}
            if not any(x in text for x in candidates): errors.append(f"missing literal {key}={r[key]}")
    else:
        for key in ("source_node_id","destination_node_id","required_slots"):
            if str(answer[key]) not in text: errors.append(f"missing literal {key}={answer[key]}")
    return (not errors, errors)




_SINGLE_OBJECTIVE_ORPHAN_PATTERNS = (
    re.compile(r"(?:若|如果|如).{0,20}(?:相同|相等|一致|一样).{0,28}(?:再|则|然后|其次)"),
    re.compile(r"(?:在此基础上|在此前提下|其次|第二优先|次一级目标|次要目标)"),
)

def _objective_language_guard(answer: dict, text: str) -> list[str]:
    objectives = answer.get("objectives")
    if not isinstance(objectives, list):
        return ["objectives must be a list"]
    if len(objectives) != 1:
        return []
    for pattern in _SINGLE_OBJECTIVE_ORPHAN_PATTERNS:
        match = pattern.search(text)
        if match:
            return [f"orphan objective-priority language for single-objective case: {match.group(0)!r}"]
    return []

def validate_rewrite(answer: dict, rewritten_prompt: str, semantic_parser=None, *, allow_machine_field_names: bool=False) -> dict:
    errors=[]
    if not isinstance(rewritten_prompt,str) or not rewritten_prompt.strip():
        errors.append("rewritten_prompt must be non-empty string")
    literal_ok,literal_errors=_literal_integrity(answer,rewritten_prompt)
    errors.extend(literal_errors)
    leakage_ok=True
    if not allow_machine_field_names:
        leaked=[x for x in _MACHINE_FIELD_NAMES if x in rewritten_prompt]
        if leaked:
            leakage_ok=False; errors.append(f"machine-field leakage: {leaked}")
    roundtrip="SKIPPED"
    mapping="PASS" if literal_ok else "FAIL"
    objective_guard_errors = _objective_language_guard(answer, rewritten_prompt)
    errors.extend(objective_guard_errors)
    objective="FAIL" if objective_guard_errors else "SKIPPED"
    if semantic_parser is not None:
        try:
            parsed=semantic_parser(rewritten_prompt)
            same=_normalize(parsed)==_normalize(answer)
            roundtrip="PASS" if same else "FAIL"
            parsed_objective_ok = parsed.get("objectives")==answer.get("objectives")
            objective="PASS" if parsed_objective_ok and not objective_guard_errors else "FAIL"
            if answer["intent_type"]=="CONCURRENT":
                mapping="PASS" if parsed.get("requests")==answer.get("requests") else "FAIL"
            if not same: errors.append("semantic roundtrip mismatch")
        except Exception as exc:
            roundtrip="FAIL"; objective="FAIL"; mapping="FAIL"; errors.append(f"semantic parser failed: {type(exc).__name__}: {exc}")
    else:
        # Without an independent parser, only unchanged deterministic base text can be accepted by pipeline.
        objective="FAIL" if objective_guard_errors else "UNVERIFIED"
    overall = "PASS" if literal_ok and leakage_ok and roundtrip in {"PASS","SKIPPED"} and mapping=="PASS" and objective in {"PASS","SKIPPED","UNVERIFIED"} else "FAIL"
    return {
        "schema":"PASS" if isinstance(rewritten_prompt,str) and bool(rewritten_prompt.strip()) else "FAIL",
        "literal_integrity":"PASS" if literal_ok else "FAIL",
        "request_mapping":mapping,
        "objective_semantics":objective,
        "semantic_roundtrip":roundtrip,
        "leakage_check":"PASS" if leakage_ok else "FAIL",
        "overall":overall,
        "errors":errors,
    }
