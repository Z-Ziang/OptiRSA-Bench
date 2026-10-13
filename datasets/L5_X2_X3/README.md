# OptiRSA-Bench: L5-family X2/X3 evaluation snapshot

See [the complete Chinese README](README_中文.md) for the dataset description, topology-by-task distributions, setup, model-platform configuration, resume commands, and scoring limitations. This research snapshot is distributed as a complete directory in the OptiRSA-Bench repository; clone the repository and enter datasets/L5_X2_X3 to use it.

The snapshot contains **8,340 unique cases: X2 5,238 and X3 3,102**, extracted from 3,102 complete five-task static families. It preserves 74 source topology labels, 73 graph hashes, and 804 graph/spectrum-state pairs. Each case has public English system/user texts, private scientific input, certified source truth, one reference output, source validation, and provenance. Other task payloads are excluded.

X2 optimizes hop count then WUFR. X3 optimizes added spectrum occupation (Delta TSO) then WUFR and admits or rejects the whole request group. The bundled frozen validators evaluate full-path RSA rather than a K-limited route set. Feasible cases are classified as optimal, feasible suboptimal, infeasible, or missing a compliant solution; certified infeasible cases and correct rejection are counted separately.

Inspect AI **0.3.278** provides the evaluation harness. The adapter transmits only the two public messages; it does not supply private targets, grading code, or dataset access tools to the model. Bring your own model platform/API credentials. The package includes locked installation wheels for Python 3.12 on Windows x64 and Linux x86_64 with glibc >=2.34; the Windows offline installation was exercised, while a Linux operating-system execution is not claimed.

```powershell
powershell -ExecutionPolicy Bypass -File .\evaluation\setup.ps1
.\.venv\Scripts\python.exe .\evaluation\verify_dataset.py --report verification_local.json
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --offline-reference --limit-per-task 2 --output results/offline_check
```

For real evaluations, copy `evaluation/model_config.example.json`, select the actual model ID/base URL/settings, set the configured API-key environment variable, and run `evaluation/run_eval.py`. An unchanged run can resume with `--resume`. Read the Chinese instructions before full-scale API requests.

**Scientific status:** source public interfaces remain `REVIEW_OBJECTIVE_DEFINITION`; the intentionally frozen English prompts do not disclose the WUFR formula. This is an executable exploratory evaluation protocol, not newly approved formal/fully specified secondary-objective interfaces. The package preserves source optimality certificates; it does not independently re-solve all global optima. Historical exposure and clustered family/state relations must be considered when designing evaluation splits. Input token counts have not been measured using a target model tokenizer.

Full payload hashes, independent reference regrading, categorical scoring checks, and offline Inspect/loopback transport acceptance are in `evaluation/verification`. Loopback and reference replay results are software fixtures, not model performance.

Dataset/code licensing and source topology redistribution permissions must be confirmed by the project author before public publication; see [release checklist](RELEASE_CHECKLIST.md). Third-party software retains its own licenses. No API key, personal model answers, account configuration, or environment installation is included.
