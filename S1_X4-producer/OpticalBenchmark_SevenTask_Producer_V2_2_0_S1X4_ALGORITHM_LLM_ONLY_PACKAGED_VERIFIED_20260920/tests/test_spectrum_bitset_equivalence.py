from __future__ import annotations

import random

from src.multi_topology.simulation import IncrementalSpectrum


def _reference_starts(spectrum: IncrementalSpectrum, path: list[int], required: int) -> list[int]:
    occupied = 0
    for link in path:
        occupied |= spectrum.occupancy[link]
    mask = (1 << required) - 1
    return [start for start in range(spectrum.slot_count - required + 1)
            if occupied & (mask << start) == 0]


def test_bitset_feasible_starts_matches_direct_scan_random_states() -> None:
    rng = random.Random(20260809)
    for slot_count in (8, 16, 40, 320):
        spectrum = IncrementalSpectrum(6, slot_count)
        for link in range(6):
            bits = 0
            for slot in range(slot_count):
                if rng.random() < 0.35:
                    bits |= 1 << slot
            spectrum.occupancy[link] = bits
        for required in (1, 2, 3, 5, 9):
            if required > slot_count:
                continue
            for path in ([0], [0, 1], [1, 3, 5]):
                expected = _reference_starts(spectrum, list(path), required)
                assert spectrum.feasible_starts(list(path), required) == expected
                assert spectrum.first_feasible_start(list(path), required) == (expected[0] if expected else None)
