# I1 评测程序说明

## 评测程序的职责

评测程序独立于 I1 Case 生产程序，负责：

1. 读取三类 I1 system prompt 和 evaluation Case；
2. 向 SiliconFlow Chat Completions 发送 system prompt + Case prompt；
3. 在 API 请求层加入可选 `response_format`；
4. 原样保存模型 assistant content；
5. 读取 Truth 后调用 canonical Validator；
6. 输出逐条分数、API metadata 和汇总结果。

## 本轮使用方式

本轮 27 条示例复评使用：

```bash
python evaluate_i1_lightweight_demo_json_mode_20260914.py \
  --demo-root <I1_MENTOR_LIGHTWEIGHT_COMPLETE_DEMO_20260913_REORDERED> \
  --producer-root <I1-PRODUCER-V2.1.3 source> \
  --output-root <results> \
  --json-mode
```

I1 通用 Runner 也支持：

```bash
python scripts/i1_second_round_pilot.py \
  --environment <environment> \
  --model-list <siliconflow-model-list.json> \
  --output <results> \
  --dut-json-mode
```

`--dut-json-mode` 只向请求体加入：

```json
{"response_format":{"type":"json_object"}}
```

API key 只从 `SILICONFLOW_API_KEY` 读取，不写入 Case、日志、JSON、Markdown 或 ZIP。

## 判分边界

模型输出固定后才读取标准答案。严格判分不做 fence 清理、JSON 截取、字段补全、Truth 修正或“挑最好答案”。判分调用：

```python
from src.i1.validator import validate_i1_output
```

## 指标

- `semantic_exact_match`：canonical 语义完全一致；
- `raw_format_valid`：原始字符串是唯一合法 JSON；
- `schema_valid`：符合当前 profile output schema；
- `final_case_pass`：格式、Schema、语义全部通过。

JSON mode 只改善机器可读性，不替代 canonical Validator。
