from pathlib import Path
import json

def test_seven_task_profile_resolves_relative_configs(tmp_path: Path):
    from src.seven_task_profile import load_seven_task_profile
    for n in ('o.json','x.json','s.json'): (tmp_path/n).write_text('{}',encoding='utf-8')
    p=tmp_path/'profile.json'; p.write_text(json.dumps({'schema_version':'SEVEN_TASK_PROFILE_V2_1_0','o_family_config':'o.json','x2x3_config':'x.json','s1x4_config':'s.json'}),encoding='utf-8')
    cfg=load_seven_task_profile(p)
    assert cfg.o_family_config==tmp_path/'o.json'
    assert cfg.x2x3_config==tmp_path/'x.json'
    assert cfg.s1x4_config==tmp_path/'s.json'


def test_seven_task_doctor_rejects_wrong_tiktoken_version(monkeypatch):
    import sys
    from types import SimpleNamespace
    import benchmark_all
    fake = SimpleNamespace(__version__='0.13.0', get_encoding=lambda name: object())
    monkeypatch.setitem(sys.modules, 'tiktoken', fake)
    result = benchmark_all._doctor(Path(__file__).resolve().parents[1])
    assert result['canonical_tokenizer']['available'] is False
    assert result['valid'] is False
    assert '0.14.0' in result['canonical_tokenizer']['error']
