from __future__ import annotations

import math
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
        pairing_id="pair_reference_v2",
    )


def test_reference_panel_uses_the_official_algorithm_environment(monkeypatch, tmp_path: Path) -> None:
    import src.s1_x4.reference_algorithms as reference

    observed = {"count": 0}
    original = reference.AlgorithmEpisodeEnvironment

    class SpyEnvironment(original):
        def __init__(self, *args, **kwargs):
            observed["count"] += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(reference, "AlgorithmEpisodeEnvironment", SpyEnvironment)
    panel = reference.run_reference_panel(_episode(tmp_path, "S1"))
    assert observed["count"] == 6
    assert [row["policy_name"] for row in panel["policy_results"]] == [
        "KSP-FF",
        "KSP-BF",
        "FF-KSP",
        "BF-KSP",
        "KME-FF",
        "KSP-EFM",
    ]


def test_reference_x4_panel_keeps_candidate_oracle_inside_reference_adapter(tmp_path: Path) -> None:
    import src.s1_x4.reference_algorithms as reference

    panel = reference.run_reference_panel(_episode(tmp_path, "X4"))
    assert [row["policy_name"] for row in panel["policy_results"]] == [
        "KSP-FF",
        "KSP-BF",
        "FF-KSP",
        "BF-KSP",
        "KME-FF",
        "KSP-EFM",
        "SW-SP",
        "SW-EFM",
    ]
    assert all(row["episode_length"] == 3 for row in panel["policy_results"])


def test_reference_parallel_panel_matches_serial_panel(tmp_path: Path) -> None:
    import src.s1_x4.reference_algorithms as reference

    episode = _episode(tmp_path, "X4")
    serial = reference.run_reference_panel(episode)
    parallel = reference.run_reference_panel(episode, parallel=True, max_workers=2)
    assert parallel == serial


def test_reference_efm_candidate_cache_is_numerically_equivalent(tmp_path: Path) -> None:
    from src.s1_x4.reference_algorithms import _base_efm, _simulate_efm
    from src.s1_x4.state_machine import DynamicEpisodeState

    episode = _episode(tmp_path, "S1")
    context = DynamicEpisodeState(episode).prepare_current_step()
    spectrum = context["spectrum_by_link"]
    actions = context["candidate_actions"][:20]
    required = int(context["request"]["required_slots"])
    base = _base_efm(spectrum)
    for action in actions:
        old = _simulate_efm(spectrum, action, required)
        fast = _simulate_efm(spectrum, action, required, base)
        assert (old is None and fast is None) or math.isclose(old, fast, rel_tol=1e-12, abs_tol=1e-12)


def test_x4_shortest_window_tie_break_is_exact_without_path_enumeration(tmp_path: Path, monkeypatch) -> None:
    """SW policies keep the legacy shortest-hop/link-id ordering exactly."""

    import networkx as nx
    import src.s1_x4.reference_algorithms as reference
    from src.s1_x4.scenario_loader import build_episode_definition, load_dynamic_public_environment
    from src.s1_x4.state_machine import DynamicEpisodeState

    index = load_dynamic_public_environment(minimal_dynamic_environment(tmp_path, slot_count=320, length=1))
    episode = build_episode_definition(index, "bs_dynamic_demo", "X4", "X4_case_window", k=None, pairing_id="pair_window")
    context = DynamicEpisodeState(episode).prepare_current_step()

    def legacy_window_shortest(ctx, required):
        links=ctx['directed_links']; spectrum=ctx['spectrum_by_link']; req=ctx['request']; slot_count=ctx['slot_count']; out=[]
        linkmap={(int(r['source_node_id']),int(r['destination_node_id'])):int(r['link_id']) for r in links}
        for start in range(slot_count-required+1):
            edges=[]
            for row in links:
                lid=int(row['link_id'])
                if all(spectrum[lid][s]==1 for s in range(start,start+required)):
                    edges.append((int(row['source_node_id']),int(row['destination_node_id'])))
            graph=nx.DiGraph(); graph.add_edges_from(edges)
            try:
                distance=nx.shortest_path_length(graph,int(req['source_node_id']),int(req['destination_node_id']))
            except (nx.NetworkXNoPath,nx.NodeNotFound):
                continue
            candidates=[]
            for nodes in nx.all_simple_paths(graph,int(req['source_node_id']),int(req['destination_node_id']),cutoff=distance):
                if len(nodes)-1!=distance:
                    continue
                lids=tuple(linkmap[(u,v)] for u,v in zip(nodes,nodes[1:]))
                candidates.append((lids,tuple(nodes)))
            if candidates:
                lids,nodes=min(candidates)
                out.append({'path_rank':0,'path_link_ids':list(lids),'path_node_ids':list(nodes),'slot_start':start,'hop_count':len(lids)})
        return out

    expected = legacy_window_shortest(context, int(context['request']['required_slots']))
    actual = reference._window_shortest(context, int(context['request']['required_slots']))
    assert actual == expected

    def fail_if_called(*args, **kwargs):
        raise AssertionError("SW reference must not enumerate all simple paths")

    monkeypatch.setattr(reference.nx, "all_simple_paths", fail_if_called)
    assert reference._window_shortest(context, int(context['request']['required_slots'])) == expected
