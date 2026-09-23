from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from src.s1_x4.generation_spec import (
    PUBLIC_GENERATION_SPEC_SCHEMA_VERSION,
    validate_generation_spec,
    validate_public_generation_spec,
)
from .loader import load_episode


RUN_CONFIG_SCHEMA_VERSION = "S1_X4_ALGORITHM_RUN_CONFIG_V2_0"
_FORBIDDEN_RUN_CONFIG_KEYS = {
    "request_events",
    "initial_existing_connections",
    "private_truth",
    "reference_output",
    "reference_trajectories",
    "active_connections",
    "release_schedule",
    "root_case_path",
    "opaque_case_handle",
}


@dataclass(frozen=True)
class ResolvedRunConfig:
    config: dict[str, Any]
    config_path: Path | None
    dataset_root: Path
    generation_spec: dict[str, Any]
    generation_spec_path: Path
    episode_path: Path
    episode: dict[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _safe_relative_path(raw: Any, *, label: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty relative POSIX path")
    if "\\" in raw:
        raise ValueError(f"{label} must use POSIX separators")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must not be absolute or contain traversal")
    return path


def _inside(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    candidate = (root / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"{label} escapes dataset root")
    return candidate


def load_run_config(path: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    """Load a harness run config without resolving or exposing an Episode."""

    value = _read_json(Path(path)) if isinstance(path, (str, Path)) else dict(path)
    required = {"schema_version", "task_type", "topology_id", "condition_id", "generation_spec_ref"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"run config missing fields: {missing}")
    if value.get("schema_version") != RUN_CONFIG_SCHEMA_VERSION:
        raise ValueError("unsupported Algorithm run config schema version")
    if value.get("task_type") not in {"S1", "X4"}:
        raise ValueError("run config task_type must be S1 or X4")
    if not isinstance(value.get("topology_id"), str) or not isinstance(value.get("condition_id"), str):
        raise ValueError("run config topology_id and condition_id must be strings")
    _safe_relative_path(value["generation_spec_ref"], label="generation_spec_ref")
    forbidden = sorted(_FORBIDDEN_RUN_CONFIG_KEYS & set(value))
    if forbidden:
        raise ValueError(f"run config contains private Episode fields: {forbidden}")
    return value


def _infer_dataset_root(config_path: Path) -> Path:
    for ancestor in (config_path.parent, *config_path.parents):
        if (ancestor / "benchmark_case").is_dir():
            return ancestor.resolve()
    raise ValueError("cannot infer dataset root; pass dataset_root explicitly")


def resolve_run_config(
    run_config_or_path: Path | str | Mapping[str, Any],
    *,
    dataset_root: Path | str | None = None,
    task_type: str | None = None,
) -> ResolvedRunConfig:
    config_path: Path | None = None
    if isinstance(run_config_or_path, (str, Path)):
        config_path = Path(run_config_or_path).resolve()
        if not config_path.is_file():
            raise ValueError(f"run config does not exist: {config_path}")
        config = load_run_config(config_path)
        root = Path(dataset_root).resolve() if dataset_root is not None else _infer_dataset_root(config_path)
        if not config_path.is_relative_to(root):
            raise ValueError("run config must be inside dataset root")
    else:
        config = load_run_config(run_config_or_path)
        if dataset_root is None:
            raise ValueError("dataset_root is required when run config is a mapping")
        root = Path(dataset_root).resolve()
    if task_type is not None and config["task_type"] != task_type:
        raise ValueError(f"run config task mismatch: expected {task_type}, got {config['task_type']}")
    spec_path = _inside(root, _safe_relative_path(config["generation_spec_ref"], label="generation_spec_ref"), label="generation spec")
    if not spec_path.is_file():
        raise ValueError(f"generation spec does not exist: {spec_path}")
    spec = _read_json(spec_path)
    is_public_spec = spec.get("schema_version") == PUBLIC_GENERATION_SPEC_SCHEMA_VERSION
    spec_errors = (
        validate_public_generation_spec(spec)
        if is_public_spec
        else validate_generation_spec(spec)
    )
    if spec_errors:
        raise ValueError(f"invalid generation spec: {spec_errors}")
    if spec.get("topology_id") != config["topology_id"] or spec.get("condition_id") != config["condition_id"]:
        raise ValueError("run config/spec identity mismatch")
    task = str(config["task_type"])
    episode_path = root / "benchmark_case" / task / "episodes" / str(config["topology_id"]) / f"{config['condition_id']}.json"
    episode_path = episode_path.resolve()
    if not episode_path.is_relative_to(root) or not episode_path.is_file():
        raise ValueError(f"materialized public Episode does not exist: {episode_path}")
    episode = load_episode(episode_path)
    if episode.get("task_type") != task or episode.get("topology_id") != config["topology_id"]:
        raise ValueError("run config/Episode identity mismatch")
    if is_public_spec:
        resource = spec["resource_config"]
        dynamic = spec["dynamic_generation"]
        if episode.get("episode_length") != resource.get("episode_length"):
            raise ValueError("public generation spec/Episode length mismatch")
        if episode.get("slot_count") != resource.get("slot_count"):
            raise ValueError("public generation spec/Episode slot count mismatch")
        if episode.get("holding_time_rate_mu") != dynamic.get("holding_time_rate_mu"):
            raise ValueError("public generation spec/Episode holding-time rate mismatch")
        if len(episode.get("request_events", [])) != resource.get("episode_length"):
            raise ValueError("public generation spec/Episode request count mismatch")
    else:
        expected = spec.get("expected_underlying_episode_fingerprint")
        from src.s1_x4.generation_spec import episode_scientific_fingerprint

        if expected != episode_scientific_fingerprint(episode):
            raise ValueError("run config Episode fingerprint mismatch")
    return ResolvedRunConfig(
        config=dict(config),
        config_path=config_path,
        dataset_root=root,
        generation_spec=spec,
        generation_spec_path=spec_path,
        episode_path=episode_path,
        episode=episode,
    )


def run_config_for_spec(spec: Mapping[str, Any], *, task_type: str) -> dict[str, Any]:
    """Create the small harness record used by the internal reference runner."""

    if task_type not in {"S1", "X4"}:
        raise ValueError("task_type must be S1 or X4")
    return {
        "schema_version": RUN_CONFIG_SCHEMA_VERSION,
        "task_type": task_type,
        "topology_id": spec["topology_id"],
        "condition_id": spec["condition_id"],
        "generation_spec_ref": f"benchmark_case/generation_specs/{spec['topology_id']}/{spec['condition_id']}.json",
    }
