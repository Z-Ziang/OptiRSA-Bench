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

## X2 / X3 合并数据及已有评测记录

展开后的数据位于 [`datasets/L5_X2_X3`](datasets/L5_X2_X3/README.md)，clone 后无需另外下载数据压缩包。

- 共 **5,369 条**：X2 **3,618**、X3 **1,751**；原 R1 选集 4,608 条，已下载补充 761 条。
- 保留 **230 条已保存答卷及评分记录**，以及原始回答、用量、耗时、Inspect 日志和来源证据。
- 目录按原数据、补充数据和统一索引分区，英文公开输入与私有真值分别保留；依赖与平台认证按各版本 README 配置。
- 本版替换旧 8,340 条发布目录；新合并集不等同于 3,102 个完整 L5 家族。科学合同、版本差异、接口 REVIEW 和服务器未下载部分见[完整说明](datasets/L5_X2_X3/README.md)。

[统一 Case 清单](datasets/L5_X2_X3/MERGED_INDEX/case_inventory.csv) · [已有评测记录](datasets/L5_X2_X3/01_original/HANDOFF_X2X3_SENIOR_20261016/README_交接说明.md) · [补充数据说明](datasets/L5_X2_X3/02_supplement/README_中文.md)
