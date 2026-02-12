# Chunk Preview 对标（企业级）与可集成能力

本文聚焦 `/chunk-preview`（前端页面）与 `/api/v1/documents/chunk-preview*`（后端接口），总结我们已经具备的能力，以及下一步可集成的企业级增强点。

## 1. 目标体验（快速结论）

主流企业级知识库 / 检索增强产品的 chunk preview 通常强调：

- 可视化预览（chunks 列表 + 定位 / 高亮）
- Parent-Child / 层级切块的可解释性
- 单 chunk 启用 / 禁用（跳过入库）
- 预处理 / 清洗规则可见、可回放、可 diff
- chunk_size / overlap / separator 等参数可调，并可导入导出

## 2. 本项目已对齐的关键能力

- 策略专属参数（enterprise tuning）
  - `parent_child`: `child_ratio` / `min_child_size`（后端支持 + 前端 sidebar 可调）
  - Response `params.strategy_params` 回显（便于复现与前后端对齐）
- Parent-Child 展示与可用性
  - Chunk List 支持 Flat / Hierarchy 视图（按 `metadata.parent_id` 分组折叠）
  - Chunk Card 显示 PARENT / CHILD 标签（便于快速审核层级切块效果）
- 跳过（SKIP）chunk
  - 单条 chunk 可切换 SKIP（前端仅做 ingestion/export 层过滤）
  - Confirm/submit 以及 manual payload 默认排除 SKIP chunk
  - 导出可选是否包含 SKIP chunk（用于审计）

## 3. 下一步建议（按优先级）

### P0：清洗 / 预处理规则与 diff 预览

目标：把“清洗”从黑盒变成可审计、可复现的可视化流程，降低脏数据进入 embedding 的概率。

- 规则层：去页眉页脚、去多余空白、去 URL/邮箱/脚注、统一换行等
- 预览层：清洗前后 diff + 命中统计（次数、覆盖率）
- 交互层：规则开关 + 参数化（可导出 / 可导入）

落地建议：

- 优先复用现有 pipeline clean-preview / llm-clean-preview（如果存在），把它们编排到 chunk preview 的 stepper 中。

### P1：结构化上下文（Hierarchical context prefixing）

目标：避免“无上下文的碎片”导致召回质量下降。

- 对 markdown/office 结构解析出的 `header_path` / `section` 元数据，在 embedding 阶段拼接轻量前缀（不破坏原文定位）
- Preview 增加“Embedding 视图”：展示原始 chunk vs embedding text

### P1：质量门禁（Quality Gate）与建议闭环

目标：把当前的 `quality_gate`/`recommendations` 变成“可操作”的 UI。

- 指标：`coverage_ratio`、`overlap_waste_ratio`、`gap_count`、`duplicate_count`、`short_count`
- 建议：一键应用（例如：提高/降低 overlap、切换策略、启用 `separator_max_chunk_size` 等）

### P2：评测与回归（检索模拟 / RAGAS）

目标：让 chunking 的修改可以量化评估，而不是靠肉眼。

- 支持对同一份文档的多组策略做 A/B 对比
- 补齐离线评测脚本、指标落盘、阈值告警（质量门禁）

## 4. 风险与治理建议（企业级落地要点）

- 可复现：preview/ingestion 相关参数应在响应与导出配置中回显（含策略参数、pipeline 覆盖、清洗规则版本）
- 可审计：SKIP、清洗命中、chunk 改写等应形成可追溯元数据（至少在导出 / 入库 metadata 中可选开启）
- 性能护栏：大文档（例如 >2000 chunks）需要分页 / 虚拟列表，以及搜索过滤性能优化（可加索引 / 缓存）

