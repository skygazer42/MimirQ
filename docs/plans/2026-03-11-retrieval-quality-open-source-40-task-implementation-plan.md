# MimirQ Retrieval-Quality and OSS-Experience 40-Task Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the highest-impact backend gaps for retrieval quality (recall/precision/ranking) and open-source developer experience, while explicitly deprioritizing security hardening and new external source integrations.

**Architecture:** Keep the existing FastAPI + Postgres + Redis/arq + Milvus stack. Prioritize ranking quality and evaluation closure first, then move to index/cache correctness, and finally polish contributor workflows so community users can reproduce improvements quickly.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, Redis, Milvus, pytest, scripts-based offline eval, Makefile workflow.

---

## Scope Guardrails

- In scope:
  - retrieval quality
  - rerank quality
  - eval and learning loop automation
  - indexing and cache correctness
  - open-source reproducibility and contributor UX
- Out of scope:
  - auth and security deepening
  - adding new connector platforms
  - GitHub/Jira/Slack/Notion integration expansion

## Execution Order

1. Workstream A and B first (quality impact to end users).
2. Workstream C next (automate quality closure and anti-regression).
3. Workstream D next (prevent stale behavior and ranking drift from infra semantics).
4. Workstream E then F (community reproducibility and contribution speed).
5. Workstream G and H in parallel with late-stage stabilization.

## Execution Status Snapshot (2026-03-11)

Legend: `done` = implemented + verified, `validated` = already present in codebase and verified by tests in this session.

- Task 1 — `validated`
  - Verified default production profile `hybrid_ce` and runtime propagation into metrics/trace metadata.
  - Verification: `pytest -q tests/test_retrieval_profile_schema.py tests/test_regression_run_runtime_wiring.py`
- Task 2 — `validated`
  - Verified lexical DB primary keyword path, optional BM25 secondary path, and channel attribution debug.
  - Verification: `pytest -q tests/test_lexical_db_primary_keyword_mode.py tests/test_retriever_dataset_id_filter_injection.py`
- Task 3 — `done`
  - Added bounded field-aware recall signal controls in retrieval fusion:
    - `RETRIEVAL_FIELD_AWARE_RECALL_ENABLED`
    - `RETRIEVAL_FIELD_AWARE_TITLE_BOOST`
    - `RETRIEVAL_FIELD_AWARE_HEADING_BOOST`
    - `RETRIEVAL_FIELD_AWARE_MAX_BOOST`
  - Added retrieval debug channel payload `channels.field_aware`.
  - Added test: `tests/test_field_aware_recall.py`.
  - Verification: `pytest -q tests/test_field_aware_recall.py tests/test_retriever_debug_metrics_shape.py`
- Task 4 — `validated`
  - Intent-router policy overlay and query-expansion routing behavior are present and passing existing tests.
  - Verification: `pytest -q tests/test_intent_router.py tests/test_query_rewrite_versioning.py`
- Task 5 — `validated`
  - Retrieval trace/citation attribution contract is present and verified by existing schema tests.
  - Verification: `pytest -q tests/test_retrieval_trace_schema_v1.py`
- Task 6 — `validated`
  - Cross-encoder production profile path is present and wired into regression runtime payloads.
  - Verification: `pytest -q tests/test_retrieval_profile_cross_encoder.py tests/test_regression_run_runtime_wiring.py`
- Task 9 — `validated`
  - Adaptive rerank budget governance behavior is present and covered by retrieval ablation checks.
  - Verification: `pytest -q tests/test_rerank_budget_governance.py tests/test_retrieval_ablation.py`
- Task 11 — `validated`
  - Nightly retrieval ablation matrix includes runtime-oriented combinations and CI gate coverage.
  - Verification: `pytest -q tests/test_run_nightly_ablations.py tests/test_ci_retrieval_gate_workflow.py`
- Task 12 — `validated`
  - Slice-aware regression gate reporting contract is present and passing.
  - Verification: `pytest -q tests/test_regression_gate_report.py`
- Task 10 — `done`
  - Added post-rerank score calibration controls:
    - `EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED`
    - `EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA`
  - Added calibration flow in orchestrator for both single-stage and pipeline post-rerank modes.
  - Added calibration metrics/trace payload:
    - `metrics.evidence_post_rerank_score_calibration_*`
    - `retrieval_trace.post_rerank.score_calibration`
  - Added citation field passthrough: `citations[*].rerank_score_calibrated`.
  - Added test: `tests/test_rerank_score_calibration.py`.
  - Verification: `pytest -q tests/test_rerank_score_calibration.py tests/test_evidence_post_rerank_pipeline.py tests/test_retrieval_trace_schema_v1.py`
