# G/X1 Case 与评测接口

公开 benchmark case 由 `case_id`、结构化算法输入、LLM 文本提示和 reference 组成。

算法评测读取结构化输入并提交符合任务输出 schema 的结果；LLM 评测读取 `evaluation_case/<TASK>/llm/` 中的 `case_id` 与 `prompt`。

Reference 与内部校验材料只用于生成端和评分端，不作为被测模型输入。
