# Knowledge Graph (知识图谱)

MimirQ 的 Knowledge Graph（KG）以“事件（Event）—实体（Entity）”为核心结构：
- 从文档切片（chunk）中抽取事件（title/summary/content + 引用/extra）。
- 识别并归一化实体（name/type/normalized_name）。
- 建立事件↔实体关系，用于图谱可视化与 KG recall/搜索。

## 开启与配置

### 关键环境变量
- `KG_ENABLED=true`：启用 KG 功能（API/Graph 页面/抽取等）。
- `KG_API_METRICS_ENABLED=true`：记录 KG API 的轻量指标（graph/expand/stats/export 的耗时与规模），用于线上观测与回归。
- `KG_EXTRACT_REPLACE_EXISTING=true`：重复抽取同一文档时，替换旧事件（避免重复写入）。
- `KG_EXTRACT_PRUNE_ORPHAN_ENTITIES=true`：替换/删除事件后，清理无任何事件关联的“孤立实体”。
- `KG_EXTRACT_EVIDENCE_REQUIRED=true`：证据优先抽取（推荐开启）。
  - 启用后：事件->实体边、实体->实体关系边需要能在 chunk 原文中找到 `evidence_quote/span` 才会落库。
  - 目的：减少噪声与幻觉边，避免 KG 关系扩展召回漂移，提升 RAG 可控性与可解释性。
- `EVENT_VECTOR_ENABLED=true` / `ENTITY_VECTOR_ENABLED=true`：把事件/实体向量写入 Milvus
  collection（`kg_events` / `kg_entities`），用于 KG vector recall。
- `KG_EXTRACT_EMBED_BATCH_SIZE=8`：KG 向量写入前的 embedding 请求批量上限。OpenAI-compatible
  provider（例如 DashScope `text-embedding-v4`）建议保持较小批量，避免大批量请求被 400 拒绝。

KG 抽取需要可用 LLM；KG vector recall 还需要 embedding provider 与 Milvus 主栈可用。Docker
主栈默认包含 Milvus，lite 模式不适合验证 KG Milvus 向量写入。

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

### pipeline_hash 版本化（重要）
当同一份文档被不同 pipeline（解析/切块/治理等配置）重复处理时，系统会同时存在多套 chunks/KG 数据。

- KG 抽取默认只作用于 **active pipeline**（`doc_metadata.active_pipeline_hash`，fallback `pipeline_hash`），避免把多个版本的 chunks 混在一起抽取。
- 如需对比不同版本（A/B）抽取漂移，可在抽取 API 里显式指定：
  - `POST /kg/documents/{document_id}/extract?pipeline_hash=ph_xxx`
  - 同时支持 `async=true`（worker 也会按该 `pipeline_hash` 选择 chunks）。

## 图谱 API（常用）
- `GET /kg/graph`：拉取图谱投影（支持文档 scope）。
  - `pipeline_hash=...`：可选；不填时默认按 active pipeline 过滤，防止跨版本混合。
  - `include_entity_links=true`：启用“实体-实体共现”边（基于共享事件数）。
  - `min_shared_events`：共现阈值（默认 2）。
  - `max_entity_links`：共现边上限（避免图过密）。
- `GET /kg/graph/expand?node_id=...`：按节点扩展邻居（同样支持共现边参数；支持 `pipeline_hash` 可选参数）。
- `GET /kg/graph/search`：节点搜索（UI autocomplete；支持 `pipeline_hash` 可选参数）。
- `GET /kg/stats`：轻量统计（events/entities/links/type breakdown；支持 `pipeline_hash` 可选参数）。
- `GET /kg/graph/export`：导出 GraphML（便于 Gephi/Cytoscape 等外部工具）。
  - `?gzip=true`：返回 gzip 压缩后的 GraphML（`Content-Encoding: gzip`，下载文件后缀为 `.graphml.gz`），适合大图导出。
- `POST /kg/search`：KG 搜索（召回 -> 扩展 -> 重排），返回事件列表 + entities/clues/stats。
- `GET /kg/events/{event_id}`：事件详情（含实体列表，受文档权限约束；支持 `pipeline_hash` 可选参数）。
- `GET /kg/entities/{entity_id}`：实体详情（含最近事件与邻居实体，受文档权限约束；支持 `pipeline_hash` 可选参数）。
- `DELETE /kg/documents/{document_id}`：删除文档对应 KG 事件（可选清理孤立实体）。