- Task 7 — `done`
  - Added explicit provider-mode regression tests: `tests/test_colbert_provider_modes.py`.
  - Hardened HF provider constraints in ColBERT reranker implementation:
    - invalid device rejected (`cpu|cuda|auto` only)
    - bounded `batch_size` (`[1, 256]`)
    - bounded `max_length` (`[8, 2048]`)
  - Updated ColBERT guide with explicit HF mode constraints.
  - Verification: `pytest -q tests/test_colbert_provider_modes.py tests/test_eval_rerank_pipeline_offline.py`
- Task 8 — `done`
  - Added LTR feature spec `v3` (`mimirq.ltr_features.v3`) with ranking-critical signals:
    - `field_aware_boost`, `field_signal_title`, `field_signal_heading`
    - `keyword_max_score`, `vector_keyword_gap`, `multi_channel_hits`
  - Extended training/eval data plumbing to carry field-aware signals.
  - Extended citation payload to expose field-aware attributes for offline LTR pipelines.
  - Extended LTR model registry manifest validation to accept `v3`.
  - Added tests: `tests/test_ltr_feature_spec_v3.py`.
  - Updated LTR guide to document v3.
  - Verification: `pytest -q tests/test_ltr_feature_spec_v3.py tests/test_train_ltr_manifest_lineage.py tests/test_eval_ltr_offline_summary_lineage.py`
- Task 13 — `validated`
  - Hard-negative mining and tenant-scope filtering pipeline are present and passing.
  - Verification: `pytest -q tests/test_hard_negative_mining.py tests/test_mine_hard_negatives_from_traces_tenant_filter.py tests/test_train_ltr_manifest_lineage.py`
- Task 14 — `validated`
  - One-command LTR rollout workflow artifacts and registry compatibility are present and passing.
  - Verification: `pytest -q tests/test_ltr_rollout_workflow.py tests/test_ltr_model_registry.py`
- Task 15 — `validated`
  - Public benchmark reproducibility artifacts are present and passing.
  - Verification: `pytest -q tests/test_public_bench_reproducibility.py tests/test_retrieval_profile_schema.py`
- Task 16 — `validated`
  - Retrieval candidate cache corpus-version invalidation semantics are present and passing.
  - Verification: `pytest -q tests/test_retrieval_candidate_cache_corpus_invalidation.py`
- Task 17 — `done`
  - Added provider-version-safe cache-key signature for shared post-rerank cache:
    - LTR: model path + manifest path + feature spec version
    - ColBERT: provider mode + model + device + batch/max-length + embed dim
    - normalized provider aliases for stable keying
  - Added tests: `tests/test_evidence_rerank_cache_redis_keying.py`.
  - Updated cache docs to describe provider-version key dimensions.
  - Verification: `pytest -q tests/test_evidence_rerank_cache_redis_keying.py tests/test_evidence_post_rerank_cache.py`
- Task 18 — `validated`
  - Dataset cache-namespace invalidation endpoint/service path exists and passes corpus-token rotation checks.
  - Verification: `pytest -q tests/test_observability_dataset_cache_invalidation.py tests/test_corpus_cache_tokens.py tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py`
- Task 19 — `done`
  - Added persisted sparse-index regression coverage: `tests/test_sparse_index_persisted.py`.
  - Locked key behaviors:
    - persisted index requires corpus-fingerprint match
    - restart/lazy-load path reuses persisted index without forcing full rebuild
  - Verification: `pytest -q tests/test_sparse_index_persisted.py tests/test_sparse_retrieval_splade_scaffold.py`
- Task 20 — `validated`
  - ColBERT ANN persisted-index build/load/reuse behavior is present and passing.
  - Verification: `pytest -q tests/test_colbert_retrieval_ann_persisted.py`
- Task 21 — `done`
  - Added minimal retrieval-only compose profile: `docker/docker-compose.retrieval-dev.yml`.
  - Added Makefile commands:
    - `up-retrieval-dev`
    - `ps-retrieval-dev`
    - `down-retrieval-dev`
  - Updated quickstart with retrieval-dev startup flow, expected startup time, and hardware assumptions.
  - Verification:
    - `make -n up-retrieval-dev`
    - `make -n api-ping`
    - `pytest -q tests/test_makefile_has_retrieval_dev_target.py`
- Task 22 — `done`
  - Added deterministic sample retrieval fixture: `data/sample/retrieval_fixture_v1.json`.
  - Added one-command sample benchmark runner: `scripts/run_sample_retrieval_benchmark.py`.
  - Updated scripts index docs: `scripts/README.md`.
  - Added tests: `tests/test_run_sample_retrieval_benchmark.py`.
  - Verification:
    - `python scripts/run_sample_retrieval_benchmark.py --out runs/sample_bench.json`
    - `pytest -q tests/test_run_sample_retrieval_benchmark.py`
- Task 23 — `done`
  - Added contributor retrieval debugging cookbook: `docs/guides/retrieval_debugging.md`.
  - Linked cookbook in docs index.
  - Added test: `tests/test_docs_retrieval_debugging_link.py`.
  - Verification:
    - `rg -n "retrieval_debugging" docs/README.md`
    - `pytest -q tests/test_docs_retrieval_debugging_link.py`
