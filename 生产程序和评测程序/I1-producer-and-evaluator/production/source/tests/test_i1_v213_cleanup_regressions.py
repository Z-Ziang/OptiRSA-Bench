from random import Random

from src.i1.renderer import render_base_prompt
from src.i1.truth import build_dynamic_answer
from src.multi_topology.requests import generate_dynamic_sequence, generate_requests
from src.production.one_topology import _dynamic_sequence


def test_request_id_codec_keeps_full_topology_id_for_static_requests():
    rows = generate_requests("topologybench_netrail", [(0, 1)], [2], Random(7))
    assert rows[0]["request_id"] == "req_topologybench_netrail_000001"


def test_request_id_codec_keeps_full_topology_id_for_dynamic_requests():
    rows = generate_dynamic_sequence(
        "topologybench_netrail", node_count=7, reference_time=0.0,
        arrival_rate=1.0, holding_rate=1.0, required_slots=[2], rng=Random(7), length=1,
    )
    assert rows["request_sequence_id"] == "seq_topologybench_netrail"
    assert rows["dynamic_request_events"][0]["request_id"] == "dynreq_topologybench_netrail_0001"


def test_one_topology_dynamic_codec_keeps_full_topology_id():
    rows = _dynamic_sequence(
        topology_id="topologybench_netrail", sequence_index=2, node_count=7,
        reference_time=0.0, arrival_rate=1.0, holding_rate=1.0,
        required_slots=(2,), seed=7, length=1,
    )
    assert rows["request_sequence_id"] == "seq_topologybench_netrail_002"
    assert rows["dynamic_request_events"][0]["request_id"] == "dynreq_topologybench_netrail_002_000001"


def test_dynamic_two_objective_prompt_states_priority_explicitly():
    answer = build_dynamic_answer(
        {
            "request_id": "dynreq_topologybench_netrail_002_000001",
            "source_node_id": 1,
            "destination_node_id": 6,
            "required_slots": 2,
            "arrival_time": 1.25,
            "holding_time": 2.5,
        },
        ["MAX-ACCEPTED-REQUESTS", "MIN-EXTERNAL-FRAGMENTATION"],
    )
    prompt = render_base_prompt(answer)
    assert "首要目标" in prompt
    assert "在此前提下" in prompt
    assert prompt.index("首要目标") < prompt.index("在此前提下")
    assert prompt.index("成功建立的业务请求数量") < prompt.index("网络外部频谱碎片")
