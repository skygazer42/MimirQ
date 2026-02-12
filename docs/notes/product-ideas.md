# Product Ideas (Legacy)

This note is kept for historical context, but intentionally avoids referencing specific external products/projects.

If you want a living roadmap, track work as `bd` issues instead of growing this file.

## Capability Ideas (Generic)

1. Connector plugin system (Notion/Confluence/GitHub/Drive/etc) with incremental sync, retries, and soft-delete.
2. Web ingestion improvements: sitemap, recursive crawl, JS rendering, authenticated fetch, robots/rate-limits, SSRF allowlist.
3. Document versioning and rollback based on `doc_hash` + `pipeline_hash`.
4. Chunk strategy templates + auto recommendations based on preview diagnostics and retrieval metrics.
5. Optional reranker (cross-encoder / LLM rerank) with top-k tuning and observability.
6. Query rewrite / multi-query / HyDE presets with toggles and metrics.
7. Context compression + dedup to reduce token cost while preserving evidence.
8. Evidence UX: sentence-level citation alignment, highlighting, jump-to-source.
9. Multi-dataset routing and weighted fusion with permission-aware filtering.
10. Memory tiers (short-term window + long-term summary/vector memory) with clear controls.
11. Feedback loop: thumbs up/down and corrections generate eval samples and run regression gates.
12. Quality dashboards: parse success, chunk counts, recall/coverage, cost/quotas per tenant/dataset.
13. Unified job center for ingest/KG/rebuild/eval (progress/events/cancel/retry).
14. Security/compliance: RBAC, SSO (OIDC/SAML), audit logs, export/delete controls.
15. Frontend performance/polish: virtualization for large lists, streaming UX, consistent errors, trace IDs.

