# RAG Quality Loop (Per-Dataset Regression + Evidence Sources) (Design)

**Date:** 2026-02-05

## Context / Goal

这个项目的目标是打造**企业级知识库系统（对标 RAGFlow）**，核心优化点在 **RAG pipeline 的质量闭环**，而不是“回答能力/对话产品形态”。

我们要把 RAG 做到“每一步极致可控、可观测、可回归”：

- 入库前：预检 + 画像（数据分布可视化 + 报告）
- 入库中：预处理（粗筛/规整）→ 解析（统一 Markdown）→ 治理（让 Markdown 更可检索）→ 切块（分布可控）→ 可选 KG
- 入库后：RAG 评测（回归/门禁/报告）驱动持续迭代

本设计聚焦“评测闭环”（质量回归 + 可审计证据），让 RAG 调参与治理优化可以被**量化、对比、复现**。

> Corridor：`AGENTS.md` 要求生成代码前使用 Corridor MCP 安全分析，但当前环境未配置 `corridor` MCP server；本轮以**人工安全审计 + 单测/类型检查 + 最小权限校验**替代。

## Key Decisions

1. **每个业务知识库（dataset）维护一套评测集**  
   - 评测框架通用（领域无关），内容由各业务数据集自维护。
   - 评测运行与报告以 `dataset_id` 为一等维度，避免跨库混跑导致指标失真。

2. **评测集形式：QA 对话的单轮用例**  
   - `question`：用户问题
   - `expected_answer`：标准答案（可选）

3. **强制证据来源（Reference Sources）**（用户确认：强制）  
   - 每条回归用例必须提供 `reference_sources[]`（至少 1 条）
   - 每条 source 至少包含 `document_id + chunk_id`
   - 允许/建议带 `quote`（证据摘录）以应对 pipeline 版本变化造成 chunk 失效

4. **必须覆盖不可回答（unanswerable）用例**  
   - 用例通过 `tags` 标记 `unanswerable`
   - 此类用例允许 `expected_answer` 为空
   - 评测不追求“答案文本相似”，而以**拒答/证据门禁信号**判定 PASS：必须 `abstain_triggered=true`

## Data Model

### Regression Case

存储模型（核心字段）：

- `dataset_id`：所属知识库（必填；企业闭环按库治理）
- `question: str`：问题（必填）
- `expected_answer: str | null`：标准答案（answerable 场景建议必填；unanswerable 可为空）
- `tags: string[]`：用例标签（至少用于 `unanswerable`）
- `reference_sources: ReferenceSource[]`：证据来源（必填，至少 1）
- `document_ids: UUID[]`：可选的召回 scope（优先级高于 dataset_id；用于限定只在某些文档内召回）
- `extra: {}`：扩展字段（语言、备注、答案风格、业务侧字段等）

### ReferenceSource

```ts
type ReferenceSource = {
  document_id: string; // UUID
  chunk_id: string;    // UUID
  // 以下为可选，但推荐：
  page_number?: number;
  start_char?: number;
  end_char?: number;
  doc_pipeline_key?: string; // `${document_id}:${pipeline_hash}` (debug/audit)
  pipeline_hash?: string;    // source chunk 对应版本（debug/audit）
  quote?: string;            // 证据摘录（用于 chunk_id 失效时的回退）
  label?: string;            // 人类可读注释（可选）
}
```

> 说明：强制 `chunk_id` 可以支撑 **ID-based** 召回命中指标（无需 LLM、稳定可回归）。`quote` 则用于处理“切块策略变化导致 chunk 不稳定”的现实问题。

## Workflows

### 创建用例（推荐路径）

1. 用户输入 `question` + 选择 `dataset`
2. 系统调用 `POST /api/v1/rag/retrieve-preview` 获取 top-k citations
3. 用户从 citations 中勾选“应当作为标准证据”的 chunk（形成 `reference_sources`）
4. 保存为回归用例

优势：
- 证据来源与系统真实检索形态一致，减少人工找 chunk 的成本
- 确保 reference 与检索/切块版本可审计

### 用例导入/导出（企业运维）

- 导出：按 dataset 导出 JSON bundle（不包含内部 id，方便跨环境/多租户迁移）
- 导入：按 `(dataset_id + question)` 匹配 upsert（支持 overwrite）
- 强校验：缺少 `reference_sources` / chunk_id 无效 → 返回错误列表，不静默吞掉

### 回归评测运行（dataset-scoped）

- 运行必须指定 `dataset_id`（或 case_ids 均属于同一 dataset）
- 运行会 snapshot：
  - retrieval 参数（top_k/threshold/mode/weights/reranker）
  - prompt template（id/key/ab）
  - abstain settings（enabled/min_citations/min_top_relevance_score）
- 每条用例输出：
  - RAGAS 指标
  - ID-based 召回命中指标
  - `abstain_triggered` 等证据门禁信号（用于 unanswerable 打分）

## Metrics & Scoring

### Metric Layers

1. **召回命中（确定性、低成本）**
   - `id_based_context_recall`
   - `id_based_context_precision`

2. **生成正确性（需要 expected_answer）**
   - `answer_similarity`（embedding）
   - `answer_correctness`（LLM + embedding，可选开启）

3. **忠实度/不胡说**
   - `faithfulness`

4. **不可回答拒答能力（unanswerable）**
   - 派生指标：`abstain_success`（0/1）
     - 规则：`tags` 含 `unanswerable` 时，必须 `abstain_triggered=true`

### Bucketed Summary

汇总必须分桶：
- `answerable`（无 `unanswerable` tag）
- `unanswerable`（含 `unanswerable` tag）

避免把拒答 KPI 与回答 KPI 混在一起导致误判。

### Stale Source Handling

当 `chunk_id` 因 pipeline 版本变化不可解析：
- 回退使用 `quote` 作为 reference_context
- 标记 `stale_source=true`
- **不混入主 KPI**，单独统计（推动评测集维护）

## Reporting & CI Gate

### Dataset Health / Report Integration

数据集级别报告应展示：
- 最近一次 regression run（时间、参数快照、指标摘要）
- `unanswerable` 的 `abstain_success_rate`
- stale sources 数量与列表（需要修复）
- top failing cases（用于迭代）

### CI Gate

CI 脚本按 dataset 运行：
- 导入用例集
- 运行 regression
- 对关键指标做阈值门禁（含 `abstain_success_rate`）

## Risks / Guardrails

- **安全/权限**：所有 reference_sources 的 document/chunk 必须通过 tenant + ACL 校验（禁止越权引用）。
- **成本控制**：指标可配置；ID-based 指标作为默认稳定底座；LLM 指标可按需开启。
- **可复现**：run.params 必须 snapshot 关键 settings + rag_params + prompt selection，避免“看起来变差但不可解释”。

