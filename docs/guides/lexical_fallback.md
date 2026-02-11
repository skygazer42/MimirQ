# Lexical Fallback (Postgres FTS + pg_trgm)

MimirQ 的检索链路除了向量检索与内存 BM25 外，还提供一个 **持久化的 lexical fallback 通道**：

- **Postgres FTS**：`websearch_to_tsquery` + `ts_rank_cd`
- **pg_trgm**：`similarity()` + `%` 操作符（短查询 / code-like 查询兜底）

目标是把企业知识库里常见的“召回假阴性”降到最低，尤其是：

- 版本号 / 编译号（`v1.2.3`、`3.10.0`）
- 数字与格式（`1,234`、`12_345`）
- 路径 / API / 标识符（`/api/v1/rag/retrieve`、`X-Request-ID`、`ChatRAGConfig`）

> 注意：这是 **检索系统优化**，不依赖 LLM 生成，适合做 retrieval-only 回归门禁与证据闭环。

---

## 1) 什么时候会触发？

在 `app/rag/retriever.py` 的 `HybridRetriever._hybrid_search()` 中：

- `retrieval_mode in ("hybrid", "keyword", "mmr")` 时，会尝试 `LEXICAL_DB` 通道
- `retrieval_mode="vector"` 时，如果向量通道完全失败，会 fallback 到 BM25 + lexical DB

lexical DB 通道不会替代 BM25 / 向量，而是作为一个 **额外的 sparse candidate source**，再通过融合策略（RRF/linear merge + rerank）进入最终候选。

---

## 2) 配置项（Settings）

后端配置（见 `app/core/config.py`）：

- `LEXICAL_DB_ENABLED`：是否启用 lexical DB 通道
- `LEXICAL_DB_FTS_CONFIG`：FTS config（默认 `simple`）
- `LEXICAL_DB_FETCH_MULTIPLIER`：候选 overfetch 倍数（默认 4）
- `LEXICAL_DB_MAX_CANDIDATES`：候选上限（默认 200）
- `LEXICAL_DB_TRGM_ENABLED`：是否启用 trigram fallback（默认 true）
- `LEXICAL_DB_TRGM_MIN_QUERY_CHARS`：触发 trigram 的最短 query 长度（默认 3）

---

## 3) 数据库依赖与索引

lexical fallback 依赖：

- Postgres 扩展：`pg_trgm`
- `document_chunks.content` 的 FTS / trigram 索引（GIN）

项目在启动时会 best-effort 执行运行时 migration（见 `app/core/migrations.py`），包含：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_document_chunks_content_fts_active
ON document_chunks USING GIN (to_tsvector('simple', content))
WHERE disabled_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm_active
ON document_chunks USING GIN (content gin_trgm_ops)
WHERE disabled_at IS NULL;
```

> 在部分云数据库（托管 Postgres）上，创建 extension 可能需要更高权限；此时请由 DBA 手动创建 `pg_trgm`。

---

## 4) 如何验证是否生效？

### 4.1 检查扩展

```sql
SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';
```

### 4.2 检查索引

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'document_chunks'
  AND indexname IN (
    'ix_document_chunks_content_fts_active',
    'ix_document_chunks_content_trgm_active'
  );
```

---

## 5) 可观测性（per-query attribution）

Evidence / 诊断链路会返回 `query_debug.channels`（best-effort），包含：

- vector/bm25/lexical_db 各通道是否启用
- 各通道候选数（candidates）
- lexical_db 的方法分布（fts vs trgm）
- 融合/去重/多文档多样性（diversity）导致的候选变化

这用于回答：**“本次召回到底靠的是哪个通道？”**，从而指导进一步的索引/配置/分词调优。

