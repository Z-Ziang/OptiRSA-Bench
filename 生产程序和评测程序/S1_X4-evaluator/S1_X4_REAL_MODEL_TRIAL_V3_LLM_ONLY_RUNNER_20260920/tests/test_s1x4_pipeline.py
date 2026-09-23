from pathlib import Path
import json
from tests.s1x4_test_utils import minimal_dynamic_environment


def test_s1x4_dataset_export_and_blind_views(tmp_path, monkeypatch):
    import src.s1_x4.exporter as ex
    monkeypatch.setattr(ex,'compute_serialization_metrics',lambda l:{'llm_prompt_char_count':len(l),'canonical_tokenizer':{'backend':'TEST','encoding':'TEST','package_version':'0'}})
    from src.s1_x4_pipeline import derive_s1x4_dataset
    env=minimal_dynamic_environment(tmp_path,length=3)
    cfg=tmp_path/'cfg.json'; cfg.write_text(json.dumps({'profile':'TEST','case_count':1,'allow_shortfall':False,'k_values':[3],'run_reference_panel':True}),encoding='utf-8')
    out=tmp_path/'dataset'; summary=derive_s1x4_dataset(env,cfg,out)
    assert summary['task_counts']=={'S1':1,'X4':1}
    for task in ('S1','X4'):
        ev=json.loads((out/'evaluation_case'/task/'llm/case_000001.json').read_text(encoding='utf-8'))
        assert set(ev)=={'case_id','prompt'}
        root=json.loads((out/'internal'/'cases'/task/f'{task}_case_000001'/'root_case.json').read_text(encoding='utf-8'))
        assert len(root['request_events'])==3
    from src.s1_x4.dataset_validator import verify_s1x4_dataset
    assert verify_s1x4_dataset(out)['valid']
