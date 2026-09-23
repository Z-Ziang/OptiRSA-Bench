from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _episode(tmp_path: Path, task: str) -> dict:
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment

    idx = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=3))
    return build_episode_definition(
        idx,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3 if task == "S1" else None,
        pairing_id="pair_parity",
    )


def test_algorithm_examples_are_present() -> None:
    assert importlib.util.find_spec("examples.s1_x4_algorithm_examples") is not None


def test_s1_algorithm_and_llm_current_step_semantics_match(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.compiler import compile_observation
    from src.s1_x4.renderer import render_s1_step
    from src.s1_x4.state_machine import DynamicEpisodeState

    episode = _episode(tmp_path, "S1")
    state = DynamicEpisodeState(episode)
    context = state.prepare_current_step()
    observation = compile_observation(context)
    llm = render_s1_step(episode, context, "llm")

    assert observation.request["request_id"] == context["request"]["request_id"]
    assert observation.request["required_slots"] == context["request"]["required_slots"]
    assert "candidate_paths" not in json.dumps({"llm": llm}, ensure_ascii=False)
    assert observation.to_public_dict()["feasible_actions"]


def test_x4_algorithm_and_llm_have_no_candidate_oracle(tmp_path: Path) -> None:
    from src.s1_x4.algorithm_api.compiler import compile_observation, compile_static_context
    from src.s1_x4.renderer import render_x4_step
    from src.s1_x4.state_machine import DynamicEpisodeState

    episode = _episode(tmp_path, "X4")
    state = DynamicEpisodeState(episode)
    context = state.prepare_current_step()
    observation = compile_observation(context)
    static = compile_static_context(episode)
    public = json.dumps(
        {"static": static.to_public_dict(), "observation": observation.to_public_dict()},
        ensure_ascii=False,
    )
    rendered = render_x4_step(episode, context, "llm")
    assert all(key not in public for key in ("candidate_paths", "candidate_actions", "path_rank"))
    assert all(key not in rendered for key in ("候选路径", "候选动作", "path_rank"))


def test_example_algorithms_do_not_read_private_scientific_files() -> None:
    source = Path(__file__).resolve().parents[1] / "examples" / "s1_x4_algorithm_examples.py"
    text = source.read_text(encoding="utf-8")
    for forbidden in ("internal/private", "reference_output", "root_case.json"):
        assert forbidden not in text

