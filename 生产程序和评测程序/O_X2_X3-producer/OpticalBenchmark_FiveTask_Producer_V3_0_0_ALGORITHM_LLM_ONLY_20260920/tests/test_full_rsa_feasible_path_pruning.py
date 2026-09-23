from tests.o_family_test_utils import toy_env


def _canonical(actions):
    return sorted(
        (
            tuple(action["path_node_ids"]),
            tuple(action["path_link_ids"]),
            int(action["hop_count"]),
            int(action["slot_start"]),
            int(action["required_slots"]),
            int(action["delta_tso_contribution"]),
        )
        for action in actions
    )


def test_spectrum_pruned_action_enumeration_is_semantically_equivalent():
    from src.case_core.full_rsa import (
        enumerate_actions_for_request,
        enumerate_feasible_actions_for_request,
        spectrum_dict,
    )

    env = toy_env(slot_count=5)
    request = env.requests["r1"]
    directed_links = next(iter(env.directed_topologies.values()))["directed_link_records"]
    spectrum = spectrum_dict(next(iter(env.resource_states.values())))

    old_actions, old_path_count = enumerate_actions_for_request(
        request, directed_links, spectrum, max_paths=100
    )
    new_actions, new_path_count = enumerate_feasible_actions_for_request(
        request, directed_links, spectrum, max_paths=100
    )

    assert _canonical(new_actions) == _canonical(old_actions)
    assert new_path_count <= old_path_count

