from __future__ import annotations

from pathlib import Path


def test_science_manifest_covers_frozen_runtime_and_detects_drift(tmp_path: Path):
    from trial_evaluation.v2.baseline import build_science_manifest, verify_science_manifest

    root = tmp_path / "source"
    for relative in (
        "src/s1_x4/state_machine.py",
        "src/s1_x4/validators.py",
        "src/s1_x4/reference_algorithms.py",
        "src/s1_x4/efm.py",
        "src/s1_x4/scenario_loader.py",
        "contracts/S1/llm_system_prompt.txt",
        "contracts/X4/llm_system_prompt.txt",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    before = build_science_manifest(root)
    assert len(before) == 7
    assert verify_science_manifest(before, root)["pass"] is True

    (root / "src/s1_x4/efm.py").write_text("changed", encoding="utf-8")
    report = verify_science_manifest(before, root)
    assert report["pass"] is False
    assert report["changed_files"] == ["src/s1_x4/efm.py"]
