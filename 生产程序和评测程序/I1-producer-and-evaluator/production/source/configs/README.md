# 配置说明

- `five_task_profile.json`：默认代表性五任务入口。
- `five_task_small_batch.json`：正式小批量试运行入口，每任务目标 2 Case。
- `o_family_*.json`：O1/O2-S/O2-C Case 参数。
- `x2x3_*.json`：X2/X3 Case 参数。
- `public_environment_small_batch.json`：从输入拓扑开始的小批量公共环境参数。
- `*_config.schema.json`：配置 schema。

所有路径在 profile 所在目录相对解析。正式批量时建议复制一个新配置并保留 seed、预算、版本信息以保证复现。

## I1 V2.1

- `i1_representative.json`: 2×I1-S + 2×I1-C + 2×I1-D，关闭远端改写，用于本地确定性验证。
- `i1_small_batch.json`: 12×3=36 Case，小批量基础模板/导出验证。
- `i1_llm_rewrite_template.json`: 正式生产侧 LLM 改写示例；通过 OpenAI-compatible Chat Completions 接口调用，API key 由 `api_key_env` 指定环境变量提供。
- `i1_config.schema.json`: I1 生产配置 schema。

I1-S/I1-C 会覆盖已冻结的静态业务目标组合：碎片最小化，以及对应 X2/X3 的词典序组合目标；I1-D 使用 S1/X4 动态长期目标。生产程序不允许自由组合未冻结 objectives。
