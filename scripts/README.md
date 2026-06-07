# Scripts

This directory contains repo maintenance / devops helper scripts.

The Makefile is the source of truth for common workflows; these scripts are the underlying building blocks.

## Documentation (`scripts/docs/`)

- `bootstrap_handbook.py`：生成 `docs-site/docs/` 下中文样板结构（覆盖式；日常以 Git 中内容为准）。
- `generate_fe_be_matrix.py`：从 `web/openapi.json`、`web/lib/api`、`web/app` 生成 `docs-site/docs/integration/generated/fe-be-matrix.mdx`（`make handbook-build` / `make api-docs-build` 会调用）。
- `make handbook-matrix-check`：再生成矩阵后与 Git 比较，未提交更新则失败（CI：`api-docs` 经 `handbook-build`、PR：`.github/workflows/handbook-matrix.yml`）。
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
- `plugin_golden_closed_loop_smoke.py`: live plugin Golden import + retrieval-only regression smoke for an already-ingested dataset
  - Example: `python scripts/plugin_golden_closed_loop_smoke.py --base-url http://127.0.0.1:8000 --dataset-id <dataset_uuid>`
- `plugin_corpus_closed_loop_smoke.py`: live plugin-backed corpus ingest + Golden regression smoke from a local directory
  - Example: `python scripts/plugin_corpus_closed_loop_smoke.py --base-url http://127.0.0.1:8000 --source-dir /path/to/domain-corpus --plugin-ref plugin:<plugin-id>@<version>:chunk --include-source-root-name --overwrite-goldens`
- `changzhou_gov_plugin_chunk_report.py`: local Changzhou plugin governance/chunk/KG review report for the 01-06 sample families
  - Example: `make changzhou-gov-plugin-chunk-report`
  - Outputs `/tmp/changzhou_gov_plugin_chunk_report.json` and `/tmp/changzhou_gov_plugin_chunk_report.md`; it does not write the database, vector store, or KG store.
- `dify_console_login.py`: refresh the Dify console Playwright `storage_state` used by workflow trace diagnostics
  - Recommended: `DIFY_CONSOLE_EMAIL=<email> DIFY_CONSOLE_PASSWORD_FILE=/tmp/dify_console_password.txt make dify-console-login`
  - `make dify-console-ensure` first validates the existing storage state; if it is expired or expiring and both `DIFY_CONSOLE_EMAIL` plus `DIFY_CONSOLE_PASSWORD_FILE` are configured, it refreshes the state automatically.
  - Avoid putting Dify console passwords in repository files or shell history; the script writes only `console_token` localStorage state to `/tmp/kingdonsoft_dify_storage_state.json` by default.
  - The Kingdonsoft Dify console web UI is served under the `/brainai` base path, for example `https://ai.kingdonsoft.com:3000/brainai/apps`. Keep `DIFY_CONSOLE_ORIGIN=https://ai.kingdonsoft.com:3000` because browser storage state is keyed by origin, not by path.
- `changzhou_gov_dify_external_knowledge_probe.py`: compare Dify external hit-testing with direct MimirQ retrieval for the same Changzhou golden cases
  - MimirQ-only preflight: `make changzhou-dify-mimirq-direct-gate` runs the same golden retrieval cases directly against MimirQ using `DIFY_EXTERNAL_KNOWLEDGE_API_KEY(S)` from `.env`, without Dify console auth.
  - Local route preflight: `make changzhou-dify-knowledge-map-check` validates `DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON` before remote Dify calls.
  - Recommended after `make dify-console-login`: `make changzhou-dify-external-probe`
  - Override output or a specific Dify external API id: `CHANGZHOU_DIFY_EXTERNAL_API_ID=<external_api_id> CHANGZHOU_DIFY_PROBE_OUT=/tmp/probe.json make changzhou-dify-external-probe`
  - The command exits non-zero unless the Dify endpoint host is non-loopback, all cases have non-empty Dify hit-testing results, direct MimirQ retrieval is non-empty, and direct records match Dify's external knowledge schema.
  - The JSON report includes `boundary.verdict`; `dify_external_boundary_ok` means endpoint config, local direct retrieval, and Dify dataset hit-testing all passed.
