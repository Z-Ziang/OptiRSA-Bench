# OptiRSA-Bench：L5 同源家族的 X2/X3 完整评测数据包

这个包交给一台新电脑后，可以直接查看 Case、统计分布，并通过 Inspect AI 调用你自己的 LLM 平台进行 X2/X3 批量评测。数据、标准答案、评分源码和必要的科学 Validator 都在包里；不需要原服务器、原始历史 ZIP、D/F 盘路径或本项目其他任务。

本包从既有 **3,102 个五任务完整 L5 家族**提取 **X2 5,238 条、X3 3,102 条，共 8,340 条唯一 Case**。它是这些家族的两个任务视图，不包含 O1/O2-S/O2-C、I/G 或动态任务的 Case 载荷。保留 L5 来源关系供同源分析，不能把本包说成有五任务输入。

## 1. 这些题目让模型做什么？

X2 是一个请求的自主路由与频谱分配：给网络和可用频谱，模型自己找路线与起始槽。先选择最少跳数的合法方案，再比较分配后的 WUFR。

X3 是多个同时到来的请求的联合分配：必须全部一起成功才 ACCEPT，否则整体 REJECT。先最小化新增频谱占用 ΔTSO，再比较 WUFR。这里不限制为预计算的 K 条路线。

两种任务都有有解和无解 Case。参考答案是一种最优方案，并非必须逐字匹配的唯一答案；同样达到最优值的其他合法方案也接受。评分时有解分最优、可行次优、不可行、缺失合规解四类；无解正确拒绝单独统计。详见 evaluation/SCORING_PROTOCOL_中文.md。

## 2. 目录如何阅读？

```text
OptiRSA_Bench_L5_X2_X3/
  README_中文.md
  AI_ASSISTANT_PROMPT_中文.txt
  RELEASE_CHECKLIST.md
  THIRD_PARTY_NOTICES.md
  case_sets/
    CONUS30_n30_TB17/
      collection.json
      X2/
        collection.json
        <Case UID 前16位>/
          public/system_prompt.txt
          public/user_prompt.txt
          private/root_case.json
          private/private_truth.json
          private/reference_output.json
          private/validation.json
          identity.json
          metadata.json
      X3/...
    DARKSTRAND_n28_TB25/...
    ...其他拓扑...
    _index/
      cases.jsonl
      case_distribution.csv
      topology_summary.csv
      coverage_scale_task.csv
      families.csv
      family_members.csv
      case_request_features.csv
      graph_structure_metrics.csv
      dataset_summary.json
  evaluation/
    run_eval.py
    inspect_tasks.py
    benchlib.py
    summarize.py
    verify_dataset.py
    model_config.example.json
    requirements-lock.txt
    setup.ps1 / setup.sh
    frozen/       冻结 Validator、依赖科学模块与任务合同
    vendor/       Inspect AI 与安装依赖 wheels
    verification/ 构建验收记录
```

同名不同规模或不同来源编号的拓扑不会混在一起。74 个拓扑来源文件夹对应 73 个不同 graph hash；RENATER2006/RENATER2008 的源标识保留各自目录，但其图哈希相同。Snapshot 共 804 个图与频谱位图组合。Snapshot 不等于独立随机生成过程，一张图和一个初态可共享给多组请求。

每个 Case 文件夹可单独检查题面、评分材料与身份，但直接评分需要包中 evaluation/frozen 的公共科学代码。对外发送模型的只有 public 下两段文本。private 内的最优值、参考答案、真值、评分源码和全数据索引不得被模型作为输入、检索或工具内容读取。

metadata.json 提供初始利用率、规模、请求数、槽位需求、来源状态和暴露分组。identity.json 提供图/快照/模型输入哈希、源档案与成员哈希、冻结 Validator 身份和 L5 家族关联。不会把科学相同的 Case 为多个家族重复复制。

## 3. 新电脑先安装什么？

建议使用 64 位 Python 3.12。包内包含固定版本 Inspect AI 0.3.278、OpenAI SDK 3.29.0、jsonschema 4.26.0，以及 Python 3.12 的 Windows x64 / Linux x86_64（glibc≥2.34，例如Ubuntu22.04/24.04）安装 wheels。安装脚本只建立包内 .venv，不修改全局 Python。Windows 离线安装与运行已经验收；Linux 提供依赖文件，但没有在一台Linux电脑上实际执行验收。Python 解释器、你的模型平台访问与 API Key 仍需接收方自己提供。macOS、ARM 或其他 Python 版本可联网执行 requirements-lock.txt，但本次不声称验证了那些平台。

