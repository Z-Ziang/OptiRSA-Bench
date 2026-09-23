import pytest
import json
import subprocess
import sys
from pathlib import Path

pytest.importorskip("tiktoken", reason="canonical token metrics require the pinned tiktoken dependency")

ROOT = Path(__file__).resolve().parents[1]


def _write_o_config(path: Path) -> Path:
    path.write_text(json.dumps({
        "schema_version":"O_FAMILY_PRODUCTION_CONFIG_V1_0",
        "profile":"REPRESENTATIVE","seed":20260908,
        "tasks":{
            "O1":{"enabled":True,"case_count":1,"request_count_values":[2],"fixed_path_rank_values":[1],"selection":"LOW_ACTION","max_complete_solutions":25000},
            "O2-S":{"enabled":True,"case_count":1,"candidate_k_values":[2],"selection":"LOW_ACTION","max_complete_solutions":5000},
            "O2-C":{"enabled":True,"case_count":1,"request_count_values":[2],"candidate_k_values":[2],"selection":"LOW_ACTION","max_complete_solutions":25000}
        },
        "execution":{"allow_shortfall":False,"resume":False}
    }), encoding="utf-8")
    return path


def _write_x_config(path: Path) -> Path:
    path.write_text(json.dumps({
        "schema_version":"X2X3_PRODUCTION_CONFIG_V1_0",
        "profile":"REPRESENTATIVE","seed":20260908,
        "tasks":{
            "X2":{"enabled":True,"case_count":1,"required_slots_values":[2],"selection":"LOW_ORACLE_COMPLEXITY","max_simple_paths":20000,"max_optimal_actions":50000},
            "X3":{"enabled":True,"case_count":1,"request_count_values":[2],"selection_values":["PREFIX"],"max_simple_paths_per_request":5000,"max_search_nodes":2000000,"max_complete_optimal_solutions":120000}
        },
        "execution":{"allow_shortfall":False}
    }), encoding="utf-8")
    return path


def test_integrated_derivation_reuses_one_environment_and_verifies_both_families(tmp_path):
    from src.integrated_o_x2x3_pipeline import derive_integrated_dataset, verify_integrated_dataset

    env = ROOT / "tests/fixtures/public_environment_gabriel10"
    out = tmp_path / "integrated"
    summary = derive_integrated_dataset(
        env,
        _write_o_config(tmp_path / "o.json"),
        _write_x_config(tmp_path / "x.json"),
        out,
    )
    assert summary["status"] == "PASS"
    assert summary["total_case_count"] == 5
    assert summary["task_counts"] == {"O1":1,"O2-S":1,"O2-C":1,"X2":1,"X3":1}
    check = verify_integrated_dataset(out)
    assert check["valid"] is True
    assert check["total_case_count"] == 5
    assert check["reference_replay_pass_count"] == 5
    # Current unified outputs must not contain the superseded probability identifier.
    legacy = "wufr_" + "demand_probabilities"
    for p in out.rglob("*"):
        if p.is_file():
            assert legacy not in p.read_text(encoding="utf-8", errors="ignore")


def test_integrated_cli_doctor_reports_all_five_tasks_ready():
    p = subprocess.run([sys.executable, str(ROOT / "benchmark_ox.py"), "doctor"], cwd=ROOT, text=True, capture_output=True)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["valid"] is True
    assert data["tasks"] == ["O1","O2-S","O2-C","X2","X3"]
