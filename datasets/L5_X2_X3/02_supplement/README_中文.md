# X2/X3 已认证增量交付
快照：2026-10-16T20:51:49.490143+08:00

包含761个有效Case：X2 276、X3 485。仅为本次统一补缺队列，不是全历史池，不修改原4608条R1选集。18项未解决仅列入pending_tasks.json，不混入有效数据。

## 使用
- case_index.csv/jsonl：Case、指标、来源、哈希及包内相对目录。
- cases/<task>/<case_id>/dataset/evaluation_case/<task>/llm/：英文模型输入；该任务目录的llm_system_prompt.txt为配套系统提示词，output_schema.json为输出格式。
- evaluation_case/<task>/algorithm/与algorithm_api/：结构化算法接口。
- dataset/internal/private/：精确真值、参考输出、特征和lineage。禁止作为模型输入。
- dataset/internal/cases/：完整原始图、频谱状态与请求，可独立读取，不需要服务器公共环境原路径。
- evidence/：生产结果、Validator、输入和来源绑定。
- runtime/frozen_source/：原科学源码、合同和冻结依赖清单；不含venv，不调用模型API。

每个Case保留原dataset完整结构。内部文件可能均叫case_000001，外层case_id才是唯一目录，不要展平覆盖。按case_index.jsonl的package_dataset_path定位数据。

解压后运行 python verify_delivery.py 检查完整性。该命令不重做精确求解。若需重新执行官方数据Validator，在独立Python环境安装runtime/frozen_source/requirements.lock.txt对应依赖，以该目录为PYTHONPATH，调用src.x2x3_dataset_validator.verify_x2x3_dataset(dataset_path)。

原system prompt未在打包时修改；科学认证、英文接口和实际模型上下文适配需区分。输入长度见features.serialized_char_count_llm，不得截断必要输入。这个交付是数据和科学验证源码，不包含Inspect模型API调度器或API密钥。

原服务器绝对路径保留用于追溯，下载后以包内相对路径读取。原来源字段UNKNOWN如实保留，没有伪造来源。761条scientific_key在本队列中唯一，不宣称全历史物理语义排重完成。旧失败日志、完整初态生成轨迹不全量复制；当前静态输入、精确真值、参考结果、Validator与lineage均保留。

SHA256SUMS.txt覆盖全部数据、脚本及FILE_MANIFEST.json。外部ZIP SHA256用于下载校验。
