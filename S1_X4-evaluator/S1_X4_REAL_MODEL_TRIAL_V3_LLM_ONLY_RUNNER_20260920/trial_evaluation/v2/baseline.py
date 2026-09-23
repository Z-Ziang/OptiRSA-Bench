from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


SCIENCE_PROTECTED_PATHS = (
    "src/s1_x4/state_machine.py",
    "src/s1_x4/validators.py",
    "src/s1_x4/reference_algorithms.py",
    "src/s1_x4/efm.py",
    "src/s1_x4/scenario_loader.py",
    "contracts/S1/llm_system_prompt.txt",
    "contracts/X4/llm_system_prompt.txt",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_science_manifest(root: Path | str) -> dict[str, str]:
    base = Path(root).resolve()
    manifest: dict[str, str] = {}
    for relative in SCIENCE_PROTECTED_PATHS:
        path = base / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        manifest[relative] = _sha256(path)
    return manifest


def verify_science_manifest(before: Mapping[str, str], root: Path | str) -> dict[str, Any]:
    base = Path(root).resolve()
    changed: list[str] = []
    missing: list[str] = []
    for relative, expected in before.items():
        path = base / relative
        if not path.is_file():
            missing.append(relative)
        elif _sha256(path) != expected:
            changed.append(relative)
    return {
        "pass": not changed and not missing,
        "changed_files": sorted(changed),
        "missing_files": sorted(missing),
        "protected_file_count": len(before),
    }
