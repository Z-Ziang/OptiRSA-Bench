from pathlib import Path

from gx1.contracts import BASE_SYSTEM, system_prompt, contract_bundle


def test_static_contract_files_match_runtime_contracts(project_root):
    for task in ["G1", "G2", "G3", "X1"]:
        llm = (project_root / "contracts" / task / "system_prompt_llm.txt").read_text(encoding="utf-8").rstrip("\n")
        assert llm == system_prompt(task)


def test_contract_bundle_is_llm_only():
    for task in ["G1", "G2", "G3", "X1"]:
        assert contract_bundle(task) == {
            "task_type": task,
            "llm_system_prompt": BASE_SYSTEM[task],
        }
