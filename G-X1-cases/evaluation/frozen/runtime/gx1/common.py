from __future__ import annotations

import hashlib
import json
from pathlib import Path
from random import Random
from typing import Any, Mapping


class GenerationError(RuntimeError):
    pass


PUBLIC_LENGTH_SIGNIFICANT_DIGITS = 6


def public_length_km(value: float | int) -> float:
    """Return the canonical numeric value exposed in G3/X1 text prompts.

    Historical GX1 prompts used Python's ``:g`` formatting, whose default is
    six significant digits.  The evaluated system can reason only over that
    public value, so weighted scientific validation must use the same value.
    """
    return float(format(float(value), f".{PUBLIC_LENGTH_SIGNIFICANT_DIGITS}g"))


def public_length_km_text(value: float | int) -> str:
    """Serialize a canonical public link length exactly as it appears in prompts."""
    return format(float(value), f".{PUBLIC_LENGTH_SIGNIFICANT_DIGITS}g")


def derive_seed(seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def weighted_choice(rng: Random, weights: Mapping[str, float]) -> str:
    pairs = [(k, float(v)) for k, v in weights.items() if float(v) > 0]
    if not pairs:
        raise GenerationError("权重配置至少需要一个正权重项")
    total = sum(v for _, v in pairs)
    x = rng.random() * total
    c = 0.0
    for k, w in pairs:
        c += w
        if x < c:
            return k
    return pairs[-1][0]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(obj), encoding="utf-8")


def strict_json_loads(raw: str) -> Any:
    if not isinstance(raw, str):
        raise ValueError("DUT output must be string")
    stripped = raw.strip()
    decoder = json.JSONDecoder()
    obj, idx = decoder.raw_decode(stripped)
    if stripped[idx:].strip():
        raise ValueError("extra non-JSON content")
    return obj
