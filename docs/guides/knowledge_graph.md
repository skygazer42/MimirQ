# Knowledge Graph (知识图谱)

MimirQ 的 Knowledge Graph（KG）以“事件（Event）—实体（Entity）”为核心结构：
- 从文档切片（chunk）中抽取事件（title/summary/content + 引用/extra）。
- 识别并归一化实体（name/type/normalized_name）。
- 建立事件↔实体关系，用于图谱可视化与 KG recall/搜索。

## 开启与配置

### 关键环境变量
- `KG_ENABLED=true`：启用 KG 功能（API/Graph 页面/抽取等）。
- `KG_EXTRACT_REPLACE_EXISTING=true`：重复抽取同一文档时，替换旧事件（避免重复写入）。
- `KG_EXTRACT_PRUNE_ORPHAN_ENTITIES=true`：替换/删除事件后，清理无任何事件关联的“孤立实体”。
- `KG_EXTRACT_EVIDENCE_REQUIRED=true`：证据优先抽取（推荐开启）。
  - 启用后：事件->实体边、实体->实体关系边需要能在 chunk 原文中找到 `evidence_quote/span` 才会落库。
  - 目的：减少噪声与幻觉边，避免 KG 关系扩展召回漂移，提升 RAG 可控性与可解释性。

### 抽取 Prompt 选择
KG 抽取支持 3 种选项（按优先级从高到低）：
1) 请求参数 `prompt_template_id` / `prompt_template_key` / `prompt_ab_experiment_key`
2) Settings 中的 `extract_prompt_*` 配置
3) 内置默认提示词

前端路径：`/settings` → KG 抽取提示词配置（包含“替换旧事件 / 清理孤立实体”开关）。

## 抽取流程（推荐）
1) 上传并完成文档处理（status=completed）
2) 触发抽取：
   - UI：文档详情弹窗 → `抽取 KG`（默认异步）
   - API：`POST /kg/documents/{document_id}/extract?async=true`
3) 图谱查看：`/graph`（Live 模式）

### 异步 vs 同步
- `async=true`：入队任务（需要 `TASK_QUEUE_ENABLED=true`），API 返回 `202`，并在文档 metadata 写入 `kg_task_id`。
- `async=false`：直接执行抽取（兼容旧行为）。

## 图谱 API（常用）
- `GET /kg/graph`：拉取图谱投影（支持文档 scope）。
  - `include_entity_links=true`：启用“实体-实体共现”边（基于共享事件数）。
  - `min_shared_events`：共现阈值（默认 2）。
  - `max_entity_links`：共现边上限（避免图过密）。
- `GET /kg/graph/expand?node_id=...`：按节点扩展邻居（同样支持共现边参数）。
- `GET /kg/stats`：轻量统计（events/entities/links/type breakdown）。
- `GET /kg/graph/export`：导出 GraphML（便于 Gephi/Cytoscape 等外部工具）。
- `GET /kg/events/{event_id}`：事件详情（含实体列表，受文档权限约束）。
- `GET /kg/entities/{entity_id}`：实体详情（含最近事件与邻居实体，受文档权限约束）。
- `DELETE /kg/documents/{document_id}`：删除文档对应 KG 事件（可选清理孤立实体）。

## 前端图谱（/graph）
- Live：从后端实时加载（支持导出 GraphML）。
- File：支持导入 `.graphml/.xml` 本地文件进行可视化。
- 交互：
  - “实体连线”开关：开启/关闭实体共现边。
  - `Co≥N`：循环调整共现阈值。
  - 侧边栏 `KG Detail`：点击节点查看实体/事件详情（Live 模式）。

## 权限与隔离
KG API 默认按 tenant + 文档权限进行过滤：
- `document_ids` 会进行去重与可访问性校验。
- KG 节点搜索/详情接口会限制到“当前可访问文档”的事件/实体集合，避免跨数据集/跨文档泄漏。

## KG Diagnostics（评测 / 诊断）

MimirQ 提供一个 **Dynamic OneEval 风格**的 KG search 诊断接口，用于提升抽取/搜索质量并可回归：

- API：`POST /api/v1/evaluations/kg/search/diagnostics`
- Seed：使用 RAGAS regression cases（`reference_sources.chunk_id` 作为 evidence ground truth）

### 常用参数
- `dataset_id`（必填）
- `max_cases`：最多评测多少个 case（默认 50）
- `k`：Hit@K / MRR@K / Recall@K 的 cutoff（默认 10）
- `auto_extract_kg=true`：评测前自动补齐 evidence 文档的 KG 抽取（默认开启）
- `hardcase_mode=llm`：对 baseline 失败 case 自动生成 hardcases（knowledge pressure + reasoning pressure）
- `persist_run=true`：持久化本次诊断的紧凑快照（params + summary + per-case attribution），用于后续对比/回归

### Run 查询接口（持久化后可用）
- `GET /api/v1/evaluations/kg/search/diagnostics/runs?dataset_id=...`：列出最近的 diagnostics runs
- `GET /api/v1/evaluations/kg/search/diagnostics/runs/{run_id}`：获取某次 run 的详情（含 compact items）

### 影响结果的开关（建议同时关注）
- `KG_ENABLED=true`：KG 总开关
- `KG_SKILL_ENABLED=true` 或请求 `extract_skills=true`：启用 Skill/SOP 抽取（SkillNet 风格 know-how 节点）
- `KG_SKILL_EVIDENCE_REQUIRED=true`：仅持久化可被 chunk-local evidence_quote/span 证据锚定的 Skill 节点/边（减少噪声，避免 relation expansion 漂移）
  - `KG_RELATION_ENABLED=true` 或请求 `extract_relations=true`：启用 triples / taxonomy edges（关系扩展的重要前置）
  - `KG_SEARCH_RELATION_EXPANSION_ENABLED=true`：KG search 召回阶段启用 relation-driven expansion
  - `KG_SEARCH_RELATION_MENTION_EVIDENCE_MULTIPLIER=0.7`：对 evidence_source=mention 的关系边进行权重惩罚（降低低信号边导致的扩展漂移）
