from __future__ import annotations

import importlib
import json

import pytest


def _loader_module():
    try:
        return importlib.import_module("src.algorithm_api.loader")
    except ModuleNotFoundError as exc:
        pytest.fail(f"expected Algorithm API loader is missing: {exc}")


def _x2_input() -> dict:
    return {
        "schema_version": "ALGORITHM_INPUT_V1_0",
        "task_type": "X2",
        "slot_count": 320,
        "nodes": [0, 1, 2],
        "directed_links": [
            {"link_id": 0, "source_node_id": 0, "destination_node_id": 1},
            {"link_id": 1, "source_node_id": 1, "destination_node_id": 2},
        ],
        "link_spectrum_states": [
            {"link_id": 0, "occupied_ranges": [[0, 1], [10, 12]]},
            {"link_id": 1, "occupied_ranges": [[2, 4]]},
        ],
        "requests": [
            {"request_id": "r1", "source_node_id": 0, "destination_node_id": 2, "required_slots": 2}
        ],
    }


def test_compile_algorithm_input_is_deterministic_and_indexed() -> None:
    module = _loader_module()
    first = module.compile_algorithm_input(_x2_input(), case_id="X2_API")
    second = module.compile_algorithm_input(_x2_input(), case_id="X2_API")
    assert first == second
    assert first.case_id == "X2_API"
    assert first.edge_src == (0, 1)
    assert first.edge_dst == (1, 2)
    assert first.out_edges == ((0,), (1,), ())
    assert dict(first.required_slots_probabilities) == {"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25}
    assert first.occupied_mask_by_link[0] & (1 << 0)
    assert first.occupied_mask_by_link[0] & (1 << 1)
    assert not (first.occupied_mask_by_link[0] & (1 << 2))


def test_load_algorithm_case_accepts_case_id_input_wrapper(tmp_path) -> None:
    module = _loader_module()
    path = tmp_path / "case.json"
    path.write_text(json.dumps({"case_id": "X2_API", "input": _x2_input()}), encoding="utf-8")
    loaded = module.load_algorithm_case(path)
    assert loaded.case_id == "X2_API"
    assert loaded.task_type == "X2"


def test_loader_rejects_out_of_range_occupied_range() -> None:
    module = _loader_module()
    invalid = _x2_input()
    invalid["link_spectrum_states"][0]["occupied_ranges"] = [[319, 320]]
    with pytest.raises(ValueError, match="occupied range"):
        module.compile_algorithm_input(invalid, case_id="X2_BAD")


def test_bitset_matches_direct_scan_for_closed_ranges() -> None:
    spectrum = importlib.import_module("src.algorithm_api.spectrum")
    ranges = [[0, 1], [10, 12], [319, 319]]
    assert spectrum.occupied_ranges_to_mask(320, ranges) == spectrum.direct_occupied_mask(320, ranges)


def test_loader_has_no_solver_or_path_search_surface() -> None:
    module = _loader_module()
    compiled = module.compile_algorithm_input(_x2_input(), case_id="X2_API")
    for name in ("find_paths", "search_paths", "select_best_path", "select_best_slot", "solve", "recommend"):
        assert not hasattr(compiled, name)
    source = module.__file__.replace("\\", "/")
    assert "/src/tasks/" not in source
