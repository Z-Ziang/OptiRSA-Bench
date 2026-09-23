# P0草案JSON Schema

本目录包含11类根对象Schema，均采用JSON Schema Draft 2020-12，并设置`additionalProperties:false`。

Schema负责：字段、类型、枚举、数组层级、条件字段和基本范围。

Schema不负责：跨文件编号、编号连续性、拓扑连通、物理—有向链路映射、路径连续、槽位冲突、状态重构、指标复算、动态事件排序与时间回放。这些规则列在字段映射清单的“额外Validator”列，由Codex在P0实现。

`schema_manifest.json`把目标交付目录中的文件模式映射到根Schema。
