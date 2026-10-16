from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _index_json_dir(directory: Path, key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.json")):
        item = _read_json(path)
        item_key = item.get(key)
        if not isinstance(item_key, str) or not item_key:
            raise ValueError(f"{path}: missing {key}")
        if item_key in result and result[item_key] != item:
            raise ValueError(f"duplicate {key}: {item_key}")
        result[item_key] = item
    return result


def _index_jsonl_dir(directory: Path, key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.jsonl")):
        for item in _read_jsonl(path):
            item_key = item.get(key)
            if not isinstance(item_key, str) or not item_key:
                raise ValueError(f"{path}: missing {key}")
            if item_key in result and result[item_key] != item:
                raise ValueError(f"duplicate {key}: {item_key}")
            result[item_key] = item
    return result


@dataclass(frozen=True)
class PublicEnvironmentIndex:
    root: Path
    physical_topologies: dict[str, dict]
    directed_topologies: dict[str, dict]
    resource_states: dict[str, dict]
    requests: dict[str, dict]
    derivations: dict[str, dict]
    concurrent_sets: dict[str, dict]
    scenarios: dict[str, dict]
    generation_configs: dict[str, dict]

    def topology_for_state(self, resource_state_id: str) -> tuple[dict, dict]:
        state = self.resource_states[resource_state_id]
        topology_id = state["topology_id"]
        return self.physical_topologies[topology_id], self.directed_topologies[topology_id]


def load_public_environment(root: Path | str) -> PublicEnvironmentIndex:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    index = PublicEnvironmentIndex(
        root=root,
        physical_topologies=_index_json_dir(root / "topologies/physical", "topology_id"),
        directed_topologies=_index_json_dir(root / "topologies/directed", "topology_id"),
        resource_states=_index_json_dir(root / "states/spectrum", "resource_state_id"),
        requests=_index_jsonl_dir(root / "requests/single", "request_id"),
        derivations=_index_jsonl_dir(root / "requests/derivation", "request_id"),
        concurrent_sets=_index_json_dir(root / "requests/concurrent", "request_set_id"),
        scenarios=_index_json_dir(root / "scenarios", "base_scenario_id"),
        generation_configs=_index_json_dir(root / "configs", "generation_config_id"),
    )
    # Fail closed for core references actually present.
    for request_id, derivation in index.derivations.items():
        if request_id not in index.requests:
            raise ValueError(f"derivation references missing request: {request_id}")
        state_id = derivation.get("resource_state_id")
        if state_id not in index.resource_states:
            raise ValueError(f"derivation references missing resource state: {state_id}")
    for set_id, item in index.concurrent_sets.items():
        for request_id in item.get("request_ids", []):
            if request_id not in index.requests:
                raise ValueError(f"concurrent set {set_id} references missing request {request_id}")
    return index
