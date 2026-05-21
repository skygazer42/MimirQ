# 表格 / TAG（Table Augmented Generation）

MimirQ 支持将结构化表格（CSV/XLS/XLSX）走 **TAG**（Table Augmented Generation）链路：把表格导入每文档 SQLite（Table Store），通过 **SQL 查询**（以及可选的 NL→SQL/语义过滤）来回答问题，而不是强行把大表切块嵌入进向量库。

从 Wave C 开始，DB Catalog connector 也可以按上限抽取行快照，写入 `dbrows` sidecar 文档进入同一套 Table Store/TAG 链路。

## 适用场景（RAG vs TAG）

- **RAG 更擅长**：非结构化文本问答（规章制度、方案、手册、合同条款解释等）
- **TAG 更擅长**：结构化表格查询/统计（筛选、聚合、排序、分组、数值比较）

常见判断：如果需求更像“查数/筛行/统计”，优先 TAG；如果更像“解释/归纳/引用原文”，优先 RAG。

## Table Store（结构化存储）

入库时对 `.csv/.xls/.xlsx`：

- 使用 pandas 读取表格
- 写入 `TABLE_STORE_DIR/{tenant_id}/{dataset_id}/{document_id}.sqlite3`
- 在文档 `doc_metadata.table_store` 中记录表资产（sheet、列信息、采样行等）
- 走 Table Store 的文档 **不进入** chunk/vector/BM25 等索引（避免成本爆炸/召回质量下降）

对 DB row sidecar（`file_type=dbrows`）同样遵循这套约束：只写入 per-document SQLite，不写入文本 chunk 索引。

> 注意：`.xls` 读取依赖运行环境（通常需要 `xlrd`）。若你们不计划支持旧格式，建议先用 LibreOffice/Pandoc 转成 `.xlsx`。

## 来自解析器的表格（PDF 解析 sidecar）

当 `table_store_enabled=true` 时，部分解析器（例如 PDF 的 Docling/DeepDoc 系列）会把表格作为独立的 “table segments” 输出（通常带 `metadata.content_type=table` / `doc_type_kwd=table`）。

MimirQ 会对这些表格做 best-effort：

- 把解析输出中的 **Markdown pipe table** 导入同一个 per-document SQLite Table Store
- 在文档 `doc_metadata.table_store` 中记录 `table_id/sheet_name/row_count/col_count/columns` 等元数据
- 因此数据集的「表格 / TAG」页面与 Chat→TAG 都能对 PDF 表格进行预览与查询

默认情况下这是一个 **sidecar** 能力（兼容历史行为）：解析器输出的 table segments 仍可能进入 RAG chunk 流程。

## TAG/RAG 独占路由（parser table sidecar exclusive）

从 Wave D 开始，可以启用“table sidecar 独占路由”，把解析器产出的表格块固定到 TAG 通道，避免表格噪声影响文本问答召回。

- 全局开关：`TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING=true`
- Pipeline 覆盖：`table_store_sidecar_exclusive_routing=true`
  - 可配置在 dataset/document pipeline（优先级高于全局）
- 生效前提：`table_store_enabled=true` 且解析 sidecar 导入成功（已写入 Table Store）

启用后行为：

- parser-emitted table segments 会继续导入 `doc_metadata.table_store`
- 这些 table chunks 会被排除出 vector/BM25 写入路径
- 非表格文本 chunks 继续正常走 RAG 索引
- 当文档只包含表格块时，任务会以 TAG-only 方式完成（不会因为“无 chunks”失败）

可审计元数据：

- `doc_metadata.table_store.routing`
  - `kind=tag_sidecar`
  - `exclusive_rag_routing_enabled`
- `doc_metadata.table_sidecar_routing`
  - `table_chunks_seen`
  - `table_chunks_excluded_from_rag`
  - `rag_exclusion_reason=table_sidecar_exclusive`
  - `excluded_samples`

数据集策略审计（用于运营排障）：

- `GET /api/v1/datasets/{dataset_id}/ingestion-policy`
- 响应中的 `table_routing_policy_audit` 会返回：
  - 全局默认值
  - 数据集 pipeline 默认值
  - 每条 ingestion rule 的 table 路由有效值和来源（`rule_pipeline_patch` / `dataset_pipeline_default` / `global_default`）

