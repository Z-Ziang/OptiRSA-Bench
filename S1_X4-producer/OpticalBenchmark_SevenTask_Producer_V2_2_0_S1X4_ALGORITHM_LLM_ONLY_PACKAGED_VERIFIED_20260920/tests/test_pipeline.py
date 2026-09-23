import json
import shutil
from pathlib import Path

from src.pipeline import run_pipeline


def test_end_to_end_has_exact_counts_and_hard_gates(tmp_path):
    input_root = Path(__file__).resolve().parents[1]
    out = tmp_path / "P0_RESULT"
    summary = run_pipeline(input_root, out)
    env = out / "public_environment"
    assert sum(1 for line in (env/"requests/single/requests_batch_001.jsonl").read_text(encoding="utf-8").splitlines() if line) == 182
    assert sum(1 for line in (env/"requests/derivation/derivations_batch_001.jsonl").read_text(encoding="utf-8").splitlines() if line) == 182
    assert len(list((env/"requests/concurrent").glob("reqset_*.json"))) == 3
    assert len(json.loads((env/"requests/dynamic/seq_0001.json").read_text(encoding="utf-8"))["dynamic_request_events"]) == 20
    assert len(list((env/"scenarios").glob("bs_*.json"))) == 4
    status = json.loads((out/"RELEASE_STATUS.json").read_text(encoding="utf-8"))
    assert status["generated_file_schema_pass"]
    assert status["cross_file_validation_pass"]
    assert status["state_reconstruction_pass"]
    assert status["dynamic_replay_pass"]
    assert status["case_generation_executed"] is False
    assert status["i1_executed"] is False
    assert status["formal_difficulty_labels_generated"] is False
    subject_files = [p for p in env.rglob("*.json*") if "reports" not in p.relative_to(env).parts]
    forbidden = "\n".join(p.read_text(encoding="utf-8") for p in subject_files)
    assert "release_time" not in forbidden
    assert "candidate_path_id" not in forbidden
    assert summary["object_counts"]["single_requests"] == 182


def test_self_contained_in_place_generation_does_not_copy_schemas_onto_themselves(tmp_path):
    source = Path(__file__).resolve().parents[1]
    package = tmp_path / "self_contained"
    package.mkdir()
    for name in ("schemas", "inputs", "examples"):
        shutil.copytree(source / name, package / name)

    summary = run_pipeline(package, package)

    assert summary["status"] == "PASS"
    assert (package / "public_environment" / "topologies" / "physical" / "top_0001.json").exists()