- `changzhou_gov_dify_full_gate.py`: run the Changzhou government-service Dify/MimirQ golden gate (preflight, generated answers, direct eval, workflow trace)
  - Recommended: `make changzhou-dify-full-gate`
  - The workflow trace artifact records retrieval node titles/results plus `region_extractors`, so district-route warnings can be traced back to the exact Dify area extractor output without reopening the console trace manually.
  - Generated-answer failures where direct retrieval is correct usually mean Dify ignored material evidence. Inspect the matched record in the eval artifact first: runtime `答案要点` / `必答要点` prefixes are adapter hints sent to Dify only, not persisted chunk text.
  - End-to-end readiness: `make changzhou-dify-readiness-gate` runs the local knowledge-map preflight, Dify console token check, strict external probe, then the full generated-answer/direct-eval/trace gate with generated-answer grounding/key-point recall thresholds defaulting to `0.9` to avoid failing on harmless wording variance, and writes `/tmp/changzhou_gov_dify_readiness_summary.json`.
  - If an upstream stage fails, the readiness summary reports only the root cause in `failed_stages`, `root_cause_stage/root_cause_reason`, and `next_action`; downstream stages are marked `status=skipped` with `blocked_by=<stage>`, so expired Dify console auth is not hidden behind skipped probe/full-gate stages.
  - Quick diagnosis: `make changzhou-dify-readiness-status` prints the latest summary's pass/fail state, freshness, boundary verdict, direct MimirQ base URL match state, non-blocking warning counters, affected case ids, advisory warning diagnoses/details, root cause, next action, skipped stages, and artifact paths.
  - If readiness status says the direct base differs from the external endpoint host, rerun with `CHANGZHOU_DIFY_MIMIRQ_BASE_URL=<MimirQ base used by Dify>` so the direct gate and Dify boundary probe compare the same service instance.
  - Override cases or thresholds without editing the Makefile: `CHANGZHOU_DIFY_CASES=/tmp/boundary_cases.json CHANGZHOU_DIFY_EXTRA_ARGS='--min-hit-at-3 0.8' make changzhou-dify-full-gate`
  - Reads `DIFY_EXTERNAL_KNOWLEDGE_API_KEY` / `DIFY_EXTERNAL_KNOWLEDGE_API_KEYS` from the environment or repo `.env`; Dify App key and console storage state default to `/tmp/dify_remote_app_api_key.json` and `/tmp/kingdonsoft_dify_storage_state.json`.
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
- `remote_chunking_matrix.py`: live chunking matrix against a running API; set `MIMIRQ_REMOTE_LONG_PDF_FIXTURE=/path/to/long.pdf` to reuse a local long PDF, or set `MIMIRQ_REMOTE_FIXTURE_DOWNLOADS=1` to download the RFC sample.
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
  - Plugin Golden source example: `python scripts/regression_gate.py --dataset-id <dataset_uuid> --plugin-golden-ref plugin:<id>@<version>:chunk --metrics "" --thresholds ci/plugin.thresholds.json`
  - Generated Plugin Golden thresholds preserve compact `case_source` provenance and reject plugin ref/package-hash mismatches before starting a run.
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
- `build_parsing_retrieval_fixture.py`: convert parser-like document rows plus query specs into a deterministic retrieval fixture
  - Example: `python scripts/build_parsing_retrieval_fixture.py --documents-json runs/parsed_docs.json --queries-json runs/proof_queries.json --out runs/parsing_proof.fixture.json`
- `build_parsing_retrieval_fixture_from_file.py`: parse a real source file first, then emit a deterministic retrieval fixture
  - Example: `python scripts/build_parsing_retrieval_fixture_from_file.py --input-file tests/fixtures/parsing_golden_broader/borderless_table_scan/input/sample.png --queries-json runs/proof_queries.json --out runs/parsing_file_proof.fixture.json --parser-backend image`
