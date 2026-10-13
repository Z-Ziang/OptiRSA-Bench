# OptiRSA-Bench：G1 / G2 / G3 / X1 完整评测数据集

本目录是已冻结 V3.1 英文全池的清爽交付版本，共 **563 个拓扑来源标识、8,619 条 Case**。每个 Case 都有完整题面、标准答案、冻结 Validator 所需的科学输入以及可核验来源。整理目录没有修改题目、答案、任务目标，也没有生成新 Case。

## 1. 数据是什么

|任务|做什么|数量|正式结果统计|
|---|---|---:|---|
|G1|图表示转换：边列表、邻接表、邻接矩阵之间转换|2,430|正确 / 不正确|
|G2|检查给定路径是否为合法简单有向路径，并判断错误类型|2,815|正确 / 不正确|
|G3|求两组源宿的最短路径，并检查是否共享同一有向链路|2,248|正确 / 不正确|
|X1|求一条全局最短路径，按题目指定的跳数或物理长度|1,126|最优 / 可行次优 / 不可行 / 缺失合规解|
|合计||8,619||

这是图推理数据。没有频谱占用状态、槽位需求 w、并发 RSA 分配或 WUFR 目标；这些字段应记为“不适用”，不能填成 0 利用率。X1 是图上最短路径，不是频谱可行最短路。本批 X1 均为有解请求，没有新增无解题或 REJECT 接口。G3 的冻结任务要求最短路及重叠判定，并非只输出一个布尔值。

来源为 `GX1_V3_1_BILINGUAL_FULLPOOL_FINAL_20261002.zip`，其冻结科学核心为 V3.0、生产版本为 3.1.0-bilingual-fullpool。中文版本、历史模型答案、Agent 文件和生产中间日志未放进本目录。后来 X3 派生 X1 的额外数据也未混入这 1,126 条。

## 2. 怎么找某个拓扑的某个任务

```
G-X1-cases/
  case_sets/
    TB_REAL_TOP_17_CONUS30_n30/
      collection.json
      G1/
        collection.json
        G1_...... /
          public/system_prompt.txt
          public/user_prompt.txt
          private/root_case.json
          private/truth.json
          private/reference_output.json
          private/validation.json
          identity.json
          metadata.json
      G2/ ...
      G3/ ...
      X1/ ...
    ...其他拓扑...
    _index/                 全量清单及分布统计
  evaluation/               Inspect 入口、评分程序、冻结 Validator、依赖版本
  source_evidence/           原始冻结清单和验收证据
```

上面的拓扑文件夹只是结构示意，具体名称以 `case_sets/_index/topology_summary.csv` 为准。每个拓扑先按来源 ID 命名，再附节点数；每个任务内一个 Case 一个文件夹。共享图结构的不同来源不因结构相似被自动合并。

**发给模型的只有 `public` 中两份文本。** `private` 用于程序评分，不能送给模型，不能让 Agent 读取。`root_case.json` 中含答案和最优值，因此属于私有评分输入。公开发布带答案的 Benchmark 时，应在运行模型的代码中保持这条边界。

`identity.json` 记录来源、原始 Case ID 和文件 SHA256；`metadata.json` 记录拓扑、规模、变体、seed 与输入字符数。`collection.json` 是各文件夹的说明。

## 3. 新电脑直接运行

需要 Python 3.12。运行平台与 API Key 由评测者自行选择。本包固定 Inspect AI 0.3.278、OpenAI SDK 3.29.0；完整锁定依赖在 `evaluation/requirements-lock.txt`。这些是源码和版本配置，安装脚本通过 pip 安装实际框架，不依赖原作者电脑或服务器。

