from pathlib import Path
import pytest

from src.case_core.scenario_loader import load_public_environment


BASE_ENV = Path(__file__).resolve().parents[1] / 'tests/fixtures/public_environment_gabriel10'


def test_loader_indexes_real_baseline_environment():
    env = load_public_environment(BASE_ENV)
    assert 'top_gabriel_10_5' in env.directed_topologies
    assert 'rs_gabriel_10_5_kspff_medium_seed01' in env.resource_states
    assert len(env.requests) == 90
    assert len(env.derivations) == 90
    assert len(env.concurrent_sets) == 3
    req = env.requests['req_gabriel_10_5_000001']
    deriv = env.derivations[req['request_id']]
    assert deriv['candidate_paths'][0]['rank'] == 1
    assert len(deriv['candidate_paths']) == 5


def test_loader_rejects_missing_environment_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_public_environment(tmp_path / 'missing')