## 表格自动分流（推荐：小表 RAG / 大表 TAG）

在企业真实数据里，表格通常分两类：

- **小表**：几十/几百行，用 Markdown 解析后切块入库即可（RAG 也能很好用）
- **大表/多 Sheet/超宽表**：入库成本高且检索差，更适合 TAG（SQL/Text-to-SQL）

因此推荐开启 **auto route**：

- `table_store_enabled=true` + `table_store_auto_route=true`
- 处理器会根据阈值（行数/列数/Sheet 数/文件大小）决定该文件走 **RAG** 还是 **TAG**
- 决策会写入 `doc_metadata.table_routing`（便于审计/排障）

## 开关与安全边界

在后端 `.env` 中配置（参考 `.env.example` / `.env.example`）：

- `TABLE_STORE_ENABLED=true`：启用表格入库到 Table Store
- `TABLE_STORE_MAX_SHEETS=50`：最多导入的 Sheet 数（防止极端 Excel 占用资源；0 不限制）
- `TABLE_STORE_SAMPLE_ROWS=0`：不持久化采样行（合规/PII 场景建议）
- `TABLE_STORE_AUTO_ROUTE=true`：开启自动分流（小表继续走 RAG；大表走 Table Store）
- `TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING=true`：解析 sidecar 表格独占走 TAG（不进 vector/BM25）
- `TABLE_STORE_AUTO_ROW_THRESHOLD / TABLE_STORE_AUTO_COL_THRESHOLD / TABLE_STORE_AUTO_SHEET_THRESHOLD / TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD`：分流阈值
- `TABLE_QUERY_MAX_ROWS / TABLE_QUERY_MAX_COLS / TABLE_QUERY_MAX_BYTES`：限制 API 返回规模
- `TABLE_QUERY_MAX_SQL_CHARS / TABLE_QUERY_TIMEOUT_SEC / TABLE_QUERY_PROGRESS_OPS`：SQL 长度与执行时间保护（DoS 防护）

## 迁移建议（从兼容模式到独占模式）

1. 先在一个数据集启用 `table_store_sidecar_exclusive_routing=true`（不要一上来全局开）。
2. 复跑该数据集的代表性问答用例，确认文本问答的 evidence 更稳定、表格问答仍由 TAG 覆盖。
3. 检查 `doc_metadata.table_sidecar_routing` 与 `table_routing_policy_audit`，确认排除数量与策略来源符合预期。
4. 再逐步放大到更多数据集，最后再考虑全局 `TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING=true`。

SQL 执行器是 **SELECT-only**：

- 拒绝多语句（`;`）
- 只允许 `SELECT` / `WITH ... SELECT`
- 通过 sqlite authorizer 禁止 PRAGMA/ATTACH/写入/DDL，并限制只能读白名单 sheet 表
- 默认拒绝 `CROSS JOIN` / `NATURAL JOIN`（可用 `TABLE_QUERY_ALLOW_CROSS_JOIN` 显式放开）
- 多表查询最多允许 `TABLE_QUERY_MAX_JOIN_TABLES` 个表

## 使用方式（Web）

1. 入库时启用 `table_store_enabled`（可在「入库策略」里开启，或通过“预检 → 入库策略”一键生成并应用）
2. CSV/XLS/XLSX 入库完成后，进入数据集页面的「表格 / TAG」
3. 支持三类操作：
   - **SQL 查询**：手写 `SELECT` / `WITH SELECT`
   - **TAG 问答（NL→SQL）**：自然语言 → SQL → 执行 → 基于结果生成答案
   - **语义过滤（sem_filter，可选）**：对表格行做自然语言过滤（LLM 批量判定；有行数/列数/单元格长度保护阈值）

## NL→SQL（TAG 问答）

开启：

- `TABLE_NL2SQL_ENABLED=true`
- 配置 `LLM_API_KEY`（以及 `LLM_API_BASE/LLM_MODEL(_FAST)`）
- `TABLE_LLM_ALLOW_RESULT_EGRESS=true`：允许把 **SQL 查询结果（rows）** 发给 LLM 生成答案（默认关闭）

