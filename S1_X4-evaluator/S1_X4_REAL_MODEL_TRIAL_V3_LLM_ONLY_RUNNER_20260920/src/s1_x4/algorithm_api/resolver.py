from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from jsonschema import Draft202012Validator

from .loader import load_episode


PUBLIC_LAUNCHER_KEYS = frozenset(
    {
        "schema_version",
        "case_id",
        "task_type",
        "interface_type",
        "future_requests_visible",
        "static_context",
        "output_schema_ref",
        "runtime_contract_ref",
        "opaque_case_handle",
    }
)

FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "canonical_episode_ref",
        "episode_length",
        "horizon",
        "total_steps",
        "sequence_length",
        "resource_state_id",
        "pairing_id",
        "request_sequence_id",
        "initial_existing_connection_set_id",
        "difficulty_context",
        "difficulty",
        "seed",
        "load_band",
        "arrival_rate_mode",
        "lambda_ratio",
        "reference",
        "oracle",
        "private_truth",
        "root_case_path",
        "root_case_sha256",
        "contains_full_episode",
        "dut_direct_access_allowed",
        "request_events",
        "initial_existing_connections",
        "active_connection",
        "release_time",
        "remaining_holding_time",
        "released_connection",
        "candidate_paths",
        "candidate_actions",
        "feasible_paths",
        "feasible_actions",
        "path_rank",
        "recommended_action",
    }
)

_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"\b(?:light|medium|high|challenge)(?:[_ -]?(?:pressure|load))?\b", re.I),
    re.compile(r"\bseed(?:[_-]?\d+)?\b", re.I),
    re.compile(r"\b(?:ksp|ff|bf|kme|sw)[_-]?(?:ff|bf|sp|efm)\b", re.I),
    re.compile(r"\b(?:policy|reference|oracle|private[_ -]?truth)\b", re.I),
    re.compile(r"arrival[_ -]?rate", re.I),
    re.compile(r"lambda[_ -]?ratio", re.I),
    re.compile(r"resource[_ -]?state", re.I),
    re.compile(r"request[_ -]?sequence", re.I),
    re.compile(r"\bdifficulty\b", re.I),
)


@dataclass(frozen=True)
class ResolvedAlgorithmEpisode:
    """Evaluator-private result of resolving one public Algorithm launcher."""

    launcher_path: Path
    dataset_root: Path
    case_id: str
    task_type: str
    opaque_case_handle: str
    root_case_path: Path
    entry: dict[str, Any]
    episode: dict[str, Any]


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_keys(value: Any, prefix: str = "") -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            location = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_PUBLIC_KEYS:
                hits.append({"key": key_text, "location": location})
            hits.extend(_walk_keys(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_walk_keys(child, f"{prefix}[{index}]"))
    return hits


def _walk_strings(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(prefix, value)]
    if isinstance(value, dict):
        out: list[tuple[str, str]] = []
        for key, child in value.items():
            location = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk_strings(child, location))
        return out
    if isinstance(value, list):
        out = []
        for index, child in enumerate(value):
            out.extend(_walk_strings(child, f"{prefix}[{index}]"))
        return out
    return []


def audit_public_launcher(launcher: Any) -> dict[str, Any]:
    """Return the recursive public metadata audit used by resolver and verifier."""

    key_hits = _walk_keys(launcher)
    value_hits: list[dict[str, str]] = []
    for location, value in _walk_strings(launcher):
        for pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                value_hits.append({"location": location, "value": value, "pattern": pattern.pattern})
    return {
        "public_keys": sorted(_collect_keys(launcher)),
        "all_string_values": [value for _, value in _walk_strings(launcher)],
        "forbidden_key_hits": key_hits,
        "forbidden_value_hits": value_hits,
        "semantic_metadata_hits": value_hits,
    }


def _collect_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_collect_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_collect_keys(child))
    return keys


def _schema_path(dataset_root: Path, task_type: str) -> Path:
    return dataset_root / "internal" / "contracts" / task_type / "schemas" / "algorithm_evaluation_case.schema.json"


