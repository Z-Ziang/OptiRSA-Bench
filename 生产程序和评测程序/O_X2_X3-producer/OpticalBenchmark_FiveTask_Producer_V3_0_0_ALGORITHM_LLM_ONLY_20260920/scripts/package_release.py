from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile


TEXT_EXTENSIONS = {
    ".py", ".md", ".json", ".txt", ".csv", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".rst",
}
TEXT_FILENAMES = {"VERSION", "SHA256SUMS.txt"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def included_files(root: Path) -> list[Path]:
    root_manifest = root / "SHA256SUMS.txt"
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path != root_manifest
        and path.suffix != ".pyc"
        and not any(part in {"__pycache__", ".pytest_cache"} for part in path.relative_to(root).parts)
    )


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in TEXT_FILENAMES


def validate_text_encodings(root: Path) -> dict[str, object]:
    """Verify that project text files are valid UTF-8 before packaging.

    The production bundle is intended to be portable across Windows, macOS and
    Linux.  Text files therefore use UTF-8 consistently.  Binary fixtures and
    archives are deliberately excluded from this check.
    """
    root = root.resolve()
    invalid: list[str] = []
    checked = 0
    for path in included_files(root):
        if not _is_text_file(path):
            continue
        checked += 1
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            invalid.append(path.relative_to(root).as_posix())
    return {
        "passed": not invalid,
        "checked_text_files": checked,
        "invalid_utf8_files": invalid,
    }


def validate_archive_encoding(output_zip: Path) -> dict[str, object]:
    """Inspect the *written ZIP* for filename-encoding portability problems.

    ZIP bit 11 (0x800) must be set whenever a member name contains non-ASCII
    characters.  Without it, some Windows archive utilities interpret UTF-8 bytes
    as CP437/local code-page text and display Chinese filenames as mojibake.
    """
    output_zip = output_zip.resolve()
    invalid_flag_entries: list[str] = []
    replacement_entries: list[str] = []
    checked = 0
    try:
        with ZipFile(output_zip) as archive:
            for info in archive.infolist():
                checked += 1
                if "\ufffd" in info.filename:
                    replacement_entries.append(info.filename)
                if any(ord(char) > 127 for char in info.filename) and not (info.flag_bits & 0x800):
                    invalid_flag_entries.append(info.filename)
    except BadZipFile:
        return {
            "passed": False,
            "checked_entries": 0,
            "invalid_utf8_flag_entries": ["<BAD_ZIP>"],
            "replacement_character_entries": [],
        }
    return {
        "passed": not invalid_flag_entries and not replacement_entries,
        "checked_entries": checked,
        "invalid_utf8_flag_entries": invalid_flag_entries,
        "replacement_character_entries": replacement_entries,
    }


def package(root: Path, output_zip: Path) -> tuple[int, str]:
    root = root.resolve()
    output_zip = output_zip.resolve()

    text_encoding = validate_text_encodings(root)
    if not text_encoding["passed"]:
        raise ValueError(
            "Project contains non-UTF-8 text files: "
            + ", ".join(text_encoding["invalid_utf8_files"])
        )

    files = included_files(root)
    lines = [f"{digest(path)}  {path.relative_to(root).as_posix()}" for path in files]
    manifest = root / "SHA256SUMS.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    with ZipFile(output_zip, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [*files, manifest]:
            archive.write(path, (Path(root.name) / path.relative_to(root)).as_posix())

    archive_encoding = validate_archive_encoding(output_zip)
    if not archive_encoding["passed"]:
        output_zip.unlink(missing_ok=True)
        raise ValueError(
            "ZIP filename encoding validation failed: "
            f"{archive_encoding['invalid_utf8_flag_entries']}"
        )

    return len(files) + 1, digest(output_zip)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    args = parser.parse_args()
    count, sha256 = package(args.root, args.output_zip)
    print(f"file_count={count}")
    print(f"sha256={sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
