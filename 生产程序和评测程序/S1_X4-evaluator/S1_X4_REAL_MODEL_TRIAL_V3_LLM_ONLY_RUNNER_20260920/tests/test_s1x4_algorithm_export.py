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
                "profile": "ALGORITHM_EXPORT",
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


def test_algorithm_launcher_is_exported_and_is_not_a_materialized_episode(tmp_path: Path) -> None:
    output = _export(tmp_path)
    for task in ("S1", "X4"):
        path = output / "evaluation_case" / task / "algorithm" / "case_000001.json"
        launcher = json.loads(path.read_text(encoding="utf-8"))
        assert launcher["interface_type"] == "DYNAMIC_ONLINE_ALGORITHM_EPISODE"
        assert launcher["future_requests_visible"] is False
        assert "request_events" not in launcher
        assert "initial_existing_connections" not in launcher
        assert "reference" not in launcher
        assert "difficulty_context" not in launcher
        assert "static_context" in launcher

    row = json.loads((output / "case_index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["algorithm_evaluation_path"] == "evaluation_case/S1/algorithm/case_000001.json"


def test_s1_and_x4_algorithm_launchers_have_public_static_connectivity_only(tmp_path: Path) -> None:
    output = _export(tmp_path)
    for task in ("S1", "X4"):
        launcher = json.loads(
            (output / "evaluation_case" / task / "algorithm" / "case_000001.json").read_text(encoding="utf-8")
        )
        static = launcher["static_context"]
        assert set(static) == {
            "schema_version",
            "case_id",
            "task_type",
            "topology_id",
            "node_ids",
            "directed_links",
            "slot_count",
        }
        assert "spectrum" not in static
