import json

from trial.prepare_unified_dataset import prepare_unified_dataset


def test_prepare_unified_dataset_joins_public_reference_to_private_root(tmp_path):
    public = tmp_path / "public"
    evidence = tmp_path / "evidence"
    output = tmp_path / "prepared"
    answers = {
        "G1": {"representation_type": "EDGE_LIST", "edge_list": []},
        "G2": {"is_valid": True, "error_type": None},
        "G3": {"shortest_paths": [], "has_shared_directed_link": False, "shared_link_ids": []},
        "X1": {"path_node_ids": [0, 1], "path_link_ids": [0], "hop_count": 1},
    }
    for task, answer in answers.items():
        case_id = f"{task}_000001"
        public_case = {"case_id": case_id, "llm_prompt": "public prompt", "reference": answer}
        public_dir = public / "benchmark_case" / task / "cases"
        public_dir.mkdir(parents=True)
        (public_dir / "case_000001.json").write_text(json.dumps(public_case), encoding="utf-8")
        evidence_case = evidence / task / case_id
        evidence_case.mkdir(parents=True)
        root = {"case_id": case_id, "task_type": task, "answer": answer}
        (evidence_case / "root_case.json").write_text(json.dumps(root), encoding="utf-8")
        (evidence_case / "actual_llm_request.json").write_text(json.dumps({"messages": []}), encoding="utf-8")

    manifest = prepare_unified_dataset(public, evidence, output)
    assert manifest["case_count"] == 4
