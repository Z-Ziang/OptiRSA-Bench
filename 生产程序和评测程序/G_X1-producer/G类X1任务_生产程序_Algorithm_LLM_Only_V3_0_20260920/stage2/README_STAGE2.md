# Stage 2 使用说明

在 producer 根目录执行：

```powershell
python -m stage2.run_stage2 --canonical-root <CANONICAL_PACKAGE_ROOT> --output <DATASET_DIR> --seed 20260913
```

`<CANONICAL_PACKAGE_ROOT>` 必须是交接包中的 canonical-km package 根目录，或仅含 9 张 canonical physical JSON 的目录。完整 package 模式会保留 supplied package 的相对路径和 hash manifest，便于 fresh extraction 后重审。

Stage 2 固定生成 45 Case：G1/G2/G3/X1 分别为 11/11/11/12，每张冻结拓扑恰好 5 Case。生产只使用既有 Unified Producer 和 Unified exporter；不调用模型 API。

验证重点：

- `00_CANONICAL_TOPOLOGY_ACCEPTANCE_AUDIT.*`
- `GX1_TEACHER_DEMO_STAGE2_COVERAGE_AUDIT.json`
- `audit/CASE_INDEX.csv`
- `audit/TOPOLOGY_INDEX.csv`
- `audit/leak_scan.json`
- `SHA256SUMS.txt`

Teacher View 是展示包装；正式机器 Case 仍必须遵循 Unified Schema。