在仓库根目录进入 `G-X1-cases`。Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\evaluation\setup.ps1
.\.venv\Scripts\python.exe .\evaluation\verify_dataset.py
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --task all --limit-per-task 2 --offline-reference --output .\outputs\offline_acceptance
```

Linux：

```bash
bash evaluation/setup.sh
.venv/bin/python evaluation/verify_dataset.py
.venv/bin/python evaluation/run_eval.py --task all --limit-per-task 2 --offline-reference --output outputs/offline_acceptance
```

离线 reference 模式用标准答案验收评分链路，不请求模型，也不构成模型成绩。安装依赖需要网络；安装完成后的离线验收不联网。

复制 `evaluation/model_config.example.json` 为 `evaluation/model_config.local.json`，填写实际 `model`、`base_url`。API Key 只放环境变量 `BENCH_API_KEY`，不要写入 Git 文件。在设置好环境变量后，先小批调用：

```powershell
.\.venv\Scripts\python.exe .\evaluation\run_eval.py --config .\evaluation\model_config.local.json --task all --limit-per-task 2 --output .\outputs\model_pilot
```

全池评测去掉 `--limit-per-task 2`；按任务运行可设 `--task X1`；按拓扑运行可设 `--topology` 为 CSV 中的完整 topology_id 或 folder。中断后用完全相同的参数和输出目录加 `--resume`。已收到并评分的答卷不重复请求；服务错误可以恢复重试。`.runner.lock` 防止同一输出目录被多个进程同时派发；若异常退出留下锁，先确认记录的主机/PID 已结束再人工移除。

默认 temperature=0、示例输出预算32768、并发4、请求超时300秒、传输重试2次。不同实验请单独冻结模型版本、思考模式、上下文/输出预算和参数；改变配置应使用新输出目录。`--dry-run` 可先验证选样及公开输入，不发请求。G1邻接矩阵的完整输出可能较长，应先检查模型支持的输出上限并测量答案Token量，保证足够预算；无法容纳完整输出的配置要单独报告，不能与完整预算实验混算。字符数不是 Token 数，需用实际模型 tokenizer 或平台 usage 统计 Token，不能静默截断题面。

结果目录包含 Inspect `.eval` 日志、逐 Case 原始回答 `answers/*.json`、`results.jsonl`、按模型及任务汇总的 `summary.csv/json`。程序没有模型工具或文件读取权限，私有答案不作为 target 传给模型。

## 4. 怎么评分

详情见 `evaluation/SCORING_PROTOCOL_中文.md`。G1/G2/G3按冻结 Validator 正确与否统计；X1合法但路径更长是次优，违反路径/成本约束是不可行，无法解析或不满足输出结构是缺失。保留完整模型原答，只允许移除整份回答外层的一层代码围栏，并同时保存未移除围栏的严格分数。不会搜索回答里某段 JSON 或修补模型决策。

API 超时、网络失败、平台错误与评分程序异常单独统计，不计为模型答错。完成覆盖率和已评分正确率必须同时报告。G3冻结Validator仍要求其原定义；不擅自放宽多最短路、链路方向或共享判定规则。X1优于保存真值的合法路径会进入 REVIEW_ORACLE，不能判模型失败。

## 5. 分布与使用限制

实际范围：5–500 节点；563 个拓扑来源标识，561 个 canonical graph hash。来源分类：{"floor5_generated": 85, "controlled_gabriel_reference_extension": 360, "first_stage_generated": 20, "real": 98}。不是563张都为真实运营网，合成拓扑需单独统计。

|规模|拓扑数|G1|G2|G3|X1|合计|
|---|---:|---:|---:|---:|---:|---:|
|5–10|38|228|190|148|76|642|
|11–29|97|582|485|388|194|1649|
|30–59|84|504|420|336|168|1428|
|60–100|107|642|535|428|214|1819|
|101–142|26|52|130|104|52|338|
|143–200|44|88|220|176|88|572|
|201–300|55|110|275|220|110|715|
|301–400|56|112|280|224|112|728|
|401–500|56|112|280|224|112|728|

|任务|变体|Case数|
|---|---|---:|
|G1|ADJACENCY_LIST_TO_ADJACENCY_MATRIX|326|
|G1|ADJACENCY_LIST_TO_EDGE_LIST|563|
|G1|ADJACENCY_MATRIX_TO_ADJACENCY_LIST|326|
|G1|ADJACENCY_MATRIX_TO_EDGE_LIST|326|
|G1|EDGE_LIST_TO_ADJACENCY_LIST|563|
|G1|EDGE_LIST_TO_ADJACENCY_MATRIX|326|
|G2|DISCONNECTED_PATH|563|
|G2|NODE_LINK_MISMATCH|563|
|G2|REPEATED_NODE|563|
|G2|VALID|563|
|G2|WRONG_DIRECTION|563|
|G3|HOP_COUNT__shared_false|563|
|G3|HOP_COUNT__shared_true|560|
|G3|TOTAL_LENGTH_KM__shared_false|563|
|G3|TOTAL_LENGTH_KM__shared_true|562|
|X1|HOP_COUNT|563|
|X1|TOTAL_LENGTH_KM|563|

输入字符数（system＋user，不是Token）：

|任务|最短字符数|最长字符数|
|---|---:|---:|
|G1|3231|24007|
|G2|2496|86958|
|G3|2451|124577|
|X1|1474|123600|

8,619 是原冻结 Case 记录数。公开题面按 task＋system/user 消息精确匹配，存在21组重复、21条冗余记录，即8,598个唯一公开问题。来源记录完整保留；重复关系见duplicate_public_questions.csv。不要把重复问题当作独立统计样本；可根据清单预声明去重选样，再固定各模型使用同一选样。

所有563拓扑的详细数量如下，也可直接用 `topology_summary.csv` 或 `case_distribution.csv` 分析。不同任务的数量与题目变体不同，不应假设每个拓扑任务数相等。seed 表示生成记录，不自动证明样本统计独立；做泛化实验应按拓扑/图结构划分开发与测试。

|拓扑ID|节点|来源|G1|G2|G3|X1|
|---|---:|---|---:|---:|---:|---:|
|FLOOR5_GEN_000001|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000002|142|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000003|101|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000004|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000005|143|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000006|171|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000007|171|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000008|200|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000009|80|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000010|100|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000011|100|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000012|60|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000013|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000014|101|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000015|142|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000016|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000017|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000018|201|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000019|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000020|300|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000021|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000022|301|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000023|400|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000024|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000025|401|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000026|500|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000027|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000028|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000029|80|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000030|60|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000031|100|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000032|80|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000033|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000034|142|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000035|101|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000036|121|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000037|171|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000038|143|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000039|200|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000040|171|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000041|30|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000042|59|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000043|44|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000044|44|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000045|171|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000046|143|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000047|200|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000048|143|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000049|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000050|201|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000051|300|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000052|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000053|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000054|301|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000055|400|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000056|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000057|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000058|401|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000059|500|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000060|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000061|7|floor5_generated|6|5|3|2|
|FLOOR5_GEN_000062|10|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000063|7|floor5_generated|6|5|3|2|
|FLOOR5_GEN_000064|10|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000065|29|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000066|20|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000067|11|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000068|20|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000069|44|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000070|30|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000071|59|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000072|44|floor5_generated|6|5|4|2|
|FLOOR5_GEN_000073|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000074|201|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000075|300|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000076|250|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000077|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000078|301|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000079|400|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000080|350|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000081|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000082|401|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000083|500|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000084|450|floor5_generated|2|5|4|2|
|FLOOR5_GEN_000085|80|floor5_generated|6|5|4|2|
|GABRIEL_CONTROLLED_N005_000|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_001|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_002|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_003|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_004|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_005|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_006|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_007|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_008|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N005_009|5|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_000|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_001|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_002|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_003|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_004|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_005|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_006|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_007|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_008|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N010_009|10|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_000|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_001|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_002|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_003|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_004|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_005|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_006|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_007|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_008|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N015_009|15|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_000|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_001|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_002|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_003|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_004|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_005|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_006|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_007|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_008|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N020_009|20|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_000|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_001|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_002|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_003|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_004|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_005|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_006|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_007|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_008|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N025_009|25|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_000|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_001|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_002|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_003|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_004|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_005|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_006|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_007|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_008|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N030_009|30|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_000|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_001|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_002|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_003|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_004|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_005|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_006|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_007|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_008|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N035_009|35|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_000|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_001|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_002|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_003|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_004|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_005|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_006|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_007|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_008|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N040_009|40|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_000|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_001|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_002|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_003|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_004|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_005|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_006|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_007|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_008|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N045_009|45|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_000|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_001|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_002|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_003|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_004|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_005|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_006|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_007|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_008|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N050_009|50|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_000|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_001|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_002|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_003|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_004|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_005|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_006|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_007|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_008|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N055_009|55|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_000|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_001|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_002|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_003|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_004|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_005|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_006|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_007|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_008|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N060_009|60|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_000|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_001|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_002|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_003|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_004|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_005|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_006|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_007|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_008|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N065_009|65|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_000|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_001|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_002|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_003|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_004|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_005|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_006|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_007|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_008|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N070_009|70|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_000|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_001|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_002|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_003|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_004|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_005|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_006|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_007|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_008|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N075_009|75|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_000|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_001|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_002|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_003|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_004|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_005|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_006|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_007|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_008|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N080_009|80|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_000|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_001|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_002|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_003|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_004|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_005|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_006|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_007|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_008|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N085_009|85|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_000|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_001|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_002|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_003|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_004|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_005|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_006|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_007|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_008|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N090_009|90|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_000|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_001|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_002|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_003|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_004|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_005|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_006|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_007|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_008|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N095_009|95|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_000|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_001|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_002|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_003|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_004|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_005|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_006|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_007|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_008|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N100_009|100|controlled_gabriel_reference_extension|6|5|4|2|
|GABRIEL_CONTROLLED_N125_000|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_001|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_002|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_003|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_004|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_005|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_006|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_007|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_008|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N125_009|125|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_000|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_001|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_002|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_003|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_004|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_005|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_006|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_007|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_008|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N150_009|150|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_000|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_001|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_002|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_003|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_004|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_005|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_006|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_007|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_008|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N175_009|175|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_000|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_001|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_002|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_003|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_004|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_005|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_006|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_007|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_008|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N200_009|200|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_000|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_001|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_002|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_003|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_004|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_005|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_006|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_007|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_008|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N225_009|225|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_000|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_001|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_002|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_003|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_004|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_005|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_006|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_007|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_008|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N250_009|250|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_000|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_001|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_002|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_003|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_004|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_005|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_006|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_007|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_008|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N275_009|275|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_000|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_001|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_002|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_003|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_004|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_005|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_006|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_007|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_008|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N300_009|300|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_000|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_001|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_002|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_003|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_004|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_005|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_006|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_007|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_008|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N325_009|325|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_000|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_001|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_002|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_003|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_004|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_005|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_006|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_007|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_008|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N350_009|350|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_000|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_001|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_002|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_003|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_004|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_005|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_006|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_007|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_008|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N375_009|375|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_000|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_001|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_002|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_003|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_004|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_005|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_006|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_007|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_008|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N400_009|400|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_000|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_001|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_002|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_003|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_004|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_005|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_006|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_007|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_008|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N425_009|425|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_000|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_001|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_002|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_003|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_004|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_005|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_006|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_007|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_008|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N450_009|450|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_000|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_001|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_002|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_003|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_004|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_005|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_006|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_007|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_008|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N475_009|475|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_000|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_001|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_002|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_003|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_004|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_005|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_006|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_007|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_008|500|controlled_gabriel_reference_extension|2|5|4|2|
|GABRIEL_CONTROLLED_N500_009|500|controlled_gabriel_reference_extension|2|5|4|2|
|GEN_000001|5|first_stage_generated|6|5|2|2|
|GEN_000002|30|first_stage_generated|6|5|4|2|
|GEN_000003|60|first_stage_generated|6|5|4|2|
|GEN_000004|60|first_stage_generated|6|5|4|2|
|GEN_000005|101|first_stage_generated|2|5|4|2|
|GEN_000006|101|first_stage_generated|2|5|4|2|
|GEN_000007|101|first_stage_generated|2|5|4|2|
|GEN_000008|143|first_stage_generated|2|5|4|2|
|GEN_000009|143|first_stage_generated|2|5|4|2|
|GEN_000010|201|first_stage_generated|2|5|4|2|
|GEN_000011|201|first_stage_generated|2|5|4|2|
|GEN_000012|201|first_stage_generated|2|5|4|2|
|GEN_000013|301|first_stage_generated|2|5|4|2|
|GEN_000014|301|first_stage_generated|2|5|4|2|
|GEN_000015|301|first_stage_generated|2|5|4|2|
|GEN_000016|301|first_stage_generated|2|5|4|2|
|GEN_000017|401|first_stage_generated|2|5|4|2|
|GEN_000018|401|first_stage_generated|2|5|4|2|
|GEN_000019|401|first_stage_generated|2|5|4|2|
|GEN_000020|401|first_stage_generated|2|5|4|2|
|TB_REAL::TOP_100_SPIRALIGHT|15|real|6|5|4|2|
|TB_REAL::TOP_101_TATANID|142|real|2|5|4|2|
|TB_REAL::TOP_102_TELECOMSERBIA|6|real|6|5|4|2|
|TB_REAL::TOP_103_UNIC|15|real|6|5|4|2|
|TB_REAL::TOP_104_USA100|100|real|6|5|4|2|
|TB_REAL::TOP_105_VIA|9|real|6|5|4|2|
|TB_REAL::TOP_10_BREN|10|real|6|5|4|2|
|TB_REAL::TOP_11_CANARIE|24|real|6|5|4|2|
|TB_REAL::TOP_12_CANARIE|19|real|6|5|4|2|
|TB_REAL::TOP_14_CESNET|12|real|6|5|4|2|
|TB_REAL::TOP_15_CLARANET|15|real|6|5|4|2|
|TB_REAL::TOP_16_CONUS100|100|real|6|5|4|2|
|TB_REAL::TOP_17_CONUS30|30|real|6|5|4|2|
|TB_REAL::TOP_18_CONUS6077|60|real|6|5|4|2|
|TB_REAL::TOP_19_CONUS6079|60|real|6|5|4|2|
|TB_REAL::TOP_1_ABILENE|11|real|6|5|4|2|
|TB_REAL::TOP_20_CONUS75|75|real|6|5|4|2|
|TB_REAL::TOP_21_CORONET|60|real|6|5|4|2|
|TB_REAL::TOP_22_COST|37|real|6|5|4|2|
|TB_REAL::TOP_23_CRLNETWORKSERVICES|33|real|6|5|4|2|
|TB_REAL::TOP_24_CWIX|23|real|6|5|4|2|
|TB_REAL::TOP_25_DARKSTRAND|28|real|6|5|4|2|
|TB_REAL::TOP_26_DIGEX|31|real|6|5|4|2|
|TB_REAL::TOP_28_ELIBACKBONE|20|real|6|5|4|2|
|TB_REAL::TOP_29_EON|19|real|6|5|4|2|
|TB_REAL::TOP_2_ANS|18|real|6|5|4|2|
|TB_REAL::TOP_30_EPOCH|6|real|6|5|4|2|
|TB_REAL::TOP_31_ERNET|16|real|6|5|4|2|
|TB_REAL::TOP_32_FUNET|24|real|6|5|4|2|
|TB_REAL::TOP_33_GAMBIA|12|real|6|5|4|2|
|TB_REAL::TOP_34_GBLNET|8|real|6|5|4|2|
|TB_REAL::TOP_35_GEANT|22|real|6|5|4|2|
|TB_REAL::TOP_37_GERMANY50|50|real|6|5|4|2|
|TB_REAL::TOP_38_GETNET|7|real|6|5|4|2|
|TB_REAL::TOP_39_GRNET|34|real|6|5|4|2|
|TB_REAL::TOP_3_ARNES|17|real|6|5|4|2|
|TB_REAL::TOP_40_GTSCZECHREPUBLIC|26|real|6|5|4|2|
|TB_REAL::TOP_41_GTSPOLAND|26|real|6|5|4|2|
|TB_REAL::TOP_42_HIBERNIACANADA|10|real|6|5|4|2|
|TB_REAL::TOP_43_HIBERNIAGLOBAL|53|real|6|5|4|2|
|TB_REAL::TOP_44_HIBERNIAIRELAND|6|real|6|5|4|2|
|TB_REAL::TOP_45_HIBERNIANIRELAND|15|real|6|5|4|2|
|TB_REAL::TOP_46_HIBERNIAUK|13|real|6|5|4|2|
|TB_REAL::TOP_47_HIBERNIAUS|20|real|6|5|4|2|
|TB_REAL::TOP_48_HOSTWAYINTERNATIONAL|16|real|6|5|4|2|
|TB_REAL::TOP_49_IBM|18|real|6|5|4|2|
|TB_REAL::TOP_4_ARPANET|20|real|6|5|4|2|
|TB_REAL::TOP_50_INTEGRA|27|real|6|5|4|2|
|TB_REAL::TOP_51_IRIS|50|real|6|5|4|2|
|TB_REAL::TOP_52_ISTAR|19|real|6|5|4|2|
|TB_REAL::TOP_53_ITALY|21|real|6|5|4|2|
|TB_REAL::TOP_54_JANOSUS|26|real|6|5|4|2|
|TB_REAL::TOP_55_JGN2PLUS|11|real|6|5|4|2|
|TB_REAL::TOP_56_JPN12|12|real|6|5|4|2|
|TB_REAL::TOP_57_JPN25|25|real|6|5|4|2|
|TB_REAL::TOP_58_JPN48|48|real|6|5|4|2|
|TB_REAL::TOP_59_KAREN|22|real|6|5|4|2|
|TB_REAL::TOP_5_ATMNET|21|real|6|5|4|2|
|TB_REAL::TOP_60_LAMBDARAIL|19|real|6|5|4|2|
|TB_REAL::TOP_61_LAYER42|6|real|6|5|4|2|
|TB_REAL::TOP_63_MARWAN|6|real|6|5|4|2|
|TB_REAL::TOP_64_MEMOREX|19|real|6|5|4|2|
|TB_REAL::TOP_65_METRONA|33|real|6|5|4|2|
|TB_REAL::TOP_66_MZIMA|14|real|6|5|4|2|
|TB_REAL::TOP_67_NETRAIL|7|real|6|5|4|2|
|TB_REAL::TOP_68_NETWORKUSA|35|real|6|5|4|2|
|TB_REAL::TOP_69_NEWNET|26|real|6|5|4|2|
|TB_REAL::TOP_6_BBNPLANET|27|real|6|5|4|2|
|TB_REAL::TOP_70_NEXTGEN|16|real|6|5|4|2|
|TB_REAL::TOP_71_NOBELEU|28|real|6|5|4|2|
|TB_REAL::TOP_72_NOBELGERMANY|17|real|6|5|4|2|
|TB_REAL::TOP_73_NOBELUS|14|real|6|5|4|2|
|TB_REAL::TOP_74_NOEL|19|real|6|5|4|2|
|TB_REAL::TOP_75_NSFNET13|13|real|6|5|4|2|
|TB_REAL::TOP_76_OPTUNETSWEDEN|25|real|6|5|4|2|
|TB_REAL::TOP_78_PACKETEXCHANGE|21|real|6|5|4|2|
|TB_REAL::TOP_79_PALMETTO|45|real|6|5|4|2|
|TB_REAL::TOP_7_BEYONDTHENETWORK|29|real|6|5|4|2|
|TB_REAL::TOP_81_PIONIERL3|27|real|6|5|4|2|
|TB_REAL::TOP_82_POLSKA|12|real|6|5|4|2|
|TB_REAL::TOP_83_PORTUGAL|26|real|6|5|4|2|
|TB_REAL::TOP_84_PSINET|24|real|6|5|4|2|
|TB_REAL::TOP_85_RAILTELINDIA|19|real|6|5|4|2|
|TB_REAL::TOP_87_REDIRIS|18|real|6|5|4|2|
|TB_REAL::TOP_88_RENATER|27|real|6|5|4|2|
|TB_REAL::TOP_89_RENATER1999|24|real|6|5|4|2|
|TB_REAL::TOP_8_BICS|33|real|6|5|4|2|
|TB_REAL::TOP_90_RENATER2001|24|real|6|5|4|2|
|TB_REAL::TOP_91_RENATER2004|24|real|6|5|4|2|
|TB_REAL::TOP_92_RENATER2006|26|real|6|5|4|2|
|TB_REAL::TOP_93_RENATER2008|26|real|6|5|4|2|
|TB_REAL::TOP_94_RENATER2010|37|real|6|5|4|2|
|TB_REAL::TOP_95_RNPBRAZIL|10|real|6|5|4|2|
|TB_REAL::TOP_96_SAGO|18|real|6|5|4|2|
|TB_REAL::TOP_97_SANET|46|real|6|5|4|2|
|TB_REAL::TOP_98_SANREN|7|real|6|5|4|2|
|TB_REAL::TOP_99_SAVVIS|19|real|6|5|4|2|
|TB_REAL::TOP_9_BIZNET|28|real|6|5|4|2|

## 6. V5 R1评分与已知复核项

本包实际评分使用 `GX1_V5_FORMAL_PROTOCOL_FROZEN_R1_20261003` 中原字节保留的 Validator，与目前本机 Inspect GX1 科学代码相同。按公开题面中六位有效数字的链路长度计算全局最短路，避免用模型看不到的更高精度长度评分。

`private/reference_output.json` 是原始生产参考；`private/evaluation_reference_output.json` 是 V5 公开数字合同下的离线验收参考。两者路径和决定不变，只在加权题中把声明的总长度重算为公开链路长度之和。原始 root、truth 和 reference 全部保留。

冻结 V5 标记 `G3_000260` 存在公共权重下多最短路导致的共享判定歧义。本包保留这条数据并标 REVIEW，默认批量队列跳过：交付8,619条，默认可派发8,618条，G3默认2,247条。

V5历史划分为100拓扑/1,476条 CALIBRATION_EXPOSED 和463拓扑/7,143条 FORMAL_UNSEEN_HELDOUT，保存于cohort manifest和每Case metadata。这描述原冻结时的历史暴露情况；后来已测过的题不能仅凭该字段称为新盲测。

本包保留V5科学规则，调用与日志使用独立Inspect执行版本。示例模型配置不等于历史V5所有运行参数；复现旧运行须核对source_evidence/V5_R1/FROZEN_PROTOCOL.json并新建对应配置，不能混算。

## 7. 验收与复现

已检查源 ZIP 的 root/truth 哈希、两条公开消息与源 actual_llm_request 一致、每个参考答案经原冻结 Validator 通过。验收报告在 `evaluation/verification`，全包文件哈希在 `FILE_MANIFEST.csv`。这不等同于已经完成全池模型评测。

`evaluation/verify_dataset.py` 可重验全部文件与参考答案，`evaluation/summarize.py --output <结果目录>` 可重算汇总。原始冻结数据不需要另外下载。仓库中的必要科学文件使用相对路径，整目录移动后可运行。

本目录的第三方框架遵循各自许可证，见 `THIRD_PARTY_NOTICES.md`。整理本身不赋予作者尚未声明的数据授权条款；数据许可证以仓库作者最终声明为准。
