from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from src.i1.renderer import render_base_prompt
from src.i1.source_loader import load_i1_sources
from src.i1.truth import build_concurrent_answer, build_dynamic_answer, build_single_answer
from src.i1.validators import validate_rewrite


DIFFICULTIES = ("EASY", "MEDIUM", "HARD")
TASKS = ("I1-S", "I1-C", "I1-D")

_MACHINE_FIELD_NAMES = (
    "intent_type",
    "source_node_id",
    "destination_node_id",
    "required_slots",
    "request_id",
    "arrival_time",
    "holding_time",
    "objectives",
)

_OBJECTIVE_PATTERNS: dict[str, tuple[str, ...]] = {
    "MIN-HOP-COUNT": (
        r"路径跳数(?:最少|最小|最低|尽可能少)",
        r"路径跳数(?:尽量|尽可能)(?:少|低)",
        r"跳数(?:最少|最小|最低|尽可能少)的路径",
        r"最少跳数的路径",
        r"跳数(?:最少|最小|最低)的传输路径",
        r"路径的跳数(?:最少|最小|最低)",
        r"传输路径经过的链路数量尽可能少",
        r"(?:选择|让|使)传输路径(?:经过的)?链路数量(?:最少|最小|尽量少)",
        r"减少(?:传输)?路径经过的链路数量",
    ),
    "MIN-FRAGMENTATION": (
        r"全网(?:剩余可用频谱)?(?:尽量保持连续|保持连续)[^。；]*",
        r"降低全网频谱碎片(?:化程度)?",
        r"减少全网频谱碎片(?:化程度)?",
        r"全网频谱碎片(?:化程度)?(?:最低|最少|最小)",
        r"全网频谱碎片(?:化)?程度(?:最低|最少|最小|尽量低|尽可能低)",
        r"(?:使|让|令|保证|确保)(?:本次)?(?:资源)?(?:(?:分配(?:完成)?|方案执行|操作完成|(?:本次)?业务建立)后)?的?全网(?:的)?频谱碎片(?:化)?(?:程度)?(?:(?:达到|降至)?最低|最少|最小|尽量低|尽可能低)",
        r"(?:资源分配(?:完成)?后|分配后)全网(?:的)?频谱碎片(?:化)?(?:程度)?(?:最低|最少|最小|降至最低)",
    ),
    "MIN-TOTAL-SLOT-USAGE": (
        r"(?:全部|所有)并发业务(?:请求)?(?:在其所选路径上)?合计占用的频谱槽位规模最小",
        r"(?:全部|所有)并发业务(?:请求)?(?:在其所选路径上)?合计占用的频谱槽位规模(?:尽量|尽可能)(?:少|小|低)",
        r"总(?:频谱)?槽位(?:占用)?(?:数)?(?:最少|最小)",
        r"总(?:频谱)?槽位(?:使用|占用)(?:数|数量)?(?:最少|最小|尽量少|尽可能少)",
        r"(?:使|让|令)(?:全部|所有)?(?:并发业务)?(?:合计)?(?:占用的)?总(?:频谱)?槽位(?:规模|数量|数)(?:尽量|尽可能)(?:少|小|低)",
        r"占用总槽位数最少",
    ),
    "MAX-ACCEPTED-REQUESTS": (
        r"尽可能多的业务(?:请求)?(?:最终)?(?:能够|可以)?成功建立",
        r"(?:提高|提升|增加)成功建立的业务请求数量",
        r"尽量提高成功建立的业务请求数量",
        r"尽可能提升成功建立的请求数目",
        r"(?:使|让|令)?成功建立的(?:业务)?请求(?:数量|数目|数)(?:最多|最大|尽可能多)",
        r"(?:尽可能|尽量)(?:提高|增加|提升)成功建立的(?:业务)?请求(?:数量|数目|总数)",
        r"(?:最大化|使其最大)成功建立的(?:业务)?请求(?:数量|数目|总数)",
    ),
    "MIN-EXTERNAL-FRAGMENTATION": (
        r"降低网络外部频谱碎片",
        r"减少网络外部的频谱碎片",
        r"减少网络外部频谱碎片",
        r"(?:最小化|尽量降低|尽可能降低)网络外部(?:的)?频谱碎片(?:程度)?",
        r"(?:使|让|令)网络外部(?:的)?频谱碎片(?:程度)?(?:最低|最少|最小|尽量少|尽可能少)",
        r"(?:让|使)后续剩余频谱保持(?:成)?更连续的空闲区段[^。；]*外部碎片",
        r"网络外部频谱碎片程度(?:最低|最少|最小)",
    ),
}

