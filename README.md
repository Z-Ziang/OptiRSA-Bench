# OptiRSA-Bench

The standalone G1/G2/G3/X1 dataset and Inspect AI evaluator are in [G-X1-cases](G-X1-cases/README.md).

**中文说明和全部拓扑分布：[G-X1-cases/README_中文.md](G-X1-cases/README_中文.md)。**

This module contains the frozen English V3.1 pool: 563 topology source IDs and 8,619 case records. Its default evaluation queue contains 8,618 records; one G3 case with documented ambiguity is retained for review. Public-question duplicates are documented separately.

The dataset is expanded into topology → task → case folders. Public prompts, private answers, provenance and a portable Inspect AI evaluation directory are included. Model platform configuration and credentials are supplied by the evaluator.

On Windows, enable long paths for the clone because some historical program paths are long:

```shell
git -c core.longpaths=true clone https://github.com/Z-Ziang/OptiRSA-Bench.git
cd OptiRSA-Bench/G-X1-cases
```

Follow the module README to install Python 3.12 dependencies, run offline acceptance, and configure your own model endpoint. No dataset ZIP or Git LFS download is required for this GX1 module. Repository access still follows the repository's visibility and permissions.

The separate `生产程序和评测程序` directory contains historical program releases. Use the GX1 module's included V5 R1 scientific validator and Inspect entry point for this dataset. Each module's version and scope must be checked before combining results.

## X2 / X3 同源家族评测数据集

完整数据和 Inspect AI 评测程序位于 [`datasets/L5_X2_X3`](datasets/L5_X2_X3)。仓库直接包含全部 Case 文件，无需另行下载 ZIP。

- X2：5,238 个；X3：3,102 个；合计 8,340 个唯一 Case。
- 来自 3,102 个 L5 静态家族，74 个拓扑来源、73 个图哈希。
- 每个拓扑下按 X2/X3 分类；包含英文模型输入、私有真值、来源、参考答案和冻结 Validator。
- 使用 Inspect AI 0.3.278 与 Python 3.12；包含 Windows 和 Linux x86_64 离线依赖。

### Windows PowerShell 快速开始

```powershell
git -c core.longpaths=true clone https://github.com/Z-Ziang/OptiRSA-Bench.git
cd OptiRSA-Bench/datasets/L5_X2_X3
powershell -ExecutionPolicy Bypass -File ./evaluation/setup.ps1
./.venv/Scripts/python.exe ./evaluation/verify_files.py
./.venv/Scripts/python.exe ./evaluation/run_eval.py --offline-reference --limit-per-task 2 --output results/offline_check
```

最后一条运行本地参考答案回放，不会调用模型 API。模型平台、API Key 环境变量、并发和续跑步骤见 [X2/X3 完整中文说明](datasets/L5_X2_X3/README_中文.md)。请勿提交个人 API Key 或评测结果。

**科学状态：** X2 按最少跳数、其次 WUFR 优化；X3 按最小 ΔTSO、其次 WUFR 优化。源接口仍标记 `REVIEW_OBJECTIVE_DEFINITION`，默认用于探索性评测；不宣称完成正式接口准入，也未对全池重新独立求解最优值。

[G/X1 中文分布说明](G-X1-cases/README_中文.md) · [X2/X3 使用说明](datasets/L5_X2_X3/README_中文.md) · [评测执行指令](datasets/L5_X2_X3/AI_ASSISTANT_PROMPT_中文.txt)
