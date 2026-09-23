from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _integer_slot_count(slot_count: int) -> int:
    if not isinstance(slot_count, int) or isinstance(slot_count, bool) or slot_count <= 0:
        raise ValueError("slot_count must be a positive integer")
    return slot_count


def binary_to_free_words(values: Sequence[int]) -> np.ndarray:
    if not isinstance(values, (list, tuple, np.ndarray)) or len(values) == 0:
        raise ValueError("slot availability must be a non-empty sequence")
    slot_count = len(values)
    words = np.zeros((slot_count + 63) // 64, dtype=np.uint64)
    for slot, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) not in (0, 1):
            raise ValueError("slot availability values must be 0 or 1")
        if int(value) == 1:
            words[slot // 64] |= np.uint64(1 << (slot % 64))
    words.setflags(write=False)
    return words


def free_words_to_binary(words: Sequence[int], slot_count: int) -> list[int]:
    slot_count = _integer_slot_count(slot_count)
    array = np.asarray(words, dtype=np.uint64)
    if array.ndim != 1 or len(array) != (slot_count + 63) // 64:
        raise ValueError("word count does not match slot_count")
    return [
        1 if int(array[slot // 64]) & (1 << (slot % 64)) else 0
        for slot in range(slot_count)
    ]
