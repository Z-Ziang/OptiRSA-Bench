# GX1 数据与完整评测记录（2026-10-17 快照）

原附件共 8,619 个 case，输入、真值、评分器和原目录结构保留。已完成结果、失败与重试历史统一收在 `evaluation/records/`，无需逐个翻 case 目录。

|任务|全部 case|Qwen3-8B 已完成独立 case|CORRECT|INFEASIBLE|MISSING|SUBOPTIMAL|
|---|---:|---:|---:|---:|---:|---:|
|G1|2430|426|65|32|329|0|
|G2|2815|1850|731|1119|0|0|
|G3|2248|1233|166|798|269|0|
|X1|1126|668|12|562|92|2|

## 阅读顺序
1. `CASE_PROGRESS.csv`：全部 case 是否已完成、四分类、来源、thinking 条件及结果位置。
2. `completed/<任务>/part-*.jsonl`：每个已完成独立 case 的完整选定结果，含输入索引、原始模型回答、模型输出、usage、时间、评分和校验原因。
3. `ALL_SCORED_RECORDS.csv`：全部已评分来源记录索引，含重复评测和其他模型。
4. `sources/<来源>/<任务>/`：原队列逐行导出、全部事件、每次 binding/answer/service_error、批次 Inspect 日志、运行与修复记录。JSONL 每片小于 40 MB，保持 GitHub 可直接管理。
5. `sources/historical/`：早期来源的原始记录及 GX1 原始证据。其他模型与离线回放仅作历史证据，不混入 Qwen3-8B 完成数。
6. `provenance/`：原附件哈希、逐文件校验以及后台源码。`SUMMARY.json` 记录逐队列采集时点和状态；这不是所有运行程序同一时刻的全局快照。

## 统计规则
完成表示已收到回答并保存评分，包含非正确答案。INFEASIBLE 为答案不满足校验，MISSING 为无法提取合规结果，SUBOPTIMAL 为可行但非最优；不表示 API 调用失败。
同 case 多份记录全部保留，汇总优先原队列、历史导入、独立批次原轮、独立批次 no-thinking 轮；各来源内按完成时间选择。没有按正确答案择优。已有回答不因错误、格式或截断重新评测。
thinking=false 只在明确的派发/配置证据或专门 no-thinking 来源存在时标注；BEFORE_DISABLE 是配置切换前，UNKNOWN 是证据不足。reasoning_tokens=0 不能单独证明关闭 thinking。
G1/G2/G3/X1 的输入与提示词逐 UID 核对；不重新调用模型、不改评分结果、不修改线上队列。原始路径保留作证据，跨机器读取使用本包相对目录。
API 密钥及凭据文件不发布；若原文出现密钥，仅替换密钥内容并在 SUMMARY.json 记载，科学输入/回答/评分不作改写。

GitHub 使用展开目录。原附件说明和 FILE_MANIFEST.csv 仍描述原始基包；新增记录以本目录 FILE_MANIFEST.csv 为准。

## 补充证据
`alternate_account_retry/` 保留原 A/B 账户补跑队列、逐次尝试与日志；其已评分 case 均已合入原队列，不重复增加完成数。外部批次的配置和入口代码收于各来源的 config/ 与 provenance/。
