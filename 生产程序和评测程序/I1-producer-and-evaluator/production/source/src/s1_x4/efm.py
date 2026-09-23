from __future__ import annotations
from statistics import fmean


def _validate_bits(bits: list[int]) -> None:
    if not isinstance(bits, list) or not bits:
        raise ValueError("slot availability must be a non-empty list")
    if any(x not in (0, 1) for x in bits):
        raise ValueError("slot availability values must be 0 or 1")


def largest_free_block(bits: list[int]) -> int:
    _validate_bits(bits)
    best = run = 0
    for bit in bits:
        if bit == 1:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def link_efm(bits: list[int]) -> float | None:
    """Classic external fragmentation metric: 1 - Bmax/F for F>0.

    When F==0 the classic formula is undefined (0/0); the benchmark contract
    represents that state as None and excludes it from network aggregation.
    """
    _validate_bits(bits)
    free = sum(bits)
    if free == 0:
        return None
    return 1.0 - largest_free_block(bits) / free


def network_efm(spectrum_by_link: dict[int, list[int]]) -> dict:
    if not spectrum_by_link:
        raise ValueError("spectrum_by_link must be non-empty")
    per_link = []
    defined = []
    for link_id in sorted(spectrum_by_link):
        bits = list(spectrum_by_link[link_id])
        value = link_efm(bits)
        per_link.append({
            "link_id": int(link_id),
            "free_slot_count": int(sum(bits)),
            "largest_free_block_length": int(largest_free_block(bits)),
            "external_fragmentation": value,
        })
        if value is not None:
            defined.append(value)
    return {
        "network_efm": fmean(defined) if defined else None,
        "efm_defined_link_count": len(defined),
        "link_efm": per_link,
    }
