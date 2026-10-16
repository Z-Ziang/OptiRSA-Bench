# X2/X3 评测交接说明

本包基于原始 4608-case 数据包 OptiRSA_X2X3_MID_5_60_FILTERED_4608_20261016_R1.zip，原始输入保持不变；新增逐 case 状态标记和评测结果。快照时间：2026-10-16T15:06:05.836066+08:00。

## 交给师兄的范围

- 可评测 4190 条：X2 3110 条、X3 1080 条，名单见 HANDOFF_X2X3_SENIOR_20261016/available_for_senior.csv。
- 本会话已评测 218 条：X2 132 条、X3 86 条。
- 另一个 600-case 会话已评测 12 条：X2 4 条、X3 8 条。12 条均按 case_uid 和 messages_sha256 与原包预留样本精确匹配，与本会话结果不重叠。
- 另有 188 条仍分配在 600-case 会话待跑或待重试：X2 96 条、X3 92 条。为避免重复，标为 EXTERNAL_600_IN_PROGRESS，暂不交给师兄。

## 使用方法与状态定义

全量 evaluation_status.csv 含 4608 条。每个输入 case 目录新增 case_handoff_status.json。AVAILABLE_FOR_SENIOR 表示可评测；EVALUATED_LOCAL 和 EVALUATED_EXTERNAL_600 已有回答及评分；EXTERNAL_600_IN_PROGRESS 仍由另一个会话负责。师兄只需按 available_for_senior.csv 筛选 case_dir。

## 完整结果

completed_results.jsonl 及 results/local 或 results/external_600 下的逐 case answer.json 保存 230 条完整响应、token usage、评分类别与验证详情。另一会话的 12 条另附原始 binding.json 和 Inspect .eval 日志。result_category 是原评测器的评分类别，不代表模型输出一定正确。

截至快照，本会话队列状态：X2 COMPLETE 106、HISTORICAL 26、PENDING 2656、RETRY 454、EXTERNAL_RESERVED 100；X3 COMPLETE 80、HISTORICAL 6、PENDING 603、RETRY 475、DEFERRED 2、EXTERNAL_RESERVED 100。X2/X3 本地进程已停止，按用户要求暂停评测。模型为 Qwen/Qwen3-8B，thinking 已关闭；外部会话 12 条结果的 reasoning_tokens 均为 0。原 ZIP 完整保留；本包未加入 API 凭据或运行配置。
