from __future__ import annotations


def assignment_interval(slot_start: int, required_slots: int, slot_count: int) -> range:
    if any(not isinstance(x, int) or isinstance(x, bool) for x in (slot_start, required_slots, slot_count)):
        raise ValueError("slot values must be integers")
    if required_slots <= 0 or slot_count <= 0 or slot_start < 0 or slot_start + required_slots > slot_count:
        raise ValueError("slot allocation is out of bounds")
    return range(slot_start, slot_start + required_slots)


def is_assignment_feasible(
    path_link_ids: list[int],
    slot_start: int,
    required_slots: int,
    spectrum_by_link: dict[int, list[int]],
) -> bool:
    if not path_link_ids:
        return False
    try:
        slot_count = len(next(iter(spectrum_by_link.values())))
        interval = assignment_interval(slot_start, required_slots, slot_count)
    except (StopIteration, ValueError):
        return False
    for link_id in path_link_ids:
        row = spectrum_by_link.get(int(link_id))
        if row is None or len(row) != slot_count:
            return False
        if any(row[slot] != 1 for slot in interval):
            return False
    return True


def joint_allocations_feasible(
    allocations: list[dict],
    request_specs: dict[str, dict],
    path_specs: dict[str, dict],
    spectrum_by_link: dict[int, list[int]],
) -> bool:
    if set(request_specs) != {item.get("request_id") for item in allocations}:
        return False
    occupied_new: set[tuple[int, int]] = set()
    slot_count = len(next(iter(spectrum_by_link.values()))) if spectrum_by_link else 0
    for item in allocations:
        request_id = item.get("request_id")
        if request_id not in request_specs or request_id not in path_specs:
            return False
        required_slots = int(request_specs[request_id]["required_slots"])
        slot_start = item.get("slot_start")
        if not isinstance(slot_start, int) or isinstance(slot_start, bool):
            return False
        path_link_ids = list(path_specs[request_id]["path_link_ids"])
        if not is_assignment_feasible(path_link_ids, slot_start, required_slots, spectrum_by_link):
            return False
        try:
            slots = assignment_interval(slot_start, required_slots, slot_count)
        except ValueError:
            return False
        cells = {(int(link_id), slot) for link_id in path_link_ids for slot in slots}
        if not occupied_new.isdisjoint(cells):
            return False
        occupied_new.update(cells)
    return True
