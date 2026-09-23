from __future__ import annotations

import importlib.util

import numpy as np
import pytest


def test_bitset_module_is_present() -> None:
    assert importlib.util.find_spec("src.s1_x4.algorithm_api.bitset") is not None


@pytest.mark.parametrize("slot_count", [1, 63, 64, 65, 130, 319, 320])
def test_binary_free_bitset_round_trip_and_shape(slot_count: int) -> None:
    from src.s1_x4.algorithm_api.bitset import binary_to_free_words, free_words_to_binary

    values = [1 if (i % 5 not in {1, 4}) else 0 for i in range(slot_count)]
    words = binary_to_free_words(values)

    assert isinstance(words, np.ndarray)
    assert words.dtype == np.uint64
    assert words.shape == ((slot_count + 63) // 64,)
    assert not words.flags.writeable
    assert free_words_to_binary(words, slot_count) == values


def test_bitset_boundaries_and_all_free_occupied() -> None:
    from src.s1_x4.algorithm_api.bitset import binary_to_free_words, free_words_to_binary

    for values in ([1] * 320, [0] * 320):
        words = binary_to_free_words(values)
        assert free_words_to_binary(words, 320) == values

    values = [0] * 320
    for slot in (0, 63, 64, 319):
        values[slot] = 1
    assert free_words_to_binary(binary_to_free_words(values), 320) == values
