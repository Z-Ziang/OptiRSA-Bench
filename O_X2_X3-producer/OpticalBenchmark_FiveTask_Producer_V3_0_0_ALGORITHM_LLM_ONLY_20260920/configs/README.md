# 配置说明

- `five_task_profile.json`：默认代表性五任务入口。
- `five_task_small_batch.json`：正式小批量试运行入口，每任务目标 2 Case。
- `o_family_*.json`：O1/O2-S/O2-C Case 参数。
- `x2x3_*.json`：X2/X3 Case 参数。
- `public_environment_small_batch.json`：从输入拓扑开始的小批量公共环境参数。
- `*_config.schema.json`：配置 schema。

所有路径在 profile 所在目录相对解析。正式批量时建议复制一个新配置并保留 seed、预算、版本信息以保证复现。