## KG Query-Mode Routing（local / global / drift）

Wave E 在现有 `kg_search` 管线上加入了 **query-mode routing**（不依赖 GraphRAG）：

- `local`：偏向“定位具体记录/局部关系”，收紧事件预算，提升实体权重阈值。
- `global`：偏向“全局汇总/分布/总体趋势”，扩大覆盖预算。
- `drift`：偏向“变化/对比/同比环比”，进一步扩大覆盖预算，减少漏召回。
- `auto`：默认模式，按 query 形态做 deterministic 分类。

### 关键配置

- `KG_SEARCH_QUERY_MODE_DEFAULT=auto|local|global|drift`
- `KG_SEARCH_QUERY_MODE_CLASSIFIER_ENABLED=true|false`
- `KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS=40`
- `KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS=120`
- `KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS=140`
- `KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS=0.05`

### 运行时观测

`POST /kg/search` 返回中会带上模式决策信息：

- `query_mode.requested`
- `query_mode.resolved`
- `query_mode.confidence`
- `query_mode.reason_codes`

`stats` 与 metrics 中也会同步输出：

- `stats.query_mode`
- `stats.query_mode_confidence`
- `stats.query_mode_reason_codes`
- `kg.search.*` 事件中的 `query_mode`

排障建议：

1. 先看 `query_mode.resolved` 是否符合预期。
2. 若不符合，检查 `reason_codes`（例如 `drift_pattern/global_pattern/local_pattern`）。
3. 若需要强制固定行为，显式传 `query_mode=local|global|drift` 或关闭 classifier。

## Entity Resolution（实体消歧 / 合并拆分 / 可撤销）

Wave15 引入一套 **tenant-scoped** 的实体消歧（Entity Resolution）机制，用于治理“同名多实体 / 同义词碎片化 / 误抽取实体”等问题。

设计目标：
- **稳定 URL**：合并后旧实体 ID 仍可访问（通过 redirect 解析到 canonical id）。
- **可逆操作**：merge/split 产生 append-only action 记录，可撤销（undo）。
- **不绑定 pipeline_hash**：实体消歧是租户级治理，跨 pipeline 版本保持一致。

### Alias（别名）
- `GET /kg/entities/{entity_id}/aliases`：列出实体 aliases（会包含已合并/已弃用 id 上的 aliases）。
- `POST /kg/entities/{entity_id}/aliases`：新增 alias（会 normalize）。
- `DELETE /kg/entities/{entity_id}/aliases/{alias_id}`：删除 alias。
- `GET /kg/entities/{entity_id}/alias_suggestions?mode=offline|vector`：alias 建议（离线 deterministic / Milvus 相似度）。

### Merge（合并）/ Split（拆分）/ Undo（撤销）
- `POST /kg/entities/merge/preview`：预览合并影响（统计 + sample）。
- `POST /kg/entities/merge`：执行合并（source → target），会：
  - 重写事件-实体边（`kg_event_entities`）与关系边端点（`kg_relations`）。
  - 对 overlap events 做去重（避免同一事件出现重复 entity edge）。
  - 删除合并后产生的 self-relations（例如 source↔target 关系合并后变为 self）。
  - 创建 redirect：`kg_entity_redirects(from=source, to=target)` 以保持旧 ID 可用。
- `POST /kg/entities/split`：按 event_ids 从原实体拆出新实体（只移动选中的事件边/对应关系边）。
- `POST /kg/entities/resolution/actions/{action_id}/undo`：撤销 merge/split（best-effort，确定性）。

> 备注：split undo 会在新实体变为“孤立（无边/无关系/无 alias/无 redirect）”时 best-effort 删除该实体，以尽量恢复到拆分前的图形态。

### 向量一致性（可选）
实体 merge/split 默认 **不会**触发 Milvus 侧向量维护（避免测试/最小部署强依赖 Milvus）。

- `KG_ENTITY_RESOLUTION_UPDATE_VECTORS_ENABLED=false`（默认）：不做向量 side effects。
- 若开启为 `true`：merge 可能会删除 source entity 的向量并在 undo 时恢复（best-effort）。

## Predicate Ontology（谓词治理 / allowlist）

Wave15 引入 tenant-scoped 的 `kg_predicate_ontology`，用于治理 KG relation triples 的谓词集合（防止 schema 漂移）。

