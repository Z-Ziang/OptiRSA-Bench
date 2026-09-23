from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from scripts.package_release import (
    package,
    validate_archive_encoding,
    validate_text_encodings,
)


def test_package_marks_non_ascii_filenames_as_utf8(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    (root / "README_生产入口.md").write_text("中文内容\n", encoding="utf-8")
    output_zip = tmp_path / "release.zip"

    package(root, output_zip)

    with ZipFile(output_zip) as archive:
        info = archive.getinfo("release/README_生产入口.md")
        assert info.flag_bits & 0x800


def test_archive_encoding_validator_accepts_standard_utf8_archive(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    (root / "README_生产入口.md").write_text("中文内容\n", encoding="utf-8")
    output_zip = tmp_path / "release.zip"
    package(root, output_zip)

    result = validate_archive_encoding(output_zip)
    assert result["passed"] is True
    assert result["invalid_utf8_flag_entries"] == []
    assert result["replacement_character_entries"] == []


def test_text_encoding_validator_detects_non_utf8_file(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    (root / "bad.md").write_bytes("中文".encode("gbk"))

    result = validate_text_encodings(root)
    assert result["passed"] is False
    assert result["invalid_utf8_files"] == ["bad.md"]


def test_package_preserves_nested_sha256_manifests(tmp_path: Path) -> None:
    root = tmp_path / "release"
    nested = root / "representative_cases_17" / "O_FAMILY"
    nested.mkdir(parents=True)
    expected = b"nested-manifest\n"
    # Write exact bytes so the fixture is platform-independent.  Path.write_text
    # uses the host newline convention on Windows unless newline is specified;
    # this test is about byte preservation by the packager, not newline rewriting.
    (nested / "SHA256SUMS.txt").write_bytes(expected)
    (root / "README.md").write_text("ok\n", encoding="utf-8", newline="\n")
    output_zip = tmp_path / "release.zip"

    package(root, output_zip)

    with ZipFile(output_zip) as archive:
        assert "release/representative_cases_17/O_FAMILY/SHA256SUMS.txt" in archive.namelist()
        assert archive.read("release/representative_cases_17/O_FAMILY/SHA256SUMS.txt") == expected
