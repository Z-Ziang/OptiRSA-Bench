from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


def atomic_write_json(path: Path | str, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


class CheckpointStore:
    """Atomic JSONL step ledger; a unit can only advance contiguously."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.steps_path = self.root / "steps.jsonl"

    def load(self) -> list[dict[str, Any]]:
        if not self.steps_path.is_file():
            return []
        rows = []
        for line in self.steps_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("checkpoint record must be an object")
                rows.append(value)
        expected = 1
        for row in rows:
            if row.get("step_index") != expected:
                raise ValueError("checkpoint steps are not contiguous")
            expected += 1
        return rows

    def append(self, record: Mapping[str, Any]) -> None:
        row = dict(record)
        step_index = row.get("step_index")
        if not isinstance(step_index, int) or isinstance(step_index, bool):
            raise ValueError("checkpoint step_index must be an integer")
        rows = self.load()
        expected = len(rows) + 1
        if step_index < expected:
            raise ValueError("duplicate checkpoint step")
        if step_index != expected:
            raise ValueError("checkpoint steps must be contiguous")
        rows.append(row)
        fd, temporary_name = tempfile.mkstemp(prefix=".steps.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for item in rows:
                    handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.steps_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def next_step_index(self) -> int:
        return len(self.load()) + 1

