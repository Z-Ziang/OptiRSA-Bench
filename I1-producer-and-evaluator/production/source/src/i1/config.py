from __future__ import annotations
import hashlib, json
from pathlib import Path

FROZEN_OBJECTIVE_VARIANTS = {
    "I1-S": [
        ["MIN-FRAGMENTATION"],
        ["MIN-HOP-COUNT", "MIN-FRAGMENTATION"],
    ],
    "I1-C": [
        ["MIN-FRAGMENTATION"],
        ["MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION"],
    ],
    "I1-D": [
        ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"],
    ],
}


def _normalize_objective_profiles(raw: dict | None) -> dict[str, list[list[str]]]:
    if raw is None:
        return json.loads(json.dumps(FROZEN_OBJECTIVE_VARIANTS))
    if set(raw) != {"I1-S", "I1-C", "I1-D"}:
        raise ValueError("objective_profiles must define I1-S, I1-C and I1-D")
    out = {}
    for task, value in raw.items():
        if not isinstance(value, list) or not value:
            raise ValueError(f"objective_profiles.{task} must be non-empty")
        # Backward-compatible shorthand: one objective vector as list[str].
        variants = [value] if all(isinstance(x, str) for x in value) else value
        if not all(isinstance(v, list) and v and all(isinstance(x, str) for x in v) for v in variants):
            raise ValueError(f"objective_profiles.{task} must be a list of objective vectors")
        frozen = {tuple(x) for x in FROZEN_OBJECTIVE_VARIANTS[task]}
        for variant in variants:
            if tuple(variant) not in frozen:
                raise ValueError(f"unfrozen objective profile for {task}: {variant}")
        # Keep user-specified ordering; remove duplicate vectors.
        dedup = []
        seen = set()
        for variant in variants:
            key = tuple(variant)
            if key not in seen:
                seen.add(key)
                dedup.append(list(variant))
        out[task] = dedup
    return out


def load_i1_config(path: Path | str) -> dict:
    p = Path(path)
    raw = p.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    allowed = {"profile", "seed", "case_counts", "objective_profiles", "rewrite", "allow_shortfall", "require_canonical_tokenizer"}
    extra = set(obj) - allowed
    if extra:
        raise ValueError(f"unknown I1 config fields: {sorted(extra)}")
    counts = obj.get("case_counts", {})
    if set(counts) - {"I1-S", "I1-C", "I1-D"}:
        raise ValueError("unknown I1 case_count task")
    for task in ("I1-S", "I1-C", "I1-D"):
        value = counts.get(task, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{task} count must be non-negative integer")
    profiles = _normalize_objective_profiles(obj.get("objective_profiles"))
    rw = obj.get("rewrite", {"enabled": False, "mode": "identity", "max_attempts": 3})
    if not isinstance(rw, dict):
        raise ValueError("rewrite must be object")
    if not isinstance(rw.get("enabled", False), bool):
        raise ValueError("rewrite.enabled must be boolean")
    mode = rw.get("mode", "identity")
    if mode not in {"identity", "openai_compatible"}:
        raise ValueError("unsupported rewrite.mode")
    if rw.get("enabled", False) and mode == "openai_compatible":
        for field in ("base_url", "api_key_env", "model"):
            if not isinstance(rw.get(field), str) or not rw.get(field):
                raise ValueError(f"rewrite.{field} is required for openai_compatible mode")
    max_attempts = rw.get("max_attempts", 3)
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
        raise ValueError("rewrite.max_attempts must be positive integer")
    out = dict(obj)
    out.setdefault("profile", "i1")
    out.setdefault("seed", 20260910)
    out.setdefault("allow_shortfall", False)
    out.setdefault("require_canonical_tokenizer", False)
    out["objective_profiles"] = profiles
    out["rewrite"] = rw
    out["config_sha256"] = hashlib.sha256(raw).hexdigest()
    return out
