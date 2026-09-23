# S1/X4 H=12 配对代表 Case

本目录给出 V2.1.0 的两个公开 `benchmark_case` 示例：`S1_case_000001.json` 与 `X4_case_000001.json`。

两者来自同一个 H=12 动态基础场景，使用相同拓扑、相同初始资源状态、相同初始连接集合和相同完整请求序列。S1 的公开 Step 1 包含规定 K 条路径范围内的全部可行动作；X4 不包含候选路径或候选动作。完整 Episode definition 与 reference trajectory 属于 internal/private 科学证据，不在此公开示例目录重复发布。

这两个文件用于人工审阅格式与首 Step 效果，不代表正式科学实验固定使用 H=12。正式 Episode 长度由公共环境 `dynamic.sequence_length` 配置决定。
