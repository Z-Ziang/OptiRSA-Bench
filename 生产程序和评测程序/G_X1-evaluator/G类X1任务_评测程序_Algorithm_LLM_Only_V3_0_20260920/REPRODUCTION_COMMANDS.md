# Verification Commands

```bash
python -m compileall -q trial
python -m pytest -q --basetemp <WRITABLE_TEMP_DIR>
python trial/run_openai_compatible_trial.py --producer-dir <PRODUCER_DIR> --dataset-dir <DATASET_DIR> --dry-run
python trial/validate_algorithm_outputs.py --producer-dir <PRODUCER_DIR> --dataset-dir <DATASET_DIR> --outputs-dir <ALGORITHM_OUTPUTS_DIR> --results-dir <RESULTS_DIR>
```
