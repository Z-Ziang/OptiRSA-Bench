from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from trial_evaluation.v2.action_schemas import action_schema


@dataclass(frozen=True)
class ParseResult:
    protocol_status: str
    code: str | None
    action: dict[str, Any] | None
    raw_text: str


class StructuredActionParser:
    def __init__(self, task: str) -> None:
        self.task = task
        self.schema = action_schema(task)
        self.validator = Draft202012Validator(self.schema)

    def parse(self, text: str | None, *, finish_reason: str | None) -> ParseResult:
        raw = text or ""
        stripped = raw.strip()
        if finish_reason in {"length", "max_tokens"}:
            return ParseResult("PROTOCOL_FAILURE", "PROTOCOL_TRUNCATED", None, raw)
        if not stripped:
            return ParseResult("PROTOCOL_FAILURE", "PROTOCOL_EMPTY_OUTPUT", None, raw)
        if stripped.startswith("```") or not stripped.startswith("{"):
            return ParseResult("PROTOCOL_FAILURE", "PROTOCOL_EXTRA_TEXT", None, raw)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return ParseResult("PROTOCOL_FAILURE", "PROTOCOL_INVALID_JSON", None, raw)
        if not isinstance(value, dict) or list(self.validator.iter_errors(value)):
            return ParseResult("PROTOCOL_FAILURE", "PROTOCOL_SCHEMA_VIOLATION", None, raw)
        return ParseResult("OK", None, value, raw)
