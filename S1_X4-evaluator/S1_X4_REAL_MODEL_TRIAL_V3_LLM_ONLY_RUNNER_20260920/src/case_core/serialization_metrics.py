from __future__ import annotations

from functools import lru_cache
from importlib import metadata

_CANONICAL_BACKEND = "tiktoken"
_CANONICAL_ENCODING = "o200k_base"


@lru_cache(maxsize=1)
def _runtime():
    try:
        import tiktoken
    except ImportError as exc:
        raise RuntimeError(
            "Canonical token statistics require tiktoken. Install the exact version "
            "pinned in requirements.txt before dataset production."
        ) from exc
    version = getattr(tiktoken, "__version__", None) or metadata.version("tiktoken")
    encoding = tiktoken.get_encoding(_CANONICAL_ENCODING)
    return encoding, str(version)


def canonical_tokenizer_metadata() -> dict[str, str]:
    _, version = _runtime()
    return {
        "backend": _CANONICAL_BACKEND,
        "encoding": _CANONICAL_ENCODING,
        "package_version": version,
    }


def compute_serialization_metrics(llm_prompt: str) -> dict:
    if not isinstance(llm_prompt, str):
        raise TypeError("llm_prompt must be a string")
    encoding, version = _runtime()
    return {
        "llm_prompt_char_count": len(llm_prompt),
        "llm_prompt_utf8_bytes": len(llm_prompt.encode("utf-8")),
        "llm_prompt_token_count": len(encoding.encode(llm_prompt)),
        "canonical_tokenizer": {
            "backend": _CANONICAL_BACKEND,
            "encoding": _CANONICAL_ENCODING,
            "package_version": version,
        },
    }
