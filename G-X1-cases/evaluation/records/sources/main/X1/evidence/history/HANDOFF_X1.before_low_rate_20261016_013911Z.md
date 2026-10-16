# X1 独立评测交接

你只负责 X1。用户已授权后台评测，仅使用 SiliconFlow 的 Qwen/Qwen3-8B，3个异步并发worker。先阅读部署根目录 README.md 和本文件，再查看状态并启动本任务。不需重复申请用户已经给出的模型调用许可。不得启动/停止其他任务，不要复制数据库或绕过后台直接运行原始附件脚本。

唯一部署根目录：`D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016`。所有聊天、Git分支共享此绝对目录内的实时队列，工作区位置变化不影响进度。不要在当前分支重新初始化一份队列。

初始可评测 1126 个；历史回答匹配并跳过 111 个；初始待评测 1015 个。实时数字必须以 SQLite/status 为准。G3另保留1个EXCLUDED，X2/X3未来还会增量补充，不以当前清单代表完整最终范围。

```powershell
$backend = 'D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\backend.ps1'
& $backend -Action status -Task X1
& $backend -Action start -Task X1
& $backend -Action status -Task X1
```

启动后程序脱离聊天后台运行；再次start会拒绝重复启动。每任务一个监督进程、一个执行进程，执行进程内3个原生Inspect并发槽位。进程结束不一定等于评测全部完成，检查PENDING/RETRY/DEFERRED/PROVIDER_PAUSED/NEEDS_REVIEW/SCORING_REVIEW计数，不能把基础设施失败当模型错误，也不能把仅有失败的case当完成。

任何已经收到的回答都不再调用，包括错误/格式错误/截断。SCORING_REVIEW仅离线重评。历史仅来自记录包FINAL并经过uid、任务、消息和科学材料哈希核对。认证/余额问题会暂停本任务；修复后先停止并等待running=false，再执行retry和start。遇NEEDS_REVIEW时先recover检查回答及Inspect日志；只有核查后确实要重发不确定请求，才使用-IncludeUncertain，并说明可能重复付费。默认不启用该选项。

```powershell
& $backend -Action stop -Task X1
& $backend -Action recover -Task X1
& $backend -Action retry -Task X1
& $backend -Action start -Task X1
& $backend -Action export -Task X1
```

