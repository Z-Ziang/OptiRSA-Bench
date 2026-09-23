from __future__ import annotations

import json
import pytest
from pathlib import Path

from tests.o_family_test_utils import toy_env
from src.tasks.x2.producer import build_x2_case
from src.x2x3_exporter import export_x2x3_dataset

ROOT = Path(__file__).resolve().parents[1]


def test_serialization_metrics_match_real_o200k_tokenizer(tmp_path):
    tiktoken = pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")
    from src.case_core.serialization_metrics import compute_serialization_metrics

    llm = "中文 network 0→1；[0,319]。"
    metrics = compute_serialization_metrics(llm)
    enc = tiktoken.get_encoding("o200k_base")
    assert metrics["llm_prompt_char_count"] == len(llm)
    assert metrics["llm_prompt_utf8_bytes"] == len(llm.encode("utf-8"))
    assert metrics["llm_prompt_token_count"] == len(enc.encode(llm))
    assert metrics["canonical_tokenizer"]["backend"] == "tiktoken"
    assert metrics["canonical_tokenizer"]["encoding"] == "o200k_base"
    assert metrics["canonical_tokenizer"]["package_version"] == tiktoken.__version__


def test_export_stores_metrics_only_in_internal_features(tmp_path):
    pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")
    bundle = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_TEST", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    out = tmp_path / "x"
    export_x2x3_dataset(out, {"X2": [bundle], "X3": []}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    benchmark = json.loads((out / "benchmark_case/X2/cases/case_000001.json").read_text(encoding="utf-8"))
    features = json.loads((out / "internal/private/X2/X2_TEST/features.json").read_text(encoding="utf-8"))
    assert "serialization_metrics" in features
    assert "serialization_metrics" not in benchmark
    assert "canonical_tokenizer" not in benchmark
    assert features["serialization_metrics"]["llm_prompt_char_count"] == len(benchmark["llm_prompt"])
