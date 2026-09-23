from pathlib import Path
from tests.s1x4_test_utils import minimal_dynamic_environment

class FakeEncoding:
    def encode(self,text): return list(range(len(text.split())))

def test_dynamic_serialization_metrics_aggregate(monkeypatch):
    import src.s1_x4.serialization as m
    monkeypatch.setattr(m,'_runtime',lambda:(FakeEncoding(),'0.14.0'))
    r=m.compute_dynamic_serialization_metrics(['a b','c d e'])
    assert r['step_count']==2 and r['total_prompt_token_count']==5
    assert r['max_step_token_count']==3 and r['canonical_tokenizer']['encoding']=='o200k_base'

def test_run_episode_with_dut_writes_immutable_evaluation_artifact(tmp_path: Path, monkeypatch):
    import src.s1_x4.serialization as ser
    monkeypatch.setattr(ser,'_runtime',lambda:(FakeEncoding(),'0.14.0'))
    from src.s1_x4.scenario_loader import load_dynamic_public_environment, build_episode_definition
    from src.s1_x4.run import run_episode_with_dut
    idx=load_dynamic_public_environment(minimal_dynamic_environment(tmp_path,length=2))
    ep=build_episode_definition(idx,'bs_dynamic_demo','S1','S1_case_000001',k=3,pairing_id='pair')
    def dut(step):
        assert set(step) == {'case_id', 'prompt'}
        return {'decision':'REJECT','path_rank':None,'slot_start':None}
    out=tmp_path/'run'; result=run_episode_with_dut(ep,'llm',dut,out)
    assert result['summary']['step_count']==2
    assert (out/'trajectory.jsonl').is_file() and (out/'serialization_metrics.json').is_file()


def test_dynamic_serialization_rejects_noncanonical_tiktoken_version(monkeypatch):
    import src.s1_x4.serialization as m
    monkeypatch.setattr(m, '_runtime', lambda: (FakeEncoding(), '0.13.0'))
    import pytest
    with pytest.raises(RuntimeError, match='0.14.0'):
        m.compute_dynamic_serialization_metrics(['a b'])
