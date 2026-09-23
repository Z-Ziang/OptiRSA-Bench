from __future__ import annotations


def _validate_binary(values: list[int]) -> None:
    if not isinstance(values, list) or not values:
        raise ValueError("slot availability must be a non-empty list")
    if any(v not in (0, 1) for v in values):
        raise ValueError("slot availability values must be 0 or 1")


def binary_to_occupied_ranges(values: list[int]) -> list[list[int]]:
    """Convert canonical 1=free/0=occupied slot state into closed occupied ranges."""
    _validate_binary(values)
    out: list[list[int]] = []
    start: int | None = None
    for i, value in enumerate(values):
        if value == 0 and start is None:
            start = i
        elif value == 1 and start is not None:
            out.append([start, i - 1])
            start = None
    if start is not None:
        out.append([start, len(values) - 1])
    return out


def occupied_ranges_to_binary(slot_count: int, ranges: list[list[int]]) -> list[int]:
    """Expand closed occupied ranges into canonical 1=free/0=occupied slot state."""
    if not isinstance(slot_count, int) or isinstance(slot_count, bool) or slot_count <= 0:
        raise ValueError("slot_count must be a positive integer")
    if not isinstance(ranges, list):
        raise ValueError("ranges must be a list")
    values = [1] * slot_count
    previous_end = -1
    for item in ranges:
        if not (isinstance(item, list) and len(item) == 2):
            raise ValueError("each occupied range must be [start,end]")
        start, end = item
        if any(not isinstance(x, int) or isinstance(x, bool) for x in (start, end)):
            raise ValueError("occupied range bounds must be integers")
        if start < 0 or end < start or end >= slot_count:
            raise ValueError("occupied range is out of bounds")
        if start <= previous_end:
            raise ValueError("occupied ranges must be disjoint and strictly ordered")
        for slot in range(start, end + 1):
            values[slot] = 0
        previous_end = end
    return values


def compress_resource_state(resource_state: dict) -> list[dict]:
    slot_count = resource_state.get("slot_count")
    rows = resource_state.get("link_spectrum_states")
    if not isinstance(slot_count, int) or not isinstance(rows, list):
        raise ValueError("resource state missing slot_count/link_spectrum_states")
    result = []
    for row in rows:
        values = row.get("slot_availability")
        if len(values) != slot_count:
            raise ValueError("slot_availability length does not match slot_count")
        ranges = binary_to_occupied_ranges(values)
        if occupied_ranges_to_binary(slot_count, ranges) != values:
            raise ValueError("spectrum codec round trip failed")
        result.append({"link_id": int(row["link_id"]), "occupied_ranges": ranges})
    result.sort(key=lambda x: x["link_id"])
    return result
