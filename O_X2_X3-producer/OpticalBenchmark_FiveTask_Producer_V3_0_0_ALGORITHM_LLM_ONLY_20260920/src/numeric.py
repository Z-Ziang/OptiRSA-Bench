from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any

import numpy as np

REL_TOL = 1e-9
ABS_TOL = 1e-12


def p90_type7(values: list[float]) -> float:
    if not values:
        raise ValueError("P90 requires at least one value")
    return float(np.percentile(np.asarray(values, dtype=np.float64), 90, method="linear"))


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, Integral)):
        return value
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite floats are not valid P0 JSON values")
        return round(number, 12)
    return value


def values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, Real) and isinstance(expected, Real):
        if isinstance(actual, Integral) and isinstance(expected, Integral):
            return int(actual) == int(expected)
        return math.isclose(float(actual), float(expected), rel_tol=REL_TOL, abs_tol=ABS_TOL)
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(values_equal(actual[key], expected[key]) for key in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(values_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected
