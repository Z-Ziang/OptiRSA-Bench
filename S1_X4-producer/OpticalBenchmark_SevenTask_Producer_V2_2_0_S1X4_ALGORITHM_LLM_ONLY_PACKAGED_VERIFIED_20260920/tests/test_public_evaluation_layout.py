from __future__ import annotations
import pytest

import json
from pathlib import Path

from tests.o_family_test_utils import toy_env
from src.case_core.exporter import export_dataset
from src.tasks.o1.producer import build_o1_case
from src.tasks.x2.producer import build_x2_case
from src.x2x3_exporter import export_x2x3_dataset

pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_new_layout(out: Path, task: str, case_id: str, reference: dict):
    bench_dir = out / "benchmark_case" / task
    eval_dir = out / "evaluation_case" / task
    for base in (bench_dir, eval_dir):
        assert (base / "llm_system_prompt.txt").read_bytes() == (ROOT / "contracts" / task / "llm_system_prompt.txt").read_bytes()
        assert (base / "algorithm_contract.json").read_bytes() == (ROOT / "contracts" / task / "algorithm_contract.json").read_bytes()
        assert (base / "algorithm_input.schema.json").read_bytes() == (ROOT / "contracts" / task / "schemas" / "algorithm_input.schema.json").read_bytes()
        assert (base / "algorithm_evaluation_case.schema.json").read_bytes() == (ROOT / "contracts" / task / "schemas" / "algorithm_evaluation_case.schema.json").read_bytes()

    benchmark = _read(bench_dir / "cases" / "case_000001.json")
    import numpy as np
    algorithm_path = eval_dir / "algorithm" / "case_000001.npz"
    llm = _read(eval_dir / "llm" / "case_000001.json")
    assert list(benchmark) == ["case_id", "instance", "llm_prompt", "reference"]
    assert benchmark["case_id"] == case_id
    assert benchmark["reference"] == reference
    with np.load(algorithm_path, allow_pickle=False) as algorithm:
        assert "format_version" in algorithm.files
        assert all(algorithm[name].dtype != np.dtype("O") for name in algorithm.files)
    assert llm == {"case_id": case_id, "prompt": benchmark["llm_prompt"]}
    assert "reference" not in llm

    internal_case = out / "internal" / "cases" / task / case_id
    internal_private = out / "internal" / "private" / task / case_id
    assert (internal_case / "root_case.json").is_file()
    assert (internal_case / "algorithm_case.json").is_file()
    for name in ("private_truth", "reference_output", "validation", "features", "lineage"):
        assert (internal_private / f"{name}.json").is_file()
    assert _read(internal_private / "reference_output.json") == reference
    assert not (out / "cases").exists()
    assert not (out / "private").exists()


def test_o_export_uses_public_benchmark_blind_evaluation_and_internal_layout(tmp_path):
    bundle = build_o1_case(toy_env(slot_count=6), ["r1", "r2"], case_id="O1_TEST", max_complete_solutions=100)
    out = tmp_path / "o"
    export_dataset(out, {"O1": [bundle]}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    _assert_new_layout(out, "O1", "O1_TEST", bundle["reference_output"])


def test_x_export_uses_same_layout(tmp_path):
    bundle = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_TEST", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    out = tmp_path / "x"
    export_x2x3_dataset(out, {"X2": [bundle], "X3": []}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    _assert_new_layout(out, "X2", "X2_TEST", bundle["reference_output"])


def test_case_files_are_deterministically_numbered_by_case_id(tmp_path):
    b2 = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_000002", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    b1 = build_x2_case(toy_env(slot_count=5), "r1", case_id="X2_000001", required_slots=2, max_simple_paths=100, max_optimal_actions=1000)
    out = tmp_path / "x"
    export_x2x3_dataset(out, {"X2": [b2, b1], "X3": []}, contracts_root=ROOT / "contracts", production_metadata={"test": True}, strict_frozen_interface=False)
    rows = [json.loads(line) for line in (out / "case_index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["case_id"] for r in rows] == ["X2_000001", "X2_000002"]
    assert [r["benchmark_case_path"] for r in rows] == [
        "benchmark_case/X2/cases/case_000001.json",
        "benchmark_case/X2/cases/case_000002.json",
    ]
    assert [r["algorithm_evaluation_path"] for r in rows] == [
        "evaluation_case/X2/algorithm/case_000001.npz",
        "evaluation_case/X2/algorithm/case_000002.npz",
    ]
