from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class EpisodeBundle:
    dataset_root: Path
    task: str
    modality: str
    topology_id: str
    condition_id: str
    episode: dict[str, Any]
    system_prompt: str
    system_prompt_sha256: str

    @property
    def case_id(self) -> str:
        return str(self.episode["case_id"])

    @property
    def episode_length(self) -> int:
        return int(self.episode["episode_length"])

    @property
    def unit_id(self) -> str:
        return f"{self.task}__{self.topology_id}__{self.condition_id}__{self.modality}"


def load_episode_bundle(
    dataset_root: Path | str,
    *,
    task: str,
    modality: str,
    topology_id: str,
    condition_id: str,
) -> EpisodeBundle:
    if task not in {"S1", "X4"}:
        raise ValueError("task must be S1 or X4")
    if modality != "llm":
        raise ValueError("modality must be llm")
    root = Path(dataset_root).resolve()
    episode_path = root / "benchmark_case" / task / "episodes" / topology_id / f"{condition_id}.json"
    prompt_path = root / "evaluation_case" / task / modality / "system_prompt.txt"
    case_view_path = root / "evaluation_case" / task / modality / topology_id / f"{condition_id}.json"
    if not episode_path.is_file():
        raise FileNotFoundError(episode_path)
    if not prompt_path.is_file():
        raise FileNotFoundError(prompt_path)
    if not case_view_path.is_file():
        raise FileNotFoundError(case_view_path)
    episode = json.loads(episode_path.read_text(encoding="utf-8"))
    if not isinstance(episode, dict) or episode.get("task_type") != task:
        raise ValueError(f"episode task_type mismatch: {episode_path}")
    if "reference" in episode:
        raise ValueError("reference data cannot enter the decision loop")
    system_bytes = prompt_path.read_bytes()
    return EpisodeBundle(
        dataset_root=root,
        task=task,
        modality=modality,
        topology_id=topology_id,
        condition_id=condition_id,
        episode=episode,
        system_prompt=system_bytes.decode("utf-8"),
        system_prompt_sha256=_sha256_bytes(system_bytes),
    )
