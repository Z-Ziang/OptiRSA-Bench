# GX1 V5 Formal Evaluation Protocol — Frozen English Track

Protocol ID: `GX1_V5_FORMAL_ENGLISH_V1`

This release freezes the evaluator-side protocol for G1/G2/G3/X1. It does **not** duplicate the 243 MB V3.1 dataset release. Future formal runs consume the separately verified source release `GX1_V3_1_BILINGUAL_FULLPOOL_FINAL_20261002.zip` (SHA256 `4f4e875efc78c27c3c1d24ebf43978cde49a763f09c1c55274d651797a385812`).


## R1 engineering revision (2026-10-03)

This package is the R1 execution-safety revision of the same scientific protocol `GX1_V5_FORMAL_ENGLISH_V1`. Model-visible prompts, Case/Truth data, Validator semantics, cohort membership, numeric contract, output mode, metrics and authoritative-attempt policy are unchanged. R1 fixes three execution/reproducibility blockers found during the first Windows P0/P1 handoff: (1) it bundles the real historical `04_CASE_INDEX_400.csv` used to derive the 100-topology exposed cohort; (2) it makes the SSE partial-event regression test tolerant of Windows process-spawn overhead without changing the formal `stream=false` run controls; and (3) `--resume` now scans persisted per-attempt raw responses and recovers the earliest complete response locally before any Case API call. A persisted complete response is therefore never re-requested after a crash window.

## Frozen evaluation scope

All 563 canonical topologies and all 8619 V3.1 English Cases remain in the final evaluation/discussion scope:

- `CALIBRATION_EXPOSED`: 100 topologies / 1476 Cases
- `FORMAL_UNSEEN_HELDOUT`: 463 topologies / 7143 Cases
- `ALL_POOL`: 563 topologies / 8619 Cases

The recommended operational run is one `ALL_POOL` run. The final authoritative ledger can then be joined with `manifests/topology_cohort_manifest.csv` to report the all-pool aggregate and the exposed/unseen slices from exactly the same model condition. `ALL_POOL` must never be described as fully held-out.

## What the model sees

Every formal Case uses exactly the two messages stored by V3.1 in `actual_llm_request.json`:

1. `system`: frozen English task system prompt
2. `user`: frozen English Case prompt

Formal V5 adds no third message, no G1 shape hint and no truth/reference/oracle information. The common provider output control is `response_format={"type":"json_object"}`.

## Reference controls

The frozen common controls are: temperature 0, max_tokens 16384, stream false, request timeout 180 s, hard request timeout 210 s, Case timeout 720 s, two transport retries after the initial attempt (maximum three transport attempts), fixed 10 s retry backoff, zero retry jitter and reference concurrency 1.

Reasoning mode is an explicit run condition: `native`, `enabled` or `disabled`. Results from different reasoning modes are separate conditions. Exact provider-specific extra-body fields are hashed into `RUN_MANIFEST.json`.

## Numeric contract

For weighted G3/X1 evaluation, V5 uses the six-significant-digit `length_km` values visible to the model. The complete audit covers 2813 weighted shortest-path queries. Three G3 queries gain extra public-optimal ties after public rounding; zero canonical reference paths cease to be public-optimal. `G3_000260` is marked `PUBLIC_AMBIGUOUS` for shared/disjoint subgroup analysis because different equally valid public-optimal path pairs can produce different shared-link status. Primary V5 scoring remains path-consistent.

## Run identity and Case-set guard

A formal `RUN_MANIFEST.json` binds the requested model, provider, endpoint label, reasoning mode, extra-body hash, exact selected Case identities/hashes, evaluator/validator hashes, dataset release, prompt hashes and static config. Each cohort config also freezes the expected Case count and SHA256 of its sorted Case-ID set. A formal run aborts before API evaluation if the selected Case set does not match the named cohort.

Never edit the frozen config templates in place. Copy the desired template to a run-specific config and replace at least:

- `provider`: e.g. `BUPT_MyAI`
- `api_base_label`: a stable non-secret endpoint label, e.g. `https://myai.bupt.edu.cn/llm-gw/v1`
- `reasoning_mode` if the run deliberately uses `native`, `enabled` or `disabled`

Provider controls for reasoning belong in `GX1_EXTRA_BODY_JSON` / the runner's extra body and are hashed. API keys belong only in environment variables.

## Recommended ALL_POOL invocation

After extracting the V3.1 release and this V5 release, install runtime dependencies and prepare a copied run config. Then set the provider-specific environment variables expected by the runner/config and run:

```powershell
python evaluator_v5\trial\run_openai_compatible_trial.py `
  --producer-dir validator_v5 `
  --dataset-dir <V31_ROOT>\02_EN_INTERNAL_DATASET `
  --runner-config <RUN_SPECIFIC_ALL_POOL_CONFIG.json> `
  --results-dir <NEW_EMPTY_RESULTS_DIR> `
  --case-id-file manifests\all_pool_cases.csv
```

Use `--resume` only against the same results directory and the identical protocol fingerprint. A mismatched or unmanifested non-empty directory is rejected.

The internal V3.1 dataset is used because the evaluator needs scientific roots for local scoring. Model-facing payload construction reads only the frozen `actual_llm_request.json`; the payload boundary audit forbids structured truth/reference/oracle fields.

## Scoring

For each scheduled Case, the first complete scientific response is authoritative. Infrastructure-only attempts may be retried; later complete answers can never replace the first complete answer based on score.

Report:

- completion rate = complete responses / scheduled Cases
- scientific accuracy = Validator PASS / complete responses
- end-to-end pass rate = Validator PASS / scheduled Cases

Report these for `ALL_POOL`, `CALIBRATION_EXPOSED`, `FORMAL_UNSEEN_HELDOUT` and each task.

## Offline verification

No model API is called by the freeze verifier. With the separately extracted V3.1 source release available:

```powershell
python tools\verify_v5_frozen_release.py `
  --v31-zip <PATH_TO_GX1_V3_1_BILINGUAL_FULLPOOL_FINAL_20261002.zip> `
  --v31-root <EXTRACTED_V31_ROOT> `
  --out VERIFICATION\FREEZE_VERIFICATION.json
```

Exit code 0 is required before use as a frozen formal protocol.

## Change control

Any change to model-visible messages, scientific validation, public numeric semantics, output mode, attempt selection, exposure split or primary metrics requires V6. Reporting/tooling-only V5 patches require a decision-equivalence proof.