_REQUEST_ID_RE = re.compile(r"(?<![A-Za-z0-9_])(?:dynreq|dyn|req)_[A-Za-z0-9_]+")
_NUMBER_RE = r"\d+(?:\.\d+)?"
_PAIR_PATTERNS = (
    re.compile(r"(?:从|由|为)?\s*节点\s*(\d+)\s*(?:到|至|与|和|向|发往|发至|通往|通达|连接至|连到|前往|出发前往)\s*节点\s*(\d+)"),
    re.compile(r"源节点(?:编号)?\s*(?:为|是)?\s*(?:节点)?(\d+)\s*(?:至|到|发往|连接至|通达|前往)?\s*(?:目的|目标)节点(?:编号)?\s*(?:为|是)?\s*(?:节点)?(\d+)"),
)
_SLOT_RE = re.compile(rf"({_NUMBER_RE})\s*个\s*(?:连续\s*)?频谱槽位")
_ARRIVAL_PATTERNS = (
    re.compile(rf"当前(?:系统)?(?:时刻|时间)\s*(?:为|是)?\s*({_NUMBER_RE})"),
    re.compile(rf"仿真时钟\s*(?:在|为|到达)?\s*({_NUMBER_RE})"),
    re.compile(rf"到达(?:时刻|时间)\s*(?:为|是)?\s*({_NUMBER_RE})"),
)
_HOLDING_PATTERNS = (
    re.compile(rf"持续(?:时长|时间)\s*(?:为|是)?\s*({_NUMBER_RE})"),
    re.compile(rf"占用网络资源(?:的)?持续时间\s*(?:为|是)?\s*({_NUMBER_RE})"),
    re.compile(rf"持续占用资源\s*({_NUMBER_RE})"),
)

_HARD_FORBIDDEN = (
    re.compile(r"(?:拓扑|候选路径|候选动作|路径候选|频谱状态|链路状态|链路编号|slot_start)", re.I),
    re.compile(r"(?:可拒绝|拒绝该请求|必须接受|必须接纳|业务拒绝|业务接纳)"),
    re.compile(r"(?:大约|约为|左右|接近|大概)"),
    re.compile(r"(?:它|前者|后者|该请求)"),
)


