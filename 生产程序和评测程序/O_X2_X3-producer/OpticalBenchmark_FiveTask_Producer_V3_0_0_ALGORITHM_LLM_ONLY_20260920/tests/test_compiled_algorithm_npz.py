from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.algorithm_api.loader import compile_algorithm_input


def _links() -> list[dict]:
    return [
        {"link_id": 0, "source_node_id": 0, "destination_node_id": 1},
        {"link_id": 1, "source_node_id": 1, "destination_node_id": 3},
        {"link_id": 2, "source_node_id": 0, "destination_node_id": 2},
        {"link_id": 3, "source_node_id": 2, "destination_node_id": 3},
        {"link_id": 4, "source_node_id": 1, "destination_node_id": 2},
        {"link_id": 5, "source_node_id": 2, "destination_node_id": 1},
        {"link_id": 6, "source_node_id": 3, "destination_node_id": 1},
        {"link_id": 7, "source_node_id": 1, "destination_node_id": 0},
        {"link_id": 8, "source_node_id": 3, "destination_node_id": 2},
        {"link_id": 9, "source_node_id": 2, "destination_node_id": 0},
    ]


def _base(task: str) -> dict:
    spectrum = [
        {"link_id": link["link_id"], "occupied_ranges": [[10, 11], [100, 101]]}
        for link in _links()
    ]
    return {
        "task_type": task,
        "slot_count": 320,
        "nodes": [0, 1, 2, 3],
        "directed_links": _links(),
        "link_spectrum_states": spectrum,
    }


def _path(rank: int, nodes: list[int], links: list[int]) -> dict:
    value = {"path_node_ids": nodes, "path_link_ids": links}
    if rank is not None:
        value = {"path_rank": rank, **value}
    return value


def _input(task: str) -> dict:
    value = _base(task)
    if task == "O1":
        value["requests"] = [
            {"request_id": "r1", "source_node_id": 0, "destination_node_id": 3, "required_slots": 2,
             "fixed_path": _path(None, [0, 1, 3], [0, 1])},
            {"request_id": "r2", "source_node_id": 0, "destination_node_id": 3, "required_slots": 3,
             "fixed_path": _path(None, [0, 2, 3], [2, 3])},
        ]
    elif task == "O2-S":
        value["requests"] = [{
            "request_id": "r1", "source_node_id": 0, "destination_node_id": 3, "required_slots": 2,
            "candidate_paths": [_path(1, [0, 1, 3], [0, 1]), _path(2, [0, 2, 3], [2, 3])],
        }]
    elif task == "O2-C":
        value["requests"] = [
            {"request_id": "r1", "source_node_id": 0, "destination_node_id": 3, "required_slots": 2,
             "candidate_paths": [_path(1, [0, 1, 3], [0, 1]), _path(2, [0, 2, 3], [2, 3])]},
            {"request_id": "r2", "source_node_id": 3, "destination_node_id": 0, "required_slots": 3,
             "candidate_paths": [_path(1, [3, 1, 0], [6, 7]), _path(2, [3, 2, 0], [8, 9])]},
        ]
    elif task == "X2":
        value["requests"] = [{"request_id": "r1", "source_node_id": 0, "destination_node_id": 3, "required_slots": 2}]
    elif task == "X3":
        value["requests"] = [
            {"request_id": "r1", "source_node_id": 0, "destination_node_id": 3, "required_slots": 2},
            {"request_id": "r2", "source_node_id": 3, "destination_node_id": 0, "required_slots": 3},
        ]
    else:
        raise AssertionError(task)
    return value


def _signature(compiled) -> dict:
    return {
        "case_id": compiled.case_id,
        "schema_version": compiled.schema_version,
        "task_type": compiled.task_type,
        "slot_count": compiled.slot_count,
        "nodes": compiled.nodes,
        "directed_links": tuple((x.link_id, x.source_node_id, x.destination_node_id) for x in compiled.directed_links),
        "edge_src": compiled.edge_src,
        "edge_dst": compiled.edge_dst,
        "out_edges": compiled.out_edges,
        "occupied": tuple(sorted(compiled.occupied_mask_by_link.items())),
        "requests": tuple((
            x.request_id, x.source_node_id, x.destination_node_id, x.required_slots,
            None if x.fixed_path is None else (x.fixed_path.path_node_ids, x.fixed_path.path_link_ids),
            tuple((p.path_rank, p.path_node_ids, p.path_link_ids) for p in x.candidate_paths),
        ) for x in compiled.requests),
    }