API：
- `GET /kg/ontology/predicates`
- `POST /kg/ontology/predicates`（upsert）
- `PATCH /kg/ontology/predicates/{predicate_id}`
- `DELETE /kg/ontology/predicates/{predicate_id}`

优先级（从高到低）：
1) DB 中 **enabled** predicates（若存在任意条，则以 DB 为准）
2) 环境变量 `KG_RELATION_ALLOWED_PREDICATES`（逗号/换行分隔）
3) 系统默认 allowlist

前端入口：`/prompts` 页面内的 “KG Predicate Ontology（谓词治理）”。

## KG Snapshots（快照）与 Diff（漂移对比）

当你需要诊断 **同一套文档**在不同 `pipeline_hash`（解析/治理/切块/抽取提示词等配置）下的 KG 规模漂移时，
可以使用 KG Snapshots API 导出一个 **轻量、默认 PII-safe** 的快照（计数 + 类型直方图），并对比两个快照的差异。

> 注意：快照按 **KG 表中的 `pipeline_hash`** 过滤（而不是按文档 metadata 选择）。
> 这意味着你可以对比同一份文档的历史/非激活版本，只要该版本对应的 KG 数据已经被抽取并落库。
> 如需补齐某个版本的 KG 数据，可用 `POST /kg/documents/{document_id}/extract?pipeline_hash=...` 显式抽取。

### 导出快照
- `GET /kg/snapshots/export?pipeline_hash=...&document_ids=...`

返回示例（简化）：
```json
{
  "schema": "mimirq.kg_snapshot.v1",
  "pipeline_hash": "ph_xxx",
  "docs": 12,
  "events": 340,
  "entities": 980,
  "links": 2100,
  "relations": 420,
  "entity_types": [{"type":"Skill","count":120}],
  "updated_at": "2026-02-27T00:00:00Z",
  "elapsed_sec": 0.123
}
```

### 对比两个 pipeline_hash
- `GET /kg/snapshots/compare?pipeline_hash_a=...&pipeline_hash_b=...&document_ids=...`

返回是 `mimirq.kg_snapshot_diff.v1`：
```json
{
  "schema": "mimirq.kg_snapshot_diff.v1",
  "pipeline_hash_a": "ph_a",
  "pipeline_hash_b": "ph_b",
  "delta": { "docs": 0, "events": 12, "entities": -3, "links": 20, "relations": 0 },
  "entity_types_delta": [{"type":"Skill","delta":+6}]
}
```

### 对比两个任意快照 payload
- `POST /kg/snapshots/diff`
  - body: `{ "snapshot_a": {...}, "snapshot_b": {...} }`

## 存储与数据模型（如何落库）

MimirQ 的 KG 默认不依赖图数据库，核心数据直接落在 PostgreSQL，并为向量召回额外写入 Milvus。

### PostgreSQL（事实存储 + provenance）
- `kg_source_events`：从 chunk 抽取的事件（chunk-scoped）。
  - 关键字段：`title/summary/content`，`document_id/chunk_id`，`references`（包含 `chunk_key/content_hash/content_len/page/start_char/end_char/source` 等）。
- `kg_entities`：实体表（实体去重主要依赖 `tenant_id + type + normalized_name` 的逻辑去重）。
  - 关键字段：`name/type/normalized_name/description`，`extra_data`（可放技能卡片、标签、工具等结构化信息）。
- `kg_event_entities`：事件↔实体边（事件里出现的实体、以及 Skill 节点与事件的连接也在这里）。
  - `weight`：边权重（Skill 边常用来表达置信度或强度）。
  - `extra_data`：证据落点（`evidence_quote/evidence_start_char/evidence_end_char/evidence_source`）。
- `kg_relations`：实体→实体关系边（triples + SkillNet 风格 taxonomy edges）。
  - `predicate/predicate_raw/confidence`：关系类型与置信度。
  - `references`：证据落点（同样包含 `evidence_quote/span` 与 chunk provenance）。

### Milvus（相似度召回）
- `kg_events`：事件内容向量（用于 KG search 的事件 recall）。
- `kg_entities`：实体向量（用于 KG search 的实体 recall；包含 Skill/Tag/Category 等类型）。

> 这意味着“KG 的存储”本质上就是：Postgres 做结构化事实与证据，Milvus 做相似度召回加速。

