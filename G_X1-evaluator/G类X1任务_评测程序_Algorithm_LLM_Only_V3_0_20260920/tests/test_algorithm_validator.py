import json


def test_algorithm_validator_uses_canonical_validator(tmp_path, monkeypatch):
    from trial.validate_algorithm_outputs import validate_algorithm_outputs

    producer = tmp_path / "producer"
    package = producer / "gx1"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "validators.py").write_text(
        "def validate_dut_output(root, raw):\n"
        "    import json\n"
        "    return {'valid': json.loads(raw) == root['answer'], 'reason': 'CANONICAL'}\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "dataset"
    case_dir = dataset / "cases" / "G2" / "G2_000001"
    case_dir.mkdir(parents=True)
    root = {"case_id": "G2_000001", "task_type": "G2", "answer": {"is_valid": True, "error_type": None}}
    (case_dir / "root_case.json").write_text(json.dumps(root), encoding="utf-8")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "G2_000001.json").write_text(json.dumps(root["answer"]), encoding="utf-8")

    result = validate_algorithm_outputs(producer, dataset, outputs, tmp_path / "results")
    assert result["case_count"] == 1
    assert result["validator_pass"] == 1
    assert result["accuracy"] == 1.0
