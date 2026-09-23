# LLM 文本评测

评测器读取冻结的系统提示词与逐步 Case，通过兼容 Chat Completions 的文本请求提交输入，并按任务 schema 校验文本响应。运行记录包括响应文本、用量、延迟、重试次数和最终评分。

离线回归入口位于 `trial_evaluation/offline.py`；真实 Provider 配置示例位于 `configs/`。
