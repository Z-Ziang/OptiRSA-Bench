# QUICKSTART — Seven-task V2.1.0 + I1-PRODUCER-V2.1.3

1. 安装冻结依赖：`python -m pip install -r requirements.txt`
2. 健康检查：`python benchmark_all.py doctor`
3. 全回归：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
4. 七任务小批量：`python benchmark_all.py produce --environment-config configs/public_environment_seven_task_small_batch.json --config configs/seven_task_profile.json --output local_output/seven_task_run`
5. 只生产 S1/X4：先用 `run_batch.py` 生产启用 dynamic 的公共环境，再运行 `benchmark_s1x4.py derive-cases`。
6. 验证 S1/X4：`python benchmark_s1x4.py verify-dataset --dataset <dataset_root>`。
7. 正式生产必须使用真实 `tiktoken==0.14.0` 的 `o200k_base`；缺少该依赖时生产器必须失败，不得估算 token。

## I1 当前接口

I1-S、I1-C、I1-D 是三个独立的 LLM-only 子任务。新的 benchmark_case 只有 `case_id + llm_prompt + answer`；evaluation_case 只有 `case_id + prompt`，且 `evaluation_case.prompt == benchmark_case.llm_prompt`。answer 不进入 evaluation_case。

```bash
python benchmark_i1.py --version
python benchmark_i1.py doctor
python benchmark_i1.py derive-base-cases --environment <public_environment> --config configs/i1_representative.json --output <base_output>
python benchmark_i1.py rewrite-base-cases --base-dataset <base_output> --config configs/i1_llm_rewrite_template.json --output <final_output>
python benchmark_i1.py verify-dataset --dataset <final_output>
```

历史 artifacts 可能使用旧 benchmark 顶层字段 `prompt`；V2.1.3 新生产统一使用 `llm_prompt`，不改变历史 prompt、answer、system prompt 或评分语义。
