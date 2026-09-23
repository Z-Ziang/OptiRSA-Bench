# V2.0.1 Maintenance Notes

## Scope

This maintenance patch is intentionally non-scientific. It does not change the frozen five-task Case-format TXT, model-visible prompts, task contracts, Reference/Truth semantics, validators, renderers, public-environment generation, or Oracle/search logic.

## Codex/Windows failures addressed

1. `tests/test_o_config_export_cli.py` no longer asserts the obsolete `cases/<TASK>/...` / `private/<TASK>/...` export layout; it verifies the frozen `benchmark_case`, `evaluation_case`, and `internal` layout.
2. The same test now validates the canonical five-task `benchmark_ox.py doctor` contract rather than stale O-family-only doctor fields such as `baseline_demo`.
3. `tests/test_package_release_utf8.py` writes the newline-sensitive nested manifest fixture as exact bytes, so the test checks archive byte preservation rather than host newline translation.

## Interface compatibility

The dataset interface identifier remains `NATURAL_LANGUAGE_DUAL_ENDPOINT_V2_0`; V2.0.1 is a maintenance release and does not introduce a V2.1 data contract.
