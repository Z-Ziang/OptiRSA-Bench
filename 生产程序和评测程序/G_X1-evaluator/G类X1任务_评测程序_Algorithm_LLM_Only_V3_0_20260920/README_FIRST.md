# GX1 Algorithm + LLM Evaluation Runner V3.0

本评测程序只包含两条路径：

1. LLM：OpenAI-compatible API 调用、结构化 JSON 输出约束和 canonical Validator。
2. Algorithm：读取算法输出文件，离线调用同一 canonical Validator。

## LLM dry-run

```bash
python trial/run_openai_compatible_trial.py --producer-dir <PRODUCER_DIR> --dataset-dir <DATASET_DIR> --dry-run
```

dry-run 不访问模型 API，只检查 Case、LLM 请求边界、JSON Schema 装配和标准答案自检。

## LLM 正式试评

先在环境变量中设置：

```text
GX1_API_BASE
GX1_API_KEY
GX1_MODEL
GX1_EXTRA_BODY_JSON   # 可选
```

然后运行：

```bash
python trial/run_openai_compatible_trial.py \
  --producer-dir <PRODUCER_DIR> \
  --dataset-dir <DATASET_DIR> \
  --results-dir <RESULTS_DIR> \
  --runner-config configs/trial_runner_json_schema.json \
  --resume
```

保留功能：JSON mode/JSON Schema、LLM preflight、connect/read/request/case timeout、最多三次有界重试、指数退避、断点续跑、原始 API response、原始模型输出、token/latency 和基础设施错误分类。

## Algorithm 离线评测

算法输出可保存为 `<OUTPUTS_DIR>/<CASE_ID>.json` 或 `<OUTPUTS_DIR>/<TASK>/<CASE_ID>.json`：

```bash
python trial/validate_algorithm_outputs.py \
  --producer-dir <PRODUCER_DIR> \
  --dataset-dir <DATASET_DIR> \
  --outputs-dir <ALGORITHM_OUTPUTS_DIR> \
  --results-dir <ALGORITHM_RESULTS_DIR>
```

算法轨不调用模型 API，不需要 system prompt。它直接使用 `root_case.json` 和生产程序的 canonical Validator。

## Unified 数据适配

如果拿到的是公开三字段 `benchmark_case` 与独立 `internal_evidence`：

```bash
python trial/prepare_unified_dataset.py \
  --public-dataset <PUBLIC_DATASET> \
  --internal-evidence <INTERNAL_EVIDENCE> \
  --output <PREPARED_DATASET>
```

适配后的私有评测目录只复制 `root_case.json` 和 `actual_llm_request.json`。

API Key 只能从环境变量读取，不会写入请求记录、结果或 ZIP。
