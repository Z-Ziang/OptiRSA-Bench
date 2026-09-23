"""Deterministic binary compiler for the public five-task Algorithm input.

The NPZ artifact is a representation-only compilation of the canonical
``benchmark_case.instance``.  It has no solver surface and contains no
reference, truth, oracle, calibration, or provenance data.
"""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

import numpy as np

from .types import CompiledAlgorithmCase, CompiledLink, CompiledPath, CompiledRequest


NPZ_FORMAT_VERSION = "COMPILED_ALGORITHM_CASE_NPZ_V1_0"
ALGORITHM_SCHEMA_VERSION = "ALGORITHM_INPUT_V1_0"
_TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
_WORD_COUNT = 5
_UINT64 = np.dtype("uint64")
_INT64 = np.dtype("int64")
_BYTE = np.dtype("uint8")

NPZ_KEYS = (
    "format_version",
    "schema_version",
    "task_type",
    "case_id",
    "slot_count",
    "nodes",
    "link_ids",
    "edge_src",
    "edge_dst",
    "out_edges_offsets",
    "out_edges_values",
    "occupied_mask_words",
    "request_ids",
    "request_source_node_ids",
    "request_destination_node_ids",
    "request_required_slots",
    "fixed_path_node_offsets",
    "fixed_path_nodes",
    "fixed_path_link_offsets",
    "fixed_path_links",
    "candidate_request_offsets",
    "candidate_path_ranks",
    "candidate_path_node_offsets",
    "candidate_path_nodes",
    "candidate_path_link_offsets",
    "candidate_path_links",
)


def _array_bytes(array: np.ndarray) -> bytes:
    if array.dtype == np.dtype("O"):
        raise ValueError("object dtype is forbidden in compiled Algorithm NPZ")
    stream = BytesIO()
    np.lib.format.write_array(stream, np.ascontiguousarray(array), allow_pickle=False)
    return stream.getvalue()


def _fixed_bytes(values: list[str]) -> np.ndarray:
    encoded = [str(value).encode("utf-8") for value in values]
    width = max((len(value) for value in encoded), default=1)
    return np.asarray(encoded, dtype=f"|S{width}")


def _decode_fixed_bytes(array: np.ndarray, field: str) -> list[str]:
    if array.dtype.kind != "S":
        raise ValueError(f"{field} must use fixed-width bytes")
    try:
        return [bytes(value).rstrip(b"\x00").decode("utf-8") for value in array.tolist()]
    except UnicodeDecodeError as exc:
        raise ValueError(f"{field} contains invalid UTF-8") from exc


def _scalar_bytes(value: str) -> np.ndarray:
    encoded = str(value).encode("utf-8")
    return np.asarray([encoded], dtype=f"|S{max(1, len(encoded))}")


def _read_scalar_bytes(array: np.ndarray, field: str) -> str:
    if array.ndim != 1 or array.size != 1:
        raise ValueError(f"{field} must be a one-element fixed-width byte array")
    return _decode_fixed_bytes(array, field)[0]


def _int_array(values: list[int]) -> np.ndarray:
    return np.asarray([int(value) for value in values], dtype=_INT64)


