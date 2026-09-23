from __future__ import annotations

import hashlib
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


EXPECTED_PROMPT_HASHES = {
    "S1/llm_system_prompt.txt": "e0cbb0a844eef28d45c4c1d85c8bebdac1b8b6b7a196263b9f5f702c54cfa797",
    "X4/llm_system_prompt.txt": "8dbb48faa3a99f185fb9b58f2dba3d0e217459a00752ca52fc67d5ab47847afe",
}

LIFECYCLE = (
    "在每个业务请求到达时，环境首先释放所有已到达释放时刻的已有连接，"
    "然后向你提供当前网络状态并进行本步决策。"
)
PRIMARY = "首要目标是在整个动态决策序列中尽量减少被阻塞的业务请求，即尽量提高成功建立数量。"
SECONDARY = "次要目标是在不违背首要目标的基础上，尽量降低网络外部频谱碎片程度（External Fragmentation Metric，EFM）。"

RENDERER_TAILS = {
    ("S1", "llm"): "你的任务是根据当前网络资源状态，从上述可行动作中选择一个资源分配方案来完成业务请求的建立，并考虑本次资源分配对后续业务请求的长期影响，首要目标是在整个动态决策序列中尽量减少被阻塞的业务请求，即尽量提高成功建立数量。次要目标是在不违背首要目标的基础上，尽量降低网络外部频谱碎片程度（External Fragmentation Metric，EFM）。",
    ("X4", "llm"): "你的任务是根据当前网络资源状态，自行搜索一条可行有向路径，并为该路径分配满足请求需求的连续频谱槽位来完成业务请求的建立，同时考虑本次资源分配对后续业务请求的长期影响。首要目标是在整个动态决策序列中尽量减少被阻塞的业务请求，即尽量提高成功建立数量。次要目标是在不违背首要目标的基础上，尽量降低网络外部频谱碎片程度（External Fragmentation Metric，EFM）。",
}


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _prompt_text(task: str, endpoint: str) -> str:
    return (_root() / "contracts" / task / f"{endpoint}_system_prompt.txt").read_text(encoding="utf-8")


def test_llm_endpoint_prompts_are_byte_exact():
    for relative, expected in EXPECTED_PROMPT_HASHES.items():
        actual = hashlib.sha256((_root() / "contracts" / relative).read_bytes()).hexdigest()
        assert actual == expected, relative


def test_latest_public_lifecycle_and_objectives_are_present_in_all_endpoints():
    for relative in EXPECTED_PROMPT_HASHES:
        task, filename = relative.split("/", 1)
        endpoint = filename.removesuffix("_system_prompt.txt")
        text = _prompt_text(task, endpoint)
        assert LIFECYCLE in text, relative
        assert PRIMARY in text, relative
        assert SECONDARY in text, relative
        assert "若当前请求被 ACCEPT" in text, relative
        assert "holding_time 结束后释放" in text, relative
        assert "若输出 REJECT，本请求不会占用新的频谱资源" in text, relative
        assert "未来业务请求仍不会提前公开" in text, relative


def test_x4_public_contract_requires_simple_directed_path():
    text = _prompt_text("X4", "llm")
    assert "所选择的路径必须为简单有向路径（simple directed path）" in text
    assert "路径节点数组中不得出现重复节点" in text


def _episode_and_context(tmp_path, task: str):
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment
    from src.s1_x4.state_machine import DynamicEpisodeState

    index = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, length=2))
    episode = build_episode_definition(
        index,
        "bs_dynamic_demo",
        task,
        f"{task}_case_000001",
        k=3,
        pairing_id="pair_1",
    )
    state = DynamicEpisodeState(episode)
    return episode, state.prepare_current_step()


def test_renderer_task_tails_are_exact_for_llm_endpoint(tmp_path):
    from src.s1_x4.renderer import render_s1_step, render_x4_step

    for task in ("S1", "X4"):
        episode, context = _episode_and_context(tmp_path / task, task)
        if task == "S1":
            prompt = render_s1_step(episode, context, "llm")
        else:
            prompt = render_x4_step(episode, context, "llm")
        assert prompt.splitlines()[-1] == RENDERER_TAILS[(task, "llm")]


def test_x4_validator_rejects_repeated_node_path(tmp_path):
    from src.s1_x4.validators import validate_x4_response

    _, context = _episode_and_context(tmp_path / "validator", "X4")
    result = validate_x4_response(
        {
            "decision": "ACCEPT",
            "path_node_ids": [0, 1, 3, 1, 3],
            "path_link_ids": [0, 2, 3, 2],
            "slot_start": 0,
        },
        context,
    )
    assert result["valid"] is False
    assert result["error"] == "path is not simple"
