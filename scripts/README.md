# Scripts

This directory contains repo maintenance / devops helper scripts.

The Makefile is the source of truth for common workflows; these scripts are the underlying building blocks.

## Documentation (`scripts/docs/`)

- `bootstrap_handbook.py`：生成 `docs-site/docs/` 下中文样板结构（覆盖式；日常以 Git 中内容为准）。
- `generate_fe_be_matrix.py`：从 `web/openapi.json`、`web/lib/api`、`web/app` 生成 `docs-site/docs/integration/generated/fe-be-matrix.mdx`（`make handbook-build` / `make api-docs-build` 会调用）。
- `split_api_md.py`：将 `docs/api/source/legacy-api-narrative.md`（若不存在则回退 `docs/API.md`）按一级标题切到 `docs/api/reference/`，并写 `_index.md`（忽略代码围栏内的 `#` 行）。
- `sync-handbook-i18n.mjs`：`docs-site` 构建前把默认语言文档镜像到 `i18n/en/.../current`，并叠加热门页的英文覆盖（`docs-site/i18n/en-overrides/`）。
- `check_doc_links.mjs`：检查手册源文件中的**相对**链接是否指向存在的路径（`docs-site` 的 `npm run check:links`）。

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
- `openapi_paths_sanity.py`: fail if exported `web/openapi.json` has too few paths (used by `make api-docs-build`)
  - Example: `python scripts/openapi_paths_sanity.py`
- `openapi_check.py`: ensure OpenAPI artifacts are present and up-to-date in git
  - Example: `python scripts/openapi_check.py`
- `api_smoke.py`: smoke test OpenAPI endpoints against a running backend (usually docker)
  - Example: `python scripts/api_smoke.py --help`
  - Live parser example: `python scripts/api_smoke.py --skip-llm-test --skip-mineru --live-parser-backends deepseek_ocr --live-parser-fixture runs/deepseek_ocr_smoke.pdf`
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
- `backfill_kg_event_vector_metadata.py`: re-upsert KG event vectors to backfill Milvus metadata fields (`pipeline_hash`, `doc_pipeline_key`)
- `learn_fusion_weights_offline.py`: grid-search fusion weights (vector/bm25/lexical/sparse) offline via Evidence API
- `apply_fusion_weights_to_dataset.py`: persist learned fusion weights into dataset `rag_defaults` (safe by default; dry-run unless --execute)
- `gen_secret_key.py`: generate a SECRET_KEY value
- `rag_trace_tail.py`: tail and pretty-print `event=rag_trace` records from the metrics JSONL (PII-safe by default)
- `rag_trace_diff.py`: diff two `event=rag_trace` records by `request_id` (PII-safe; outputs compact delta summary)
- `mine_hard_negatives_from_traces.py`: mine PII-safe hard negatives from `event=rag_trace` metrics logs (outputs `mimirq.hard_negatives.v1` JSONL)
- `access_graph_diff.py`: diff two access-graph exports (NDJSON/JSON) and output a bounded PII-safe change summary (for access reviews)
- `regression_gate.py`: enforce regression thresholds from evaluation outputs
- `release_gate.py`: combine regression gate + SLO snapshot + cost budgets into a single release gate (CI/staging)
- `train_ltr_from_regression_cases.py`: train an xgboost LTR reranker model from regression cases via Evidence API (retrieval-only)
  - Writes a sidecar manifest by default: `<out-model>.manifest.json` (can be disabled with `--no-manifest`)
- `eval_ltr_offline.py`: compare baseline retrieval vs local LTR rerank offline (candidates via Evidence API)
- `prepare_ltr_rollout.py`: materialize approved evidence / selected feedback into a bounded LTR rollout workflow, then train, evaluate, compare, and optionally register a candidate model without activating it
- `eval_rerank_pipeline_offline.py`: compare baseline retrieval vs a local multi-stage rerank pipeline (LTR/ColBERT), offline
  - Supports `--colbert-provider deterministic|hf` plus model/device/batch flags
  - Summary JSON includes per-metric `wins/losses/ties` so you can see when the stronger path helps or hurts
- `eval_retrieval_fusion_offline.py`: compare fusion strategy variants offline via Evidence API (retrieval-only)
- `run_sample_retrieval_benchmark.py`: run a deterministic local sample benchmark from `data/sample/retrieval_fixture_v1.json`
  - Outputs: `runs/sample_bench.json` (schema: `mimirq.sample_retrieval_benchmark.v1`)
  - Example: `python scripts/run_sample_retrieval_benchmark.py --out runs/sample_bench.json`
- `run_queryset_health_diagnostics.py`: build query-set health snapshot from benchmark report and maintain bounded trend history
  - Output snapshot schema: `mimirq.queryset_health_snapshot.v1`
  - Adds risk summary (`miss_rate`, `weak_hit_rate`, `hard_cases`) and trend deltas for nightly drift checks
  - Embeds `policy_source` + stable `policy_hash` in snapshot/cron output for reproducible trend analysis across config changes
  - Emits `trend.policy_changed` when policy hash changes relative to previous snapshot
  - Supports threshold policy via `--policy-json` and per-run overrides such as `--miss-rate-regression-threshold`, `--weak-hit-rate-regression-threshold`
  - `--cron` emits machine-readable JSON with status + risk summary for CI logs
- `diff_queryset_health_snapshots.py`: diff baseline/current query-set health snapshots for PR/release review
  - Output schema: `mimirq.queryset_health_diff.v1`
  - Includes metric deltas, policy drift (`policy_source`/`policy_hash`), hard-case churn, degradation-flag churn
  - Supports `--out-md` to emit a human-readable Markdown summary for PR comments
- `validate_queryset_health_policy.py`: validate query-set health threshold policy JSON before CI/nightly usage
  - Example: `python scripts/validate_queryset_health_policy.py --policy ci/queryset_health_policy.v1.json`
- `check_retrieval_profile_compat.py`: validate retrieval profile + reranker compatibility before runtime/CI
  - Example: `python scripts/check_retrieval_profile_compat.py --retrieval-profile hybrid_ce --enable-reranker true --reranker-provider cross_encoder`

## Exit Codes

Most scripts follow a simple contract:

- `0`: success
- non-zero: failure (prints a readable message)
