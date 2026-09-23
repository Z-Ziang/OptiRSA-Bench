from __future__ import annotations

import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _export(tmp_path: Path) -> Path:
    from src.s1_x4_pipeline import derive_s1x4_dataset

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "profile": "ALGORITHM_VALIDATOR",
                "case_count": 1,
                "allow_shortfall": False,
                "k_values": [3],
                "run_reference_panel": True,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "dataset"
    derive_s1x4_dataset(minimal_dynamic_environment(tmp_path, length=3), config, output)
    return output


def test_dataset_validator_requires_algorithm_launcher_views(tmp_path: Path) -> None:
    from src.s1_x4.dataset_validator import verify_s1x4_dataset

    output = _export(tmp_path)
    report = verify_s1x4_dataset(output)
    assert report["valid"] is True
    assert report["algorithm_view_pass_count"] == 2


def test_dataset_validator_rejects_private_and_future_fields_in_algorithm_launcher(tmp_path: Path) -> None:
    from src.s1_x4.dataset_validator import verify_s1x4_dataset

    output = _export(tmp_path)
    path = output / "evaluation_case" / "X4" / "algorithm" / "case_000001.json"
    launcher = json.loads(path.read_text(encoding="utf-8"))
    launcher["request_events"] = [{"request_id": "future_request"}]
    path.write_text(json.dumps(launcher), encoding="utf-8")
    report = verify_s1x4_dataset(output)
    assert report["valid"] is False
    assert any("algorithm" in error and "leakage" in error for error in report["errors"])