接口：

- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/ask`

### NL→SQL schema-link diagnostics（Wave B）

为了解决“SQL 为什么这么生成、字段是否真正命中”的可追溯问题，`/tables/{table_id}/ask` 现在会返回 schema-link 诊断字段：

- `sql_generation_mode`：`llm` / `deterministic`
- `schema_link_diagnostics`：
  - `matched_tables`
  - `matched_columns`
  - `matched_values`
  - `score`
  - `strategy`
  - `reason`

在 `TABLE_NL2SQL_ENABLED=true` 但缺少可用 LLM key 的场景，系统会自动走 deterministic fallback，并仍然输出上述 diagnostics，便于确认“召回到表但生成策略降级”的具体原因。

### 多表 explain 元数据（Wave C）

`/tables/{table_id}/ask` 现在还会返回：

- `planner_diagnostics`：确定性规划器信息（strategy/reason/group/order/limit 等）
- `join_provenance`：JOIN 关系证据（left/right table+column、confidence、reason）

这两个字段用于审计 “为什么选了这些表、为何按这个 JOIN 条件执行”。

## 语义过滤（sem_filter，可选）

开启（默认关闭，避免意外产生高额 LLM 调用）：

- `TABLE_LOTUS_ENABLED=true`
- 配置 `LLM_API_KEY`
- `TABLE_LLM_ALLOW_ROW_EGRESS=true`：允许把 **表格行数据** 发给 LLM 做语义过滤（默认关闭）
- 可调保护阈值：`TABLE_SEM_FILTER_MAX_IN_ROWS / TABLE_SEM_FILTER_MAX_COLS / TABLE_SEM_FILTER_MAX_CELL_CHARS / TABLE_SEM_FILTER_BATCH_SIZE`

接口：

- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/lotus/sem-filter`

> 说明：该接口路径保留了历史命名（`/lotus/sem-filter`），但实现为 MimirQ 内置的“LOTUS-like”语义过滤能力，不依赖外部 LOTUS 包。

## Chat 自动 TAG（可选）

当你希望「对话」里也能直接查表（而不是手动去“表格 / TAG”页面）时，可以开启 Chat→TAG 桥接：

- `CHAT_TAG_ENABLED=true`
- `TABLE_NL2SQL_ENABLED=true`
- `TABLE_LLM_ALLOW_RESULT_EGRESS=true`（因为 chat 会把 SQL 结果作为上下文引用材料注入到 LLM）

Chat 侧会：

1. 从当前会话绑定的 `document_ids` 中，找出已走 Table Store 的表格资产（`doc_metadata.table_store`）。
2. 基于问题与表结构（文件名/sheet/列名）选择少量候选表（默认最多 2 个）。
3. 若候选表在同一文档 SQLite 且可推断关系，优先走 deterministic JOIN 规划（单次查询）。
4. 否则回退为逐表 bounded NL→SQL→SELECT，并把结果以 JSON 形式注入到引用材料中（`retrieval_role=tag`）。

Chat TAG 注入的 payload 与 citations 也会透出 schema-link 关键信息（例如 `schema_link_score` / `schema_link_strategy`），用于线上排障与“有据可查”的审计。

多表 JOIN 路径下，还会透出：

- `join_provenance`：JOIN 关系推断链路
- `join_table_ids`：本次查询涉及的表资产 ID
- `join_sql_tables`：实际 SQL 使用的 `sheet_*` 表名白名单

当数据来源是 DB row sidecar 时，还会额外透出行级追溯字段：

- `row_source.table`：来源表（例如 `demo.users`）
- `row_source.sync_token`：该表本次快照 token
- `row_source.pk_hashes`：命中行的稳定哈希（默认列 `__row_pk_hash`）

这些字段会进入 TAG payload 和 citation（`row_source_table` / `row_source_sync_token` / `row_source_pk_hashes`），用于“哪一行被召回、是否可复现”的审计。

可调参数（见 `.env.example`）：

- `CHAT_TAG_MAX_TABLES / CHAT_TAG_MAX_DOC_IDS / CHAT_TAG_MAX_ROWS / CHAT_TAG_MAX_COLS / CHAT_TAG_MAX_BYTES`

