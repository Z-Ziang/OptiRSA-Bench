# S1/X4 Dynamic Algorithm API

S1/X4 的正式 Algorithm 入口是 run-config/environment-level，不是把完整 `root_case.json` 交给算法解析：

```python
from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark

def solve(static_context, observation):
    # 只读取当前 observation；static_context 只在 Episode 开始编译一次
    ...

result = run_algorithm_benchmark(
    "evaluation_case/S1/algorithm/run_configs/topologybench_netrail/A_MEDIUM_MATCH.json",
    solve,
    task_type="S1",
    dataset_root="<public-dataset-root>",
)
```

Harness 负责读取 generation spec 和 materialized Episode，并驱动 `reset()` → `solve(static_context, observation)` → `step(action)`。callback 不接收未来请求、完整 Episode、私有连接/释放台账、reference/oracle、difficulty、seed、load 或 lambda。S1 observation 提供当前 K 条路径范围内的全部可行 `(path_rank, slot_start)`；X4 observation 不提供候选路径/候选动作/path rank。

`run_algorithm_episode(...)` 保留为 `EVALUATOR_INTERNAL / FROZEN_EPISODE_REPLAY`，只用于内部回归和审计，不是公共算法主入口。

动态 320 槽频谱使用 `ceil(slot_count / 64)` 个 `numpy.uint64` words；因此正式数据每条有向链路为 5 words。bitset 的 free/occupied 语义与现有科学实现一致，并有 round-trip 测试。
