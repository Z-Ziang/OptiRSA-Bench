# 七任务评测程序

本目录提供 O1、O2-S、O2-C、X2、X3、S1、X4 的算法结果校验与 LLM 文本评测。

静态任务使用各任务 algorithm contract 和 output schema；S1/X4 算法评测使用 `src/s1_x4/algorithm_api/runner.py`。LLM 评测读取 `evaluation_case/<TASK>/llm/` 下的 Case，并通过兼容 Chat Completions 的文本接口获取模型响应。

环境检查：`python benchmark_all.py doctor`。数据格式见 `docs/格式规范_冻结版.txt`。
