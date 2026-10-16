# DeepSeek 真实 API 分层测试

在数据集根目录执行以下命令。脚本自动读取根目录 `.env` 中的 `BENCH_API_KEY`，环境中已有的同名变量优先。不要把密钥写入配置文件。

已准备清单 `results/deepseek_stratified_plan/selection.json`：X2、X3 各 100 题，排除之前 4 道试跑题。按任务、规模、有解/无解、负载、请求数均衡抽样，并优先分散请求家族、快照和拓扑。稀少分层用尽后将配额分配给其余分层。该清单包含 126 道有解题、74 道无解题，覆盖 73 个图。

## 启动真实 API 测试

```bash
.venv/bin/python evaluation/stratified_eval.py run \
  --selection results/deepseek_stratified_plan/selection.json \
  --results results/deepseek_stratified \
  --config evaluation/deepseek_stratified_config.json
```

模型配置沿用原试跑：deepseek-v4-pro、thinking enabled、reasoning_effort high、temperature 0、并发 8、最多输出 65536 Token。可在运行前编辑配置。测试启动后配置、输入哈希和清单会冻结；恢复时必须一致。

## 中断后继续

在启动命令末尾加 `--resume`。已保存且评分完成的答卷会跳过；服务失败与评分异常会重试。若整个进程被强制终止，可能留下 `.runner.lock`，须先确认其中记录的主机/PID 对应的进程已退出，再处理锁文件。尚未完整写入日志的 API 调用可能在恢复时重新请求并再次计费。

## 查看阶段结果

```bash
.venv/bin/python evaluation/stratified_eval.py report \
  --selection results/deepseek_stratified_plan/selection.json \
  --results results/deepseek_stratified
```

每批最多 50 题，批次完成后导出答卷。运行结束自动输出分层报告；中途手动汇总只统计已导出的答卷。

输出：`stratified_summary.json`、`stratified_summary.csv`，包含计划数、已记录/待完成/已收到/可评分数、四分类、无解正确拒绝、错误接纳、服务错误、REVIEW、评分错误、可行率、一级目标及完整最优率、Token 和平均/P95 时延。另有原始答卷、Inspect 日志和常规汇总。

## 重新生成清单

使用新的输出目录，避免覆盖已冻结的样本：

```bash
.venv/bin/python evaluation/stratified_eval.py plan \
  --output results/deepseek_stratified_plan_v2 \
  --per-task 100 --seed 20261015 \
  --exclude-results results/model_pilot
```

`--exclude-results` 可重复指定。`plan` 不调用 API。同一数据集、种子和参数产生相同清单。

本轮为探索性评测：当前公开题面没有 WUFR 公式。均衡样本的总体正确率不是原始数据池按比例加权的正确率；请求家族/快照可能重复，不能将全部题目视为独立样本。输入长度报告使用字符数，不是模型 Token 数。
