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

### Changed

- Evidence retrieval orchestrator supports optional post-fusion reranking for retrieval-only workflows (`EVIDENCE_POST_RERANK_*`).
- Evidence citations now surface additional per-channel sparse scores (`lexical_score`, `sparse_score`) for debugging/training.

### Fixed

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
