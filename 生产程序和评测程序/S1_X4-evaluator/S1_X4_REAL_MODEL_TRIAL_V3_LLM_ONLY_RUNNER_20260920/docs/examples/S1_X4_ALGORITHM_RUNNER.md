# S1/X4 Algorithm runner

The formal Algorithm interface starts from a DUT-facing V1.1 launcher and an
evaluator dataset root. The launcher contains an opaque case handle; the
evaluator-private registry resolves and SHA256-checks the canonical dynamic
Episode before the runtime starts. The DUT callback never receives the root
path, root object, registry entry, reference result, or private truth.

```python
from examples.s1_x4_algorithm_examples import FirstFeasibleS1, SimpleFullSpaceX4
from src.s1_x4.algorithm_api.runner import run_algorithm_evaluation

result = run_algorithm_evaluation(
    launcher_path,
    evaluator_dataset_root,
    FirstFeasibleS1(),
    output_dir=output_path,
)
```

The callable receives exactly `(static_context, current_observation)`. The S1 example selects the first entry in the complete public feasible-action array. The X4 example searches simple directed paths and continuous slots using only compiled public topology and current spectrum.

The runner prepares one current observation, calls the algorithm once, submits its response to the existing Validator, commits through the existing dynamic state machine, and only then exposes the next observation. The output timing file separates loading, compilation, observation construction, solving, validation, commit, environment, and end-to-end time. `run_algorithm_episode(root_path, ...)` remains `EVALUATOR_INTERNAL / DIRECT_CANONICAL_EPISODE` and is not the formal public DUT entry. This interface does not claim OS-level sandboxing.
