# S1/X4 真实模型试评 V2

这是 S1/X4 动态 Episode 的 LLM 协议加固版试评 runner。它复用官方
`DynamicEpisodeSession`、validator 和 state machine；不会把
网络失败或协议失败写入科学 RBR。

## Windows 运行顺序

在源码目录打开 PowerShell：

```powershell
$env:SILICONFLOW_API_KEY="你的 key"
python -m trial_evaluation.v2.cli doctor
python -m trial_evaluation.v2.cli offline `
  --dataset <public_dataset_root> `
  --output <output>\OFFLINE_VERIFICATION
python -m trial_evaluation.v2.cli capability-probe `
  --output <output>\PROVIDER_CAPABILITY_PROBE.json
```

能力探测会先读取 `/v1/models?sub_type=chat`，只接受精确模型 ID
`deepseek-ai/DeepSeek-V4-Flash`。缺少该 ID 时不会发出后续 POST 请求。

通过能力探测后，运行 5-Step A/B 协议诊断：

```powershell
python -m trial_evaluation.v2.cli diagnostic `
  --dataset <public_dataset_root> `
  --output <output>\PROTOCOL_DIAGNOSTIC_PREFIX_5 `
  --capability-probe <output>\PROVIDER_CAPABILITY_PROBE.json `
  --max-steps 5
```

只有某个 profile 的 protocol/infra gate 都通过，才可以运行 16-Step
confirm；confirm 通过后才可以显式执行 64-Step Pilot：

```powershell
python -m trial_evaluation.v2.cli confirm16 `
  --dataset <public_dataset_root> `
  --output <output>\CONFIRM16_PROFILE_B `
  --diagnostic <output>\PROTOCOL_DIAGNOSTIC_PREFIX_5\PROTOCOL_DIAGNOSTIC_RESULT.json `
  --profile B --max-steps 16

python -m trial_evaluation.v2.cli pilot `
  --dataset <public_dataset_root> `
  --output <output>\PILOT_V2_PREFIX_64 `
  --confirm16 <output>\CONFIRM16_PROFILE_B\CONFIRM16_RESULT.json `
  --profile B --max-steps 64 --episode-concurrency 3 --execute
```

`--execute` 是真实 API 的显式开关。API key 不写入配置、源码、raw log
或 ZIP。每个 Episode 独立 checkpoint；同一 Episode 的 Step 始终串行。

## 失败分层

- `INFRA_*`：网络、429/5xx、402、超时等；不 commit，不进入 RBR。
- `PROTOCOL_*`：空输出、截断、非法 JSON、Schema 或响应 envelope 错误；不 commit，不进入 RBR。
- `MODEL_*`：合法动作后的 REJECT、非法或不可行决策；只有这一层进入科学统计。

JSON 输出只接受严格 `json.loads` + 官方动作 Schema，不做 fence stripping、
正则提取、语义修复或二次追问。