- Task 24 — `done`
  - Added retrieval regression issue template:
    - `.github/ISSUE_TEMPLATE/retrieval-quality-regression.yml`
  - Template enforces repro query, dataset scope, retrieval profile, expected citations, and regression artifacts.
  - Added test: `tests/test_retrieval_quality_issue_template.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_quality_issue_template.py`
    - `rg -n "repro query|dataset scope|retrieval profile|regression artifacts" .github/ISSUE_TEMPLATE/retrieval-quality-regression.yml -i`
- Task 25 — `done`
  - Added public retrieval release-note guide:
    - `docs/guides/retrieval_release_notes.md`
  - Added `Retrieval Quality` changelog block template in `CHANGELOG.md`.
  - Linked retrieval release notes guide in docs index.
  - Added tests: `tests/test_retrieval_release_notes_docs.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_release_notes_docs.py`
    - `rg -n "Retrieval Quality" CHANGELOG.md docs/guides/retrieval_release_notes.md`
- Task 26 — `done`
  - Added retrieval profile introspection endpoint:
    - `app/api/v1/retrieval_profiles.py`
    - route: `GET /api/v1/retrieval/profiles`
  - Endpoint exposes supported profiles, effective defaults, and reproducibility `version_hash`.
  - Omitted hidden scope/query/internal fields from profile definition payload.
  - Added tests: `tests/test_retrieval_profiles_endpoint.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_profiles_endpoint.py`
- Task 27 — `done`
  - Added single-query retrieval explain endpoint:
    - `app/api/v1/retrieval_explain.py`
    - route: `POST /api/v1/retrieval/explain`
  - Reused retrieval-only runtime (`build_rag_state` + `run_retrieval`) and surfaced deterministic explain schema:
    - channels
    - candidate counts
    - top citations
    - rerank metadata
    - stage timings
  - Added tests: `tests/test_retrieval_explain_endpoint.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_explain_endpoint.py tests/test_evidence_api_offline_regression_gate.py`
- Task 28 — `done`
  - Added retrieval config fingerprint endpoint:
    - `app/api/v1/retrieval_config_hash.py`
    - route: `POST /api/v1/retrieval/config-hash`
  - Endpoint computes stable hash from effective request config (+ optional runtime defaults).
  - Added tests: `tests/test_retrieval_config_hash_endpoint.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_config_hash_endpoint.py tests/test_retrieval_config_fingerprint.py`
- Task 29 — `done`
  - Added retrieval profile compatibility checker script:
    - `scripts/check_retrieval_profile_compat.py`
  - Added Makefile target:
    - `check-retrieval-profile-compat`
  - Added tests: `tests/test_retrieval_profile_compat_checker.py`.
  - Verification:
    - `python scripts/check_retrieval_profile_compat.py`
    - `pytest -q tests/test_retrieval_profile_compat_checker.py`
- Task 30 — `done`
  - Added retrieval API examples bundle:
    - `docs/examples/retrieval_api_examples.http`
    - `docs/examples/retrieval_api_examples.md`
  - Linked examples in docs index: `docs/README.md`.
  - Added tests: `tests/test_retrieval_api_examples_docs.py`.
  - Verification:
    - `pytest -q tests/test_retrieval_api_examples_docs.py`

---

## Workstream A: Recall and Candidate Generation (Tasks 1-5)

### Task 1: Define one production default retrieval profile

**Priority:** P0  
**Outcome:** Make a single high-quality retrieval baseline explicit and measurable.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/core/config.py`
- Modify: `docs/guides/rag_optimization.md`
- Test: `tests/test_retrieval_profile_schema.py`

**Acceptance:**
- Default profile is declared (for example `hybrid_ce`).
- Profile parameters are surfaced in traces and regression run metadata.
- Backward-compatible fallback remains available.

**Verify:**
- `pytest -q tests/test_retrieval_profile_schema.py tests/test_regression_run_runtime_wiring.py`

### Task 2: Make lexical DB the primary keyword path for single-node mode

**Priority:** P0  
**Outcome:** Reduce recall collapse when in-memory BM25 cache is cold or oversized.

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `docs/guides/lexical_fallback.md`
- Test: `tests/test_retriever_dataset_id_filter_injection.py`
- Add: `tests/test_lexical_keyword_mode_routing.py`

**Acceptance:**
- `keyword` mode can prefer lexical DB first.
- BM25 stays optional and does not silently override lexical path.
- Query debug output reports lexical vs BM25 channel contribution.

**Verify:**
- `pytest -q tests/test_lexical_keyword_mode_routing.py tests/test_retriever_dataset_id_filter_injection.py`

### Task 3: Add field-aware recall (title/heading/body channel hints)

**Priority:** P1  
**Outcome:** Improve recall for documents where key facts are concentrated in headings/tables.

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `app/services/indexer.py`
- Add: `tests/test_field_aware_recall.py`

**Acceptance:**
- Candidate scoring includes bounded field-aware signals.
- Signals are traceable in retrieval debug metadata.
- Disabled by default behind a config flag.

**Verify:**
- `pytest -q tests/test_field_aware_recall.py tests/test_retriever_debug_metrics_shape.py`

### Task 4: Improve query expansion routing policy (rewrite/multi-query/HyDE/decomposition)

**Priority:** P1  
**Outcome:** Reduce over-expansion noise while preserving recall gains on hard queries.

**Files:**
- Modify: `app/rag/policy/intent_router.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Add: `tests/test_intent_router_policy_overlays.py`

