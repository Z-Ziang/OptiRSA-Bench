# QUICKSTART — V2.1.0

1. 安装冻结依赖：`python -m pip install -r requirements.txt`
2. 健康检查：`python benchmark_all.py doctor`
3. 全回归：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
4. 七任务小批量：`python benchmark_all.py produce --environment-config configs/public_environment_seven_task_small_batch.json --config configs/seven_task_profile.json --output local_output/seven_task_run`
5. 只生产 S1/X4：先用 `run_batch.py` 生产启用 dynamic 的公共环境，再运行 `benchmark_s1x4.py derive-cases`。
6. 验证 S1/X4：`python benchmark_s1x4.py verify-dataset --dataset <dataset_root>`。
7. 正式生产必须使用真实 `tiktoken==0.14.0` 的 `o200k_base`；缺少该依赖时生产器必须失败，不得估算 token。