Windows PowerShell，在解压目录中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\evaluation\setup.ps1
.\.venv\Scripts\python.exe .\evaluation\verify_dataset.py --report .\verification_local.json
```

Linux x86_64：

```bash
bash evaluation/setup.sh
.venv/bin/python evaluation/verify_dataset.py --report verification_local.json
```

如需首次离线验收 Inspect 的组织与评分链路，无需 API Key：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --offline-reference --limit-per-task 2 --output .\results\offline_check
```

这会回放包内参考答案，测试评分和日志，不是模型能力结果。

## 4. 接入你自己的平台

复制 evaluation/model_config.example.json 为 evaluation/model_config.json。填写 provider、真实模型 API ID、平台 base_url、输出 Token 上限与并发。默认支持 OpenAI-compatible Chat Completions；如使用 Inspect 的其他原生 provider，需自行安装对应 provider 的官方依赖并将 provider 改为 native_inspect、model 填 Inspect 模型标识。API Key 只通过 api_key_env 指定的环境变量读取，配置文件不放 Key。

默认参数是 temperature=0、max_output_tokens=8192、connections=4、max_retries=2、timeout_seconds=300、chunk_size=50。extra_body 默认为空；思考开关与预算因模型平台而异，必须由接收方明确冻结和记录，不能冒称不同平台参数等效。未配置 response_format 强制 JSON，也未给模型提供评分公式。若要改变输入、思考预算或强制输出协议，应作为独立实验保存。

Windows 设置 Key，不会在终端回显：

```powershell
$benchSecret = Read-Host '输入本次平台 API Key' -AsSecureString
$env:BENCH_API_KEY = [System.Net.NetworkCredential]::new('', $benchSecret).Password
```

Linux 可 `read -s BENCH_API_KEY; export BENCH_API_KEY`。真实请求由你自己的账号计费；包本身不包含账号或凭据。

先做仅检查、不调用模型的 dry-run：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --dry-run --topology CONUS30 --limit-per-task 2 --output .\results\unused
```

再做每任务两题的平台接口试评：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --config .\evaluation\model_config.json --limit-per-task 2 --output .\results\model_pilot
```

确认模型ID、回答格式、Token费用、网络和时延后，使用新目录开始全量：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --config .\evaluation\model_config.json --output .\results\model_full
```

只评一个拓扑或任务可加 `--topology CONUS30 --task X2`；按规模可加 `--scale 11-29`。Linux 用 `.venv/bin/python` 替换 Windows 的 Python 路径即可。

## 5. 中断、恢复和查看结果

恢复必须使用同样的配置、筛选条件与 output 路径，加 `--resume`。例如：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --config .\evaluation\model_config.json --output .\results\model_full --resume
```

程序读取已关闭的 Inspect 日志并恢复单题结果；已有收到且完成评分的答卷不重复请求，无论最优、次优、不可行或格式失败。服务错误可在下一次恢复中再试。配置、输入清单、题面哈希、评测代码和框架版本都绑定到 run_config.json；改变它们需要新运行目录。运行目录有独占锁，两个程序不能重复领取同一队列；异常断电遗留锁时，先核对锁内主机/PID已退出，再仅删除该锁。

每完成一批就输出 answers/<UID>.json、results.jsonl、summary.csv、summary.json，完整 Inspect 日志位于 inspect_logs。保存原始最终答卷、四分类、严格格式诊断、词典序 Gap、无解正确拒绝、服务错误、Token 用量和时延。Inspect 原始日志是详细复核入口；分享结果时检查平台是否返回额外的推理内容，不必把它当公开模型答卷发布。

如果师兄用其他程序得到答卷，也可以单独评分：`python evaluation/benchlib.py --case-dir case_sets/实际拓扑/X2或X3/实际Case编号 --answer 答卷.txt`。将实际路径填入即可；评分仍使用同一套冻结 Validator，格式和分类规则不变。

