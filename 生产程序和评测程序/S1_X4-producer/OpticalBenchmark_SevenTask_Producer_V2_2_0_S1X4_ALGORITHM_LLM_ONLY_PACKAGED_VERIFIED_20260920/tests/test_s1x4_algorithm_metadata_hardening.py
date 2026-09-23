from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

from tests.s1x4_test_utils import minimal_dynamic_environment


ALLOWED_LAUNCHER_KEYS = {
    "schema_version",
    "case_id",
    "task_type",
    "interface_type",
    "future_requests_visible",
    "static_context",
    "output_schema_ref",
    "runtime_contract_ref",
    "opaque_case_handle",
}
FORBIDDEN_KEYS = {
    "canonical_episode_ref",
    "episode_length",
    "horizon",
    "total_steps",
    "sequence_length",
    "resource_state_id",
    "pairing_id",
    "request_sequence_id",
    "initial_existing_connection_set_id",
    "difficulty_context",
    "seed",
    "load_band",
    "arrival_rate_mode",
    "lambda_ratio",
    "reference",
    "oracle",
    "private_truth",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"\b(?:light|medium|high|challenge)(?:[_ -]?(?:pressure|load))?\b", re.I),
    re.compile(r"\bseed(?:[_-]?\d+)?\b", re.I),
    re.compile(r"\b(?:ksp|ff|bf|kme|sw)[_-]?(?:ff|bf|sp|efm)\b", re.I),
    re.compile(r"arrival[_ -]?rate", re.I),
    re.compile(r"lambda[_ -]?ratio", re.I),
    re.compile(r"resource[_ -]?state", re.I),
    re.compile(r"request[_ -]?sequence", re.I),
)


def _export(tmp_path: Path) -> Path:
    from src.s1_x4_pipeline import derive_s1x4_dataset

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "profile": "METADATA_HARDENING_RED",
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


def _launcher(output: Path, task: str) -> tuple[Path, dict]:
    path = output / "evaluation_case" / task / "algorithm" / "case_000001.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_walk_keys(child))
    return keys


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _walk_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _walk_strings(child)]
    return []


def _resolver_module():
    spec = importlib.util.find_spec("src.s1_x4.algorithm_api.resolver")
    assert spec is not None, "evaluator-private algorithm resolver is required"
    return importlib.import_module("src.s1_x4.algorithm_api.resolver")


def _runner_module():
    module = importlib.import_module("src.s1_x4.algorithm_api.runner")
    assert hasattr(module, "run_algorithm_evaluation"), "official public launcher runner is required"
    return module


def test_algorithm_launcher_is_v11_and_contains_only_public_fields(tmp_path: Path) -> None:
    output = _export(tmp_path)
    for task in ("S1", "X4"):
        _, launcher = _launcher(output, task)
        assert set(launcher) == ALLOWED_LAUNCHER_KEYS
        assert launcher["schema_version"] == "S1_X4_ALGORITHM_EVALUATION_CASE_V1_1"
        assert "canonical_episode_ref" not in launcher
        assert not (_walk_keys(launcher) & FORBIDDEN_KEYS)
        values = _walk_strings(launcher)
        assert not [value for value in values if any(pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS)]


def test_algorithm_launcher_schema_is_v11_and_rejects_legacy_reference(tmp_path: Path) -> None:
    output = _export(tmp_path)
    for task in ("S1", "X4"):
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts" / task / "schemas" / "algorithm_evaluation_case.schema.json")
            .read_text(encoding="utf-8")
        )
        assert schema["properties"]["schema_version"]["const"] == "S1_X4_ALGORITHM_EVALUATION_CASE_V1_1"
        assert "canonical_episode_ref" not in schema["properties"]
        assert set(schema["properties"]) == ALLOWED_LAUNCHER_KEYS
        _, launcher = _launcher(output, task)
        launcher["canonical_episode_ref"] = {"episode_length": 3}
        from jsonschema import Draft202012Validator

        assert list(Draft202012Validator(schema).iter_errors(launcher))


