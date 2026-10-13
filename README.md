# OptiRSA-Bench

## X2 / X3 同源家族评测数据集

完整数据和 Inspect AI 评测程序位于 [`datasets/L5_X2_X3`](datasets/L5_X2_X3)。无需下载或解压 ZIP；本目录全部文件随 Git clone 获取。

- X2：5,238 个；X3：3,102 个；合计 **8,340 个唯一 Case**。
- 来自 3,102 个 L5 静态家族，74 个拓扑来源、73 个图哈希。
- 按拓扑 / 任务 / Case 目录分类，包含英文模型输入、私有真值、来源、参考答案和冻结 Validator。
- Inspect AI 0.3.278，Python 3.12。包含 Windows / Linux 离线安装依赖。

### 获取和开始（Windows PowerShell）

```powershell
git -c core.longpaths=true clone https://github.com/Z-Ziang/OptiRSA-Bench.git
cd OptiRSA-Bench/datasets/L5_X2_X3
powershell -ExecutionPolicy Bypass -File ./evaluation/setup.ps1
./.venv/Scripts/python.exe ./evaluation/verify_files.py
./.venv/Scripts/python.exe ./evaluation/run_eval.py --offline-reference --limit-per-task 2 --output results/offline_check
```

这段命令执行离线参考答案回放，不调用模型 API。实际模型平台设置、API Key 环境变量、并发及断点续跑见 [完整中文使用说明](datasets/L5_X2_X3/README_中文.md)。API Key 和结果目录不得提交到仓库。

### 科学解释边界

X2 按最少跳数、其次 WUFR 优化；X3 按最小 ΔTSO、其次 WUFR 优化。源提示词保留 `REVIEW_OBJECTIVE_DEFINITION` 状态，默认用于探索性评测，不宣称已完成正式接口准入。源认证保留，全池未重新独立求解最优。私有答案由评分器读取，不发给模型。

[数据包英文说明](datasets/L5_X2_X3/README.md) · [评测执行指令](datasets/L5_X2_X3/AI_ASSISTANT_PROMPT_中文.txt) · [许可与发布说明](datasets/L5_X2_X3/RELEASE_CHECKLIST.md)

仓库原有 G/X1 数据及生产与评测程序保留原路径，其统计与本批 X2/X3 数据分开。
