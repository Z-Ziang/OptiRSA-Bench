# X2 / X3 — merged dataset and saved evaluation records

本目录为 2026-10-17 合并版，替换旧版 8,340 条 L5 发布目录。本版共有 **5,369 条唯一科学对象：X2 3,618 条、X3 1,751 条**。新增生产数据与原筛选集属于不同版本，整个合并集不等同于完整 L5 家族集。

| 来源 | X2 | X3 | 合计 |
|---|---:|---:|---:|
| 原 R1 筛选集 | 3,342 | 1,266 | 4,608 |
| 服务器已下载补充 | 276 | 485 | 761 |
| 合计 | 3,618 | 1,751 | 5,369 |

## 文件入口

- [完整中文合并说明](README_合并说明_中文.md)
- [统一逐 Case 清单 CSV](MERGED_INDEX/case_inventory.csv) / [JSONL](MERGED_INDEX/case_inventory.jsonl)：全部路径相对于本目录；含公开题面、真值 root、Validator、参数和来源。
- [唯一对象清单](MERGED_INDEX/unique_cases.jsonl) / [审计汇总](MERGED_INDEX/SUMMARY.json)
- [原 4,608 条数据及评测框架](01_original/OptiRSA_X2X3_MID_5_60_HOP_GE2_R1/README_中文.md)：Case 按拓扑 → 任务 → Case 分类。
- [已有评测交接说明](01_original/HANDOFF_X2X3_SENIOR_20261016/README_交接说明.md) / [230 条已保存答卷与评分](01_original/HANDOFF_X2X3_SENIOR_20261016/completed_results.jsonl)。原始回答、用量、耗时及 Inspect 日志保留。这些是回答记录，不能全部视为正确结果。
- [新增 761 条数据说明](02_supplement/README_中文.md) / [新增 Case 索引](02_supplement/case_index.jsonl)。该部分按任务 → Case 分类，每例独立保留原科学数据结构及冻结源码。

## Clone 后使用

文件均已展开，无需下载或解压数据 ZIP。Windows 建议：

```shell
git -c core.longpaths=true clone https://github.com/Z-Ziang/OptiRSA-Bench.git
cd OptiRSA-Bench/datasets/L5_X2_X3
```

原 R1 集的 Inspect AI 程序在 `01_original/OptiRSA_X2X3_MID_5_60_HOP_GE2_R1/evaluation/`，使用前阅读该版 README。新增数据的独立验证程序是 `02_supplement/verify_delivery.py`，在该子目录运行；其科学代码与合同位于 `02_supplement/runtime/frozen_source/`。运行环境、依赖和模型平台认证需自行配置。

两批数据的输入包装与冻结评分代码不同，统一索引用于定位；它不代表新增题已经接入旧版 Inspect 调度器。按对应版本加载公开输入并评分，保留 Case×模型×提示词及参数身份，排除已答题和其他工作流责任范围，避免重复调用。原交接任务状态只是快照，不是实时队列。

X2 的目标为最少跳数后最小 WUFR，X3 为最小 ΔTSO 后最小 WUFR，均保留全图求解合同。已有接口 REVIEW 标记保持；本次只验证来源、文件哈希、已有 Validator 状态和合并一致性，没有独立重新求解全池真值，也没有调用模型验收新接口。私有真值和参考输出仅供评分，不能作为模型输入。

补充包另列 18 项未解决任务，未计入有效 Case。用户提到还有十多个已生产 Case 尚未下载；其数量及身份待服务器恢复后核对，本版未包含。补充题没有重新执行旧 R1 的两跳占比配额。

## 完整性与复现

`SHA256SUMS_MERGED.txt` 是原合并包的载荷校验清单，GitHub 新增本 README 不在原清单中。源清单、逐文件来源、合并脚本和已保存科学证据均保留。各子目录旧版完成证明和计数仅适用于各自版本，合并总数以 `MERGED_INDEX/SUMMARY.json` 为准。
