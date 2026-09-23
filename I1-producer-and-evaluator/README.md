# I1 数据生产与评测程序

本模块生产 I1-S、I1-C、I1-D 三类光网络意图 Case，提供标准 LLM prompt、输出 schema、DUT 响应校验和 reference 比较。

生产入口位于 `production/source/benchmark_i1.py`，评测入口位于 `evaluation/`。数据样例保存在 `production/source/examples/`。