**Acceptance:**
- Routing policy is explicit and versioned.
- Each expansion strategy logs activation reason in trace metadata.
- A kill switch exists for each expansion family.

**Verify:**
- `pytest -q tests/test_intent_router_policy_overlays.py tests/test_query_rewrite_versioning.py`

### Task 5: Add deterministic candidate-channel attribution schema

**Priority:** P1  
**Outcome:** Explain why a chunk was retrieved, not only its final rank.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/trace_schema.py`
- Add: `tests/test_candidate_channel_attribution.py`

**Acceptance:**
- Each citation includes bounded channel attribution.
- Attribution is exportable and replay-safe.
- No PII-bearing raw text in channel fields.

**Verify:**
- `pytest -q tests/test_candidate_channel_attribution.py tests/test_retrieval_trace_schema_v1.py`

---

## Workstream B: Rerank and Fusion Quality (Tasks 6-10)

### Task 6: Promote one cross-encoder rerank profile to first-class production path

**Priority:** P0  
**Outcome:** Provide a robust default precision path before deeper experimental rerankers.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/api/v1/rag.py`
- Test: `tests/test_retrieval_profile_cross_encoder.py`

**Acceptance:**
- Profile activates bounded cross-encoder reranking after hybrid recall.
- Profile metadata persists into regression artifacts.
- Latency budget is configurable.

**Verify:**
- `pytest -q tests/test_retrieval_profile_cross_encoder.py tests/test_regression_run_runtime_wiring.py`

### Task 7: Productionize ColBERT provider modes cleanly

**Priority:** P1  
**Outcome:** Keep deterministic mode for CI and add clearly bounded HF mode for quality trials.

**Files:**
- Modify: `app/rag/reranker/colbert.py`
- Modify: `app/rag/reranker/factory.py`
- Modify: `docs/guides/reranking_colbert.md`
- Add: `tests/test_colbert_provider_modes.py`

**Acceptance:**
- `deterministic` and `hf` modes are explicit and observable.
- HF mode uses strict model/device constraints.
- Deterministic mode behavior remains stable for tests.

**Verify:**
- `pytest -q tests/test_colbert_provider_modes.py tests/test_eval_rerank_pipeline_offline.py`

### Task 8: Upgrade LTR feature spec to emphasize ranking-critical signals

**Priority:** P1  
**Outcome:** Improve LTR capacity using stable, auditable feature schema evolution.

**Files:**
- Modify: `app/rag/reranker/ltr.py`
- Modify: `scripts/train_ltr_from_regression_cases.py`
- Modify: `scripts/eval_ltr_offline.py`
- Add: `tests/test_ltr_feature_spec_v3.py`

**Acceptance:**
- New feature spec version is hash-fingerprinted.
- Offline train/eval scripts are compatible with old and new specs.
- Manifest lineage includes spec fingerprint.

**Verify:**
- `pytest -q tests/test_ltr_feature_spec_v3.py tests/test_train_ltr_manifest_lineage.py tests/test_eval_ltr_offline_summary_lineage.py`

### Task 9: Add adaptive rerank budget policy

**Priority:** P1  
**Outcome:** Spend rerank budget where it improves MRR/ndcg most.

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `app/core/config.py`
- Test: `tests/test_rerank_budget_governance.py`

**Acceptance:**
- Budget policy can adapt by query complexity and candidate uncertainty.
- Behavior remains deterministic with fixed seed and same config.
- Existing budget tests remain green.

**Verify:**
- `pytest -q tests/test_rerank_budget_governance.py tests/test_retrieval_ablation.py`

### Task 10: Add calibrated score blending between fusion and rerank

