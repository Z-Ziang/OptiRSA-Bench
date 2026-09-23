from __future__ import annotations
from math import ceil
from statistics import fmean
from src.case_core.serialization_metrics import _runtime

CANONICAL_TIKTOKEN_VERSION = '0.14.0'
CANONICAL_ENCODING = 'o200k_base'


def _exact_runtime():
    enc, version = _runtime()
    version = str(version)
    if version != CANONICAL_TIKTOKEN_VERSION:
        raise RuntimeError(
            f'Canonical S1/X4 token statistics require tiktoken=={CANONICAL_TIKTOKEN_VERSION}; '
            f'found {version}'
        )
    return enc, version


def _nearest_rank(values, q: float):
    if not values:
        return None
    vals = sorted(values)
    rank = max(1, ceil(q * len(vals)))
    return vals[rank - 1]


def compute_serialization_metrics(llm_prompt: str) -> dict:
    if not isinstance(llm_prompt, str):
        raise TypeError('llm_prompt must be a string')
    enc, version = _exact_runtime()
    return {
        'llm_prompt_char_count': len(llm_prompt),
        'llm_prompt_utf8_bytes': len(llm_prompt.encode('utf-8')),
        'llm_prompt_token_count': len(enc.encode(llm_prompt)),
        'canonical_tokenizer': {
            'backend': 'tiktoken',
            'encoding': CANONICAL_ENCODING,
            'package_version': version,
        },
    }


def compute_dynamic_serialization_metrics(prompts: list[str]) -> dict:
    if not isinstance(prompts, list) or not all(isinstance(x, str) for x in prompts):
        raise TypeError('prompts must be list[str]')
    enc, version = _exact_runtime()
    chars = [len(x) for x in prompts]
    bytes_ = [len(x.encode('utf-8')) for x in prompts]
    tokens = [len(enc.encode(x)) for x in prompts]
    return {
        'step_count': len(prompts),
        'total_prompt_char_count': sum(chars),
        'total_prompt_utf8_bytes': sum(bytes_),
        'total_prompt_token_count': sum(tokens),
        'mean_step_token_count': fmean(tokens) if tokens else None,
        'p95_step_token_count': _nearest_rank(tokens, 0.95),
        'max_step_token_count': max(tokens) if tokens else None,
        'canonical_tokenizer': {
            'backend': 'tiktoken',
            'encoding': CANONICAL_ENCODING,
            'package_version': version,
        },
    }
