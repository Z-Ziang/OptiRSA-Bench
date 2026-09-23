# S1/X4 External Fragmentation Metric (EFM)

## 1. 链路级公式

对有空闲频谱槽位的有向链路 e：

`EFM_e = 1 - Bmax_e / F_e`

其中 `F_e` 是链路当前全部空闲 Frequency Slots 数量，`Bmax_e` 是最大连续空闲频谱块长度。空闲槽全部集中在一个连续块时 EFM=0；空闲资源越分散，EFM 越接近 1。

代码实现：`src/s1_x4/efm.py`。实现直接从 canonical 0/1 slot availability 计算整数 `F_e` 和 `Bmax_e`，只在最终比值处进行浮点除法，不从自然语言 Renderer 反解析指标。

## 2. 文献依据

1. E. J. Davalos, M. F. Romero, S. M. Galeano, D. A. Baez, A. Leiva, B. Baran, “Spectrum Defragmentation in Elastic Optical Networks: Two Approaches With Metaheuristics,” *IEEE Access*, vol. 7, pp. 119835–119843, 2019. DOI: 10.1109/ACCESS.2019.2937032. 该文明确给出链路 EFM：`1 - MaxBlock / FS_free`。
2. Y. Khorasani, A. Ghaffarpour Rahbar, M. Jafari-Beyrami, “A novel two-dimensional metric for fragmentation evaluation in elastic optical networks,” *Computer Networks*, vol. 216, 109275, 2022. DOI: 10.1016/j.comnet.2022.109275. 该文系统比较既有碎片度量，并将 External Fragmentation 作为经典基线之一讨论其局限。
3. R. Srivastava, Y. N. Singh, “A novel fragmentation metric and fragmentation-aware adaptive routing and spectrum allocation algorithm in elastic optical network,” *Optical Fiber Technology*, vol. 94, 104318, 2025. DOI: 10.1016/j.yofte.2025.104318. 该文将 EFM 作为既有 benchmark fragmentation metric，并明确写为最大连续空闲 FS 与总可用 FS 之比的补数。
4. 项目数据集规范也定义“平均链路外部碎片率”为有空闲槽位链路的链路外部碎片率算术平均，并把无空闲槽链路的最大连续空闲块长度记为 0。

## 3. F_e=0 的 Benchmark 边界约定

经典公式在 `F_e=0` 时出现 `0/0`，数学上未定义。V2.1.0 冻结以下工程/评测约定：

- `F_e > 0`：按经典公式计算数值 EFM。
- `F_e = 0`：`EFM_e = null`，`efm_defined=false`。
- Network EFM：仅对 `F_e>0` 的链路做算术平均。
- 若一个 Step 所有链路均无空闲槽：该 Step `network_efm=null`。
- Mean Network EFM：只对有定义的 Step 做算术平均；若整条 Episode 全部未定义，则为 null。

这一 `null/exclude` 规则是本 Benchmark 对经典公式未定义边界的显式约定，不宣称为上述文献的原始定义。
