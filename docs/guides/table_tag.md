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
- `TABLE_STORE_SAMPLE_ROWS=0`：不持久化采样行（合规/PII 场景建议）
- `TABLE_STORE_AUTO_ROUTE=true`：开启自动分流（小表继续走 RAG；大表走 Table Store）
- `TABLE_STORE_AUTO_ROW_THRESHOLD / TABLE_STORE_AUTO_COL_THRESHOLD / TABLE_STORE_AUTO_SHEET_THRESHOLD / TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD`：分流阈值
- `TABLE_QUERY_MAX_ROWS / TABLE_QUERY_MAX_COLS / TABLE_QUERY_MAX_BYTES`：限制 API 返回规模

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

接口：

- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/ask`

## 语义过滤（sem_filter，可选）

开启（默认关闭，避免意外产生高额 LLM 调用）：

- `TABLE_LOTUS_ENABLED=true`
- 配置 `LLM_API_KEY`
- 可调保护阈值：`TABLE_SEM_FILTER_MAX_IN_ROWS / TABLE_SEM_FILTER_MAX_COLS / TABLE_SEM_FILTER_MAX_CELL_CHARS / TABLE_SEM_FILTER_BATCH_SIZE`

接口：

- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/lotus/sem-filter`

> 说明：该接口路径保留了历史命名（`/lotus/sem-filter`），但实现为 MimirQ 内置的“LOTUS-like”语义过滤能力，不依赖外部 LOTUS 包。
