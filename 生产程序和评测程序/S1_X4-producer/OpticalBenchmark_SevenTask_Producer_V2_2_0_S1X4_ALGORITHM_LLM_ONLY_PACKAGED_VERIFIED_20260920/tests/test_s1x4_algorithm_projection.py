from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _step(tmp_path: Path, task: str = "S1"):
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment
    from src.s1_x4.state_machine import DynamicEpisodeState

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=3))
    episode = build_episode_definition(
        idx,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3 if task == "S1" else None,
        pairing_id="pair_1",
    )
    state = DynamicEpisodeState(episode)
    return episode, state.prepare_current_step()


def test_public_projection_module_is_present() -> None:
    assert importlib.util.find_spec("src.s1_x4.public_projection") is not None


def test_s1_projection_contains_current_request_and_complete_actions(tmp_path: Path) -> None:
    from src.s1_x4.public_projection import build_static_context, project_current_step

    episode, context = _step(tmp_path, "S1")
    static = build_static_context(episode)
    observation = project_current_step(context)
    public = observation.to_public_dict()

    assert static.to_public_dict()["case_id"] == episode["case_id"]
    assert public["case_id"] == episode["case_id"]
    assert public["request"]["request_id"] == context["request"]["request_id"]
    expected = {(int(a["path_rank"]), int(a["slot_start"])) for a in context["candidate_actions"]}
    actual = {tuple(int(x) for x in row) for row in observation.feasible_actions.tolist()}
    assert actual == expected
    assert observation.feasible_actions.shape[1] == 2
    assert not observation.feasible_actions.flags.writeable
    assert not observation.spectrum.free_words.flags.writeable

    visible = json.dumps(public, ensure_ascii=False)
    for forbidden in (
        "request_events",
        "initial_existing_connections",
        "difficulty_context",
        "reference",
        "private_truth",
    ):
        assert forbidden not in visible
    for future in episode["request_events"][1:]:
        assert future["request_id"] not in visible


def test_x4_projection_has_current_spectrum_but_no_candidate_oracle(tmp_path: Path) -> None:
    from src.s1_x4.public_projection import build_static_context, project_current_step

    episode, context = _step(tmp_path, "X4")
    static = build_static_context(episode)
    observation = project_current_step(context)
    public = observation.to_public_dict()
    visible = json.dumps({"static": static.to_public_dict(), "observation": public}, ensure_ascii=False)

    assert public["request"]["request_id"] == context["request"]["request_id"]
    assert "candidate_paths" not in public
    assert "feasible_actions" not in public
    for forbidden in (
        "candidate_paths",
        "candidate_actions",
        "feasible_paths",
        "feasible_actions",
        "path_rank",
        "recommended_action",
    ):
        assert forbidden not in visible
