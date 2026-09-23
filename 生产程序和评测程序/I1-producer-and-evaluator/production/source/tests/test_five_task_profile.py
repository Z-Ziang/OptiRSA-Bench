from pathlib import Path
import json


def test_five_task_profile_resolves_config_paths_relative_to_profile(tmp_path):
    from src.five_task_profile import load_five_task_profile
    (tmp_path/'o.json').write_text('{}',encoding='utf-8')
    (tmp_path/'x.json').write_text('{}',encoding='utf-8')
    p=tmp_path/'profile.json'
    p.write_text(json.dumps({
        'schema_version':'FIVE_TASK_PROFILE_V1_0',
        'o_family_config':'o.json',
        'x2x3_config':'x.json'
    }),encoding='utf-8')
    profile=load_five_task_profile(p)
    assert profile.o_family_config == (tmp_path/'o.json').resolve()
    assert profile.x2x3_config == (tmp_path/'x.json').resolve()


def test_shipped_small_batch_profile_targets_two_cases_per_task():
    from src.five_task_profile import load_five_task_profile
    root=Path(__file__).resolve().parents[1]
    profile=load_five_task_profile(root/'configs/five_task_small_batch.json')
    o=json.loads(profile.o_family_config.read_text(encoding='utf-8'))
    x=json.loads(profile.x2x3_config.read_text(encoding='utf-8'))
    assert {k:v['case_count'] for k,v in o['tasks'].items()} == {'O1':2,'O2-S':2,'O2-C':2}
    assert {k:v['case_count'] for k,v in x['tasks'].items()} == {'X2':2,'X3':2}
    assert o['execution']['allow_shortfall'] is False
    assert x['execution']['allow_shortfall'] is False
