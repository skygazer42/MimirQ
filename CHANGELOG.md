# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Evidence retrieval gate helpers for retrieval-only regression (Recall/Hit/MRR/NDCG) plus deterministic offline tests.
- Optional sparse retrieval channel (SPLADE-style scaffolding) with deterministic provider for unit/regression validation.
- Optional reranker providers: ColBERT-style late-interaction scaffold (`colbert`) and XGBoost LTR reranker (`ltr`).
- Offline training helper: `scripts/train_ltr_from_regression_cases.py` (build LTR model artifacts from regression cases via Evidence API).
- Docs: evidence retrieval gate, sparse retrieval, ColBERT/LTR reranking guides, and a retrieval-only parity gap snapshot.
- Stable retrieval config fingerprint (`retrieval_config`) in retrieval trace plus `retrieval_config_hash` metric for cross-run comparisons.
- Retrieval orchestrator hard-fallback path (opt-in) with deterministic fallback metrics/trace (`hard_fallback_*`) and config-fingerprint keys.
- Strict evidence-span mode for retrieval (`RAG_EVIDENCE_REQUIRE_SPANS_ENABLED`) including span-based citation filtering and abstain coupling.
- Hardcase candidate emission from retrieval metrics (`mimirq.hardcase_candidate.v1`) with stable dedupe key.
- Docs: hardcase feedback automation playbook (`docs/guides/hardcase_feedback_automation.md`).
- Chat-side default retrieval profile setting (`CHAT_DEFAULT_RETRIEVAL_PROFILE`) with omitted-knob apply semantics and explicit-knob override preservation.
- TAG deterministic NL2SQL fallback path (`generate_sql_for_table_with_mode`) and no-key behavior for chat TAG.
- Parse-quality retrieval diagnostics (`metrics.parse_quality`, `retrieval_trace.parse_quality`) and operator guide `docs/guides/parse_quality_retrieval_diagnostics.md`.
- Must-recall strict diagnostics and partial-miss recovery signals in retrieval contract trace/query-debug.
- Deterministic TAG planner upgrades: schema-graph candidate scoring, ambiguity controls, SQL fingerprint, and planner-vs-execution mismatch diagnostics.
- Evidence capsule contract (`mimirq.evidence_capsule.v1`) with citation/anchor hash fields, persistence API, replay CLI, and one-shot must-recall+provenance gate script.
- CI parser benchmark strict-gate diff artifacts and must-recall/provenance gate artifact wiring.

### Retrieval Quality

#### Snapshot

| Metric | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| hit@10 | TBD | TBD | TBD |
| mrr@10 | TBD | TBD | TBD |
| ndcg@10 | TBD | TBD | TBD |
| p95 latency (ms) | TBD | TBD | TBD |

#### Artifacts

- Benchmark summary: `runs/.../leaderboard.json`
- Gate report: `runs/.../gate_report.json`
- Thresholds: `runs/.../thresholds.v2.json`
- Template guide: `docs/guides/retrieval_release_notes.md`

### Changed

- Remove unconnected custom stream-writer and image-URL mapping implementations already superseded by the active LangGraph and authenticated image paths.
- Replace scheduler timing thresholds with thread-identity checks and execute ingestion/connector ACL subqueries against in-memory SQLite.
- Evidence retrieval orchestrator supports optional post-fusion reranking for retrieval-only workflows (`EVIDENCE_POST_RERANK_*`).
- Evidence citations now surface additional per-channel sparse scores (`lexical_score`, `sparse_score`) for debugging/training.
- Retrieval profiles endpoint now exposes runtime `chat_default_profile` and `chat_default_effective`.
- TAG citation payloads now include stable table traceability keys (`table_id`, `sheet_index`, `sheet_name`, `sql_generation_mode`) for tag hits.
- RAG evidence retrieve response now optionally returns immutable `evidence_capsule` payload for replay/audit.

### Fixed

- Offload streaming extractive fallback and corrective second-pass retrieval from the async event loop without adding retrieval calls.
- CI: install Linux CPU-only PyTorch wheels to avoid pulling huge CUDA runtime dependencies (disk exhaustion in CI/docker builds).
- CI: ensure `pnpm` is available before enabling `actions/setup-node` pnpm caching.
- OpenAPI: regenerate `web/types/openapi.ts` so `make openapi-check` stays stable in CI.
- Web: cover missing backend routes in `web/lib/api-client.ts` (SCIM Groups/Users mutations; observability periodic job freshness).
- Web: pin ESLint to v9 to avoid a runtime crash in `eslint-plugin-react` when linting.

## [0.7.4] - 2026-07-15

### Changed

- Pin the MinerU runtime to 3.4.4 and align cache readiness with its OCRv6, pipeline, and `MinerU2.5-Pro-2605-1.2B` model contracts.
- Document the A6000 real-document parser validation matrix in `docs/ops/parser-gpu-validation-v0.7.4.md`.

### Fixed

- Route the advertised ColPali PDF backend through the parser factory.
- Reject stale MagicPDF CUDA health results and keep its container build on the available `stringzilla` binary wheel.

## [0.7.3] - 2026-07-15

### Changed

- Remove internal iteration markers, garbled comments, and commented-out debug output from public source files.
- Make legacy application-side timestamp defaults UTC-aware without requiring a database migration.
- Validate four controlled runtime settings with `Literal` types and remove duplicate manual checks.

### Fixed

- Preserve stable API error codes for HTTP 400, 409, and 416 responses.
- Keep frontend file-size formatting valid for non-finite, negative, and terabyte-scale values.
- Align the document status comment with the six statuses exposed by the document API.

