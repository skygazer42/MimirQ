# Scripts

This directory contains repo maintenance / devops helper scripts.

The Makefile is the source of truth for common workflows; these scripts are the underlying building blocks.

## Common

- `init_env.py`: create local env files from templates (non-destructive by default)
  - Example: `python scripts/init_env.py`
  - Options: `--force`, `--dry-run`, `--gen-secret-key`
- `doctor.py`: quick environment sanity check (python/node/pnpm/docker + required files)
  - Example: `python scripts/doctor.py`
- `check_parsers.py`: print parser backend availability/config status
  - Example: `python scripts/check_parsers.py`
- `export_openapi.py`: export backend OpenAPI to JSON (used by `make openapi-export`)
  - Example: `python scripts/export_openapi.py --out web/openapi.json`
- `openapi_check.py`: ensure OpenAPI artifacts are present and up-to-date in git
  - Example: `python scripts/openapi_check.py`
- `api_smoke.py`: smoke test OpenAPI endpoints against a running backend (usually docker)
  - Example: `python scripts/api_smoke.py --help`
- `clean.py`: remove local caches/artifacts (used by `make clean`)
  - Example: `python scripts/clean.py`

## Dev (Windows PowerShell)

- `dev_all.ps1`: Windows helper that starts backend + web (if you don't have `make`)
  - `dev.ps1` is kept as a compatibility wrapper (deprecated)
- `dev_backend.ps1`: start backend only
- `dev_web.ps1`: start web only
- `verify.ps1`: Windows equivalent of `make verify`
- `audit.ps1`: dependency audit helper

## Misc / Advanced

- `benchmark_io_concurrency.py`: local benchmarking helper
- `chunk_preview_batch_eval.py`: batch evaluate chunk preview behavior
- `convert_text_encoding.py`: best-effort text encoding conversion utility
- `gen_secret_key.py`: generate a SECRET_KEY value
- `regression_gate.py`: enforce regression thresholds from evaluation outputs
- `train_ltr_from_regression_cases.py`: train an xgboost LTR reranker model from regression cases via Evidence API (retrieval-only)
- `eval_ltr_offline.py`: compare baseline retrieval vs local LTR rerank offline (candidates via Evidence API)

## Exit Codes

Most scripts follow a simple contract:

- `0`: success
- non-zero: failure (prints a readable message)
