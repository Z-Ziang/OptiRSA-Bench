# O1 / O2-S / O2-C / X2 / X3 评测程序 V3.0.0

本程序只评测 Algorithm 和 LLM，不包含其他被测接口。

## Algorithm

Algorithm 读取数据集中的 `.npz`：

```python
from algorithm_api.loader import load_compiled_algorithm_case

case = load_compiled_algorithm_case("evaluation_case/X2/algorithm/case_000001.npz")
answer = algorithm.solve(case)
```

将算法输出保存为 JSON，再使用正式 Validator 评分。建议分别记录数据加载、求解和验证时间，其中核心性能指标是 `solve_time_ms`。

## LLM

LLM runner 读取：

- 对应任务的 `llm_system_prompt.txt`
- `evaluation_case/<TASK>/llm/case_xxxxxx.json`

模型原始输出不做人工修补，依次经过 JSON 解析和正式 Validator。评测保留 API 状态、原始响应、token、时延、决策正确性、可行性与任务质量指标。

运行示例：

```bash
set SILICONFLOW_API_KEY=已设置
python run_siliconflow_low_cost_trial.py --help
```

验证已有试评结果：

```bash
python verify_siliconflow_trial.py --help
```

API Key 不应写入配置、日志或结果包。