**Priority:** P2  
**Outcome:** Reduce unstable ranking jumps when channels have different score scales.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/reranker/types.py`
- Add: `tests/test_rerank_score_calibration.py`

**Acceptance:**
- Final ranking uses a documented calibration strategy.
- Calibration can be toggled for A/B comparison.
- Metrics report calibrated vs raw rerank impact.

**Verify:**
- `pytest -q tests/test_rerank_score_calibration.py tests/test_evidence_post_rerank_pipeline.py`

---

## Workstream C: Evaluation and Learning Loop (Tasks 11-15)

### Task 11: Expand retrieval ablation matrix to match runtime knobs

**Priority:** P0  
**Outcome:** Ensure ablations reflect real production runtime combinations.

**Files:**
- Modify: `scripts/retrieval_ablation.py`
- Modify: `scripts/run_nightly_ablations.py`
- Modify: `docs/guides/retrieval_ablation.md`
- Test: `tests/test_run_nightly_ablations.py`

**Acceptance:**
- Matrix covers retrieval profile, fusion strategy, sparse toggle, rewrite, multi-query, reranker provider.
- Nightly output includes machine-readable summary for trend tracking.

**Verify:**
- `pytest -q tests/test_run_nightly_ablations.py tests/test_ci_retrieval_gate_workflow.py`

### Task 12: Raise regression gate with slice-aware retrieval metrics

**Priority:** P0  
**Outcome:** Catch regressions hidden by global averages.

**Files:**
- Modify: `scripts/regression_gate.py`
- Modify: `docs/guides/regression_gate.md`
- Test: `tests/test_regression_gate_report.py`

**Acceptance:**
- Gate supports per-slice thresholds (language/file_type/hit_type/quality).
- Output artifacts include pass/fail rationale per slice.
- Existing threshold formats remain compatible.

**Verify:**
- `pytest -q tests/test_regression_gate_report.py tests/test_regression_gate_thresholds.py`

### Task 13: Automate hard-negative mining from trace bundles

**Priority:** P1  
**Outcome:** Continuously improve training data quality without manual curation bottlenecks.

**Files:**
- Modify: `scripts/mine_hard_negatives_from_traces.py`
- Modify: `scripts/train_ltr_from_regression_cases.py`
- Add: `tests/test_hard_negative_mining.py`

**Acceptance:**
- Hard negatives are mined with stable query hash linkage.
- Training pipeline can consume mined negatives deterministically.
- Data schema remains versioned.

**Verify:**
- `pytest -q tests/test_hard_negative_mining.py tests/test_train_ltr_manifest_lineage.py`

### Task 14: Build one-command candidate train/eval/compare workflow

**Priority:** P1  
**Outcome:** Reduce manual workflow friction for model iteration.

**Files:**
- Modify: `scripts/prepare_ltr_rollout.py`
- Modify: `app/services/ltr_rollout_workflow.py`
- Test: `tests/test_ltr_rollout_workflow.py`

**Acceptance:**
- Single command produces cases bundle, candidate model, eval report, baseline diff.
- Activation remains manual by design.
- Workflow artifacts are self-describing.

**Verify:**
- `pytest -q tests/test_ltr_rollout_workflow.py tests/test_ltr_model_registry.py`

### Task 15: Add retrieval benchmark leaderboard artifacts for OSS comparability

**Priority:** P2  
**Outcome:** Make progress visible to contributors and users over time.

**Files:**
- Modify: `scripts/seed_public_bench_cfever_dev.py`
- Modify: `scripts/seed_public_bench_miracl_zh_pool.py`
- Modify: `docs/guides/public_benchmarks_zh.md`
- Add: `scripts/export_retrieval_leaderboard.py`

**Acceptance:**
- Bench run exports normalized summary table (hit@k, mrr, ndcg, latency bands).
- Output format is stable for CI artifact diffing.
- Docs include reproducible command set.

**Verify:**
- `pytest -q tests/test_public_bench_reproducibility.py tests/test_retrieval_profile_schema.py`

---

## Workstream D: Index, Cache, and Freshness Semantics (Tasks 16-20)

### Task 16: Make candidate cache key fully corpus-version aware

**Priority:** P0  
**Outcome:** Prevent stale retrieval reuse after ingest/reindex changes.

**Files:**
- Modify: `app/rag/retrieval_candidate_cache.py`
- Modify: `app/services/corpus_cache_tokens.py`
- Test: `tests/test_retrieval_candidate_cache_corpus_invalidation.py`

**Acceptance:**
- Cache key includes corpus token and embedding space fingerprint.
- Token change guarantees cache miss.
- Skip reason metrics are emitted.

**Verify:**
- `pytest -q tests/test_retrieval_candidate_cache_corpus_invalidation.py`

### Task 17: Make post-rerank cache shared and version-safe

**Priority:** P1  
**Outcome:** Avoid duplicate rerank compute while keeping correctness.

**Files:**
- Modify: `app/rag/rerank_result_cache.py`
- Modify: `app/core/config.py`
- Add: `tests/test_evidence_rerank_cache_redis_keying.py`

**Acceptance:**
- Redis-backed cache supports deterministic key versioning.
- Provider/model/spec version is part of cache identity.
- stale-skip reasons are visible.

**Verify:**
- `pytest -q tests/test_evidence_rerank_cache_redis_keying.py tests/test_evidence_post_rerank_cache.py`

### Task 18: Add dataset-level cache invalidation endpoint

**Priority:** P2  
**Outcome:** Give operators deterministic recovery from stale cache incidents.

**Files:**
- Add: `app/api/v1/cache_admin.py`
- Modify: `app/api/v1/__init__.py`
- Add: `tests/test_cache_admin_invalidate.py`

**Acceptance:**
- Endpoint invalidates dataset-scoped candidate/rerank/chat cache namespaces.
- Response returns counts for invalidated keys/buckets.
- Endpoint is disabled by default in non-admin mode.

**Verify:**
- `pytest -q tests/test_cache_admin_invalidate.py`

### Task 19: Persist sparse index with fingerprinted rebuild semantics

**Priority:** P1  
**Outcome:** Make sparse retrieval usable on growing corpora without repeated cold builds.

**Files:**
- Modify: `app/rag/retriever.py`
- Add: `app/rag/retrieval/sparse_index_store.py`
- Add: `tests/test_sparse_index_persisted.py`

**Acceptance:**
- Sparse index persists by scope key + corpus fingerprint.
- Fingerprint mismatch triggers rebuild.
- Restart reload path avoids unnecessary full recompute.

**Verify:**
- `pytest -q tests/test_sparse_index_persisted.py tests/test_sparse_retrieval_splade_scaffold.py`

### Task 20: Harden ColBERT ANN persisted index semantics

**Priority:** P1  
**Outcome:** Keep ANN recall stable across restarts and index refreshes.

**Files:**
- Modify: `app/rag/retriever.py`
- Test: `tests/test_colbert_retrieval_ann_persisted.py`

**Acceptance:**
- Persisted ANN index is reused when fingerprint matches.
- Rebuild is explicit and observable on mismatch.
- No silent partial reuse across incompatible corpus states.

**Verify:**
- `pytest -q tests/test_colbert_retrieval_ann_persisted.py`

---

## Workstream E: OSS Reproducibility and Developer UX (Tasks 21-25)

### Task 21: Ship a minimal quickstart profile for quality experiments

**Priority:** P0  
**Outcome:** Let new contributors run retrieval evaluation quickly on a single machine.

**Files:**
- Modify: `Makefile`
- Add: `docker/docker-compose.retrieval-dev.yml`
- Modify: `docs/quickstart.md`

**Acceptance:**
- One command starts API + required dependencies for retrieval-only eval.
- Startup avoids unnecessary heavy parsers by default.
- Docs include expected startup time and hardware assumptions.

**Verify:**
- `make up-retrieval-dev`
- `make api-ping`

### Task 22: Add deterministic sample corpus and one-command benchmark script

**Priority:** P0  
**Outcome:** Standardize "before/after" comparisons for pull requests.

**Files:**
- Add: `data/sample/retrieval_fixture_v1.json`
- Add: `scripts/run_sample_retrieval_benchmark.py`
- Modify: `scripts/README.md`

**Acceptance:**
- Script seeds fixture and emits stable summary metrics.
- Result can be checked into CI artifacts.
- Script works without proprietary APIs when `LLM_MOCK_ENABLED=true`.

**Verify:**
- `python scripts/run_sample_retrieval_benchmark.py --out runs/sample_bench.json`

### Task 23: Add retrieval debugging cookbook for contributors

**Priority:** P1  
**Outcome:** Reduce maintainer load from repeated "why recall dropped?" questions.

**Files:**
- Add: `docs/guides/retrieval_debugging.md`
- Modify: `docs/README.md`

**Acceptance:**
- Cookbook includes trace reading, ablation flow, and common failure patterns.
- Every section maps to concrete commands in current repo.
- Includes "known anti-patterns" for config tuning.

**Verify:**
- `rg -n "retrieval_debugging" docs/README.md`

### Task 24: Add issue template for retrieval quality regressions

**Priority:** P2  
**Outcome:** Collect actionable bug reports from community users.

**Files:**
- Add: `.github/ISSUE_TEMPLATE/retrieval-quality-regression.yml`
- Modify: `.github/dependabot.yml` (only if needed to keep formatting/schema tooling aligned)

**Acceptance:**
- Template requires repro query, dataset scope, retrieval profile, and expected citations.
- Template asks for regression artifact attachment.
- Maintainer triage labels are pre-filled.

**Verify:**
- Manual check in GitHub issue template preview.

### Task 25: Add public changelog section for retrieval quality metrics

**Priority:** P2  
**Outcome:** Make quality improvements and regressions transparent release-to-release.

**Files:**
- Modify: `CHANGELOG.md`
- Add: `docs/guides/retrieval_release_notes.md`

**Acceptance:**
- Release template includes hit@k/mrr/ndcg snapshot block.
- Notes link to benchmark artifacts and gating thresholds.
- Format is stable for future automation.

**Verify:**
- `rg -n "Retrieval Quality" CHANGELOG.md docs/guides/retrieval_release_notes.md`

---

## Workstream F: API and Runtime Productization for Community Use (Tasks 26-30)

### Task 26: Expose retrieval profile introspection endpoint

**Priority:** P1  
**Outcome:** Let operators and contributors inspect effective runtime retrieval config.

**Files:**
- Add: `app/api/v1/retrieval_profiles.py`
- Modify: `app/api/v1/__init__.py`
- Add: `tests/test_retrieval_profiles_endpoint.py`

**Acceptance:**
- Endpoint returns profile definitions and effective defaults.
- Response includes version hash for reproducibility.
- Hidden/internal-only fields are omitted.

**Verify:**
- `pytest -q tests/test_retrieval_profiles_endpoint.py`

### Task 27: Expose retrieval explain endpoint for a single query

**Priority:** P1  
**Outcome:** Simplify fast diagnosis without running full chat flow.

**Files:**
- Add: `app/api/v1/retrieval_explain.py`
- Modify: `app/api/v1/__init__.py`
- Add: `tests/test_retrieval_explain_endpoint.py`

**Acceptance:**
- Endpoint returns channels, candidate counts, top citations, and rerank metadata.
- Supports retrieval-only mode and deterministic output schema.
- Includes execution timings per stage.

**Verify:**
- `pytest -q tests/test_retrieval_explain_endpoint.py tests/test_evidence_api_offline_regression_gate.py`

### Task 28: Add retrieval config fingerprint endpoint

**Priority:** P2  
**Outcome:** Enable external tools to pin and compare runs safely.

**Files:**
- Add: `app/api/v1/retrieval_config_hash.py`
- Add: `tests/test_retrieval_config_hash_endpoint.py`

**Acceptance:**
- Endpoint computes hash from effective runtime + request overrides.
- Hash is stable for same config and changes on meaningful knob changes.
- Used by regression scripts.

**Verify:**
- `pytest -q tests/test_retrieval_config_hash_endpoint.py tests/test_retrieval_config_fingerprint.py`

### Task 29: Add retrieval profile compatibility checker

**Priority:** P2  
**Outcome:** Prevent invalid profile combinations from reaching runtime.

**Files:**
- Add: `scripts/check_retrieval_profile_compat.py`
- Modify: `Makefile`
- Add: `tests/test_retrieval_profile_compat_checker.py`

**Acceptance:**
- Checker validates incompatible flags (for example unsupported reranker with profile).
- Returns actionable error messages.
- CI target exists for checker.

**Verify:**
- `python scripts/check_retrieval_profile_compat.py`
- `pytest -q tests/test_retrieval_profile_compat_checker.py`

### Task 30: Add API examples bundle for retrieval-focused users

**Priority:** P2  
**Outcome:** Lower onboarding friction for OSS adopters evaluating retrieval quality.

**Files:**
- Add: `docs/examples/retrieval_api_examples.http`
- Add: `docs/examples/retrieval_api_examples.md`
- Modify: `docs/README.md`

**Acceptance:**
- Examples cover retrieve, explain, regression gate, and ablation commands.
- Examples avoid vendor-specific dependencies.
- Sample payloads are runnable against local docker setup.

**Verify:**
- Manual smoke with `curl` and `http` clients.

---

## Workstream G: Data Quality and Chunk/Index Quality Controls (Tasks 31-35)

### Task 31: Add chunk-quality signal export to retrieval traces

**Priority:** P1  
**Outcome:** Connect chunk preprocessing quality to downstream recall behavior.

**Files:**
- Modify: `app/services/chunk_quality_scoring.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Add: `tests/test_chunk_quality_trace_fields.py`

