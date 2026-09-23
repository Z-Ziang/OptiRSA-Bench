from __future__ import annotations

import sys
import zipfile
from pathlib import Path


SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def package(root: Path, destination: Path) -> dict[str, object]:
    root = root.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(root).parts
            if any(part in SKIP_DIRS for part in relative_parts):
                continue
            if path.suffix.lower() == ".pyc" or path.name.endswith(".tmp"):
                continue
            archive.write(path, path.relative_to(root).as_posix())
            count += 1
    with zipfile.ZipFile(destination) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC failed at {bad}")
    return {"path": str(destination), "file_count": count, "size": destination.stat().st_size}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: package_v2_runner.py SOURCE_ROOT OUTPUT_ZIP")
    print(package(Path(sys.argv[1]), Path(sys.argv[2])))
