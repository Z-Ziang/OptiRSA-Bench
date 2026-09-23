# S1/X4 Algorithm public/private boundary

The formal DUT-facing Algorithm input is the V1.1 launcher under
`evaluation_case/<TASK>/algorithm/`. It contains only the public static
connectivity context and an opaque case handle. It does not contain a
canonical Episode reference, horizon, resource-state identity, pairing or
request-sequence identity, difficulty/load/seed/policy lineage, reference
output, oracle, private truth, or future observations.

The evaluator-private registry is
`internal/algorithm_episode_registry.json`. It maps each opaque handle to the
canonical root path and SHA256. The evaluator verifies the registry entry,
path confinement, case/task identity, and root hash before starting the
runtime. This registry is evaluator-private and is never passed to the DUT.

Public and private categories:

- Public launcher: `schema_version`, `case_id`, `task_type`, interface flag,
  `future_requests_visible=false`, static topology connectivity, schema
  references, and `opaque_case_handle`.
- Evaluator-private provenance: canonical root Episode, episode length,
  pairing/resource/request identities, initial state, difficulty context,
  seeds, references, private truth, registry paths, and hashes.
- Runtime public step: only the current observation. S1 receives the complete
  current feasible action set; X4 receives no candidate-path/action oracle.
- Evaluator outputs: validation, trajectory, RBR/EFM metrics, timing, and
  replay evidence. These are not DUT input.

`run_algorithm_episode(root_path, ...)` is retained only as
`EVALUATOR_INTERNAL / DIRECT_CANONICAL_EPISODE`. The documented public entry
is `run_algorithm_evaluation(launcher_path, evaluator_dataset_root, ...)`.
The implementation does not claim OS-level sandboxing.