**Acceptance:**
- Trace can expose chunk quality buckets for top candidates.
- Fields are bounded and deterministic.
- No large payload bloat.

**Verify:**
- `pytest -q tests/test_chunk_quality_trace_fields.py`

### Task 32: Add ingest-time recall risk heuristics to dataset profile

**Priority:** P2  
**Outcome:** Warn users when corpus characteristics predict poor recall.

**Files:**
- Modify: `app/services/dataset_profile_service.py`
- Modify: `app/services/dataset_profile_utils.py`
- Add: `tests/test_dataset_profile_recall_risk.py`

**Acceptance:**
- Profile summary includes recall-risk hints (for example too-short chunks, low lexical diversity).
- Hints are best-effort and never block ingest.
- Exported report includes risk summary.

**Verify:**
- `pytest -q tests/test_dataset_profile_recall_risk.py tests/test_dataset_profile_summary_schema_contract.py`

### Task 33: Add query-set health diagnostics job

**Priority:** P2  
**Outcome:** Periodically detect recall drift against canonical query sets.

**Files:**
- Add: `scripts/run_queryset_health_diagnostics.py`
- Add: `app/services/queryset_health_service.py`
- Add: `tests/test_queryset_health_service.py`

**Acceptance:**
- Job evaluates fixed query set and records trend metrics.
- Output is machine-readable and includes profile hash.
- Can run in cron/nightly mode.