## [0.7.2] - 2026-07-14

### Changed

- Move blocking retrieval, graph, and parsing work off async request loops, remove duplicate enrichment, push feedback pagination into SQL, and reuse embedding clients without adding retrieval calls.
- Consolidate sync-over-async bridging, embedding HTTP retries, and optional Redis client lifecycles into shared tested implementations.
- Remove unused async database, provider alias, reranker shim, delegate, upload wrapper, and exception surfaces without changing active runtime contracts.
- Replace source-sniffing tests with deterministic API drift, ACL pagination, query decomposition, frontend behavior, and robustness gates; allow cold container builds enough time to complete.

### Fixed

- Surface vector ingestion failures through the existing failed-job and retry path instead of marking incomplete documents as completed.
- Distinguish partial retrieval degradation from genuine zero-hit results and return an error when every retrieval channel fails.
- Keep worker heartbeats, BM25 cache state, bounded stream completion, logout cache isolation, polling cleanup, and local search rebuilds coherent under failure and concurrency.
- Keep generated frontend API types aligned with feedback triage contracts and avoid fixed PostgreSQL port collisions on shared CI runners.

### Security

- Upgrade Pillow to its patched release and `langchain-anthropic` to `1.4.6`, closing the dependency audit findings including `PYSEC-2026-2556`.

## [0.5.1] - 2026-03-17

### Fixed

- Web: stabilize React hooks dependencies in several pages/components to avoid stale closures and reduce `react-hooks/exhaustive-deps` noise.
- Web: cover additional backend routes in `web/lib/api-client.ts` (SAML metadata, evidence training export/capsules, connectors reconcile, retrieval explain/config hash, observability cache invalidation and index drift).
- OpenAPI: regenerate `web/types/openapi.ts` after adding new backend endpoints so contract checks stay consistent.
- Retrieval: fix hierarchy expansion fetcher tenant scoping and include hierarchy family aggregation metadata in retrieval metrics/debug output.
- Lint/Test: ruff cleanup (import order, unused vars) and test module import ordering guard fixes.

## [0.2] - 2026-02-22

### Added

- Windows-friendly dev helpers: `scripts/dev_all.ps1` (`scripts/dev.ps1` wrapper) and `scripts/verify.ps1`.
- Repo docs: `CONTRIBUTING.md`, `SECURITY.md`, and `LICENSE`.
- Parsing: fallback DOCX parser now emits chunk-friendly structured Markdown (headings/lists/pipe tables).
- Table store (TAG): best-effort DOCX embedded table import into per-document SQLite store (sidecar; RAG chunking preserved).
- Parsing (PaddleOCR-VL): external `doc_parser` service integration (v1.5) with `/convert` ZIP artifacts and best-effort `/health` metadata probing.
- Parsing: ZIP artifact normalizer (md/json/images) to stabilize external parser outputs.
- Chunk Preview: richer metrics (stats + histogram), AB diff summary, reusable presets (API + UI), and new `markdown_outline` chunk strategy.
- Ingestion analytics: unified `DocumentAnalytics` schema + parsing analytics panel (raw vs cleaned) for explainability.
- Governance: rule packs catalog + API/UI integration, stronger server-side regex safety validation, and ingestion-policy export from governance profiles.
- RAG observability: stable trace schema + history trace panel + graph replay for “retrieve → rerank → citations”.
- UI: provider icons migrated to LobeHub colored SVGs (settings + cards unified), and parsing preview JSON bbox overlay.
- Demo: reproducible ingestion-flow scripts (`scripts/demo_ingestion_flow.ps1` and `scripts/demo_ingestion_flow.sh`).
- KG: graph expand/export now supports relation (triple) links via `include_relation_links`, and the web graph UI exposes a toggle.
- Evaluations: web API client now includes KG search diagnostics endpoints for running and browsing diagnostics runs.
- KG/RAG: KG-derived query expansion can exclude entity types via `RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES` (defaults exclude SkillNet taxonomy nodes).
- Docs: KG guide now documents storage model (Postgres tables + Milvus collections) and how KG enhances RAG (query expansion / chunk injection).

### Changed

- Table store (TAG): make SQLite connection timeout configurable via `TABLE_STORE_SQLITE_TIMEOUT_SEC`.
- Health/readiness probes: add short TTL cache to reduce hot-loop dependency checks.
- Table store (TAG): improve CSV import robustness (delimiter sniffing) and column-name sanitization for SQLite.
- Table store (TAG): improve max_rows truncation accuracy by reading one extra row before trimming.
- TAG consumers: allow DOCX documents with `doc_metadata.table_store` in dataset tables listing and chat table context selection.
- Governance: treat Markdown pipe tables without outer pipes as structural lines; normalize them when table normalization is enabled.
- KG search: event recall via entity links now prefers events with higher total edge weight (e.g., skill edges) for better ranking.
- KG extraction: entity normalized_name now strips common edge punctuation/wrappers to reduce fragmentation.
- KG extraction: relation predicates are canonicalized via conservative synonym mapping (e.g. “works at” -> `works_for`) to reduce ontology drift.
- KG extraction: drop obvious noise entities earlier (single-char ASCII, digits-only, punct-only) to keep the graph compact.
- Skill extraction: Skill tags are deduped before persistence.

### Fixed

- Excel import: ensure file handles are closed to avoid Windows temp file cleanup issues.
- KG extraction: evidence span matching for ASCII quotes is more robust to casing differences (reduces false drops under evidence_required).
