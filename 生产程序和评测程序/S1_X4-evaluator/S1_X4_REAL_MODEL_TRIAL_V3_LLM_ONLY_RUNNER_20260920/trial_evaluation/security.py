from __future__ import annotations

import re
from typing import Iterable


_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_KEY_ASSIGNMENT_PATTERN = re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+")


def redact_text(value: object, *, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    text = _KEY_ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", text)
    return text


def scan_for_secrets(values: Iterable[object], *, secrets: Iterable[str] = ()) -> dict[str, object]:
    secret_values = [secret for secret in secrets if secret]
    hits = []
    for index, value in enumerate(values):
        text = str(value)
        if any(secret in text for secret in secret_values) or _BEARER_PATTERN.search(text) or _KEY_ASSIGNMENT_PATTERN.search(text):
            hits.append(index)
    return {"passed": not hits, "hit_count": len(hits), "hit_indexes": hits}

