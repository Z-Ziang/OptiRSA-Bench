# 七任务生产程序

本目录生产 O1、O2-S、O2-C、X2、X3、S1、X4 七类光网络资源调度数据，并提供算法和 LLM 评测入口。

静态任务输出结构化算法输入与 LLM 文本 Case；S1/X4 输出动态 Episode、逐步 LLM 输入和算法运行配置。算法运行入口位于 `src/s1_x4/algorithm_api/runner.py`，LLM 评测入口读取 `evaluation_case/<TASK>/llm/`。

运行环境检查：`python benchmark_all.py doctor`。数据格式见 `docs/格式规范_冻结版.txt`。