结果在 `tasks\X1\exports\`；逐次绑定/回答在 `tasks\X1\attempts\`，Inspect日志在 `tasks\X1\batches\`。后台每60秒导出一次，退出时再导出，实时进度以queue.sqlite为准。保留所有来源、原始回答、usage、时长及严格/允许单层代码围栏两套评分。不得为提高分数重跑已回答case、修改公开提示词/冻结评分器或读取私有答案生成模型回答。

增量X2/X3包只通过根目录import-cases.ps1导入；先停止受影响任务，原历史压缩包须可读。同uid内容变更拒绝导入，新增case入队，旧回答保留。X2/X3保留REVIEW_OBJECTIVE_DEFINITION标记，当前结果按原探索性协议解释。

Key已用当前Windows用户DPAPI加密保存，不要向用户索要或打印、不写入源码或日志。部署验收没有调用真实平台，首次启动才检验线上权限/额度。机器休眠、关机期间不能继续计算，开机后恢复。本轮部署不注册系统服务或计划任务。


当前新账户失败补跑规则见 `D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\NEW_ACCOUNT_RETRY.md`。owner为alternate-retry的NEEDS_REVIEW case由独立补跑服务负责，禁止用原账户重新领取；其他原任务照常推进。


用户最新指令：独立账户补跑已停止，失败 case 已归还原队列；X2/X3 使用账户 A（已配置 DPAPI），G1/G2/G3/X1 沿用原账户。不要重启 retry_runs 中的补跑服务。全部旧记录保留。


## X1 transport recovery (2026-10-16)

X1 requests through the local HTTP proxy repeatedly failed with `APIConnectionError`; Inspect traces showed the proxy path disconnecting before an HTTP response. The local proxy remained reachable, and direct TCP/443 to `api.siliconflow.cn` was reachable. The launcher now applies a process-scoped `NO_PROXY=api.siliconflow.cn` only for `backend.ps1 -Action start -Task X1`, following the existing G1 idle-timeout workaround. It preserves inherited exclusions and does not change the global proxy, credentials, model, workers, public prompt, scorer, or queue. The original X1 credential remains in use. Real API completion must be verified from X1 queue events before treating the transport repair as successful.

The prior launcher, X1 config, run manifest, and this handoff were archived under `tasks\X1\history`. The X1 SQLite audit event and JSON transport record were added; the protocol fingerprint remains unchanged because scientific config and scoring code did not change. Do not restart the independent account retry service.


## X1 TPM downgrade (authorized, 2026-10-15 22:12 UTC)

A fresh 3-worker X1 run produced SiliconFlow `429 / TPM limit reached` errors; the latest observed at 2026-10-15 22:04:02.354 UTC. After graceful stop and `recover`, 90 attempt directories from that run had 0 `answer.json` files; 57 TPM 429 failures, 6 attempt timeouts, and 27 requests stopped before dispatch were recorded. The queue recovered to PENDING=569, RETRY=424, COMPLETE=22, HISTORICAL=111.

User-authorized X1 workers are now 2. Only `workers` changed; original account, Qwen/Qwen3-8B, prompt, scorer, and queue remain unchanged. The 3-worker config, run manifest, and prior handoff were archived under `D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\history`. Queue protocol fingerprint was migrated from `2715f520e5425bd39ef0f822adec64fa9b536b02d8cf154a002df2282864d606` to `04d10a69267cac64c9b8baab2275fbde703a09003dd527e2ee4b5cb09d73b361` and the change is recorded in the X1 event log and `D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\history\x1_workers_3_to_2_tpm_20261015_221221Z.json`. The 5-minute wait from the latest 429 has elapsed. Retry only confirmed service failures; never use IncludeUncertain. If a fresh 2-worker TPM 429 occurs, stop and recover, wait 5 minutes, and make only the one authorized automatic retry; stop and notify if it persists.


## X1 paused pending provider action (2026-10-15 22:40 UTC)

A 2-worker run produced 14 fresh SiliconFlow `429 / TPM limit reached` errors (latest 2026-10-15 22:17:42.860 UTC). X1 was stopped and recovered, then the authorized one-time retry/start was performed after the 5-minute wait. That run had 20 attempt records, 0 saved `answer.json` files, 6 request timeouts at 300 seconds, 14 samples stopped before a provider request, and no further TPM 429. Inspect recovery found no model outputs.

No-key direct TCP/TLS checks to `api.siliconflow.cn` succeeded over IPv4 and IPv6 (TLS 1.3); actual inference requests still timed out. X1 is now stopped with no processes. Current statuses: COMPLETE=22, HISTORICAL=111, PENDING=578, RETRY=415. User action is needed to check/increase the original account TPM quota and confirm SiliconFlow inference availability. Do not restart, lower concurrency further, or loop retry until the user directs resumption/provider capacity is confirmed. Evidence: `D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\history\x1_pause_provider_errors_20261015_224020Z.json`; stop event is recorded in the X1 SQLite queue.


## X1 paused again after user-directed resume (2026-10-15 23:25 UTC)

At the user's standing direction to continue X1, the existing backend was resumed at 2 workers on the original queue at 23:13 UTC. Four fresh API dispatches (attempt 13) timed out after about 300 seconds; there were no fresh TPM 429s. The latest Inspect `.eval` records 20 samples, all with errors, zero completion text/choices, and no `answer.json` files. X1 was gracefully stopped at 23:20 UTC; after the in-flight requests timed out, `recover` completed and confirmed `running=false`. Current queue: COMPLETE=22, HISTORICAL=111, PENDING=580, RETRY=413. No config, prompt, scorer, account, or protocol changes were made.

A no-key, unauthenticated `GET /v1/models` returned HTTP 401 quickly; this only confirms that the gateway responded, and does not verify inference availability, account quota, or credentials. Evidence is in `D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\history\x1_pause_recheck_timeout_20261015_232538Z.json`; SQLite audit event 2691 records the pause. Keep X1 stopped to avoid repeating 300-second requests. Resume only after original-account TPM/inference availability is resolved or materially confirmed; do not loop retries.


## X1 single-case probe and safe resume (2026-10-16 01:25 UTC)

A user-directed probe used the original X1 queue/backend, original account, Qwen/Qwen3-8B, and unchanged prompt/scorer. Only the untouched PENDING case X1_000935 was eligible: it had no prior dispatch, answer, attempt directory, or alternate-account lease. Other claimable rows were temporarily held using recorded retry_after snapshots. X1 ran with one worker and chunk_size=1, then was gracefully stopped after the response was saved.

The probe completed successfully in about 148 seconds: one API_DISPATCH and one RESPONSE_SAVED, 85 completion characters, one Inspect choice, category CORRECT, and no fresh API error. Answer: D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\attempts\870607a92f3558677cefaea192d7a1c999aa23cb8851f82147cd7f6da9693033\0001\answer.json. Inspect log: D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\batches\565069e73b6f40749d881c7f55250944\inspect_logs\2026-10-16T01-20-08-00-00_task_Kfx5zQ5eXSRGZsD4drvq7x.eval.

Six earlier timeout cases X1_000001–X1_000006 were checked against their Inspect `.eval` samples and attempt folders: the dispatched attempts had no completion choices and no `answer.json`. They were moved to NEEDS_REVIEW; no uncertain request was resent. All other temporary retry_after values were restored from D:\codex\BENCHMARK\OptiRSA_SiliconFlow_Backend_20261016\tasks\X1\history\x1_single_probe_isolation_20261016_011937Z.json.

The temporary probe config and manifest were archived. X1 config was restored to two workers with no chunk_size override; the queue protocol fingerprint is restored to `04d10a69267cac64c9b8baab2275fbde703a09003dd527e2ee4b5cb09d73b361`. No other task, account, prompt, scorer, or model configuration was changed.
