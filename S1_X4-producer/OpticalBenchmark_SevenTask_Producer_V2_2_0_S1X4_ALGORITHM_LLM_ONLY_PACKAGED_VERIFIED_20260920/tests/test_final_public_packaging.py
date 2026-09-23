from __future__ import annotations

import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


ROOT = Path(__file__).resolve().parents[1]


def _episode(tmp_path: Path, task: str = "S1") -> dict:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    index = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=3))
    return build_episode_definition(
        index,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3 if task == "S1" else None,
        pairing_id="pair_public_packaging",
    )


def test_public_generation_spec_projection_has_only_approved_science_fields(tmp_path: Path) -> None:
    from src.s1_x4.generation_spec import build_generation_spec
    from src.s1_x4.public_dataset_v2 import _public_generation_spec

    episode = _episode(tmp_path)
    spec = build_generation_spec(
        topology_id=episode["topology_id"],
        condition_id="A_MEDIUM_MATCH",
        production_config={
            "condition_id": "A_MEDIUM_MATCH",
            "dynamic": {"sequence_length": 3},
            "scientific_profile": {"od_distribution": "UNIFORM"},
        },
        episode=episode,
        canonical_topology_sha256="a" * 64,
    )

    public = _public_generation_spec(spec)
    assert set(public) == {"schema_version", "generation_spec_id", "topology_id", "condition_id", "resource_config", "initial_state_generation", "request_generation", "dynamic_generation", "seed_block"}
    assert set(public["resource_config"]) == {"episode_length", "slot_count", "guard_band_slots"}
    assert set(public["initial_state_generation"]) == {"load_band", "policy", "candidate_path_k", "state_arrival_rate_lambda"}
    assert set(public["request_generation"]) == {"od_distribution", "payload_slot_values", "required_slot_values", "slot_probabilities"}
    assert set(public["dynamic_generation"]) == {"arrival_rate_mode", "arrival_rate_multiplier", "dynamic_arrival_rate_lambda", "holding_time_rate_mu"}
    assert "producer_runtime" not in json.dumps(public, ensure_ascii=False)
    assert "expected_underlying_episode_fingerprint" not in json.dumps(public, ensure_ascii=False)


def test_public_minimal_generation_spec_still_runs_algorithm_environment(tmp_path: Path) -> None:
    from src.s1_x4.generation_spec import build_generation_spec
    from src.s1_x4.public_dataset_v2 import export_public_dataset_v2, verify_public_dataset_v2
    from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark
    from src.s1_x4.reference_algorithms import run_reference_panel
    from examples.s1_x4_algorithm_examples import FirstFeasibleS1

    episode = _episode(tmp_path, "S1")
    x4_episode = _episode(tmp_path, "X4")
    spec = build_generation_spec(
        topology_id=episode["topology_id"],
        condition_id="A_MEDIUM_MATCH",
        production_config={"condition_id": "A_MEDIUM_MATCH", "dynamic": {"sequence_length": 3}},
        episode=episode,
        canonical_topology_sha256="a" * 64,
    )
    output = tmp_path / "public"
    export_public_dataset_v2(
        output,
        specs=[spec],
        episodes_by_task={"S1": [episode], "X4": [x4_episode]},
        reference_panels={"S1": [run_reference_panel(episode)], "X4": [run_reference_panel(x4_episode)]},
        contracts_root=ROOT / "contracts",
        source_runtime_root=ROOT,
    )

    report = verify_public_dataset_v2(output)
    assert report["valid"] is True, report
    config = output / "evaluation_case/S1/algorithm/run_configs" / episode["topology_id"] / "A_MEDIUM_MATCH.json"
    result = run_algorithm_benchmark(
        config,
        FirstFeasibleS1(),
        task_type="S1",
        dataset_root=output,
        output_dir=tmp_path / "algorithm_run",
    )
    assert result["summary"]["step_count"] == 3


def test_source_package_required_assets_manifest_is_complete() -> None:
    manifest_path = ROOT / "release_evidence/source_package_required_files.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "SOURCE_PACKAGE_REQUIRED_FILES_V1"
    for relative in manifest["required_files"]:
        assert (ROOT / relative).is_file(), relative
    for relative in manifest["required_directories"]:
        assert (ROOT / relative).is_dir(), relative
