import pytest
import json
from pathlib import Path

from src.o_family_pipeline import derive_o_family_dataset
from src.case_core.dataset_validator import verify_dataset


pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")

def _write_config(path: Path):
    data={
      "schema_version":"O_FAMILY_PRODUCTION_CONFIG_V1_0",
      "profile":"REPRESENTATIVE","seed":20260908,
      "tasks":{
        "O1":{"enabled":True,"case_count":1,"request_count_values":[2],"fixed_path_rank_values":[1],"selection":"PREFIX","max_complete_solutions":10000},
        "O2-S":{"enabled":True,"case_count":2,"candidate_k_values":[2,3],"selection":"LOW_ACTION","max_complete_solutions":10000},
        "O2-C":{"enabled":True,"case_count":1,"request_count_values":[2],"candidate_k_values":[2],"selection":"LOW_ACTION","max_complete_solutions":10000}
      },
      "execution":{"allow_shortfall":False,"resume":False}
    }
    path.write_text(json.dumps(data),encoding='utf-8')
    return path


def test_derive_pipeline_uses_existing_environment_and_exports_verified_dataset(tmp_path):
    env=Path('tests/fixtures/public_environment_gabriel10')
    config=_write_config(tmp_path/'representative.json')
    out=tmp_path/'out'
    result=derive_o_family_dataset(env,config,out)
    assert result['case_count'] == 4
    assert result['task_counts'] == {'O1':1,'O2-S':2,'O2-C':1}
    assert (out/'production_summary.json').is_file()
    check=verify_dataset(out)
    assert check['valid'] is True
    assert check['case_count'] == 4


def test_derive_pipeline_is_byte_deterministic(tmp_path):
    env=Path('tests/fixtures/public_environment_gabriel10')
    config=_write_config(tmp_path/'representative.json')
    out1=tmp_path/'out1'; out2=tmp_path/'out2'
    derive_o_family_dataset(env,config,out1)
    derive_o_family_dataset(env,config,out2)
    files1={p.relative_to(out1).as_posix():p.read_bytes() for p in out1.rglob('*') if p.is_file()}
    files2={p.relative_to(out2).as_posix():p.read_bytes() for p in out2.rglob('*') if p.is_file()}
    assert files1 == files2
