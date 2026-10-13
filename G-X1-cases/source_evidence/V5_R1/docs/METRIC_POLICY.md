# V5 Metric Policy

For a scheduled cohort:

- `completion_rate = completed_responses / scheduled_cases`
- `scientific_accuracy = validator_pass / completed_responses`
- `end_to_end_pass_rate = validator_pass / scheduled_cases`

A completed but invalid JSON/schema/semantic answer is a model failure and remains in the scientific denominator. A transport/infrastructure failure that never produced a complete scientific response is reported separately and does not silently become a scientific error.

Metrics must be reported for ALL_POOL and separately for CALIBRATION_EXPOSED and FORMAL_UNSEEN_HELDOUT; task-level breakdowns are mandatory.
