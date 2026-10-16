# Algorithm 输入接口

五个公开任务的结构化问题保存在 `benchmark_case.instance`。
算法实际评测时读取由它确定性编译得到的 `case_xxxxxx.npz`，不再重复提供 Algorithm JSON。

`compile_algorithm_input` 校验 canonical instance，并构建只读的拓扑、
邻接关系、频谱 bitset 和题目提供的路径对象。它不会搜索路径、选择槽位、优化目标，
也不会调用 reference/oracle；这些由算法实现和正式评测器负责。

`write_compiled_algorithm_case` 将校验后的 instance 写成 NPZ。
`load_compiled_algorithm_case` 使用 `numpy.load(..., allow_pickle=False)` 加载，
返回只读 `CompiledAlgorithmCase`。NPZ 不含 object 数组或 pickle。

频谱约定：bit `i=1` 表示该槽位已占用；每条 320 槽有向链路使用 5 个 `uint64`。
O1 保存 fixed path，O2-S/O2-C 保存 candidate paths，X2/X3 不保存预置路径。

计时：`solve_time_ms` 从 NPZ 加载并构造 `CompiledAlgorithmCase` 完成后开始，
不包含编译和文件 I/O。公开 `instance` 不重复保存 `schema_version`；固定的
`ALGORITHM_INPUT_V1_0` 由 NPZ 元数据和任务合同承载。