def _fixed_path_arrays(requests: tuple[CompiledRequest, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    node_offsets = [0]
    link_offsets = [0]
    nodes: list[int] = []
    links: list[int] = []
    for request in requests:
        path = request.fixed_path
        if path is not None:
            nodes.extend(path.path_node_ids)
            links.extend(path.path_link_ids)
        node_offsets.append(len(nodes))
        link_offsets.append(len(links))
    return _int_array(node_offsets), _int_array(nodes), _int_array(link_offsets), _int_array(links)


def _candidate_path_arrays(requests: tuple[CompiledRequest, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    request_offsets = [0]
    ranks: list[int] = []
    node_offsets = [0]
    link_offsets = [0]
    nodes: list[int] = []
    links: list[int] = []
    for request in requests:
        for path in request.candidate_paths:
            if path.path_rank is None:
                raise ValueError("candidate path is missing path_rank")
            ranks.append(int(path.path_rank))
            nodes.extend(path.path_node_ids)
            links.extend(path.path_link_ids)
            node_offsets.append(len(nodes))
            link_offsets.append(len(links))
        request_offsets.append(len(ranks))
    return (
        _int_array(request_offsets),
        _int_array(ranks),
        _int_array(node_offsets),
        _int_array(nodes),
        _int_array(link_offsets),
        _int_array(links),
    )


def _mask_words(mask: int) -> np.ndarray:
    return np.asarray([(int(mask) >> (64 * index)) & ((1 << 64) - 1) for index in range(_WORD_COUNT)], dtype=_UINT64)


def _arrays_from_compiled(case: CompiledAlgorithmCase) -> dict[str, np.ndarray]:
    if case.case_id is None or not str(case.case_id):
        raise ValueError("compiled Algorithm case requires a non-empty case_id")
    links = tuple(case.directed_links)
    fixed_node_offsets, fixed_nodes, fixed_link_offsets, fixed_links = _fixed_path_arrays(case.requests)
    candidate_request_offsets, candidate_ranks, candidate_node_offsets, candidate_nodes, candidate_link_offsets, candidate_links = _candidate_path_arrays(case.requests)
    out_offsets = [0]
    for edges in case.out_edges:
        out_offsets.append(out_offsets[-1] + len(edges))
    return {
        "format_version": _scalar_bytes(NPZ_FORMAT_VERSION),
        "schema_version": _scalar_bytes(case.schema_version),
        "task_type": _scalar_bytes(case.task_type),
        "case_id": _scalar_bytes(str(case.case_id)),
        "slot_count": np.asarray([int(case.slot_count)], dtype=_INT64),
        "nodes": _int_array(list(case.nodes)),
        "link_ids": _int_array([link.link_id for link in links]),
        "edge_src": _int_array([link.source_node_id for link in links]),
        "edge_dst": _int_array([link.destination_node_id for link in links]),
        "out_edges_offsets": _int_array(out_offsets),
        "out_edges_values": _int_array([edge for edges in case.out_edges for edge in edges]),
        "occupied_mask_words": np.asarray([_mask_words(case.occupied_mask_by_link[link.link_id]) for link in links], dtype=_UINT64),
        "request_ids": _fixed_bytes([request.request_id for request in case.requests]),
        "request_source_node_ids": _int_array([request.source_node_id for request in case.requests]),
        "request_destination_node_ids": _int_array([request.destination_node_id for request in case.requests]),
        "request_required_slots": _int_array([request.required_slots for request in case.requests]),
        "fixed_path_node_offsets": fixed_node_offsets,
        "fixed_path_nodes": fixed_nodes,
        "fixed_path_link_offsets": fixed_link_offsets,
        "fixed_path_links": fixed_links,
        "candidate_request_offsets": candidate_request_offsets,
        "candidate_path_ranks": candidate_ranks,
        "candidate_path_node_offsets": candidate_node_offsets,
        "candidate_path_nodes": candidate_nodes,
        "candidate_path_link_offsets": candidate_link_offsets,
        "candidate_path_links": candidate_links,
    }


def _write_npz(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in NPZ_KEYS:
            if name not in arrays:
                raise ValueError(f"missing compiled NPZ array: {name}")
            info = ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            info.flag_bits = 0x800
            archive.writestr(info, _array_bytes(np.asarray(arrays[name])), compress_type=ZIP_DEFLATED, compresslevel=9)


def write_compiled_algorithm_case(
    path: str | Path,
    input_obj: dict[str, Any],
    *,
    case_id: str,
    contract: dict[str, Any] | None = None,
) -> None:
    """Compile one public Algorithm input and write a deterministic NPZ."""

    from .loader import compile_algorithm_input

    compiled = compile_algorithm_input(input_obj, case_id=case_id, contract=contract)
    _write_npz(Path(path).resolve(), _arrays_from_compiled(compiled))


def _require_array(arrays: Mapping[str, np.ndarray], name: str, *, dtype: np.dtype | None = None, ndim: int | None = None) -> np.ndarray:
    if name not in arrays:
        raise ValueError(f"compiled NPZ is missing {name}")
    value = np.asarray(arrays[name])
    if value.dtype == np.dtype("O"):
        raise ValueError(f"compiled NPZ {name} uses forbidden object dtype")
    if dtype is not None and value.dtype != dtype:
        raise ValueError(f"compiled NPZ {name} dtype must be {dtype}, got {value.dtype}")
    if ndim is not None and value.ndim != ndim:
        raise ValueError(f"compiled NPZ {name} must have ndim={ndim}")
    return value


def _offsets(array: np.ndarray, total: int, expected_length: int, field: str) -> list[int]:
    if array.dtype != _INT64 or array.ndim != 1 or array.size != expected_length:
        raise ValueError(f"{field} must be int64 with length {expected_length}")
    values = [int(value) for value in array.tolist()]
    if not values or values[0] != 0 or values[-1] != total or any(a > b for a, b in zip(values, values[1:])):
        raise ValueError(f"{field} is not a valid monotone offset array")
    return values


def _path_from_arrays(
    node_values: list[int],
    link_values: list[int],
    *,
    source: int,
    destination: int,
    link_by_id: dict[int, CompiledLink],
    path_rank: int | None,
) -> CompiledPath:
    if len(node_values) != len(link_values) + 1 or not node_values:
        raise ValueError("compiled path node/link lengths are inconsistent")
    if node_values[0] != source or node_values[-1] != destination:
        raise ValueError("compiled path endpoints do not match request")
    if len(set(node_values)) != len(node_values):
        raise ValueError("compiled path is not simple")
    for index, link_id in enumerate(link_values):
        link = link_by_id.get(link_id)
        if link is None or link.source_node_id != node_values[index] or link.destination_node_id != node_values[index + 1]:
            raise ValueError("compiled path links are not directionally contiguous")
    return CompiledPath(tuple(node_values), tuple(link_values), path_rank)


def _contract_for_task(task: str, contract_path: str | Path | None, use_default_contract: bool) -> dict[str, Any] | None:
    if contract_path is not None:
        path = Path(contract_path).resolve()
        if not path.is_file():
            raise ValueError(f"Algorithm contract not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Algorithm contract must be an object")
        return value
    if not use_default_contract:
        return None
    source_root = Path(__file__).resolve().parents[2]
    dataset_root = Path(__file__).resolve().parents[1]
    for root in (source_root, dataset_root):
        path = root / "contracts" / task / "algorithm_contract.json"
        if path.is_file():
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
    return None


def _metric_constants(contract: dict[str, Any] | None) -> dict[str, float]:
    if contract is None:
        return {"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25}
    value = contract.get("metric_contract", {}).get("required_slots_probabilities")
    if not isinstance(value, dict):
        return {"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25}
    result = {str(key): float(item) for key, item in value.items()}
    if set(result) != {"2", "3", "5", "9"} or any(item < 0 for item in result.values()) or not np.isclose(sum(result.values()), 1.0, atol=1e-12, rtol=0.0):
        raise ValueError("invalid required_slots_probabilities in Algorithm contract")
    return result


def _load_arrays(path: Path) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            names = tuple(archive.files)
            if set(names) != set(NPZ_KEYS) or len(names) != len(NPZ_KEYS):
                raise ValueError("compiled NPZ key set does not match the formal layout")
            return {name: np.array(archive[name], copy=True) for name in NPZ_KEYS}
    except (ValueError, OSError, BadZipFile) as exc:
        raise ValueError(f"cannot load compiled Algorithm NPZ: {path}") from exc


def _case_from_arrays(arrays: Mapping[str, np.ndarray], contract: dict[str, Any] | None) -> CompiledAlgorithmCase:
    format_version = _read_scalar_bytes(_require_array(arrays, "format_version"), "format_version")
    if format_version != NPZ_FORMAT_VERSION:
        raise ValueError("unsupported compiled NPZ format_version")
    task = _read_scalar_bytes(_require_array(arrays, "task_type"), "task_type")
    if task not in _TASKS:
        raise ValueError("unsupported compiled NPZ task_type")
    schema_version = _read_scalar_bytes(_require_array(arrays, "schema_version"), "schema_version")
    if schema_version != ALGORITHM_SCHEMA_VERSION:
        raise ValueError("compiled NPZ schema_version must be ALGORITHM_INPUT_V1_0")
    case_id = _read_scalar_bytes(_require_array(arrays, "case_id"), "case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("compiled NPZ case_id must be a non-empty string")
    slot_array = _require_array(arrays, "slot_count", dtype=_INT64, ndim=1)
    if slot_array.size != 1:
        raise ValueError("compiled NPZ slot_count must be a one-element int64 array")
    slot_count = int(slot_array[0])
    if slot_count < 1 or slot_count > 320:
        raise ValueError("compiled NPZ slot_count must be in the range 1..320")

    nodes_array = _require_array(arrays, "nodes", dtype=_INT64, ndim=1)
    nodes = tuple(int(value) for value in nodes_array.tolist())
    if len(set(nodes)) != len(nodes) or len(nodes) < 2:
        raise ValueError("compiled NPZ nodes must be unique and non-empty")
    node_set = set(nodes)
    link_ids = _require_array(arrays, "link_ids", dtype=_INT64, ndim=1)
    edge_src = _require_array(arrays, "edge_src", dtype=_INT64, ndim=1)
    edge_dst = _require_array(arrays, "edge_dst", dtype=_INT64, ndim=1)
    if not (link_ids.size == edge_src.size == edge_dst.size):
        raise ValueError("compiled NPZ link arrays have inconsistent lengths")
    links: list[CompiledLink] = []
    link_by_id: dict[int, CompiledLink] = {}
    for link_id, source, destination in zip(link_ids.tolist(), edge_src.tolist(), edge_dst.tolist(), strict=True):
        link = CompiledLink(int(link_id), int(source), int(destination))
        if link.link_id in link_by_id or link.source_node_id not in node_set or link.destination_node_id not in node_set:
            raise ValueError("compiled NPZ directed link is invalid")
        link_by_id[link.link_id] = link
        links.append(link)

    out_values = _require_array(arrays, "out_edges_values", dtype=_INT64, ndim=1)
    out_offsets = _offsets(_require_array(arrays, "out_edges_offsets"), len(out_values), len(nodes) + 1, "out_edges_offsets")
    out_edges: list[tuple[int, ...]] = []
    for start, end in zip(out_offsets, out_offsets[1:]):
        values = tuple(int(value) for value in out_values[start:end].tolist())
        if any(value < 0 or value >= len(links) for value in values):
            raise ValueError("out_edges_values contains an invalid edge index")
        out_edges.append(values)
    expected_out: list[list[int]] = [[] for _ in nodes]
    node_index = {node_id: index for index, node_id in enumerate(nodes)}
    for index, link in enumerate(links):
        expected_out[node_index[link.source_node_id]].append(index)
    if tuple(out_edges) != tuple(tuple(value) for value in expected_out):
        raise ValueError("compiled NPZ CSR adjacency is inconsistent with links")

    words = _require_array(arrays, "occupied_mask_words", dtype=_UINT64, ndim=2)
    if words.shape != (len(links), _WORD_COUNT):
        raise ValueError("occupied_mask_words must have shape [num_directed_links, 5]")
    occupied: dict[int, int] = {}
    for link, row in zip(links, words, strict=True):
        mask = sum(int(value) << (64 * index) for index, value in enumerate(row.tolist()))
        if slot_count < 320 and mask >> slot_count:
            raise ValueError("occupied_mask_words sets bits above slot_count")
        occupied[link.link_id] = mask

    request_ids = _decode_fixed_bytes(_require_array(arrays, "request_ids", ndim=1), "request_ids")
    request_sources = _require_array(arrays, "request_source_node_ids", dtype=_INT64, ndim=1)
    request_destinations = _require_array(arrays, "request_destination_node_ids", dtype=_INT64, ndim=1)
    request_slots = _require_array(arrays, "request_required_slots", dtype=_INT64, ndim=1)
    request_count = len(request_ids)
    if not (request_sources.size == request_destinations.size == request_slots.size == request_count):
        raise ValueError("compiled NPZ request arrays have inconsistent lengths")
    if len(set(request_ids)) != request_count or any(not value for value in request_ids):
        raise ValueError("compiled NPZ request IDs must be unique and non-empty")

    fixed_nodes = _require_array(arrays, "fixed_path_nodes", dtype=_INT64, ndim=1)
    fixed_links = _require_array(arrays, "fixed_path_links", dtype=_INT64, ndim=1)
    fixed_node_offsets = _offsets(_require_array(arrays, "fixed_path_node_offsets"), len(fixed_nodes), request_count + 1, "fixed_path_node_offsets")
    fixed_link_offsets = _offsets(_require_array(arrays, "fixed_path_link_offsets"), len(fixed_links), request_count + 1, "fixed_path_link_offsets")
    candidate_nodes = _require_array(arrays, "candidate_path_nodes", dtype=_INT64, ndim=1)
    candidate_links = _require_array(arrays, "candidate_path_links", dtype=_INT64, ndim=1)
    candidate_ranks = _require_array(arrays, "candidate_path_ranks", dtype=_INT64, ndim=1)
    candidate_node_offsets = _offsets(_require_array(arrays, "candidate_path_node_offsets"), len(candidate_nodes), len(candidate_ranks) + 1, "candidate_path_node_offsets")
    candidate_link_offsets = _offsets(_require_array(arrays, "candidate_path_link_offsets"), len(candidate_links), len(candidate_ranks) + 1, "candidate_path_link_offsets")
    candidate_request_offsets = _offsets(_require_array(arrays, "candidate_request_offsets"), len(candidate_ranks), request_count + 1, "candidate_request_offsets")

    requests: list[CompiledRequest] = []
    for index, (request_id, source_raw, destination_raw, slots_raw) in enumerate(zip(request_ids, request_sources.tolist(), request_destinations.tolist(), request_slots.tolist(), strict=True)):
        source = int(source_raw)
        destination = int(destination_raw)
        slots = int(slots_raw)
        if source not in node_set or destination not in node_set or slots not in (2, 3, 5, 9):
            raise ValueError("compiled NPZ request is invalid")
        fixed_path = None
        if fixed_node_offsets[index] != fixed_node_offsets[index + 1] or fixed_link_offsets[index] != fixed_link_offsets[index + 1]:
            fixed_path = _path_from_arrays(
                [int(value) for value in fixed_nodes[fixed_node_offsets[index]:fixed_node_offsets[index + 1]].tolist()],
                [int(value) for value in fixed_links[fixed_link_offsets[index]:fixed_link_offsets[index + 1]].tolist()],
                source=source, destination=destination, link_by_id=link_by_id, path_rank=None,
            )
        candidates: list[CompiledPath] = []
        for path_index in range(candidate_request_offsets[index], candidate_request_offsets[index + 1]):
            candidates.append(_path_from_arrays(
                [int(value) for value in candidate_nodes[candidate_node_offsets[path_index]:candidate_node_offsets[path_index + 1]].tolist()],
                [int(value) for value in candidate_links[candidate_link_offsets[path_index]:candidate_link_offsets[path_index + 1]].tolist()],
                source=source, destination=destination, link_by_id=link_by_id, path_rank=int(candidate_ranks[path_index]),
            ))
        requests.append(CompiledRequest(request_id, source, destination, slots, fixed_path=fixed_path, candidate_paths=tuple(candidates)))

    if task == "O1":
        if any(request.fixed_path is None for request in requests) or any(request.candidate_paths for request in requests):
            raise ValueError("O1 compiled NPZ must contain fixed paths only")
    elif task in ("O2-S", "O2-C"):
        if any(request.fixed_path is not None or not request.candidate_paths for request in requests):
            raise ValueError(f"{task} compiled NPZ must contain candidate paths only")
    elif any(request.fixed_path is not None or request.candidate_paths for request in requests):
        raise ValueError(f"{task} compiled NPZ must not contain supplied paths")

    return CompiledAlgorithmCase(
        case_id=case_id,
        schema_version=schema_version,
        task_type=task,
        slot_count=slot_count,
        nodes=nodes,
        directed_links=tuple(links),
        edge_src=tuple(link.source_node_id for link in links),
        edge_dst=tuple(link.destination_node_id for link in links),
        out_edges=tuple(out_edges),
        occupied_mask_by_link=occupied,
        required_slots_probabilities=_metric_constants(contract),
        requests=tuple(requests),
    )


def load_compiled_algorithm_case(path: str | Path, *, contract_path: str | Path | None = None, use_default_contract: bool = True) -> CompiledAlgorithmCase:
    """Load and validate one compiled Algorithm Case without solving it."""

    path = Path(path).resolve()
    arrays = _load_arrays(path)
    task = _read_scalar_bytes(arrays["task_type"], "task_type")
    if task not in _TASKS:
        raise ValueError("compiled NPZ has unsupported task_type")
    contract = _contract_for_task(task, contract_path, use_default_contract)
    return _case_from_arrays(arrays, contract)


def validate_compiled_algorithm_case(
    path: str | Path,
    *,
    expected_task: str | None = None,
    expected_case_id: str | None = None,
    contract_path: str | Path | None = None,
) -> dict[str, Any]:
    case = load_compiled_algorithm_case(path, contract_path=contract_path)
    if expected_task is not None and case.task_type != expected_task:
        raise ValueError("compiled NPZ task_type does not match expected task")
    if expected_case_id is not None and case.case_id != expected_case_id:
        raise ValueError("compiled NPZ case_id does not match expected case")
    return {
        "valid": True,
        "case_id": case.case_id,
        "task_type": case.task_type,
        "slot_count": case.slot_count,
        "node_count": len(case.nodes),
        "directed_link_count": len(case.directed_links),
        "request_count": len(case.requests),
    }
