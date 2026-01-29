# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Windows-friendly dev helpers: `scripts/dev_all.ps1` (`scripts/dev.ps1` wrapper) and `scripts/verify.ps1`.
- Repo docs: `CONTRIBUTING.md`, `SECURITY.md`, and `LICENSE`.
- Parsing: fallback DOCX parser now emits chunk-friendly structured Markdown (headings/lists/pipe tables).
- Table store (TAG): best-effort DOCX embedded table import into per-document SQLite store (sidecar; RAG chunking preserved).

### Changed

- Table store (TAG): make SQLite connection timeout configurable via `TABLE_STORE_SQLITE_TIMEOUT_SEC`.
- Health/readiness probes: add short TTL cache to reduce hot-loop dependency checks.
- Table store (TAG): improve CSV import robustness (delimiter sniffing) and column-name sanitization for SQLite.
- Table store (TAG): improve max_rows truncation accuracy by reading one extra row before trimming.
- TAG consumers: allow DOCX documents with `doc_metadata.table_store` in dataset tables listing and chat table context selection.
- Governance: treat Markdown pipe tables without outer pipes as structural lines; normalize them when table normalization is enabled.

### Fixed

- Excel import: ensure file handles are closed to avoid Windows temp file cleanup issues.
