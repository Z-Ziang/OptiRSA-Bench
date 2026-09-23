from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def test_windows_path_audit_rejects_reserved_invalid_trailing_and_casefold():
    # Invalid Windows names cannot be created on a Windows filesystem. Exercise
    # the pure path-component validator with synthetic relative names instead.
    from scripts.release_audit import _path_errors
    errors = _path_errors(['CON.txt', 'bad?.txt', 'trail.', 'A.txt', 'a.TXT'])
    joined = '\n'.join(errors)
    assert 'reserved' in joined.lower()
    assert 'invalid character' in joined.lower()
    assert 'trailing dot/space' in joined.lower()
    assert 'casefold collision' in joined.lower()


def test_zip_audit_checks_crc_duplicates_and_windows_names(tmp_path: Path):
    from scripts.release_audit import validate_zip_archive
    z = tmp_path / 'bad.zip'
    with ZipFile(z, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('release/ok.txt', '1')
        archive.writestr('release/OK.TXT', '2')
        archive.writestr('release/NUL.txt', '3')
    result = validate_zip_archive(z)
    assert result['passed'] is False
    assert result['crc_passed'] is True
    assert any('casefold collision' in e.lower() for e in result['errors'])
    assert any('reserved' in e.lower() for e in result['errors'])


def test_manifest_verifier_requires_exact_file_set_and_hashes(tmp_path: Path):
    from scripts.release_audit import verify_sha256_manifest
    import hashlib
    root = tmp_path / 'release'
    root.mkdir()
    a = root / 'a.txt'; a.write_text('abc', encoding='utf-8')
    digest = hashlib.sha256(a.read_bytes()).hexdigest()
    (root / 'SHA256SUMS.txt').write_text(f'{digest}  a.txt\n', encoding='utf-8')
    assert verify_sha256_manifest(root)['passed'] is True
    (root / 'extra.txt').write_text('extra', encoding='utf-8')
    result = verify_sha256_manifest(root)
    assert result['passed'] is False
    assert any('unlisted' in e.lower() for e in result['errors'])