- `run_parsing_retrieval_proof.py`: build a retrieval fixture from parser-like outputs and immediately run the deterministic retrieval benchmark
  - Outputs: retrieval fixture JSON plus benchmark report JSON
  - Example: `python scripts/run_parsing_retrieval_proof.py --documents-json runs/parsed_docs.json --queries-json runs/proof_queries.json --fixture-out runs/parsing_proof.fixture.json --report-out runs/parsing_proof.report.json`
- `run_parsing_retrieval_proof_from_file.py`: parse a real source file, build a retrieval fixture from the parsed output, and immediately run the deterministic retrieval benchmark
  - Outputs: retrieval fixture JSON plus benchmark report JSON
  - Example: `python scripts/run_parsing_retrieval_proof_from_file.py --input-file tests/fixtures/parsing_golden_broader/cross_page_table_pdf/input/sample.pdf --queries-json runs/proof_queries.json --fixture-out runs/parsing_file_proof.fixture.json --report-out runs/parsing_file_proof.report.json --parser-backend basic`
- `run_parsing_retrieval_proof_batch.py`: run multiple file-driven parsing proofs from a batch spec JSON and emit per-case fixtures/reports plus an aggregate batch report
  - Outputs: `<out-dir>/<case>.fixture.json`, `<out-dir>/<case>.report.json`, and `<out-dir>/batch.report.json`
  - Example: `python scripts/run_parsing_retrieval_proof_batch.py --spec-json runs/parsing_proof_batch.spec.json --out-dir runs/parsing_proof_batch`
- `build_parsing_retrieval_proof_batch_spec.py`: derive a batch proof spec from a parser manifest plus a case-id -> queries mapping JSON
  - Example: `python scripts/build_parsing_retrieval_proof_batch_spec.py --manifest-json tests/fixtures/parsing_golden_broader/manifest.json --case-queries-json runs/parsing_proof_case_queries.json --out runs/parsing_proof_batch.spec.json`
- `build_parsing_retrieval_proof_artifacts.py`: derive normalized `summary.json` and `report.json` from a parsing-proof batch report
  - Example: `python scripts/build_parsing_retrieval_proof_artifacts.py --batch-report runs/parsing_proof_batch/batch.report.json --summary-out runs/parsing_proof_batch/summary.json --report-out runs/parsing_proof_batch/report.json`
- `parsing_retrieval_proof_gate.py`: evaluate parsing-proof summary artifacts against thresholds and emit `gate.json`
  - Example: `python scripts/parsing_retrieval_proof_gate.py --input runs/parsing_proof_batch/summary.json --thresholds ci/parsing_retrieval_proof_thresholds.v1.json --out runs/parsing_proof_batch/gate.json`
- `diff_parsing_retrieval_proof_summaries.py`: diff a baseline parsing-proof summary and a current one into JSON/Markdown review artifacts
  - Example: `python scripts/diff_parsing_retrieval_proof_summaries.py --a ci/parsing_retrieval_proof_summary_baseline.v1.json --b runs/parsing_proof_batch/summary.json --out runs/parsing_proof_batch/diff.json --out-md runs/parsing_proof_batch/diff.md`
- `validate_parsing_retrieval_proof_governance.py`: validate the machine-readable broader parsing-proof governance JSON
  - Example: `python scripts/validate_parsing_retrieval_proof_governance.py --governance ci/parsing_retrieval_proof_governance.v1.json`
- `validate_parsing_retrieval_proof_rollout.py`: validate the staged rollout policy for broader parsing-proof (`informational` -> `warn` -> `fail`)
  - Example: `python scripts/validate_parsing_retrieval_proof_rollout.py --rollout ci/parsing_retrieval_proof_rollout.v1.json`
- `run_sample_parsing_retrieval_proof.py`: run the repo's sample broader parsing-proof sweep using the checked-in broader manifest and sample query map
  - Outputs: a generated batch spec plus per-case reports, `summary.json`, `report.json`, `gate.json`, and `diff.json` / `diff.md`
  - Example: `python scripts/run_sample_parsing_retrieval_proof.py --out-dir runs/parsing_proof_broader_sample`
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