def test_deterministic_npz_round_trip_and_public_field_allowlist(tmp_path: Path) -> None:
    from src.algorithm_api.compiled_npz import NPZ_KEYS, write_compiled_algorithm_case
    from src.algorithm_api.loader import load_compiled_algorithm_case

    value = _input("O1")
    first = tmp_path / "first.npz"
    second = tmp_path / "second.npz"
    write_compiled_algorithm_case(first, value, case_id="O1_NPZ_TEST")
    write_compiled_algorithm_case(second, value, case_id="O1_NPZ_TEST")
    assert first.read_bytes() == second.read_bytes()
    with np.load(first, allow_pickle=False) as archive:
        assert set(archive.files) == set(NPZ_KEYS)
        assert all(archive[name].dtype != np.dtype("O") for name in archive.files)
        assert archive["occupied_mask_words"].dtype == np.dtype("uint64")
        assert archive["occupied_mask_words"].shape == (len(value["directed_links"]), 5)
    loaded = load_compiled_algorithm_case(first)
    assert _signature(loaded) == _signature(compile_algorithm_input(value, case_id="O1_NPZ_TEST"))


def test_spectrum_ranges_are_bitset_equivalent_for_all_links(tmp_path: Path) -> None:
    from src.algorithm_api.compiled_npz import write_compiled_algorithm_case

    value = _input("X2")
    path = tmp_path / "x2.npz"
    write_compiled_algorithm_case(path, value, case_id="X2_NPZ_TEST")
    with np.load(path, allow_pickle=False) as archive:
        words = archive["occupied_mask_words"]
        for row, state in zip(words, value["link_spectrum_states"], strict=True):
            mask = sum(int(word) << (64 * index) for index, word in enumerate(row))
            expected = 0
            for start, end in state["occupied_ranges"]:
                expected |= sum(1 << slot for slot in range(start, end + 1))
            assert mask == expected


def test_paths_and_requests_round_trip_for_o2s_and_o2c(tmp_path: Path) -> None:
    from src.algorithm_api.compiled_npz import write_compiled_algorithm_case
    from src.algorithm_api.loader import load_compiled_algorithm_case

    for task in ("O2-S", "O2-C"):
        value = _input(task)
        path = tmp_path / f"{task}.npz"
        write_compiled_algorithm_case(path, value, case_id=f"{task}_NPZ_TEST")
        loaded = load_compiled_algorithm_case(path)
        assert _signature(loaded) == _signature(compile_algorithm_input(value, case_id=f"{task}_NPZ_TEST"))


def test_x2_x3_compiled_files_have_no_supplied_path_payload(tmp_path: Path) -> None:
    from src.algorithm_api.compiled_npz import write_compiled_algorithm_case

    for task in ("X2", "X3"):
        path = tmp_path / f"{task}.npz"
        write_compiled_algorithm_case(path, _input(task), case_id=f"{task}_NPZ_TEST")
        with np.load(path, allow_pickle=False) as archive:
            assert archive["fixed_path_node_offsets"].size == len(_input(task)["requests"]) + 1
            assert archive["fixed_path_link_offsets"].size == len(_input(task)["requests"]) + 1
            assert archive["fixed_path_nodes"].size == 0
            assert archive["fixed_path_links"].size == 0
            assert archive["candidate_request_offsets"].size == len(_input(task)["requests"]) + 1
            assert archive["candidate_path_ranks"].size == 0
            assert archive["candidate_path_nodes"].size == 0
            assert archive["candidate_path_links"].size == 0


def test_compiled_npz_has_no_answer_or_private_payload(tmp_path: Path) -> None:
    from src.algorithm_api.compiled_npz import write_compiled_algorithm_case

    path = tmp_path / "case.npz"
    write_compiled_algorithm_case(path, _input("X3"), case_id="X3_NPZ_TEST")
    with np.load(path, allow_pickle=False) as archive:
        payload_parts = []
        for name in archive.files:
            value = archive[name]
            if value.dtype.kind == "S":
                payload_parts.append(b" ".join(bytes(item) for item in value.tolist()).decode("utf-8"))
            else:
                payload_parts.append(json.dumps(value.tolist(), ensure_ascii=False))
        payload = " ".join(payload_parts).lower()
    for forbidden in ("reference", "oracle", "truth", "calibration", "provenance", "difficulty", "feasible_action"):
        assert forbidden not in payload
