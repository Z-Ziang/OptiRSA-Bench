from __future__ import annotations

import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _episode(tmp_path: Path, task: str = "S1") -> dict:
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


def _write_run_config(tmp_path: Path, episode: dict, task: str) -> Path:
    from src.s1_x4.generation_spec import build_generation_spec

    dataset = tmp_path / "dataset"
    (dataset / "benchmark_case" / "generation_specs" / episode["topology_id"]).mkdir(parents=True)
    (dataset / "benchmark_case" / task / "episodes" / episode["topology_id"]).mkdir(parents=True)
    (dataset / "evaluation_case" / task / "algorithm" / "run_configs" / episode["topology_id"]).mkdir(parents=True)
    spec = build_generation_spec(
        topology_id=episode["topology_id"],
        condition_id="A_MEDIUM_MATCH",
        production_config={"condition_id": "A_MEDIUM_MATCH", "dynamic": {"sequence_length": 3}},
        episode=episode,
        canonical_topology_sha256="a" * 64,
    )
    spec_path = dataset / "benchmark_case" / "generation_specs" / episode["topology_id"] / "A_MEDIUM_MATCH.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    episode_path = dataset / "benchmark_case" / task / "episodes" / episode["topology_id"] / "A_MEDIUM_MATCH.json"
    episode_path.write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")
    config = {
        "schema_version": "S1_X4_ALGORITHM_RUN_CONFIG_V2_0",
        "task_type": task,
        "topology_id": episode["topology_id"],
        "condition_id": "A_MEDIUM_MATCH",
        "generation_spec_ref": f"benchmark_case/generation_specs/{episode['topology_id']}/A_MEDIUM_MATCH.json",
    }
    config_path = (
        dataset
        / "evaluation_case"
        / task
        / "algorithm"
        / "run_configs"
        / episode["topology_id"]
        / "A_MEDIUM_MATCH.json"
    )
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return config_path


def test_frozen_generation_matrix_has_exact_27_shared_specs() -> None:
    from src.s1_x4.generation_spec import FROZEN_CONDITIONS, FROZEN_TOPOLOGIES, frozen_matrix_keys

    assert len(FROZEN_TOPOLOGIES) == 9
    assert tuple(FROZEN_CONDITIONS) == ("A_MEDIUM_MATCH", "B_HIGH_MATCH", "C_HIGH_X1P2")
    assert len(frozen_matrix_keys()) == 27
    assert len(set(frozen_matrix_keys())) == 27
    assert ("topologybench_netrail", "A_MEDIUM_MATCH") in frozen_matrix_keys()
    assert ("topohub_gabriel_450_9", "C_HIGH_X1P2") in frozen_matrix_keys()


def test_run_config_is_the_primary_algorithm_input_and_callback_is_observation_only(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark

    episode = _episode(tmp_path, "S1")
    config_path = _write_run_config(tmp_path, episode, "S1")
    seen: list[tuple[dict, dict]] = []

    def spy(static_context, observation):
        seen.append((static_context.to_public_dict(), observation.to_public_dict()))
        if observation.feasible_actions.size:
            row = observation.feasible_actions[0]
            return {"decision": "ACCEPT", "path_rank": int(row[0]), "slot_start": int(row[1])}
        return {"decision": "REJECT", "path_rank": None, "slot_start": None}

    result = run_algorithm_benchmark(config_path, spy, task_type="S1", dataset_root=config_path.parents[5])
    assert result["summary"]["step_count"] == 3
    assert len(seen) == 3
    for static, observation in seen:
        serialized = json.dumps({"static": static, "observation": observation}, ensure_ascii=False)
        for forbidden in ("request_events", "initial_existing_connections", "difficulty_context", "reference", "seed"):
            assert forbidden not in serialized
    assert seen[0][1]["request"]["request_id"] not in {
        event["request_id"] for event in episode["request_events"][1:]
    }


def test_x4_run_config_callback_has_no_candidate_oracle(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark

    episode = _episode(tmp_path, "X4")
    config_path = _write_run_config(tmp_path, episode, "X4")

    def reject(_static, observation):
        assert observation.task_type == "X4"
        public = observation.to_public_dict()
        assert "candidate_paths" not in public
        assert "feasible_actions" not in public
        return {"decision": "REJECT", "path_node_ids": [], "path_link_ids": [], "slot_start": None}

    result = run_algorithm_benchmark(config_path, reject, task_type="X4", dataset_root=config_path.parents[5])
    assert result["summary"]["step_count"] == 3
