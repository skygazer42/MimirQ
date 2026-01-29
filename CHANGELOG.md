# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Windows-friendly dev helpers: `scripts/dev_all.ps1` (`scripts/dev.ps1` wrapper) and `scripts/verify.ps1`.
- Repo docs: `CONTRIBUTING.md`, `SECURITY.md`, and `LICENSE`.

### Changed

- Table store (TAG): make SQLite connection timeout configurable via `TABLE_STORE_SQLITE_TIMEOUT_SEC`.
- Health/readiness probes: add short TTL cache to reduce hot-loop dependency checks.

### Fixed

- Excel import: ensure file handles are closed to avoid Windows temp file cleanup issues.
