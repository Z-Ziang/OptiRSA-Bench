# O/X2/X3 五任务生产程序

本目录包含 O1、O2-S、O2-C、X2、X3 的数据生产、格式校验和算法/LLM 评测接口。

## V3.1.0 双语 LLM Case 导出

正式模型输入采用英文。生产程序继续使用原有正式目录：

- `benchmark_case/<TASK>/`：英文完整公开 Case（含 `llm_prompt` 与 `reference`）。
- `evaluation_case/<TASK>/llm/`：英文正式 LLM 输入，仅含 `case_id` 与 `prompt`。

同时自动生成中文镜像，供人工审计、复核与语义对照：

- `benchmark_case_zh/<TASK>/`：中文完整公开 Case。
- `evaluation_case_zh/<TASK>/llm/`：中文 LLM 输入镜像。

英文提示词由原冻结中文提示词逐句等义翻译。两种语言共享同一个 `case_id`、结构化 `instance`、`reference`、请求、路径、频谱资源状态和随机生产结果；语言切换只发生在自然语言渲染/导出层。算法输入、Oracle、reference 求解、验证器、拓扑/资源状态/请求生成和核心生产机制保持原有实现。

`contracts/<TASK>/llm_system_prompt.txt` 为正式英文系统提示词；原中文系统提示词逐字保存在 `contracts/<TASK>/llm_system_prompt_zh.txt`。

正式 `serialization_metrics` 仍针对正式英文 `llm_prompt` 计算。中文镜像不改变正式模型接口，也不改变 Algorithm NPZ 接口。

入口：`benchmark_ox.py doctor`、`benchmark_ox.py produce`、`benchmark_ox.py verify-dataset`。配置示例位于 `configs/`，任务契约位于 `contracts/`。