**Verify:**
- `pytest -q tests/test_queryset_health_service.py`

### Task 34: Add lightweight near-duplicate chunk suppression controls

**Priority:** P1  
**Outcome:** Improve candidate diversity and reduce top-k redundancy.

**Files:**
- Modify: `app/rag/retriever.py`
- Add: `tests/test_retrieval_near_dedup_simhash.py`

**Acceptance:**
- Dedup settings are profile-aware and configurable.
- Diversity metrics are exposed in debug metadata.
- No hidden filtering when feature is disabled.

**Verify:**
- `pytest -q tests/test_retrieval_near_dedup_simhash.py tests/test_retrieval_content_hash_dedup.py`

### Task 35: Add multi-lingual recall sanity tests for zh/en mixed corpora

**Priority:** P2  
**Outcome:** Catch language-tokenization regressions early.

**Files:**
- Add: `tests/test_multilingual_recall_regression.py`
- Modify: `app/rag/preprocessing/tokenization.py`

**Acceptance:**
- Mixed-language retrieval cases are part of regression gate fixtures.
- Tokenization changes cannot silently degrade one language family.
- Results are deterministic across runs.

**Verify:**
- `pytest -q tests/test_multilingual_recall_regression.py`

---

## Workstream H: Delivery Discipline and Maintainer Workflow (Tasks 36-40)

