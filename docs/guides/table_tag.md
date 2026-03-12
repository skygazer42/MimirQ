# 表格 / TAG（Table Augmented Generation）

MimirQ 支持将结构化表格（CSV/XLS/XLSX）走 **TAG**（Table Augmented Generation）链路：把表格导入每文档 SQLite（Table Store），通过 **SQL 查询**（以及可选的 NL→SQL/语义过滤）来回答问题，而不是强行把大表切块嵌入进向量库。

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

> 注意：`.xls` 读取依赖运行环境（通常需要 `xlrd`）。若你们不计划支持旧格式，建议先用 LibreOffice/Pandoc 转成 `.xlsx`。

## 来自解析器的表格（PDF 解析 sidecar）

当 `table_store_enabled=true` 时，部分解析器（例如 PDF 的 Docling/DeepDoc 系列）会把表格作为独立的 “table segments” 输出（通常带 `metadata.content_type=table` / `doc_type_kwd=table`）。

MimirQ 会对这些表格做 best-effort：

- 把解析输出中的 **Markdown pipe table** 导入同一个 per-document SQLite Table Store
- 在文档 `doc_metadata.table_store` 中记录 `table_id/sheet_name/row_count/col_count/columns` 等元数据
- 因此数据集的「表格 / TAG」页面与 Chat→TAG 都能对 PDF 表格进行预览与查询

> 说明：这是一个 **sidecar** 能力（不改变现有 RAG 主流程）。目前不会默认把 PDF 表格从文本 chunks 中移除；若你希望“大表不入向量库”，可在后续任务中继续做表格路由优化。

## 表格自动分流（推荐：小表 RAG / 大表 TAG）

在企业真实数据里，表格通常分两类：

- **小表**：几十/几百行，用 Markdown 解析后切块入库即可（RAG 也能很好用）
- **大表/多 Sheet/超宽表**：入库成本高且检索差，更适合 TAG（SQL/Text-to-SQL）

因此推荐开启 **auto route**：

- `table_store_enabled=true` + `table_store_auto_route=true`
- 处理器会根据阈值（行数/列数/Sheet 数/文件大小）决定该文件走 **RAG** 还是 **TAG**
- 决策会写入 `doc_metadata.table_routing`（便于审计/排障）

## 开关与安全边界

在后端 `.env` 中配置（参考 `.env.example` / `docker/.env.example`）：

- `TABLE_STORE_ENABLED=true`：启用表格入库到 Table Store
- `TABLE_STORE_MAX_SHEETS=50`：最多导入的 Sheet 数（防止极端 Excel 占用资源；0 不限制）
- `TABLE_STORE_SAMPLE_ROWS=0`：不持久化采样行（合规/PII 场景建议）
- `TABLE_STORE_AUTO_ROUTE=true`：开启自动分流（小表继续走 RAG；大表走 Table Store）
- `TABLE_STORE_AUTO_ROW_THRESHOLD / TABLE_STORE_AUTO_COL_THRESHOLD / TABLE_STORE_AUTO_SHEET_THRESHOLD / TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD`：分流阈值
- `TABLE_QUERY_MAX_ROWS / TABLE_QUERY_MAX_COLS / TABLE_QUERY_MAX_BYTES`：限制 API 返回规模
- `TABLE_QUERY_MAX_SQL_CHARS / TABLE_QUERY_TIMEOUT_SEC / TABLE_QUERY_PROGRESS_OPS`：SQL 长度与执行时间保护（DoS 防护）

SQL 执行器是 **SELECT-only**：

- 拒绝多语句（`;`）
- 只允许 `SELECT` / `WITH ... SELECT`
- 通过 sqlite authorizer 禁止 PRAGMA/ATTACH/写入/DDL，并限制只能读目标 sheet 表

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
3. 对每个候选表执行一次 bounded NL→SQL→SELECT，并把结果以 JSON 形式注入到引用材料中（`retrieval_role=tag`）。

Chat TAG 注入的 payload 与 citations 也会透出 schema-link 关键信息（例如 `schema_link_score` / `schema_link_strategy`），用于线上排障与“有据可查”的审计。

可调参数（见 `.env.example`）：

- `CHAT_TAG_MAX_TABLES / CHAT_TAG_MAX_DOC_IDS / CHAT_TAG_MAX_ROWS / CHAT_TAG_MAX_COLS / CHAT_TAG_MAX_BYTES`
