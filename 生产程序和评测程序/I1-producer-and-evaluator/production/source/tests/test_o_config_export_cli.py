import json
from pathlib import Path
import subprocess, sys

import pytest

from src.case_core.config import OFamilyConfigurationError, load_o_family_config
from src.case_core.exporter import export_dataset
from src.case_core.dataset_validator import verify_dataset
from src.tasks.o1.producer import build_o1_case
from tests.o_family_test_utils import toy_env


pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")

def _config(path: Path, *, k=3):
    data={
      "schema_version":"O_FAMILY_PRODUCTION_CONFIG_V1_0",
      "profile":"FORMAL","seed":20260908,
      "tasks":{
        "O1":{"enabled":True,"case_count":1,"request_count_values":[2],"fixed_path_rank_values":[1],"selection":"PREFIX","max_complete_solutions":1000},
        "O2-S":{"enabled":True,"case_count":1,"candidate_k_values":[k],"selection":"PREFIX","max_complete_solutions":1000},
        "O2-C":{"enabled":True,"case_count":1,"request_count_values":[2],"candidate_k_values":[k],"selection":"PREFIX","max_complete_solutions":1000}
      },
      "execution":{"allow_shortfall":False,"resume":False}
    }
    path.write_text(json.dumps(data),encoding='utf-8')
    return path


def test_formal_config_locks_candidate_k_and_request_ranges(tmp_path):
    cfg=load_o_family_config(_config(tmp_path/'ok.json'))
    assert cfg.o2s.candidate_k_values == (3,)
    bad=_config(tmp_path/'bad.json',k=1)
    with pytest.raises(OFamilyConfigurationError, match='candidate_k'):
        load_o_family_config(bad)


def test_exporter_writes_standard_dataset_and_verifier_replays_reference(tmp_path):
    bundle=build_o1_case(toy_env(slot_count=6,occupied0={2}),['r1','r2'],case_id='O1_000001')
    out=tmp_path/'dataset'
    export_dataset(out, {'O1':[bundle]}, contracts_root=Path('contracts'), production_metadata={'profile':'TEST'}, strict_frozen_interface=False)

    benchmark_path = out/'benchmark_case/O1/cases/case_000001.json'
    llm_eval_path = out/'evaluation_case/O1/llm/case_000001.json'
    internal_case = out/'internal/cases/O1/O1_000001'
    internal_private = out/'internal/private/O1/O1_000001'

    assert benchmark_path.is_file()
    assert llm_eval_path.is_file()
    assert (internal_case/'root_case.json').is_file()
    assert (internal_case/'algorithm_case.json').is_file()
    assert (internal_private/'private_truth.json').is_file()
    assert (internal_private/'reference_output.json').is_file()
    assert (out/'reports/REFERENCE_REPLAY_SUMMARY.json').is_file()
    assert not (out/'cases').exists()
    assert not (out/'private').exists()

    benchmark=json.loads(benchmark_path.read_text(encoding='utf-8'))
    llm_eval=json.loads(llm_eval_path.read_text(encoding='utf-8'))
    assert benchmark['case_id'] == 'O1_000001'
    assert benchmark['reference'] == bundle['reference_output']
    assert llm_eval == {'case_id':'O1_000001','prompt':benchmark['llm_prompt']}
    assert 'reference' not in llm_eval

    result=verify_dataset(out, contracts_root=Path('contracts'))
    assert result['valid'] is True
    assert result['case_count'] == 1
    assert result['reference_replay_pass_count'] == 1


def test_benchmark_help_exposes_production_commands():
    p=subprocess.run([sys.executable,'benchmark.py','--help'],text=True,capture_output=True,check=True)
    for name in ('doctor','derive-cases','produce','verify-dataset'):
        assert name in p.stdout


def test_formal_config_accepts_frozen_o_family_candidate_and_request_values(tmp_path):
    path=tmp_path/'full.json'
    data={
      "schema_version":"O_FAMILY_PRODUCTION_CONFIG_V1_0",
      "profile":"FORMAL","seed":20260908,
      "tasks":{
        "O1":{"enabled":True,"case_count":1,"request_count_values":[2,4,6,8,10,12,14,16],"fixed_path_rank_values":[1,2,3,4,5],"selection":"PREFIX","max_complete_solutions":1000},
        "O2-S":{"enabled":True,"case_count":1,"candidate_k_values":[2,3,5],"selection":"PREFIX","max_complete_solutions":1000},
        "O2-C":{"enabled":True,"case_count":1,"request_count_values":[2,4,6,8,9,10,11,12,14,16],"candidate_k_values":[2,3,5],"selection":"PREFIX","max_complete_solutions":1000}
      },
      "execution":{"allow_shortfall":True,"resume":False}
    }
    path.write_text(json.dumps(data),encoding='utf-8')
    cfg=load_o_family_config(path)
    assert cfg.o2s.candidate_k_values == (2,3,5)
    assert cfg.o2c.request_count_values == (2,4,6,8,9,10,11,12,14,16)


def test_config_schema_rejects_wrong_boolean_type(tmp_path):
    p=_config(tmp_path/'bad_type.json')
    data=json.loads(p.read_text())
    data['tasks']['O1']['enabled']='false'
    p.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(OFamilyConfigurationError, match='schema'):
        load_o_family_config(p)


def test_dataset_verifier_rejects_manifest_tampering(tmp_path):
    bundle=build_o1_case(toy_env(slot_count=6,occupied0={2}),['r1','r2'],case_id='O1_000001')
    out=tmp_path/'dataset_manifest'
    export_dataset(out, {'O1':[bundle]}, contracts_root=Path('contracts'), production_metadata={'profile':'TEST'}, strict_frozen_interface=False)
    manifest=json.loads((out/'RUN_MANIFEST.json').read_text())
    manifest['file_count'] += 1
    (out/'RUN_MANIFEST.json').write_text(json.dumps(manifest),encoding='utf-8')
    result=verify_dataset(out, contracts_root=Path('contracts'))
    assert result['valid'] is False
    assert any('RUN_MANIFEST' in err for err in result['errors'])


def test_doctor_checks_current_five_task_contracts_profile_and_tokenizer():
    p=subprocess.run([sys.executable,'benchmark_ox.py','doctor'],text=True,capture_output=True,check=True)
    result=json.loads(p.stdout)
    assert result['valid'] is True
    assert result['tasks'] == ['O1','O2-S','O2-C','X2','X3']
    assert result['contracts'] is True
    assert result['benchmark_schemas'] is True
    assert result['frozen_format'] is True
    assert result['five_task_profile'] is True
    assert result['generated_local_output_absent'] is True
    assert result['canonical_tokenizer']['available'] is True
    assert result['canonical_tokenizer']['encoding'] == 'o200k_base'
    assert result['canonical_tokenizer']['version'] == '0.14.0'