## KG 如何增强 RAG（面向集成）

KG 的目标不是替代 RAG，而是让 RAG 在“多跳关联 / 术语对齐 / know-how 技能”上更稳、更可控：

- KG query expansion（可选）：从 KG recall 的实体名衍生额外检索 query，降低 false negative。
  - 该能力由“检索编排层”统一提供，Evidence API（检索-only）与 LangGraph retrieve 节点都会复用同一套逻辑。
  - `RAG_KG_QUERY_EXPANSION_ENABLED=true`
  - `RAG_KG_QUERY_EXPANSION_MAX_ENTITIES=5`：最多选取多少个实体名参与扩展（按权重排序）。
  - `RAG_KG_QUERY_EXPANSION_MAX_QUERIES=5`：最多生成多少条扩展 query（每条 query = 原 query + 实体名）。
  - `RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT=0.15`：实体权重阈值（低于该值不参与扩展）。
  - `RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES=Skill,SkillTag,SkillCategory`：默认排除 SkillNet taxonomy 节点，避免 query 漂移（可按需调整）。
- KG chunk injection（可选）：把 KG recall 的事件 chunk 作为额外 evidence 注入检索结果，提升召回覆盖。
  - `RAG_KG_CHUNK_INJECTION_ENABLED=true`
  - `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS=5`：最多注入的 KG evidence chunks 数量上限。

- KG ranking features（可选）：把 KG 从 “召回扩展” 提升为 “排序信号来源”。
  - 当候选 chunk 带有 `retrieval_role="kg"`（来自 KG chunk injection）时，系统会在候选元数据里附加一组 **稳定、低基数** 的 KG 特征，用于后置精排（LTR 等）。
  - 这些特征只包含数值/布尔信号，不包含 tenant/dataset/event/entity 等 scope identifier，便于下游稳定解析与离线训练。

  当前特征（best-effort）：
  - `kg_pagerank`: KG 召回分数（工程近似，可视为 pagerank/graph score proxy）
  - `kg_shared_events`: 与 query 关键实体共享事件数（v1 先用注入事件计数近似）
  - `kg_path_length`: 图路径长度（v1 先用 1-hop 注入近似）
  - `kg_edge_conf_low|mid|high`: 边置信度桶（粗阈值 one-hot，低基数）
  - `kg_evidence_anchored`: 是否 evidence-anchored（布尔）

  与 LTR 集成：
  - LTR feature spec v2 会包含以上 KG 特征（`LTR_FEATURE_SPEC_VERSION=2`，详见 `docs/guides/reranking_ltr.md`）。

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
- 当请求显式带了 `document_ids` 但 ACL 过滤后没有任何可访问文档时：KG 搜索会返回空结果（不会退化为 tenant-wide 搜索）。
- 内部语义上，`document_ids=[]` 被视为“显式空 scope”（空集合），同样会返回空结果，用于防止误用导致 scope 变宽。

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
  - `KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX=0.4` / `KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX=0.7`：关系边置信度分桶阈值（low/mid/high），用于 clues/diagnostics 的可解释性与低基数特征
    - `conf < LOW_MAX` => `low`
    - `LOW_MAX <= conf < MID_MAX` => `mid`
    - `conf >= MID_MAX` => `high`
  - `KG_SEARCH_CLUES_ENABLED=true`：返回 KG search 的 `clues`（用于 UI/诊断解释 “为什么这条边/路径被纳入”）
    - 其中 `method=relation_expansion` 的 clues 会包含 `evidence_source/confidence_bucket` 以及 best-effort 的 `relation_id/document_id/chunk_id/event_id` provenance 字段
  - `KG_SEARCH_VECTOR_RECALL_ENABLED=false`：禁用 Milvus + embeddings 的 vector recall（用于 CI/离线环境）。
    - 召回会退化为 alias（lexical）+ event↔entity links（结构化）+ 可选 relation expansion。
  - `KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED=true`：启用离线、可复现的 graph embeddings（node2vec-like）用于 entity recall。
    - 仅在 vector recall 不可用/被禁用时生效：从 alias seeds 出发构建局部子图（events + 可选 relations），并用 random-walk embeddings 拉回额外实体候选。
    - 关键参数：`KG_SEARCH_GRAPH_EMBEDDINGS_DIM/NUM_WALKS/WALK_LENGTH/WINDOW_SIZE/TOP_K`。
