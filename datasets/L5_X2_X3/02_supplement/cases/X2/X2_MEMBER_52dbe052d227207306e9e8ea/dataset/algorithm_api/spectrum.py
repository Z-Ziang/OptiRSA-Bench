"""Bitset helpers for the public Algorithm runtime.

The canonical public encoding is a list of closed occupied ranges.  Bit ``i``
is one when slot ``i`` is occupied, so one 320-slot link can be represented by
one Python arbitrary-precision integer or, equivalently, five ``uint64``
words in another language.
"""

from __future__ import annotations

from typing import Iterable


def occupied_ranges_to_mask(slot_count: int, occupied_ranges: Iterable[Iterable[int]]) -> int:
    if isinstance(slot_count, bool) or not isinstance(slot_count, int) or slot_count <= 0:
        raise ValueError("slot_count must be a positive integer")
    if not isinstance(occupied_ranges, (list, tuple)):
        raise ValueError("occupied_ranges must be a list")
    mask = 0
    previous_end = -1
    for item in occupied_ranges:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("occupied range must be [start, end]")
        start, end = item
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)):
            raise ValueError("occupied range bounds must be integers")
        if start < 0 or end < start or end >= slot_count or start <= previous_end:
            raise ValueError("occupied range is out of bounds or not strictly ordered")
        width = end - start + 1
        mask |= ((1 << width) - 1) << start
        previous_end = end
    return mask


def direct_occupied_mask(slot_count: int, occupied_ranges: Iterable[Iterable[int]]) -> int:
    """Reference direct-scan implementation used by equivalence tests."""

    if not isinstance(occupied_ranges, (list, tuple)):
        raise ValueError("occupied_ranges must be a list")
    values = [0] * slot_count
    for item in occupied_ranges:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("occupied range must be [start, end]")
        start, end = item
        if start < 0 or end < start or end >= slot_count:
            raise ValueError("occupied range is out of bounds")
        for slot in range(start, end + 1):
            values[slot] = 1
    return sum(value << slot for slot, value in enumerate(values))


def path_occupied_mask(path_link_ids: Iterable[int], occupied_mask_by_link: dict[int, int]) -> int:
    """Return the occupied union for an already supplied path.

    This helper only evaluates a supplied path.  It does not discover paths or
    choose an action.
    """

    mask = 0
    for link_id in path_link_ids:
        try:
            mask |= occupied_mask_by_link[int(link_id)]
        except KeyError as exc:
            raise ValueError(f"unknown link_id {link_id}") from exc
    return mask
