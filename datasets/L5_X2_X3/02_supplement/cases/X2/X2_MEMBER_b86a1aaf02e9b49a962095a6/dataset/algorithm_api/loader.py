"""Official loader for the five-task public Algorithm input.

The loader validates and compiles supplied data only.  It deliberately has no
path-search, objective, solver, or reference dependency.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .spectrum import occupied_ranges_to_mask
from .types import CompiledAlgorithmCase, CompiledLink, CompiledPath, CompiledRequest


_TASKS = ("O1", "O2-S", "O2-C", "X2", "X3")
_REQUIRED_SLOTS = (2, 3, 5, 9)
_DEFAULT_REQUIRED_SLOTS_PROBABILITIES = {"2": 0.25, "3": 0.25, "5": 0.25, "9": 0.25}
_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_DATASET_ROOT = Path(__file__).resolve().parents[1]


def _asset_roots() -> tuple[Path, ...]:
    """Support both the source tree and the self-contained dataset copy."""

    roots = [_SOURCE_ROOT, _DATASET_ROOT]
    return tuple(dict.fromkeys(root for root in roots if root.is_dir()))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def _schema_path(task_type: str) -> Path:
    candidates = []
    for root in _asset_roots():
        candidates.extend((
            root / "contracts" / task_type / "schemas" / "algorithm_input.schema.json",
            root / "benchmark_case" / task_type / "algorithm_input.schema.json",
            root / "evaluation_case" / task_type / "algorithm_input.schema.json",
        ))
    return next((path for path in candidates if path.is_file()), candidates[0])


def _validate_schema(input_obj: dict[str, Any], task_type: str) -> None:
    path = _schema_path(task_type)
    if not path.is_file():
        raise ValueError(f"missing Algorithm input schema for {task_type}")
    schema = _read_json(path)
    errors = sorted(Draft202012Validator(schema).iter_errors(input_obj), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(x) for x in errors[0].path)
        suffix = f" at {location}" if location else ""
        raise ValueError(f"Algorithm input schema violation{suffix}: {errors[0].message}")


def _validate_contract(input_obj: dict[str, Any], contract: dict[str, Any] | None) -> None:
    if contract is None:
        return
    if contract.get("task_type") != input_obj["task_type"]:
        raise ValueError("Algorithm contract task_type does not match input")
    if contract.get("input_schema_version") != input_obj["schema_version"]:
        raise ValueError("Algorithm contract schema version does not match input")
    frozen_slots = contract.get("slot_count")
    if frozen_slots is not None and int(frozen_slots) != int(input_obj["slot_count"]):
        raise ValueError("Algorithm input slot_count does not match the task contract")


def _metric_constants(contract: dict[str, Any] | None) -> dict[str, float]:
    if contract is None:
        return dict(_DEFAULT_REQUIRED_SLOTS_PROBABILITIES)
    value = contract.get("metric_contract", {}).get("required_slots_probabilities")
    if not isinstance(value, dict):
        return dict(_DEFAULT_REQUIRED_SLOTS_PROBABILITIES)
    result = {str(key): float(value[key]) for key in value}
    if set(result) != set(_DEFAULT_REQUIRED_SLOTS_PROBABILITIES):
        raise ValueError("Algorithm contract required_slots_probabilities keys are invalid")
    if any(not math.isfinite(probability) or probability < 0.0 for probability in result.values()):
        raise ValueError("Algorithm contract required_slots_probabilities contains an invalid probability")
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("Algorithm contract required_slots_probabilities must sum to one")
    return result


def _compile_path(
    raw: dict[str, Any],
    *,
    source_node_id: int,
    destination_node_id: int,
    link_by_id: dict[int, CompiledLink],
    candidate: bool,
) -> CompiledPath:
    node_ids = tuple(int(value) for value in raw["path_node_ids"])
    link_ids = tuple(int(value) for value in raw["path_link_ids"])
    if len(node_ids) != len(link_ids) + 1:
        raise ValueError("path node/link lengths are inconsistent")
    if node_ids[0] != source_node_id or node_ids[-1] != destination_node_id:
        raise ValueError("path endpoints do not match request endpoints")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("path is not simple")
    for index, link_id in enumerate(link_ids):
        link = link_by_id.get(link_id)
        if link is None:
            raise ValueError(f"path refers to unknown link_id {link_id}")
        if link.source_node_id != node_ids[index] or link.destination_node_id != node_ids[index + 1]:
            raise ValueError("path links are not directionally contiguous")
    rank = int(raw["path_rank"]) if candidate else None
    return CompiledPath(path_node_ids=node_ids, path_link_ids=link_ids, path_rank=rank)


def _compile_requests(
    input_obj: dict[str, Any],
    *,
    node_set: set[int],
    link_by_id: dict[int, CompiledLink],
) -> tuple[CompiledRequest, ...]:
    task_type = str(input_obj["task_type"])
    seen_request_ids: set[str] = set()
    result: list[CompiledRequest] = []
    for raw in input_obj["requests"]:
        request_id = str(raw["request_id"])
        if request_id in seen_request_ids:
            raise ValueError(f"duplicate request_id {request_id}")
        seen_request_ids.add(request_id)
        source = int(raw["source_node_id"])
        destination = int(raw["destination_node_id"])
        if source not in node_set or destination not in node_set:
            raise ValueError("request endpoint is not in nodes")
        required_slots = int(raw["required_slots"])
        fixed_path = None
        candidates: tuple[CompiledPath, ...] = ()
        if "fixed_path" in raw:
            fixed_path = _compile_path(
                raw["fixed_path"],
                source_node_id=source,
                destination_node_id=destination,
                link_by_id=link_by_id,
                candidate=False,
            )
        if "candidate_paths" in raw:
            paths = [
                _compile_path(
                    path,
                    source_node_id=source,
                    destination_node_id=destination,
                    link_by_id=link_by_id,
                    candidate=True,
                )
                for path in raw["candidate_paths"]
            ]
            ranks = [path.path_rank for path in paths]
            if len(set(ranks)) != len(ranks):
                raise ValueError("candidate path ranks must be unique")
            candidates = tuple(paths)
        if task_type in ("X2", "X3") and (fixed_path is not None or candidates):
            raise ValueError(f"{task_type} does not accept supplied paths")
        result.append(CompiledRequest(
            request_id=request_id,
            source_node_id=source,
            destination_node_id=destination,
            required_slots=required_slots,
            fixed_path=fixed_path,
            candidate_paths=candidates,
        ))
    return tuple(result)


def compile_algorithm_input(
    input_obj: dict[str, Any],
    *,
    case_id: str | None = None,
    contract: dict[str, Any] | None = None,
) -> CompiledAlgorithmCase:
    """Validate and compile one public Algorithm input deterministically."""

    if not isinstance(input_obj, dict):
        raise ValueError("Algorithm input must be an object")
    normalized_input = dict(input_obj)
    normalized_input.setdefault("schema_version", "ALGORITHM_INPUT_V1_0")
    if normalized_input["schema_version"] != "ALGORITHM_INPUT_V1_0":
        raise ValueError("Algorithm input schema_version must be ALGORITHM_INPUT_V1_0")
    task_type = str(normalized_input.get("task_type", ""))
    if task_type not in _TASKS:
        raise ValueError(f"unsupported Algorithm task_type: {task_type}")
    schema_input = dict(normalized_input)
    schema_input.pop("schema_version", None)
    _validate_schema(schema_input, task_type)
    _validate_contract(normalized_input, contract)

    nodes = tuple(int(value) for value in normalized_input["nodes"])
    node_set = set(nodes)
    if len(node_set) != len(nodes):
        raise ValueError("nodes must be unique")
    links: list[CompiledLink] = []
    link_by_id: dict[int, CompiledLink] = {}
    for raw in normalized_input["directed_links"]:
        link = CompiledLink(
            link_id=int(raw["link_id"]),
            source_node_id=int(raw["source_node_id"]),
            destination_node_id=int(raw["destination_node_id"]),
        )
        if link.link_id in link_by_id:
            raise ValueError(f"duplicate link_id {link.link_id}")
        if link.source_node_id not in node_set or link.destination_node_id not in node_set:
            raise ValueError(f"link {link.link_id} endpoint is not in nodes")
        link_by_id[link.link_id] = link
        links.append(link)

    state_by_link: dict[int, int] = {}
    for raw in normalized_input["link_spectrum_states"]:
        link_id = int(raw["link_id"])
        if link_id in state_by_link:
            raise ValueError(f"duplicate spectrum state link_id {link_id}")
        if link_id not in link_by_id:
            raise ValueError(f"spectrum state refers to unknown link_id {link_id}")
        state_by_link[link_id] = occupied_ranges_to_mask(int(normalized_input["slot_count"]), raw["occupied_ranges"])
    if set(state_by_link) != set(link_by_id):
        raise ValueError("spectrum states must cover exactly the directed links")

    node_index = {node_id: index for index, node_id in enumerate(nodes)}
    out_edges: list[list[int]] = [[] for _ in nodes]
    for edge_index, link in enumerate(links):
        out_edges[node_index[link.source_node_id]].append(edge_index)

    requests = _compile_requests(normalized_input, node_set=node_set, link_by_id=link_by_id)
    return CompiledAlgorithmCase(
        case_id=None if case_id is None else str(case_id),
        schema_version=str(normalized_input["schema_version"]),
        task_type=task_type,
        slot_count=int(normalized_input["slot_count"]),
        nodes=nodes,
        directed_links=tuple(links),
        edge_src=tuple(link.source_node_id for link in links),
        edge_dst=tuple(link.destination_node_id for link in links),
        out_edges=tuple(tuple(edges) for edges in out_edges),
        occupied_mask_by_link=state_by_link,
        required_slots_probabilities=_metric_constants(contract),
        requests=requests,
    )


def load_algorithm_case(path: str | Path, *, contract_path: str | Path | None = None) -> CompiledAlgorithmCase:
    """Load an Algorithm evaluation wrapper and compile its ``input`` once."""

    wrapper = _read_json(Path(path).resolve())
    if set(wrapper) != {"case_id", "input"}:
        raise ValueError("Algorithm evaluation case must contain exactly case_id and input")
    case_id = wrapper["case_id"]
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("Algorithm evaluation case case_id must be a non-empty string")
    input_obj = wrapper["input"]
    if not isinstance(input_obj, dict):
        raise ValueError("Algorithm evaluation case input must be an object")
    contract = None
    if contract_path is None:
        task_type = str(input_obj.get("task_type", ""))
        candidates = []
        for root in _asset_roots():
            candidates.extend((
                root / "contracts" / task_type / "algorithm_contract.json",
                root / "benchmark_case" / task_type / "algorithm_contract.json",
                root / "evaluation_case" / task_type / "algorithm_contract.json",
            ))
        contract_path = next((path for path in candidates if path.is_file()), candidates[0] if candidates else Path(""))
    contract_file = Path(contract_path).resolve()
    if contract_file.is_file():
        contract = _read_json(contract_file)
    return compile_algorithm_input(input_obj, case_id=case_id, contract=contract)


def load_compiled_algorithm_case(path: str | Path, *, contract_path: str | Path | None = None, use_default_contract: bool = True) -> CompiledAlgorithmCase:
    """Load the primary binary Algorithm evaluation artifact."""

    from .compiled_npz import load_compiled_algorithm_case as _load_compiled_algorithm_case

    return _load_compiled_algorithm_case(path, contract_path=contract_path, use_default_contract=use_default_contract)
