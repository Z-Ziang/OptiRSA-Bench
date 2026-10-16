# 第三方组件与来源

本项目的 X2/X3 Case 与冻结评分源码提取自 package case_sets/_index/dataset_summary.json 所列四个历史交付档案。源任务与原案例身份、成员 SHA256、图/频谱状态哈希在 identity.json 中保留。没有复制其他任务的载荷或任何个人模型账号。

Inspect AI 0.3.278 为开源评测框架，MIT License，官方项目 https://github.com/UKGovernmentBEIS/inspect_ai 。OpenAI Python SDK 3.29.0 与其他固定依赖为第三方软件，均以各自原 wheel 中的许可证为准。vendor 保存分发 wheel，不复制原作者的 .venv 或账户文件。依赖精确版本见 evaluation/requirements-lock.txt。

源数据 ZIP 未附可确定的项目数据/代码公开许可，发布许可由本项目作者确认；本文件只是来源说明，不是新授权。
