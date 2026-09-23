# OpticalBenchmark G1/G2/G3/X1 独立生产程序 V3.0

本版本只面向 **Algorithm + LLM**。G1/G2/G3/X1 的科学任务、Truth、canonical Validator、生产配置和 LLM 提示词保持不变。

## 生产与验证

```bash
python run_production.py --doctor
python run_production.py --config configs/example_batch.json --output outputs/example_batch
python run_production.py --verify-output outputs/example_batch
```

每个内部 Case 目录包含：

```text
cases/<TASK>/<CASE_ID>/
├─ root_case.json
├─ llm_case.json
├─ truth.json
├─ validation_metadata.json
└─ actual_llm_request.json
```

`root_case.json` 是 Algorithm 输入与科学实例。算法输出直接交给 canonical Validator，不需要自然语言 prompt。

`llm_case.json` 保存 `case_id + prompt + answer`，用于展示和离线验证；真正发送给模型的是 `actual_llm_request.json` 所表达的 system prompt 加 user prompt，且不含答案。

## 公开发布格式

```bash
python run_production.py --export-unified outputs/example_batch --unified-output outputs/example_batch_public
python run_production.py --verify-unified outputs/example_batch_public
```

公开 `benchmark_case` 严格为三个字段：

```json
{
  "case_id": "G1_000001",
  "llm_prompt": "...",
  "reference": {}
}
```

公开 `evaluation_case` 严格为两个字段：

```json
{
  "case_id": "G1_000001",
  "prompt": "..."
}
```

每项任务只保存 `llm_system_prompt.txt`。`reference/answer/truth/oracle/private_truth` 不进入实际 LLM 请求。

## 不变项

- 继续接受 `GX1_PRODUCTION_CONFIG_V2_0/V2_1/V2_2` 配置。
- G1 三种图表示与六种转换不变。
- G2 FIRST_MATCH 与严格 WRONG_DIRECTION 不变。
- G3 最短路径与共享有向 `link_id` 判定不变。
- X1 允许任意合法的全局最优路径，多最优 accepted set 不变。
- `TOTAL_LENGTH_KM` 仍只使用具有完整正数 `length_km` 的拓扑。

## 测试

```bash
python -m compileall -q gx1 stage2 run_production.py
python -m pytest -q --basetemp <WRITABLE_TEMP_DIR>
```

生产程序不包含模型 API 密钥。模型试评由独立的 Algorithm+LLM 评测程序完成。
