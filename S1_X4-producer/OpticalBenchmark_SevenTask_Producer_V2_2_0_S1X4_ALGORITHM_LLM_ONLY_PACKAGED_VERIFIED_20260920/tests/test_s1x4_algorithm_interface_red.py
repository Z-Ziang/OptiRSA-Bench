from __future__ import annotations

import json
from pathlib import Path

from tests.s1x4_test_utils import minimal_dynamic_environment


def _derive_one_case(tmp_path: Path) -> Path:
    from src.s1_x4_pipeline import derive_s1x4_dataset

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "profile": "RED_ALGORITHM_INTERFACE",
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


def test_formal_algorithm_evaluation_views_are_exported_for_s1_and_x4(tmp_path: Path) -> None:
    output = _derive_one_case(tmp_path)

    for task in ("S1", "X4"):
        path = output / "evaluation_case" / task / "algorithm" / "case_000001.json"
        assert path.is_file(), f"missing formal Algorithm evaluation view: {path}"


def test_algorithm_environment_module_is_present() -> None:
    from src.s1_x4.algorithm_api.environment import AlgorithmEpisodeEnvironment

    assert AlgorithmEpisodeEnvironment is not None