### Task 36: Create retrieval-quality epic and child issue taxonomy in bd

**Priority:** P0  
**Outcome:** Make the 40-task plan trackable with clear ownership.

**Files:**
- Modify: `.beads/issues.jsonl` (via `bd` commands, not manual edits)

**Acceptance:**
- One epic for this plan and 40 child tasks are created.
- Dependencies are encoded where sequencing matters.
- Labels include `retrieval-quality` and `oss-experience`.

**Verify:**
- `bd ready`
- `bd show <epic-id>`

### Task 37: Add contributor checklist for retrieval PRs

**Priority:** P1  
**Outcome:** Ensure PRs include quality evidence, not only code diffs.

**Files:**
- Add: `docs/contributing/retrieval_pr_checklist.md`
- Modify: `CONTRIBUTING.md`

**Acceptance:**
- Checklist enforces ablation or regression evidence for ranking changes.
- Includes minimum commands and artifact expectations.
- Referenced from main contributing guide.

**Verify:**
- `rg -n "retrieval_pr_checklist" CONTRIBUTING.md`

### Task 38: Add CI job for retrieval-only bounded gate

**Priority:** P1  
**Outcome:** Prevent recall regressions from merging unnoticed.

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `ci/retrieval_thresholds.v2.json`
- Test: `tests/test_ci_retrieval_gate_workflow.py`

**Acceptance:**
- CI runs retrieval-only gate on deterministic fixture.
- Failure output points to metric and threshold deltas.
- Runtime remains bounded for contributor forks.

**Verify:**
- CI run in PR
- `pytest -q tests/test_ci_retrieval_gate_workflow.py`

### Task 39: Add release-gate extension for retrieval leaderboard drift

**Priority:** P2  
**Outcome:** Block releases when key retrieval metrics drop below policy.

**Files:**
- Modify: `scripts/release_gate.py`
- Modify: `docs/guides/release_gate.md`
- Add: `tests/test_release_gate_retrieval_leaderboard.py`

**Acceptance:**
- Release gate can consume leaderboard artifact and apply min thresholds.
- Gate supports warning mode and hard-fail mode.
- Output is human-readable and CI-friendly.

**Verify:**
- `pytest -q tests/test_release_gate_retrieval_leaderboard.py`

### Task 40: Add quarterly retrieval debt audit report generator

**Priority:** P2  
**Outcome:** Keep long-tail quality debt visible and prioritized.

**Files:**
- Add: `scripts/generate_retrieval_debt_audit.py`
- Add: `docs/templates/retrieval_debt_audit_template.md`
- Modify: `docs/operations.md`

**Acceptance:**
- Script summarizes stale thresholds, flaky tests, unstable profiles, and TODO hotspots.
- Report format is consistent across quarters.
- Ops docs include cadence and ownership guidance.

**Verify:**
- `python scripts/generate_retrieval_debt_audit.py --out runs/retrieval_debt_audit.md`

---

## Suggested Delivery Milestones

1. Milestone M1 (Weeks 1-2): Tasks 1-12  
2. Milestone M2 (Weeks 3-4): Tasks 13-25  
3. Milestone M3 (Weeks 5-6): Tasks 26-40

## Definition of Done for This Plan

- All P0 tasks are complete and passing.
- Retrieval-only regression gate is enforced in CI.
- One production default retrieval profile is documented and benchmarked.
- OSS contributors can reproduce a baseline benchmark in under 30 minutes.
- LTR candidate train/eval/compare is a one-command workflow with auditable artifacts.