输入仍为原英文题面，未截断。字符长度分布在后面的统计中；它不是目标模型的 Token 数，不保证小模型上下文一定容纳最大 Case。应对你实际平台测量输入 Token，并为输出/思考预留窗口。上下文不支持必须单独记录，不能截断网络再当同一道题评测。

## 6. 科学状态与公开发布边界

本包的完整性与评分链路可验收，但源 interface_status=REVIEW_OBJECTIVE_DEFINITION 被完整保留。原冻结规则不向模型提供 WUFR 公式，因此二级指标的公开接口定义仍是一个需要在论文中说明的限制；没有在打包时悄悄解除这个状态。默认 --purpose exploratory 可以做探索性评测；--purpose formal 会因待审接口停止。

源 X2/X3 真值分别保存 EXACT_CERTIFIED 或 INFEASIBLE_CERTIFIED，原 Validator PASS 随 Case 保留。构建对全部 8,340 例重新比对题面、拓扑、频谱位图和请求，检查参考答案的资源可行性及一级目标；完整冻结 Validator 的抽样复评分与离线 Inspect 验收见 evaluation/verification。没有对全池独立重求全局最优。

具体复验包括全部50,040个Case载荷文件的哈希与8,340例公开输入绑定，以及按图哈希×任务×有无解分组抽取的254个参考答案完整Validator复评分，均通过。评分适配器另外验证了16项四分类/拒绝/格式处理行为；本机模拟API的服务错误重试与恢复不重复请求也通过。这些验收没有调用真实模型，不是模型能力实验。

这些 Case 来自历史公开、试评或已暴露资料，不宣称是全新的盲测集。不同任务 Case 可能共享家族、请求或初态，不能简单当 8,340 个完全独立网络；统计置信区间与开发/测试切分应按图、Snapshot 与家族分组。低/中/高初始占用不等于已证明的 LLM 难度等级。

仅打包本地交付，没有上传 GitHub。公开前请完成 RELEASE_CHECKLIST.md 中的作者、许可和来源授权确认。原资料没有提供可直接采用的数据许可，本包不会替项目作者擅自授予 MIT/CC 等许可证。

## 7. 数据的详细分布

下方统计由本包 cases.jsonl 自动生成；更细的逐题参数在 case_sets/_index/case_distribution.csv 与 case_request_features.csv，可用 Excel 打开筛选。所有拓扑与两任务数量见 topology_summary.csv，所有 3102 家族和 Case 关系见 families.csv、family_members.csv。

### 规模、任务与真值分布

| 节点规模 | X2 | X3 | X2 ACCEPT / REJECT | X3 ACCEPT / REJECT |
| --- | --- | --- | --- | --- |
| 5-10 | 472 | 296 | 469 / 3 | 293 / 3 |
| 11-29 | 4271 | 2524 | 4149 / 122 | 2338 / 186 |
| 30-59 | 475 | 270 | 453 / 22 | 239 / 31 |
| 60-100 | 5 | 3 | 4 / 1 | 2 / 1 |
| 101-142 | 15 | 9 | 8 / 7 | 3 / 6 |
| 143-200 | 0 | 0 | 0 / 0 | 0 / 0 |
| 201-300 | 0 | 0 | 0 / 0 | 0 / 0 |
| 301-400 | 0 | 0 | 0 / 0 | 0 / 0 |
| 401-500 | 0 | 0 | 0 / 0 | 0 / 0 |

总量：X2 ACCEPT 5,083 / REJECT 155；X3 ACCEPT 2,875 / REJECT 227。这是标准答案的可行性分布，不是模型成功率。大多数完整家族来自小拓扑，143节点以上没有本包家族；不能用本包声称九规模档已均衡。

### 初始资源占用

| 任务 | LOW（<25%） | MID（25%–<45%） | HIGH（≥45%） |
| --- | --- | --- | --- |
| X2 | 81 | 4711 | 446 |
| X3 | 81 | 2575 | 446 |

按3,102个家族锚点计：LOW 81、MID 2,575、HIGH 446；初始占用率范围 14.16%–67.48%，中位数 35.00%。这些是观测利用率分箱，不是新增正式难度标签，也不能证明模型求解难度。

### 请求参数

X2全部为单请求；X3中R=2有3,098例，R=4有4例。R=4覆盖很少，不能宣称已有充分并发规模梯度。每条链路320槽，编号0–319；w=2/3/5/9是完整所需槽数。请求OD最短跳数为1–19跳，中位数3，P90约6。

