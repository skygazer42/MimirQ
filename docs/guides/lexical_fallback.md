# Lexical Retrieval for Keyword Mode

MimirQ exposes a persisted lexical retrieval channel backed by Postgres full-text search and `pg_trgm`.
It is intended to catch the kinds of exact-ish queries that vector retrieval often misses:

- version numbers such as `v1.2.3`
- numeric formats such as `1,234`
- paths, headers, identifiers, and API names such as `/api/v1/rag/retrieve`

## Keyword-mode behavior

`HybridRetriever._hybrid_search()` now treats lexical DB as the primary keyword channel when
`retrieval_mode="keyword"`:

- `LEXICAL_DB_ENABLED=true` and `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED=false`
  - run lexical DB only
  - skip in-memory BM25
- `LEXICAL_DB_ENABLED=true` and `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED=true`
  - run lexical DB first
  - run BM25 as a secondary keyword channel
- `LEXICAL_DB_ENABLED=false`
  - fall back to BM25 for keyword mode

Hybrid/MMR retrieval modes still treat lexical DB as an additional sparse candidate source.

## Settings

Relevant backend settings in `app/core/config.py`:

- `LEXICAL_DB_ENABLED`
- `RETRIEVAL_KEYWORD_BM25_SECONDARY_ENABLED`
- `LEXICAL_DB_FTS_CONFIG`
- `LEXICAL_DB_FETCH_MULTIPLIER`
- `LEXICAL_DB_MAX_CANDIDATES`
- `LEXICAL_DB_TRGM_ENABLED`
- `LEXICAL_DB_TRGM_MIN_QUERY_CHARS`

## Query debug attribution

`query_debug.channels` includes per-channel attribution for lexical DB, BM25, vector, and sparse
retrieval. In keyword mode it also includes a `keyword_strategy` block so it is explicit whether
the request ran:

- lexical only
- lexical + BM25 secondary
- BM25 fallback because lexical DB is disabled

## Database prerequisites

The lexical channel depends on:

- the Postgres `pg_trgm` extension
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