## Must-Recall 语义（G1）

当问题属于“数据库必定存在答案”的场景，建议在请求侧显式声明 must-recall 约束：

- `rag_config.must_recall=true`
- `rag_config.retrieval_contract_mode=must_recall_strict`
- `rag_config.must_recall_expected_source_keys=[...]`（例如 `table_id` / `sheet_name` / 文件名）

Chat TAG 侧会执行两层保障：

1. **候选表源键约束**：当 `CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH=true` 且请求提供了 `must_recall_expected_source_keys`，只有命中源键的候选表才会进入执行阶段。
2. **DB rows SQL-first**：`dbrows` sidecar 资产在 `CHAT_TAG_DBROWS_SQL_FIRST_ENABLED=true` 时优先 deterministic SQL 路径，减少 LLM 生成漂移。

若候选表全部被源键过滤掉，`meta.reason` 会返回 `must_recall_source_key_miss`，可作为显式 fail reason 进入上层检索合同诊断。

## 多表规划规则（G3）

多表规划从“单条启发式关系”升级为“schema graph + top-N candidate”：

- `TABLE_TAG_PLAN_CANDIDATES_TOP_N`：保留的 join 候选数（按 score 排序）
- `TABLE_TAG_AMBIGUITY_SCORE_GAP`：前两名候选分差阈值（越小越严格）
- `TABLE_TAG_AMBIGUITY_STRICT_ENABLED`：
  - `true`：候选歧义时直接拒绝 `ambiguous_join_plan`
  - `false`：继续使用 top-1，但在 `planner_diagnostics` 暴露歧义信号

每次规划会产出：

- `planner_diagnostics.candidates`
- `planner_diagnostics.ambiguous / ambiguity_gap`
- `planner_diagnostics.sql_fingerprint`

执行后会再输出：

- `planner_execution_mismatch`（期望/实际 SQL 指纹与表集比对）
- `TABLE_TAG_PLANNER_MISMATCH_STRICT=true` 时遇 mismatch 会直接失败，防止“规划说一套、执行跑另一套”。

## 全局 JOIN 规划与风险契约（G4）

在多表（>=3）场景下，规划器会在 pairwise 候选之外执行有界 beam-style 全局搜索，尽量选出覆盖更多表且代价可控的 join path。

新增关键诊断字段（位于 `planner_diagnostics`）：

- `strategy`：固定 `deterministic_join`（兼容上游消费）
- `planner_mode`：`pairwise` / `beam`
- `multi_candidates`：多跳候选路径（含 `joins`、`selected_tables`、`hop_count`）
- `join_statistics_snapshot`：离线快照（`pairwise` + `multi` 候选、`ambiguous`、`ambiguity_gap`、`states_explored`）
- `dry_run_cardinality`：执行前规模估计（`estimated_upper_rows`、`max_rows_budget`、`explosive`）
- `join_plan_risk`：风险契约对象
  - `fanout_explosive`：估计 fanout 过高或 dry-run 规模爆炸
  - `selectivity_unknown`：join 键采样选择性不足，风险不可判定
  - `reason_codes`：风险原因码集合（低基数字段）

`join_plan_risk` 与 `dry_run_cardinality` 会同时透传到：

- `/tables/{table_id}/ask` 的返回体（`planner_diagnostics` / `join_plan_risk`）
- Chat TAG 注入 payload（`planner` / `join_plan_risk`）
- Chat citation metadata（`join_plan_risk_fanout_explosive` / `join_plan_risk_selectivity_unknown`）

建议线上巡检策略：

- 若 `join_plan_risk.fanout_explosive=true`，优先缩小筛选条件或降级为单表路径。
- 若 `selectivity_unknown=true`，优先补采样或补充键约束（避免“看似可 JOIN，实际扩大结果集”）。
- 若 `planner_mode=beam` 且 `ambiguous=true`，在严格模式下直接阻断（`ambiguous_join_plan`），在非严格模式下记录候选并审计 top-2 gap。

常见 fail reasons（用于告警归因）：

- `no_join_relationship_found`
- `invalid_join_relationship`
- `ambiguous_join_plan`
- `low_confidence_join_plan`
- `planner_execution_mismatch`
