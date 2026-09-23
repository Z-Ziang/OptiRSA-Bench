import pytest
import json, subprocess, sys
from pathlib import Path

from tests.o_family_test_utils import toy_env
from src.tasks.x2.producer import build_x2_case
from src.tasks.x3.producer import build_x3_case
from src.x2x3_config import load_x2x3_config
from src.x2x3_exporter import export_x2x3_dataset
from src.x2x3_dataset_validator import verify_x2x3_dataset

pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")

ROOT=Path(__file__).resolve().parents[1]


def test_representative_config_loads_frozen_ranges():
    cfg=load_x2x3_config(ROOT/'configs/x2x3_representative.json')
    assert cfg.x2.required_slots_values == (2,3,5,9)
    assert set(cfg.x3.request_count_values).issubset({2,4,8,12})
    assert cfg.x3.selection_values == ('PREFIX','HIGH_CONFLICT_X3')


def test_export_and_verify_reference_replay(tmp_path):
    env=toy_env(slot_count=5)
    x2=build_x2_case(env,'r1',case_id='X2_000001',required_slots=2,max_simple_paths=100,max_optimal_actions=1000)
    x3=build_x3_case(env,['r1','r2'],case_id='X3_000001',max_simple_paths_per_request=100,max_complete_optimal_solutions=10000)
    out=tmp_path/'dataset'
    summary=export_x2x3_dataset(out,{'X2':[x2],'X3':[x3]},contracts_root=ROOT/'contracts',production_metadata={'test':True}, strict_frozen_interface=False)
    assert summary['case_count']==2
    check=verify_x2x3_dataset(out)
    assert check['valid'], check['errors']
    assert check['reference_replay_pass_count']==2


def test_x2x3_cli_doctor():
    p=subprocess.run([sys.executable,str(ROOT/'benchmark_x2x3.py'),'doctor'],cwd=ROOT,text=True,capture_output=True)
    assert p.returncode==0, p.stdout+p.stderr
    assert json.loads(p.stdout)['valid'] is True
