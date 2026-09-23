from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

_INVALID_CHARS = set('<>:"\\|?*')
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)
_IGNORED_DIRS = {'__pycache__', '.pytest_cache', '.git'}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _path_errors(names: list[str]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for raw in names:
        name = raw.replace('\\', '/')
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts:
            errors.append(f'unsafe relative path: {raw}')
            continue
        normalized_parts: list[str] = []
        for part in p.parts:
            if part in {'', '.'}:
                continue
            if any(ch in _INVALID_CHARS or ord(ch) < 32 for ch in part):
                errors.append(f'invalid character in Windows path component: {raw}')
            if part.endswith('.') or part.endswith(' '):
                errors.append(f'trailing dot/space in Windows path component: {raw}')
            if _RESERVED.match(part):
                errors.append(f'reserved Windows device name: {raw}')
            normalized_parts.append(part.casefold())
        key = '/'.join(normalized_parts)
        if key in seen and seen[key] != raw:
            errors.append(f'casefold collision: {seen[key]} <-> {raw}')
        else:
            seen[key] = raw
    return errors


def validate_windows_paths(root: Path | str) -> dict[str, object]:
    root = Path(root).resolve()
    if not root.is_dir():
        return {'passed': False, 'checked_paths': 0, 'errors': [f'root not found: {root}']}
    rels: list[str] = []
    for p in root.rglob('*'):
        rel = p.relative_to(root)
        if any(part in _IGNORED_DIRS for part in rel.parts):
            continue
        rels.append(rel.as_posix())
    errors = _path_errors(sorted(rels))
    return {'passed': not errors, 'checked_paths': len(rels), 'errors': errors}


def validate_zip_archive(zip_path: Path | str) -> dict[str, object]:
    zip_path = Path(zip_path).resolve()
    errors: list[str] = []
    try:
        with ZipFile(zip_path) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)):
                dupes = sorted({n for n in names if names.count(n) > 1})
                errors.extend(f'duplicate ZIP member: {n}' for n in dupes)
            errors.extend(_path_errors(names))
            for info in infos:
                if '\ufffd' in info.filename:
                    errors.append(f'replacement character in ZIP filename: {info.filename}')
                if any(ord(ch) > 127 for ch in info.filename) and not (info.flag_bits & 0x800):
                    errors.append(f'non-ASCII ZIP filename lacks UTF-8 flag: {info.filename}')
            bad = archive.testzip()
            crc_passed = bad is None
            if bad is not None:
                errors.append(f'ZIP CRC failure: {bad}')
    except (BadZipFile, OSError) as exc:
        return {
            'passed': False,
            'checked_entries': 0,
            'crc_passed': False,
            'errors': [f'{type(exc).__name__}: {exc}'],
        }
    return {
        'passed': not errors,
        'checked_entries': len(infos),
        'crc_passed': crc_passed,
        'errors': errors,
    }


def verify_sha256_manifest(root: Path | str) -> dict[str, object]:
    root = Path(root).resolve()
    manifest = root / 'SHA256SUMS.txt'
    errors: list[str] = []
    if not manifest.is_file():
        return {'passed': False, 'checked_files': 0, 'errors': ['missing SHA256SUMS.txt']}
    expected: dict[str, str] = {}
    for line_no, line in enumerate(manifest.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, rel = line.split('  ', 1)
        except ValueError:
            errors.append(f'malformed manifest line {line_no}')
            continue
        if rel in expected:
            errors.append(f'duplicate manifest path: {rel}')
        expected[rel] = digest
    actual: set[str] = set()
    for p in root.rglob('*'):
        if not p.is_file() or p == manifest:
            continue
        relp = p.relative_to(root)
        if any(part in _IGNORED_DIRS for part in relp.parts) or p.suffix == '.pyc':
            continue
        rel = relp.as_posix()
        actual.add(rel)
        if rel not in expected:
            errors.append(f'unlisted file: {rel}')
        elif _sha256(p) != expected[rel]:
            errors.append(f'SHA256 mismatch: {rel}')
    for rel in sorted(set(expected) - actual):
        errors.append(f'manifest lists missing file: {rel}')
    return {'passed': not errors, 'checked_files': len(actual), 'errors': errors}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='OpticalBenchmark V2.1.0 release auditor')
    p.add_argument('--root', type=Path)
    p.add_argument('--zip', dest='zip_path', type=Path)
    args = p.parse_args(argv)
    result: dict[str, object] = {}
    if args.root:
        result['windows_paths'] = validate_windows_paths(args.root)
        result['sha256_manifest'] = verify_sha256_manifest(args.root)
    if args.zip_path:
        result['zip'] = validate_zip_archive(args.zip_path)
    if not result:
        p.error('provide --root and/or --zip')
    passed = all(bool(v.get('passed')) for v in result.values())
    result['passed'] = passed
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
