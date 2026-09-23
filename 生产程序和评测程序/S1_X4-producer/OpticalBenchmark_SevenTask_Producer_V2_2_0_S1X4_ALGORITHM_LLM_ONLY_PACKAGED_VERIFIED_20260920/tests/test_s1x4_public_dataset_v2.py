from __future__ import annotations

import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _episode(tmp_path: Path, task: str) -> dict:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    index = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=3))
    return build_episode_definition(
        index,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3 if task == "S1" else None,
        pairing_id="pair_v2",
    )


def test_public_v2_export_has_cases_episodes_run_configs_and_no_legacy_index(tmp_path: Path) -> None:
    from src.s1_x4.generation_spec import build_generation_spec
    from src.s1_x4.public_dataset_v2 import export_public_dataset_v2, verify_public_dataset_v2
    from src.s1_x4.reference_algorithms import run_reference_panel

    episodes = {"S1": [_episode(tmp_path, "S1")], "X4": [_episode(tmp_path, "X4")]}
    specs = [
        build_generation_spec(
            topology_id=episodes["S1"][0]["topology_id"],
            condition_id="A_MEDIUM_MATCH",
            production_config={"condition_id": "A_MEDIUM_MATCH", "dynamic": {"sequence_length": 3}},
            episode=episodes["S1"][0],
            canonical_topology_sha256="a" * 64,
        )
    ]
    panels = {task: [run_reference_panel(episodes[task][0])] for task in ("S1", "X4")}
    output = tmp_path / "public_v2"
    export_public_dataset_v2(
        output,
        specs=specs,
        episodes_by_task=episodes,
        reference_panels=panels,
        contracts_root=Path(__file__).resolve().parents[1] / "contracts",
        source_runtime_root=Path(__file__).resolve().parents[1],
    )
    assert {p.name for p in output.iterdir()} == {"README.md", "benchmark_case", "evaluation_case", "reference"}
    assert (output / "benchmark_case" / "S1" / "cases").is_dir()
    assert (output / "benchmark_case" / "S1" / "episodes").is_dir()
    assert (output / "evaluation_case" / "S1" / "algorithm" / "run_configs").is_dir()
    assert not (output / "case_index.jsonl").exists()
    assert not (output / "DATASET_INDEX.json").exists()
    assert not any(p.name == "endpoint_view" for p in output.rglob("*"))
    report = verify_public_dataset_v2(output)
    assert report["valid"] is True, report


def test_case_overview_contains_refs_but_not_a_fixed_future_prompt_sequence(tmp_path: Path) -> None:
    from src.s1_x4.generation_spec import build_generation_spec

    episode = _episode(tmp_path, "S1")
    spec = build_generation_spec(
        topology_id=episode["topology_id"],
        condition_id="A_MEDIUM_MATCH",
        production_config={"condition_id": "A_MEDIUM_MATCH", "dynamic": {"sequence_length": 3}},
        episode=episode,
        canonical_topology_sha256="a" * 64,
    )
    from src.s1_x4.public_dataset_v2 import build_case_overview
    overview = build_case_overview(episode, spec, {"policy_results": []}, task="S1")
    assert {"generation_spec_ref", "episode_ref", "reference_ref", "first_step_views", "reference_summary"} <= set(overview)
    assert "step_000" not in json.dumps(overview, ensure_ascii=False)
    assert "request_events" not in overview.get("first_step_views", {})
