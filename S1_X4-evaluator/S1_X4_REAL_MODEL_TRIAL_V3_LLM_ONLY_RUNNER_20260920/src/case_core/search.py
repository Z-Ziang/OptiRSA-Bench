from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from src.case_core.allocation_validation import is_assignment_feasible
from src.case_core.wufr import WUFR_ABS_TOL, build_reference_paths


class SearchBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    feasible: bool
    optimal_wufr: float | None
    reference_action: dict | None
    equivalent_optimum_count: int | None
    evaluated_complete_solutions: int


def enumerate_feasible_actions(
    paths: list[dict], required_slots: int, spectrum_by_link: dict[int, list[int]]
) -> list[dict]:
    if not spectrum_by_link:
        return []
    slot_count = len(next(iter(spectrum_by_link.values())))
    actions: list[dict] = []
    for path in sorted(paths, key=lambda x: int(x.get("path_rank", 1))):
        path_rank = int(path.get("path_rank", 1))
        path_link_ids = [int(x) for x in path["path_link_ids"]]
        for slot_start in range(0, slot_count - int(required_slots) + 1):
            if is_assignment_feasible(path_link_ids, slot_start, int(required_slots), spectrum_by_link):
                actions.append({
                    "path_rank": path_rank,
                    "slot_start": slot_start,
                    "path_link_ids": path_link_ids,
                })
    return actions


def _required_slots_probability_table(required_slots_probabilities: dict[int, float], slot_count: int) -> list[float]:
    table=[]
    for length in range(slot_count+1):
        table.append(sum(float(p) for width,p in required_slots_probabilities.items() if int(width) <= length))
    return table


def _run_lengths(mask: int) -> list[int]:
    lengths=[]
    while mask:
        while mask and (mask & 1) == 0:
            mask >>= 1
        if not mask:
            break
        length=0
        while mask & 1:
            length += 1
            mask >>= 1
        lengths.append(length)
    return lengths


class _ExactWufrScorer:
    """Exact network WUFR scorer using integer free-slot masks and affected-path deltas."""
    def __init__(self, spectrum_by_link: dict[int,list[int]], required_slots_probabilities: dict[int,float], reference_paths: list[dict]):
        if not spectrum_by_link:
            raise ValueError("empty spectrum state")
        self.slot_count=len(next(iter(spectrum_by_link.values())))
        self.free_masks={}
        for link_id,row in spectrum_by_link.items():
            if len(row) != self.slot_count or any(v not in (0,1) for v in row):
                raise ValueError("invalid spectrum state")
            mask=0
            for i,v in enumerate(row):
                if v == 1:
                    mask |= 1 << i
            self.free_masks[int(link_id)]=mask
        self.qfit=_required_slots_probability_table(required_slots_probabilities,self.slot_count)
        self.refs=reference_paths
        self.refs_by_link={}
        self.base_values=[]
        for idx,ref in enumerate(reference_paths):
            links=[int(x) for x in ref['path_link_ids']]
            for link_id in links:
                self.refs_by_link.setdefault(link_id,set()).add(idx)
            self.base_values.append(self._path_value(links,self.free_masks))
        self.base_sum=sum(self.base_values)

    def _path_value(self, links: list[int], masks: dict[int,int]) -> float:
        if not links:
            raise ValueError("path must contain at least one link")
        link_masks=[masks.get(link_id,self.free_masks[link_id]) for link_id in links]
        free_total=sum(mask.bit_count() for mask in link_masks)
        if free_total == 0:
            return 0.0
        common=link_masks[0]
        for mask in link_masks[1:]:
            common &= mask
        common_free=common.bit_count()
        n=len(link_masks)
        wasted=free_total - n*common_free
        unusable=0.0
        for length in _run_lengths(common):
            unusable += n*length*(1.0-self.qfit[length])
        return float((wasted+unusable)/free_total)

    def score(self, allocations: list[dict]) -> float:
        modified={}
        changed_links=set()
        for item in allocations:
            start=int(item['slot_start']); width=int(item['required_slots'])
            interval_mask=((1 << width)-1) << start
            for link_id_raw in item['path_link_ids']:
                link_id=int(link_id_raw)
                current=modified.get(link_id,self.free_masks[link_id])
                if current & interval_mask != interval_mask:
                    raise ValueError("allocation collides with occupied spectrum")
                modified[link_id]=current & ~interval_mask
                changed_links.add(link_id)
        affected=set()
        for link_id in changed_links:
            affected.update(self.refs_by_link.get(link_id,()))
        total=self.base_sum
        for idx in affected:
            total -= self.base_values[idx]
            links=[int(x) for x in self.refs[idx]['path_link_ids']]
            total += self._path_value(links,modified)
        return float(total/len(self.refs))


