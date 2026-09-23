import json
import math


def test_p90_uses_hyndman_fan_type7_vector():
    from src.numeric import p90_type7

    assert p90_type7([0.0, 0.1, 0.2, 0.3, 0.4]) == 0.36


def test_spectrum_metrics_keep_binary64_until_serialization():
    from src.state_simulation.core import spectrum_metrics

    metrics = spectrum_metrics({0: [0, 1, 1, 1, 1, 1, 1]}, 7)
    expected = 1 - 6 / 7
    assert metrics["link_spectrum_metrics"][0]["link_utilization"] == expected
    assert metrics["link_spectrum_metrics"][0]["link_utilization"] != round(expected, 12)


def test_json_serialization_has_at_most_12_fractional_digits_without_mutating_input(tmp_path):
    from src.pipeline import write_json

    value = 1 / 7
    obj = {"derived": value}
    path = tmp_path / "value.json"
    write_json(path, obj)
    encoded = path.read_text(encoding="utf-8")
    assert obj["derived"] == value
    assert json.loads(encoded)["derived"] == round(value, 12)
    fractional = encoded.split(".", 1)[1].split("\n", 1)[0].rstrip(",")
    assert len(fractional) <= 12


def test_validator_float_tolerance_and_discrete_exactness():
    from src.numeric import values_equal

    assert values_equal(1.0 + 5e-10, 1.0)
    assert not values_equal(1.0 + 2e-9, 1.0)
    assert values_equal(5e-13, 0.0)
    assert not values_equal(2e-12, 0.0)
    assert values_equal([1, 2, 3], [1, 2, 3])
    assert not values_equal([1, 2, 3], [1, 3, 2])
    assert not values_equal(True, 1)
