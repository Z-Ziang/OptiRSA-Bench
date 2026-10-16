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
