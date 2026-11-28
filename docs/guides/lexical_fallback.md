# Lexical Retrieval for Keyword Mode

Ragvia exposes a persisted lexical retrieval channel backed by Postgres full-text search and `pg_trgm`.
It is intended to catch the kinds of exact-ish queries that vector retrieval often misses:

- version numbers such as `v1.2.3`
- numeric formats such as `1,234`
- paths, headers, identifiers, and API names such as `/api/v1/rag/retrieve`

## Keyword-mode behavior

`HybridRetriever._hybrid_search()` now treats lexical DB as the primary keyword channel when
`retrieval_mode="keyword"`:

- `LEXICAL_DB_ENABLED=true` and `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED=false`
  - run lexical DB only
  - skip the Milvus BM25 channel
- `LEXICAL_DB_ENABLED=true` and `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED=true`
  - run lexical DB first
  - run BM25 as a secondary keyword channel
- `LEXICAL_DB_ENABLED=false`
  - fall back to BM25 for keyword mode

Hybrid/MMR retrieval modes still treat lexical DB as an additional keyword candidate source.

With `LEXICAL_DB_HYBRID_FALLBACK_ONLY=true`, hybrid retrieval counts distinct chunks from vector search and BM25 against the requested result count. If the primary channels have enough candidates, body-text fallback is skipped. A caller can enable `lexical_db_hybrid_metadata_exact_fallback_enabled` to look up a missing exact title or FAQ anchor. The metadata lookup runs on its own when primary recall already has enough candidates.

The optional PostgreSQL queries in a single retrieval share `LEXICAL_DB_FALLBACK_BUDGET_MS`, which defaults to 600 ms. Results already found can still be ranked if the budget expires. Keyword mode uses PostgreSQL as its primary search channel.

## Settings

Relevant backend settings in `app/infrastructure/config.py`:

- `LEXICAL_DB_ENABLED`
- `LEXICAL_DB_HYBRID_METADATA_EXACT_FALLBACK_ENABLED` (default `false`)
- `LEXICAL_DB_FALLBACK_BUDGET_MS` (default `600`)
- `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED`
- `LEXICAL_DB_FTS_CONFIG`
- `LEXICAL_DB_FETCH_MULTIPLIER`
- `LEXICAL_DB_MAX_CANDIDATES`
- `LEXICAL_DB_TRGM_ENABLED`
- `LEXICAL_DB_TRGM_MIN_QUERY_CHARS`

## Query debug attribution

`query_debug.channels` includes per-channel attribution for PostgreSQL lexical, Milvus BM25, and vector
retrieval. In keyword mode it also includes a `keyword_strategy` block so it is explicit whether
the request ran:

- lexical only
- lexical + BM25 secondary
- BM25 fallback because lexical DB is disabled

## Database prerequisites

Alembic revision `0033_chunk_lexical_indexes` adds the scope and body indexes with concurrent builds. The lexical channel uses:

- the Postgres `pg_trgm` extension
- a B-tree index for `(tenant_id, document_id)`
- GIN indexes for `document_chunks.content`

Typical runtime migration SQL looks like:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_document_chunks_content_fts_active
ON document_chunks USING GIN (to_tsvector('simple', content))
WHERE disabled_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_document_chunks_content_trgm_active
ON document_chunks USING GIN (content gin_trgm_ops)
WHERE disabled_at IS NULL;
```

## Validation

Useful checks after enabling lexical retrieval:

```sql
SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';
```

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'document_chunks'
  AND indexname IN (
    'ix_document_chunks_content_fts_active',
    'ix_document_chunks_content_trgm_active'
  );
```
