from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PROMPT_PATH = Path(__file__).with_name("system_prompts.json")
BASE_SYSTEM: dict[str, str] = json.loads(_PROMPT_PATH.read_text(encoding="utf-8"))

def unified_system_prompt(task: str) -> str:
    return system_prompt(task)


def system_prompt(task: str) -> str:
    return BASE_SYSTEM[task]


def contract_bundle(task: str) -> dict[str, Any]:
    return {
        "task_type": task,
        "llm_system_prompt": system_prompt(task),
    }