def _sha_obj(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique_matches(patterns, text: str, label: str) -> list[re.Match[str]]:
    matches: dict[tuple[int, int, str], re.Match[str]] = {}
    for pattern in patterns:
        for match in pattern.finditer(text):
            key = (match.start(), match.end(), match.group(0))
            matches[key] = match
    rows = sorted(matches.values(), key=lambda match: (match.start(), match.end()))
    if not rows:
        raise ValueError(f"missing {label}")
    return rows


def _one_pair(text: str) -> tuple[int, int]:
    matches = _unique_matches(_PAIR_PATTERNS, text, "source/destination pair")
    values = {(int(m.group(1)), int(m.group(2))) for m in matches}
    if len(values) != 1:
        raise ValueError(f"ambiguous source/destination pair: {sorted(values)}")
    return next(iter(values))


def _one_slot(text: str) -> int:
    matches = list(_SLOT_RE.finditer(text))
    values = {int(float(m.group(1))) for m in matches}
    if len(values) != 1:
        raise ValueError(f"ambiguous required_slots: {sorted(values)}")
    return next(iter(values))


def _one_time(patterns, text: str, label: str) -> float:
    matches = _unique_matches(patterns, text, label)
    values = {float(m.group(1)) for m in matches}
    if len(values) != 1:
        raise ValueError(f"ambiguous {label}: {sorted(values)}")
    return next(iter(values))


def _objectives(text: str) -> list[str]:
    matches: list[tuple[int, str, str]] = []
    for code, patterns in _OBJECTIVE_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                matches.append((match.start(), code, match.group(0)))
    if not matches:
        raise ValueError("missing objective language")
    matches.sort(key=lambda row: (row[0], -len(row[2])))
    ordered: list[str] = []
    spans: list[tuple[int, int]] = []
    for start, code, phrase in matches:
        end = start + len(phrase)
        if any(start < other_end and end > other_start for other_start, other_end in spans):
            continue
        spans.append((start, end))
        if code not in ordered:
            ordered.append(code)
    return ordered


def _parse_single(text: str) -> dict:
    source, destination = _one_pair(text)
    return {
        "intent_type": "SINGLE",
        "source_node_id": source,
        "destination_node_id": destination,
        "required_slots": _one_slot(text),
        "objectives": _objectives(text),
    }


def _parse_concurrent(text: str) -> dict:
    id_matches = list(_REQUEST_ID_RE.finditer(text))
    if not id_matches:
        raise ValueError("missing concurrent request_id")
    ids = [match.group(0) for match in id_matches]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate or repeated concurrent request_id")
    requests = []
    for index, match in enumerate(id_matches):
        end = id_matches[index + 1].start() if index + 1 < len(id_matches) else len(text)
        segment = text[match.start() : end]
        source, destination = _one_pair(segment)
        requests.append(
            {
                "request_id": match.group(0),
                "source_node_id": source,
                "destination_node_id": destination,
                "required_slots": _one_slot(segment),
            }
        )
    return {"intent_type": "CONCURRENT", "requests": requests, "objectives": _objectives(text)}


def _parse_dynamic(text: str) -> dict:
    ids = list(_REQUEST_ID_RE.finditer(text))
    if len(ids) != 1:
        raise ValueError(f"dynamic request_id count must be 1, got {len(ids)}")
    source, destination = _one_pair(text)
    request = {
        "request_id": ids[0].group(0),
        "source_node_id": source,
        "destination_node_id": destination,
        "required_slots": _one_slot(text),
        "arrival_time": _one_time(_ARRIVAL_PATTERNS, text, "arrival_time"),
        "holding_time": _one_time(_HOLDING_PATTERNS, text, "holding_time"),
    }
    return {"intent_type": "DYNAMIC", "request": request, "objectives": _objectives(text)}


def parse_controlled_prompt(text: str, task_type: str) -> dict:
    """Parse the controlled natural-language vocabulary without using canonical truth.

    This parser is deliberately conservative. It is an independent semantic gate for the
    second-round vocabulary, not a general-purpose Chinese NLP parser.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError("prompt must be a non-empty string")
    if task_type == "I1-S":
        return _parse_single(text)
    if task_type == "I1-C":
        return _parse_concurrent(text)
    if task_type == "I1-D":
        return _parse_dynamic(text)
    raise ValueError(f"unsupported task_type: {task_type}")


def _task_for_answer(answer: dict) -> str:
    return {"SINGLE": "I1-S", "CONCURRENT": "I1-C", "DYNAMIC": "I1-D"}.get(
        answer.get("intent_type"), ""
    )


def _hard_forbidden(text: str, task_type: str) -> list[str]:
    errors = []
    patterns = list(_HARD_FORBIDDEN)
    # “该请求” is unambiguous when I1-S/I1-D has one explicitly described
    # request.  In I1-C it can hide which concurrent request is meant, so it
    # remains forbidden there.  This keeps the gate semantic rather than
    # banning ordinary Chinese reference expressions mechanically.
    if task_type != "I1-C":
        patterns = [pattern for pattern in patterns if pattern.pattern != r"(?:它|前者|后者|该请求)"]
        patterns.append(re.compile(r"(?:它|前者|后者)"))
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            errors.append(f"hard forbidden pattern: {match.group(0)!r}")
    return errors


def _objective_code_leakage(text: str) -> list[str]:
    codes = [code for code in _OBJECTIVE_PATTERNS if code in text]
    if codes:
        return [f"objective enum leakage: {codes}"]
    return []


def validate_difficulty_variant(answer: dict, rewritten_prompt: str, *, difficulty: str) -> dict:
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unsupported difficulty: {difficulty}")
    task_type = _task_for_answer(answer)
    if not task_type:
        raise ValueError("answer has unsupported intent_type")

    errors: list[str] = []
    parsed = None
    try:
        parsed = parse_controlled_prompt(rewritten_prompt, task_type)
    except Exception as exc:
        errors.append(f"independent semantic parser failed: {type(exc).__name__}: {exc}")

    base = validate_rewrite(
        answer,
        rewritten_prompt,
        semantic_parser=lambda prompt: parse_controlled_prompt(prompt, task_type),
    )
    errors.extend(base["errors"])
    leakage_errors = _objective_code_leakage(rewritten_prompt)
    if leakage_errors:
        errors.extend(leakage_errors)
    forbidden_errors = _hard_forbidden(rewritten_prompt, task_type) if difficulty == "HARD" else []
    errors.extend(forbidden_errors)

    roundtrip = base["semantic_roundtrip"]
    semantic_exact = roundtrip == "PASS"
    leakage_ok = base["leakage_check"] == "PASS" and not leakage_errors
    forbidden_ok = not forbidden_errors
    overall = "PASS" if base["overall"] == "PASS" and semantic_exact and leakage_ok and forbidden_ok else "FAIL"
    return {
        "difficulty": difficulty,
        "schema": base["schema"],
        "literal_integrity": base["literal_integrity"],
        "request_mapping": base["request_mapping"],
        "objective_semantics": base["objective_semantics"],
        "semantic_roundtrip": roundtrip,
        "semantic_exact_match": semantic_exact,
        "leakage_check": "PASS" if leakage_ok else "FAIL",
        "forbidden_patterns": "PASS" if forbidden_ok else "FAIL",
        "parsed_answer": parsed,
        "overall": overall,
        "errors": errors,
    }


def _record(truth_id: str, task_type: str, source_ref: str, answer: dict) -> dict:
    base_prompt = render_base_prompt(answer)
    validation = validate_difficulty_variant(answer, base_prompt, difficulty="EASY")
    if validation["overall"] != "PASS":
        raise ValueError(f"base prompt failed independent validation: {truth_id}: {validation['errors']}")
    return {
        "truth_id": truth_id,
        "task_type": task_type,
        "source_ref": source_ref,
        "canonical_answer": deepcopy(answer),
        "canonical_answer_sha256": _sha_obj(answer),
        "base_prompt": base_prompt,
        "base_prompt_sha256": hashlib.sha256(base_prompt.encode("utf-8")).hexdigest(),
    }


def _must_find_single(singles: dict[str, dict], source: int, destination: int, slots: int) -> dict:
    for row in singles.values():
        if (
            int(row["source_node_id"]) == source
            and int(row["destination_node_id"]) == destination
            and int(row["required_slots"]) == slots
        ):
            return row
    raise ValueError(f"source pool lacks single request {source}->{destination}/{slots}")


def build_pilot_truths(environment_root: Path | str, *, seed: int = 20260911) -> dict[str, list[dict]]:
    """Build the fixed 7/7/7 second-round truth panel from the public source pool."""

    del seed  # The explicit panel is part of the pilot pre-registration.
    sources = load_i1_sources(environment_root)
    singles = {str(row["request_id"]): row for row in sources["single"]}

    single_specs = [(0, 1, 5), (1, 4, 3), (2, 8, 2), (3, 4, 9), (4, 8, 2), (6, 8, 3), (8, 9, 5)]
    single_objectives = [
        ["MIN-FRAGMENTATION"],
        ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
        ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
        ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
    ]
    out: dict[str, list[dict]] = {task: [] for task in TASKS}
    for index, (spec, objectives) in enumerate(zip(single_specs, single_objectives), 1):
        request = _must_find_single(singles, *spec)
        answer = build_single_answer(request, objectives)
        out["I1-S"].append(_record(f"I1_S_{index:06d}", "I1-S", str(request["request_id"]), answer))

    concurrent_groups = [
        ["req_gabriel_10_5_000065", "req_gabriel_10_5_000087"],
        ["req_gabriel_10_5_000039", "req_gabriel_10_5_000026", "req_gabriel_10_5_000031"],
        ["req_gabriel_10_5_000048", "req_gabriel_10_5_000052", "req_gabriel_10_5_000074", "req_gabriel_10_5_000089"],
        ["req_gabriel_10_5_000031", "req_gabriel_10_5_000082", "req_gabriel_10_5_000009"],
        ["req_gabriel_10_5_000020", "req_gabriel_10_5_000048"],
        ["req_gabriel_10_5_000026", "req_gabriel_10_5_000074", "req_gabriel_10_5_000089", "req_gabriel_10_5_000039"],
        ["req_gabriel_10_5_000087", "req_gabriel_10_5_000052"],
    ]
    concurrent_objectives = [
        ["MIN-FRAGMENTATION"],
        ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
        ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
        ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
        ["MIN-FRAGMENTATION"],
    ]
    for index, (request_ids, objectives) in enumerate(zip(concurrent_groups, concurrent_objectives), 1):
        if any(request_id not in singles for request_id in request_ids):
            raise ValueError(f"source pool lacks concurrent request in group {request_ids}")
        requests = [singles[request_id] for request_id in request_ids]
        answer = build_concurrent_answer(requests, objectives)
        out["I1-C"].append(
            _record(f"I1_C_{index:06d}", "I1-C", f"synthetic_group_{index:02d}", answer)
        )

    dynamic_indices = [0, 3, 5, 7, 10, 14, 17]
    for index, source_index in enumerate(dynamic_indices, 1):
        try:
            request = sources["dynamic"][source_index]
        except IndexError as exc:
            raise ValueError("source pool lacks the pre-registered dynamic panel") from exc
        answer = build_dynamic_answer(
            request,
            ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"],
        )
        source_ref = f"{request.get('request_sequence_id', 'seq')}::{request['request_id']}"
        out["I1-D"].append(_record(f"I1_D_{index:06d}", "I1-D", source_ref, answer))

    if {task: len(rows) for task, rows in out.items()} != {"I1-S": 7, "I1-C": 7, "I1-D": 7}:
        raise ValueError("second-round truth panel is not exactly 7/7/7")
    return out


def build_pilot_case(truth_row: dict, difficulty: str, *, rewritten_prompt: str | None = None) -> dict:
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unsupported difficulty: {difficulty}")
    prompt = rewritten_prompt if rewritten_prompt is not None else truth_row["base_prompt"]
    validation = validate_difficulty_variant(
        truth_row["canonical_answer"], prompt, difficulty=difficulty
    )
    if validation["overall"] != "PASS":
        raise ValueError(f"rewrite validation failed for {truth_row['truth_id']}_{difficulty}: {validation['errors']}")
    return {
        "case_id": f"{truth_row['truth_id']}_{difficulty}",
        "truth_id": truth_row["truth_id"],
        "task_type": truth_row["task_type"],
        "difficulty": difficulty,
        "source_ref": truth_row["source_ref"],
        "canonical_answer": deepcopy(truth_row["canonical_answer"]),
        "base_prompt": truth_row["base_prompt"],
        "rewritten_prompt": prompt,
        "canonical_answer_sha256": truth_row["canonical_answer_sha256"],
        "base_prompt_sha256": truth_row["base_prompt_sha256"],
        "rewritten_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "validation": validation,
    }
