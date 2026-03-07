# Top-Tier Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the highest-value remaining gaps between the current MimirQ codebase and a top-tier enterprise knowledge platform, based on the March 7, 2026 code review of `main` plus the `mimirq-4ey9-connector-sync` worktree.

**Architecture:** This plan does not replace the existing RAG roadmap. It narrows the next execution window to the code-confirmed gaps that still materially limit product maturity: enterprise auth completion, connector ecosystem and sync semantics, runtime-quality evaluation breadth, learning-loop automation, retrieval/rerank productionization, cache/version safety, and lifecycle governance. Work is split into independently shippable tracks, with dependencies only where stronger regression coverage must land before adaptive or automated rollout work.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, Redis, Milvus, MinIO, arq/task queue, Next.js App Router, TypeScript, `bd` issue tracking.

---

## Review Basis

This plan is grounded in the current code, not generic RAG advice:
- `web/app/api/saml/acs/route.ts` is still a `501 saml_not_implemented` skeleton.
- `app/api/v1/connectors.py` on `main` still exposes only 8 connectors and only resumes `url_batch`; the connector-sync worktree adds capability metadata and broader resume support but not broad source-of-truth incremental sync.
- Retrieval/evidence/eval are already strong, but CI and nightly ablations do not cover the full runtime retrieval surface.
- LTR and feedback loops exist, but training/promotion remain offline-heavy.
- Cache layers are useful but not yet uniformly corpus-version-aware or replica-safe.
- Retention helpers exist, but not yet across the full ingest/index/KG/storage lifecycle.

## Execution Order

### Task 1: Finish enterprise SSO instead of leaving SAML as a stub

**Problem:** OIDC and SCIM are present, but SAML ACS remains unimplemented, which keeps enterprise auth incomplete.

**Likely files:**
- `web/app/api/saml/acs/route.ts`
- backend auth/session exchange endpoints and JWT helpers
- group sync services/tests under `app/services/`
- auth UI/docs under `web/app/auth/` and `web/README.md`

**Acceptance:**
- SAMLResponse signature, audience, and time validation are implemented.
- NameID/email mapping works against MimirQ accounts.
- Optional group sync integrates with existing tenant group model.
- Successful ACS flow results in a real backend session or trusted token exchange.
- Invalid assertions, expired assertions, and replay protection have tests.

### Task 2: Upgrade connectors from checkpoint resume toward true source incremental sync

**Problem:** Capability metadata is improving, but most non-database connectors still behave as resume/checkpoint flows instead of real source delta syncs.

**Likely files:**
- `app/api/v1/connectors.py`
- shared connector registry/state services
- connector executor tests under `tests/`
- web connector settings surfaces

**Acceptance:**
- Capability model clearly distinguishes `supports_resume` from `supports_incremental`.
- Saved state is versioned and auditable per connector.
- At least one of `web_crawl`, `github_repo`, `drive_files`, or `minio_bucket` moves from resume-only semantics to real source delta semantics.
- No-op reruns, partial failures, and resumed reruns are covered by focused tests.
- API/UI describe capabilities consistently.

### Task 3: Expand connector portfolio toward top enterprise source coverage

**Problem:** The shared connector surface is still too narrow for a top-tier enterprise knowledge product.

**Likely files:**
- shared connector registry
- connector schema and API files
- connector settings UI
- docs/guides for ingestion/connectors

**Acceptance:**
- Pick a prioritized source list from the obvious high-value gaps (for example Jira, Notion, Slack, SharePoint, or similar).
- Ship at least one new enterprise connector end-to-end using the shared registry/capability model.
- New connector supports ACL-aware ingestion where the source allows it.
- Tests/documentation make the connector reusable as a template for follow-on sources.

### Task 4: Make regression and ablation coverage match the real retrieval runtime

**Problem:** Current evaluation is strong, but CI/nightly coverage is still narrower than the runtime configuration surface.

**Likely files:**
- `scripts/retrieval_ablation.py`
- `scripts/run_nightly_ablations.py`
- `.github/workflows/ci.yml`
- regression fixtures and evaluation docs

**Acceptance:**
- Ablation runner supports the major runtime knobs now missing from the default sweep: retrieval profiles, fusion strategy/weights, rewrite/multi-query, sparse, and reranker variants.
- Nightly ablations include at least one representative hybrid+r rerank configuration.
- CI exercises at least one bounded hybrid configuration with BM25/rerank enabled.
- Artifacts remain deterministic and bounded enough for CI.

### Task 5: Automate the feedback/evidence to training to rollout loop

**Problem:** Feedback, evidence export, and LTR registry exist, but the loop is still manual and offline-heavy.

**Likely files:**
- `app/api/v1/feedback.py`
- `app/api/v1/evidence.py`
- LTR services/registry
- scheduled jobs or scripts under `scripts/` / task queue

**Acceptance:**
- Approved evidence and/or selected feedback can be materialized into training bundles automatically.
- Training/eval lineage is persisted and auditable.
- Candidate-vs-baseline comparison is generated before activation.
- Promotion stays manually controlled but is one bounded workflow, not a loose script chain.
- Rollback path remains one-step and tested.

### Task 6: Productionize the advanced retrieval stack

**Problem:** The system already has advanced hooks, but some of the highest-end ranking and routing paths are still scaffolds or heuristic-only.

**Likely files:**
- `app/rag/policy/intent_router.py`
- `app/rag/reranker/colbert.py`
- related reranker factory/eval scripts/tests

**Acceptance:**
- Add a real late-interaction reranker provider behind flags/config.
- Keep the deterministic scaffold/fallback for offline and CI-safe use.
- Routing can incorporate learned/configurable behavior beyond fixed regex classes.
- Offline evaluation shows when the stronger path helps and when it should stay off.

### Task 7: Make retrieval/chat/rerank caches version-aware and multi-replica safe

**Problem:** Current cache keys are useful but still underspecified for fast-changing corpora and multi-instance deployments.

**Likely files:**
- `app/rag/retrieval_candidate_cache.py`
- `app/services/chat_response_cache.py`
- `app/rag/rerank_result_cache.py`
- related tests/metrics

**Acceptance:**
- Cache keys bind to a corpus or pipeline invalidation token strong enough to avoid stale reuse after reprocess/reindex.
- Evidence post-rerank cache has a Redis-backed or equivalent shared implementation for multi-replica deployments.
- Metrics expose hit/miss/skip reasons.
- Tests cover invalidation after content changes.

### Task 8: Extend retention and lifecycle governance across the full knowledge pipeline

**Problem:** Retention exists for audit logs and regression runs, but not as a unified lifecycle policy across stored knowledge assets.

**Likely files:**
- `app/services/retention_jobs.py`
- service-specific purge helpers
- ops scripts/docs

**Acceptance:**
- Retention hooks cover documents/chunks/KG/vector/object-store artifacts directly or through bounded delegates.
- Dry-run and apply flows are auditable and tenant-safe.
- At least one end-to-end purge path is tested.
- Ops docs explain cron/task-queue usage and failure handling.

## Sequencing Rules

- Task 2 should land before Task 3 so new connectors do not build on weak sync semantics.
- Task 4 should land before broad rollout work in Task 5 and before enabling stronger adaptive retrieval paths in Task 6.
- Tasks 1, 7, and 8 are independent hardening tracks and can run in parallel once staffed.

## `bd` Mapping

Create one epic for this plan and one child issue per task above. Parent-child should track the roadmap, while explicit blocker links should encode only the sequencing rules above.
