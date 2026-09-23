from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.o_family_test_utils import toy_env
from src.case_core.exporter import export_dataset
from src.tasks.o1.producer import build_o1_case
from src.tasks.x2.producer import build_x2_case
from src.x2x3_exporter import export_x2x3_dataset

ROOT = Path(__file__).resolve().parents[1]


def _require_tiktoken():
    return pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")


def _check_case(dataset: Path, task: str, case_id: str):
    benchmark = json.loads((dataset / f"benchmark_case/{task}/cases/case_000001.json").read_text(encoding="utf-8"))
    import numpy as np
    algorithm_path = dataset / f"evaluation_case/{task}/algorithm/case_000001.npz"
    llm = json.loads((dataset / f"evaluation_case/{task}/llm/case_000001.json").read_text(encoding="utf-8"))
    reference = json.loads((dataset / f"internal/private/{task}/{case_id}/reference_output.json").read_text(encoding="utf-8"))
    features = json.loads((dataset / f"internal/private/{task}/{case_id}/features.json").read_text(encoding="utf-8"))
    assert set(benchmark) == {"case_id", "instance", "llm_prompt", "reference"}
    assert benchmark["reference"] == reference
    with np.load(algorithm_path, allow_pickle=False) as algorithm:
        assert "format_version" in algorithm.files
        assert all(algorithm[name].dtype != np.dtype("O") for name in algorithm.files)
    assert llm == {"case_id": benchmark["case_id"], "prompt": benchmark["llm_prompt"]}
    assert "reference" not in llm
    assert "当前网络有向链路及频谱资源状态" in llm["prompt"]
    assert "serialization_metrics" in features


def test_o_export_writes_benchmark_and_runtime_text_views(tmp_path):
    _require_tiktoken()
    bundle = build_o1_case(toy_env(slot_count=6), ["r1", "r2"], case_id="O1_TEST", max_complete_solutions=100)
    out = tmp_path / "o"
    export_dataset(out, {"O1": [bundle]}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    _check_case(out, "O1", "O1_TEST")


def test_x_export_writes_benchmark_and_runtime_text_views(tmp_path):
    _require_tiktoken()
    bundle = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_TEST", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    out = tmp_path / "x"
    export_x2x3_dataset(out, {"X2": [bundle], "X3": []}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    _check_case(out, "X2", "X2_TEST")