| 任务 | w=2 | w=3 | w=5 | w=9 |
| --- | --- | --- | --- | --- |
| X2 | 1287 | 1352 | 1304 | 1295 |
| X3 | 1538 | 1583 | 1564 | 1527 |

上表按单条请求计数；X3一个Case包含多个请求，不能把这些次数当Case数。本包任务均为full-path，K对本包不适用。可行路径数未重新全量计算，LLM难度和真实模型tokenizer测量值目前UNKNOWN；Case清单seed字段也保留UNKNOWN，不从文件名猜测。

### 最终模型输入长度

| 任务 | 最小字符数 | 中位数 | P90字符数 | 最大字符数 |
| --- | --- | --- | --- | --- |
| X2 | 5837 | 13999 | 19696 | 132875 |
| X3 | 8038 | 16236 | 22146 | 135070 |

这里是最终system和user内容的字符总和，不含provider消息封装开销，不是Token估计。实际模型API返回的prompt_tokens/input_tokens应保存在运行结果中，不用固定字符倍数冒充实测Token。

### 所有拓扑来源文件夹

| 拓扑文件夹 | 节点 | Snapshot | 家族关联 | X2 | X3 |
| --- | --- | --- | --- | --- | --- |
| EPOCH_n6_TB30 | 6 | 12 | 27 | 41 | 27 |
| LAYER42_n6_TB61 | 6 | 6 | 13 | 21 | 13 |
| MARWAN_n6_TB63 | 6 | 7 | 19 | 32 | 19 |
| TELECOMSERBIA_n6_TB102 | 6 | 13 | 31 | 46 | 31 |
| GETNET_n7_TB38 | 7 | 7 | 24 | 38 | 24 |
| NETRAIL_n7_TB67 | 7 | 7 | 27 | 47 | 27 |
| GBLNET_n8_TB34 | 8 | 15 | 21 | 22 | 21 |
| VIA_n9_TB105 | 9 | 16 | 49 | 83 | 49 |
| HIBERNIACANADA_n10_TB42 | 10 | 14 | 38 | 59 | 38 |
| RNPBRAZIL_n10_TB95 | 10 | 8 | 47 | 83 | 47 |
| ABILENE_n11_TB1 | 11 | 15 | 51 | 84 | 51 |
| CESNET_n12_TB14 | 12 | 16 | 51 | 85 | 51 |
| GAMBIA_n12_TB33 | 12 | 20 | 55 | 88 | 55 |
| JPN12_n12_TB56 | 12 | 8 | 43 | 73 | 43 |
| POLSKA_n12_TB82 | 12 | 11 | 42 | 74 | 42 |
| HIBERNIAUK_n13_TB46 | 13 | 9 | 59 | 106 | 59 |
| NSFNET13_n13_TB75 | 13 | 10 | 47 | 82 | 47 |
| NOBELUS_n14_TB73 | 14 | 8 | 47 | 83 | 47 |
| CLARANET_n15_TB15 | 15 | 17 | 49 | 81 | 49 |
| HIBERNIANIRELAND_n15_TB45 | 15 | 11 | 39 | 65 | 39 |
| SPIRALIGHT_n15_TB100 | 15 | 15 | 63 | 108 | 63 |
| UNIC_n15_TB103 | 15 | 18 | 66 | 105 | 66 |
| ERNET_n16_TB31 | 16 | 18 | 49 | 78 | 49 |
| NEXTGEN_n16_TB70 | 16 | 15 | 23 | 28 | 23 |
| ARNES_n17_TB3 | 17 | 10 | 52 | 91 | 52 |
| NOBELGERMANY_n17_TB72 | 17 | 10 | 46 | 80 | 46 |
| ANS_n18_TB2 | 18 | 16 | 49 | 82 | 49 |
| IBM_n18_TB49 | 18 | 11 | 47 | 82 | 47 |
| REDIRIS_n18_TB87 | 18 | 10 | 45 | 79 | 45 |
| SAGO_n18_TB96 | 18 | 16 | 18 | 18 | 18 |
| CANARIE_n19_TB12 | 19 | 14 | 52 | 88 | 52 |
| ISTAR_n19_TB52 | 19 | 14 | 42 | 66 | 42 |
| LAMBDARAIL_n19_TB60 | 19 | 11 | 46 | 80 | 46 |
| MEMOREX_n19_TB64 | 19 | 7 | 46 | 81 | 46 |
| NOEL_n19_TB74 | 19 | 11 | 48 | 83 | 48 |
| RAILTELINDIA_n19_TB85 | 19 | 8 | 47 | 82 | 47 |
| SAVVIS_n19_TB99 | 19 | 9 | 45 | 79 | 45 |
| ARPANET_n20_TB4 | 20 | 9 | 47 | 82 | 47 |
| ELIBACKBONE_n20_TB28 | 20 | 17 | 52 | 86 | 52 |
| HIBERNIAUS_n20_TB47 | 20 | 10 | 43 | 76 | 43 |
| ATMNET_n21_TB5 | 21 | 10 | 45 | 79 | 45 |
| ITALY_n21_TB53 | 21 | 11 | 48 | 84 | 48 |
| PACKETEXCHANGE_n21_TB78 | 21 | 12 | 51 | 87 | 51 |
| GEANT_n22_TB35 | 22 | 9 | 44 | 76 | 44 |
| CWIX_n23_TB24 | 23 | 17 | 51 | 84 | 51 |
| CANARIE_n24_TB11 | 24 | 17 | 55 | 90 | 55 |
| FUNET_n24_TB32 | 24 | 13 | 52 | 89 | 52 |
| PSINET_n24_TB84 | 24 | 8 | 44 | 77 | 44 |
| RENATER1999_n24_TB89 | 24 | 14 | 18 | 19 | 18 |
| RENATER2001_n24_TB90 | 24 | 11 | 41 | 69 | 41 |
| RENATER2004_n24_TB91 | 24 | 10 | 47 | 81 | 47 |
| OPTUNETSWEDEN_n25_TB76 | 25 | 10 | 44 | 79 | 44 |
| GTSCZECHREPUBLIC_n26_TB40 | 26 | 13 | 18 | 19 | 18 |
| GTSPOLAND_n26_TB41 | 26 | 12 | 46 | 80 | 46 |
| JANOSUS_n26_TB54 | 26 | 6 | 40 | 73 | 40 |
| NEWNET_n26_TB69 | 26 | 2 | 42 | 79 | 42 |
| RENATER2006_n26_TB92 | 26 | 12 | 62 | 84 | 48 |
| RENATER2008_n26_TB93 | 26 | 11 | 54 | 79 | 54 |
| BBNPLANET_n27_TB6 | 27 | 8 | 43 | 75 | 43 |
| INTEGRA_n27_TB50 | 27 | 8 | 44 | 76 | 44 |
| PIONIERL3_n27_TB81 | 27 | 8 | 45 | 79 | 45 |
| RENATER_n27_TB88 | 27 | 11 | 48 | 85 | 48 |
| DARKSTRAND_n28_TB25 | 28 | 13 | 52 | 88 | 52 |
| NOBELEU_n28_TB71 | 28 | 11 | 49 | 85 | 49 |
| BEYONDTHENETWORK_n29_TB7 | 29 | 9 | 46 | 80 | 46 |
| CONUS30_n30_TB17 | 30 | 13 | 53 | 90 | 53 |
| DIGEX_n31_TB26 | 31 | 13 | 49 | 82 | 49 |
| BICS_n33_TB8 | 33 | 13 | 48 | 82 | 48 |
| METRONA_n33_TB65 | 33 | 8 | 46 | 82 | 46 |
| GRNET_n34_TB39 | 34 | 9 | 39 | 70 | 39 |
| NETWORKUSA_n35_TB68 | 35 | 1 | 34 | 68 | 34 |
| COST_n37_TB22 | 37 | 1 | 1 | 1 | 1 |
| CORONET_n60_TB21 | 60 | 2 | 3 | 5 | 3 |
| TATANID_n142_TB101 | 142 | 2 | 9 | 15 | 9 |

表中家族关联按每个拓扑源标识统计。相同graph hash的不同来源名称保留原身份；不能把该列直接相加声称独立家族更多。

### 可复算

可执行 `python evaluation/analyze_distribution.py --output results/distribution` 重新生成规模×任务×占用×R×可行性统计。逐题详情、图结构、原始来源哈希与家族证据均随包提供。所有统计不使用模型得分筛选Case。