def _validate_launcher(launcher: dict[str, Any], dataset_root: Path) -> None:
    task_type = launcher.get("task_type")
    if task_type not in {"S1", "X4"}:
        raise ValueError("launcher task_type must be S1 or X4")
    schema_path = _schema_path(dataset_root, task_type)
    if not schema_path.is_file():
        raise ValueError(f"missing evaluator-private Algorithm launcher schema: {schema_path}")
    schema = _read_json(schema_path, "Algorithm launcher schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(launcher), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"public launcher schema invalid: {errors[0].message}")
    audit = audit_public_launcher(launcher)
    if audit["forbidden_key_hits"] or audit["forbidden_value_hits"]:
        raise ValueError(
            "public launcher contains forbidden metadata: "
            f"keys={audit['forbidden_key_hits']}, values={audit['forbidden_value_hits']}"
        )
    if set(launcher) != PUBLIC_LAUNCHER_KEYS:
        raise ValueError("public launcher has an invalid top-level field set")


def _safe_root_path(dataset_root: Path, raw_path: Any) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("registry root case path must be a non-empty string")
    if "\\" in raw_path:
        raise ValueError("registry root case path must use safe relative POSIX separators")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("registry root case path traversal or absolute path")
    if len(relative.parts) < 4 or relative.parts[0:2] != ("internal", "cases"):
        raise ValueError("registry root case path is outside internal/cases")
    if relative.name != "root_case.json":
        raise ValueError("registry root case path must point to root_case.json")
    candidate = (dataset_root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(dataset_root):
        raise ValueError("registry root case path escapes evaluator dataset root")
    if not candidate.is_file():
        raise ValueError(f"registry root case path does not exist: {raw_path}")
    return candidate


def _load_registry(dataset_root: Path) -> list[dict[str, Any]]:
    path = dataset_root / "internal" / "algorithm_episode_registry.json"
    if not path.is_file():
        raise ValueError(f"missing evaluator-private Algorithm episode registry: {path}")
    registry = _read_json(path, "Algorithm episode registry")
    if not isinstance(registry, dict) or registry.get("schema_version") != "S1_X4_ALGORITHM_EPISODE_REGISTRY_V1_0":
        raise ValueError("invalid Algorithm episode registry schema version")
    entries = registry.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Algorithm episode registry entries must be an array")
    handles: set[str] = set()
    identities: set[tuple[str, str]] = set()
    checked: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Algorithm episode registry entry must be an object")
        required = {"opaque_case_handle", "case_id", "task_type", "root_case_path", "root_case_sha256"}
        if set(entry) != required:
            raise ValueError("Algorithm episode registry entry fields are invalid")
        handle = entry["opaque_case_handle"]
        case_id = entry["case_id"]
        task_type = entry["task_type"]
        digest = entry["root_case_sha256"]
        if not all(isinstance(value, str) and value for value in (handle, case_id, task_type, digest)):
            raise ValueError("Algorithm episode registry entry contains an invalid string")
        if task_type not in {"S1", "X4"}:
            raise ValueError("Algorithm episode registry entry has invalid task_type")
        if handle in handles:
            raise ValueError(f"duplicate handle in Algorithm episode registry: {handle}")
        if (task_type, case_id) in identities:
            raise ValueError(f"duplicate case identity in Algorithm episode registry: {task_type}/{case_id}")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("Algorithm episode registry root SHA256 is invalid")
        handles.add(handle)
        identities.add((task_type, case_id))
        root_case_path = _safe_root_path(dataset_root, entry["root_case_path"])
        actual_digest = _sha256(root_case_path)
        if actual_digest.lower() != digest.lower():
            raise ValueError(f"Algorithm episode registry root hash mismatch: {entry['root_case_path']}")
        checked.append({**entry, "root_case_path": root_case_path})
    return checked


def resolve_algorithm_launcher(
    launcher_path: Path | str,
    evaluator_dataset_root: Path | str,
    expected_task: str | None = None,
) -> ResolvedAlgorithmEpisode:
    """Resolve a DUT-facing launcher through evaluator-private, hash-checked provenance."""

    dataset_root = Path(evaluator_dataset_root).resolve()
    launcher = Path(launcher_path).resolve()
    if not launcher.is_file():
        raise ValueError(f"public launcher does not exist: {launcher}")
    if not launcher.is_relative_to(dataset_root):
        raise ValueError("public launcher path is outside evaluator dataset root")
    public_obj = _read_json(launcher, "public Algorithm launcher")
    if not isinstance(public_obj, dict):
        raise ValueError("public Algorithm launcher must be an object")
    _validate_launcher(public_obj, dataset_root)
    task_type = public_obj["task_type"]
    case_id = public_obj["case_id"]
    if expected_task is not None and task_type != expected_task:
        raise ValueError(f"wrong task for public Algorithm launcher: expected {expected_task}, got {task_type}")
    handle = public_obj["opaque_case_handle"]
    entries = _load_registry(dataset_root)
    matches = [entry for entry in entries if entry["opaque_case_handle"] == handle]
    if len(matches) != 1:
        raise ValueError(f"opaque case handle is not registered uniquely: {handle}")
    entry = matches[0]
    if entry["task_type"] != task_type or entry["case_id"] != case_id:
        raise ValueError("opaque handle registry case/task identity mismatch")
    episode = load_episode(entry["root_case_path"])
    if episode.get("case_id") != case_id or episode.get("task_type") != task_type:
        raise ValueError("canonical root case/task identity mismatch")
    static = public_obj.get("static_context")
    if not isinstance(static, dict) or static.get("case_id") != case_id or static.get("task_type") != task_type:
        raise ValueError("public static context identity mismatch")
    if static.get("topology_id") != episode.get("topology_id"):
        raise ValueError("public static context topology identity mismatch")
    return ResolvedAlgorithmEpisode(
        launcher_path=launcher,
        dataset_root=dataset_root,
        case_id=case_id,
        task_type=task_type,
        opaque_case_handle=handle,
        root_case_path=entry["root_case_path"],
        entry=dict(entry),
        episode=episode,
    )