def search_single_optimum(
    nodes: list[int], directed_links: list[dict], spectrum_by_link: dict[int, list[int]],
    required_slots_probabilities: dict[int, float], required_slots: int, paths: list[dict],
    *, max_complete_solutions: int = 100_000,
) -> SearchResult:
    actions = enumerate_feasible_actions(paths, required_slots, spectrum_by_link)
    if not actions:
        return SearchResult(False, None, None, None, 0)
    if len(actions) > max_complete_solutions:
        raise SearchBudgetExceeded(f"single-request exact search requires {len(actions)} evaluations")
    refs = build_reference_paths(nodes, directed_links)
    scorer = _ExactWufrScorer(spectrum_by_link, required_slots_probabilities, refs)
    best_value: float | None = None
    best_action: dict | None = None
    equivalent = 0
    evaluated = 0
    for action in actions:
        evaluated += 1
        value = scorer.score([{"path_link_ids": action["path_link_ids"], "slot_start": action["slot_start"], "required_slots": required_slots}])
        public_action = {"path_rank": action["path_rank"], "slot_start": action["slot_start"]}
        if best_value is None or value < best_value - WUFR_ABS_TOL:
            best_value = value
            best_action = public_action
            equivalent = 1
        elif isclose(value, best_value, rel_tol=0.0, abs_tol=WUFR_ABS_TOL):
            equivalent += 1
            if (public_action["path_rank"], public_action["slot_start"]) < (best_action["path_rank"], best_action["slot_start"]):
                best_action = public_action
    return SearchResult(True, float(best_value), best_action, equivalent, evaluated)


def search_joint_optimum(
    nodes: list[int], directed_links: list[dict], spectrum_by_link: dict[int, list[int]],
    required_slots_probabilities: dict[int, float], requests: list[dict],
    *, max_complete_solutions: int = 100_000,
) -> SearchResult:
    refs = build_reference_paths(nodes, directed_links)
    scorer = _ExactWufrScorer(spectrum_by_link, required_slots_probabilities, refs)
    per_request: dict[str, tuple[int, list[dict]]] = {}
    input_order: list[str] = []
    for request in requests:
        rid = str(request["request_id"])
        input_order.append(rid)
        width = int(request["required_slots"])
        actions = enumerate_feasible_actions(list(request["paths"]), width, spectrum_by_link)
        if not actions:
            return SearchResult(False, None, None, None, 0)
        per_request[rid] = (width, actions)

    visit_order = sorted(input_order, key=lambda rid: (len(per_request[rid][1]), rid))
    occupied_new: set[tuple[int, int]] = set()
    chosen: dict[str, dict] = {}
    best_value: float | None = None
    best_public: dict | None = None
    equivalent = 0
    evaluated = 0

    def recurse(index: int) -> None:
        nonlocal best_value, best_public, equivalent, evaluated
        if index == len(visit_order):
            evaluated += 1
            if evaluated > max_complete_solutions:
                raise SearchBudgetExceeded(
                    f"joint exact search exceeded {max_complete_solutions} complete feasible solutions"
                )
            full_allocations = []
            public_allocations = []
            for rid in input_order:
                width, _ = per_request[rid]
                action = chosen[rid]
                full_allocations.append({
                    "path_link_ids": action["path_link_ids"],
                    "slot_start": action["slot_start"],
                    "required_slots": width,
                })
                item = {"request_id": rid, "slot_start": action["slot_start"]}
                if action.get("path_rank") is not None:
                    item["path_rank"] = action["path_rank"]
                public_allocations.append(item)
            value = scorer.score(full_allocations)
            public = {"allocations": public_allocations}
            key = tuple((x["request_id"], x.get("path_rank", 0), x["slot_start"]) for x in public_allocations)
            best_key = tuple((x["request_id"], x.get("path_rank", 0), x["slot_start"]) for x in best_public["allocations"]) if best_public else None
            if best_value is None or value < best_value - WUFR_ABS_TOL:
                best_value = value
                best_public = public
                equivalent = 1
            elif isclose(value, best_value, rel_tol=0.0, abs_tol=WUFR_ABS_TOL):
                equivalent += 1
                if best_key is None or key < best_key:
                    best_public = public
            return

        rid = visit_order[index]
        width, actions = per_request[rid]
        for action in actions:
            cells = {
                (int(link_id), slot)
                for link_id in action["path_link_ids"]
                for slot in range(action["slot_start"], action["slot_start"] + width)
            }
            if not occupied_new.isdisjoint(cells):
                continue
            occupied_new.update(cells)
            chosen[rid] = action
            recurse(index + 1)
            chosen.pop(rid, None)
            occupied_new.difference_update(cells)

    recurse(0)
    if best_value is None:
        return SearchResult(False, None, None, None, evaluated)
    return SearchResult(True, float(best_value), best_public, equivalent, evaluated)
