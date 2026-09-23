# O/X2/X3 五任务生产程序

本目录包含 O1、O2-S、O2-C、X2、X3 的数据生产、格式校验和算法/LLM 评测接口。

每条公开 Case 包含结构化算法输入、LLM prompt 和 reference。算法接口读取结构化输入，LLM 接口读取 `evaluation_case/<TASK>/llm/` 下的 `case_id` 与 `prompt`。生产结果同时保留内部 reference replay、schema 校验、运行清单和 SHA-256 校验。

入口：`benchmark_ox.py doctor`、`benchmark_ox.py produce`、`benchmark_ox.py verify-dataset`。配置示例位于 `configs/`，任务契约位于 `contracts/`。