def test_evaluator_private_registry_resolves_opaque_handle_and_fail_closes(tmp_path: Path) -> None:
    output = _export(tmp_path)
    resolver = _resolver_module()
    launcher_path, launcher = _launcher(output, "S1")
    resolved = resolver.resolve_algorithm_launcher(launcher_path, output, expected_task="S1")
    assert resolved.case_id == launcher["case_id"]
    assert resolved.task_type == "S1"
    assert resolved.episode["case_id"] == launcher["case_id"]
    assert resolved.entry["root_case_sha256"] == hashlib.sha256(resolved.root_case_path.read_bytes()).hexdigest()

    registry_path = output / "internal" / "algorithm_episode_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert isinstance(registry.get("entries"), list)
    assert len(registry["entries"]) == 2

    bad_hash = tmp_path / "bad_hash"
    shutil.copytree(output, bad_hash)
    bad_registry_path = bad_hash / "internal" / "algorithm_episode_registry.json"
    bad_registry = json.loads(bad_registry_path.read_text(encoding="utf-8"))
    bad_registry["entries"][0]["root_case_sha256"] = "0" * 64
    bad_registry_path.write_text(json.dumps(bad_registry), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        resolver.resolve_algorithm_launcher(bad_hash / "evaluation_case/S1/algorithm/case_000001.json", bad_hash)

    bad_handle = tmp_path / "bad_handle"
    shutil.copytree(output, bad_handle)
    bad_launcher_path, bad_launcher = _launcher(bad_handle, "S1")
    bad_launcher["opaque_case_handle"] = "algorithm_episode:not_registered"
    bad_launcher_path.write_text(json.dumps(bad_launcher), encoding="utf-8")
    with pytest.raises(ValueError, match="handle"):
        resolver.resolve_algorithm_launcher(bad_launcher_path, bad_handle)

    bad_path = tmp_path / "bad_path"
    shutil.copytree(output, bad_path)
    bad_registry_path = bad_path / "internal" / "algorithm_episode_registry.json"
    bad_registry = json.loads(bad_registry_path.read_text(encoding="utf-8"))
    bad_registry["entries"][0]["root_case_path"] = "../private_truth.json"
    bad_registry_path.write_text(json.dumps(bad_registry), encoding="utf-8")
    with pytest.raises(ValueError, match="path"):
        resolver.resolve_algorithm_launcher(
            bad_path / "evaluation_case/S1/algorithm/case_000001.json", bad_path, expected_task="S1"
        )

    bad_duplicate = tmp_path / "bad_duplicate"
    shutil.copytree(output, bad_duplicate)
    bad_registry_path = bad_duplicate / "internal" / "algorithm_episode_registry.json"
    bad_registry = json.loads(bad_registry_path.read_text(encoding="utf-8"))
    bad_registry["entries"].append(dict(bad_registry["entries"][0]))
    bad_registry_path.write_text(json.dumps(bad_registry), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate handle"):
        resolver.resolve_algorithm_launcher(
            bad_duplicate / "evaluation_case/S1/algorithm/case_000001.json", bad_duplicate
        )

    with pytest.raises(ValueError, match="wrong task"):
        resolver.resolve_algorithm_launcher(launcher_path, output, expected_task="X4")

    bad_missing = tmp_path / "bad_missing"
    shutil.copytree(output, bad_missing)
    missing_root = bad_missing / "internal/cases/S1/S1_case_000001/root_case.json"
    missing_root.unlink()
    with pytest.raises(ValueError, match="does not exist"):
        resolver.resolve_algorithm_launcher(
            bad_missing / "evaluation_case/S1/algorithm/case_000001.json", bad_missing
        )


def test_official_public_runner_accepts_launcher_and_callback_only_sees_public_objects(tmp_path: Path) -> None:
    output = _export(tmp_path)
    runner = _runner_module()
    from examples.s1_x4_algorithm_examples import FirstFeasibleS1

    seen: list[tuple[object, object]] = []

    class Probe:
        def solve(self, static_context, current_observation):
            seen.append((static_context, current_observation))
            return FirstFeasibleS1().solve(static_context, current_observation)

    launcher_path, launcher = _launcher(output, "S1")
    result = runner.run_algorithm_evaluation(
        launcher_path,
        output,
        Probe(),
        output_dir=tmp_path / "algorithm_run",
    )
    assert result["summary"]["case_id"] == launcher["case_id"]
    assert result["summary"]["step_count"] == 3
    assert len(seen) == 3
    for static_context, observation in seen:
        assert static_context.case_id == launcher["case_id"]
        assert observation.case_id == launcher["case_id"]
        assert not hasattr(static_context, "episode")
        assert not hasattr(observation, "root_case")


def test_official_example_uses_public_launcher_not_direct_canonical_root(tmp_path: Path) -> None:
    example = (Path(__file__).resolve().parents[1] / "examples" / "run_s1_x4_algorithm.py").read_text(encoding="utf-8")
    assert "run_algorithm_evaluation" in example
    assert "--launcher" in example
    assert "--dataset-root" in example
    assert "--episode" not in example
    assert "run_algorithm_episode" not in example
