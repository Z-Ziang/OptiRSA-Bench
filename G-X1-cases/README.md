# OptiRSA-Bench GX1 standalone dataset

563 topology source IDs; 8,619 frozen English cases: G1 2,430, G2 2,815, G3 2,248, X1 1,126.

See [Chinese README](README_中文.md) for all topology/task counts, setup and scoring details. Each topology/task/case folder contains public prompts and private scoring materials. Only public prompts are sent to models.

Python 3.12; Inspect AI 0.3.278. Install `evaluation/requirements-lock.txt`, then run `evaluation/verify_dataset.py` and `evaluation/run_eval.py`. Model platform credentials are supplied by the evaluator. No real model API calls were made to build this release.
