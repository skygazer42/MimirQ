# MimirQ 40-Task Top-Tier Optimization Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the highest-value remaining gaps between the current MimirQ codebase and top-tier enterprise RAG/knowledge platforms with a 40-task execution program grounded in the current implementation, not in stale roadmap assumptions.

**Architecture:** This plan assumes MimirQ already has a strong product shell, hybrid retrieval stack, Evidence/Regression loop, connector framework, KG tooling, and enterprise baseline controls. The remaining work is mostly about correctness at scale, productionizing the strongest retrieval paths, hardening sync semantics, tightening authz and lifecycle guarantees, and raising frontend/operator workflows from powerful internal tooling to fully hardened platform features.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, Redis, Milvus, MinIO, arq/task queue, Next.js App Router, TypeScript, Vitest, pytest, Prometheus/OTel, `bd` issue tracking.

---

## Planning Assumptions

- This plan is based on the current code paths in:
  - `app/api/v1/connectors.py`
  - `app/rag/retriever.py`
  - `app/rag/retrieval/orchestrator.py`
  - `app/rag/reranker/*`
  - `app/api/v1/evidence.py`
  - `app/api/v1/evaluations.py`
  - `app/services/*cache*`
  - `app/services/document_access.py`
  - `app/services/saml_service.py`
  - `web/app/*`
- Current code is ahead of some plan docs. In particular, SAML ACS is implemented in code and documented in `docs/guides/saml_sso.md`, even though some older plan docs still describe it as a stub.
- The biggest remaining gaps are not "missing features" but "missing closure":
  - incremental sync edge correctness
  - strongest retrieval/rerank path productionization
  - automated training/eval/promotion workflow
  - version-safe shared caches
  - finer-grained authz and lifecycle controls
  - browser-level product hardening

## Execution Rules

1. Land work by workstream order unless an explicit dependency says otherwise.
2. For behavior changes, start with tests or regression fixtures before implementation.
3. Treat ACL, auth, retention, and lifecycle work as fail-closed by default.
4. Anything used by CI or release gates must have deterministic fallback behavior.
5. Prefer one bounded feature flag per risky rollout path.
6. Use `bd` to track each workstream as an epic and each task below as a child task.

## Workstream Overview

- Workstream A: Connector Sync Correctness
- Workstream B: Retrieval and Rerank Productionization
- Workstream C: Evaluation and Learning Loop Automation
- Workstream D: Cache, Routing, and Runtime Safety
- Workstream E: Enterprise Identity, RBAC, and ACL Hardening
- Workstream F: Frontend Workbench Hardening
- Workstream G: Ops, Scheduler, and Lifecycle Governance
- Workstream H: Documentation, Drift Control, and Release Discipline

## Dependency Summary

- Workstream A should start first because connector correctness affects corpus freshness, ACL drift, and downstream eval validity.
- Workstream B and Workstream D can run in parallel after A1-A3 are in place.
- Workstream C depends on B1-B3 and D1-D3 for stable offline/online comparison.
- Workstream E can partially run in parallel, but E3-E5 should wait until A and D tighten scope/corpus behavior.
- Workstream F should follow the first completed slices of A/B/C so browser E2E covers the real workflows.
- Workstream G should start after A and D establish stable state models.
- Workstream H should run throughout, but H1-H3 should land early.

---

## Workstream A: Connector Sync Correctness

### Task 1: Define connector sync semantics matrix

**Priority:** P0  
**Outcome:** Make `supports_resume` vs `supports_incremental` vs `full_reconcile` explicit across connectors.

**Files:**
- Modify: `app/services/connector_registry.py`
- Modify: `app/api/schemas/connector.py`
- Modify: `app/api/v1/connectors.py`
- Modify: `docs/guides/connectors.md`

**Acceptance:**
- API returns distinct capability flags for resume, incremental, and full reconciliation.
- UI/docs no longer imply all connectors have the same sync semantics.
- Tests cover schema serialization and `/connectors` output shape.

**Verify:**
- `pytest -q tests/test_connector_sync_state.py tests/test_connectors_endpoints.py`

### Task 2: Introduce versioned connector state schema v2

**Priority:** P0  
**Outcome:** Replace ad hoc per-connector state with a common envelope that can carry high-water marks, manifests, and reconciliation metadata.

**Files:**
- Modify: `app/services/connector_sync_state.py`
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connector_sync_state.py`

**Acceptance:**
- State payloads carry `state_schema_version=2`.
- Common fields exist for cursor family, source manifest family, and last successful reconcile marker.
- Existing v1 state is read compatibly and upgraded on next sync.

**Verify:**
- `pytest -q tests/test_connector_sync_state.py tests/test_connector_run_retry_resume.py`

### Task 3: Fix timestamp-boundary safety for Confluence incremental sync

**Priority:** P0  
**Outcome:** Remove the risk of missing pages when multiple source rows share the same `lastmodified` boundary.

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_confluence_connector_unit.py`
- Add: `tests/test_confluence_incremental_cursor_boundary.py`

**Acceptance:**
- Confluence incremental state stores a composite watermark, not just raw timestamp.
- Boundary replay is deterministic and idempotent.
- Tests cover equal-timestamp pages across page boundaries and interrupted runs.

**Verify:**
- `pytest -q tests/test_confluence_connector_unit.py tests/test_confluence_incremental_cursor_boundary.py`

### Task 4: Fix timestamp-boundary safety for Jira incremental sync

**Priority:** P0  
**Outcome:** Remove the risk of missing issues when multiple issues share the same `updated` value around pagination or cancellation boundaries.

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_jira_connector_full_sync_disable_semantics.py`
- Add: `tests/test_jira_incremental_cursor_boundary.py`

**Acceptance:**
- Jira incremental state uses a composite watermark such as `(updated, issue_id)` or equivalent deterministic replay window.
- No issue is silently skipped across restarts.
- Existing tests for full-sync disable semantics still pass.

**Verify:**
- `pytest -q tests/test_jira_connector_full_sync_disable_semantics.py tests/test_jira_incremental_cursor_boundary.py`

### Task 5: Upgrade `web_crawl` from checkpoint resume to source delta sync

**Priority:** P0  
**Outcome:** Turn site crawl from "resume a run" into "track source state and reconcile changes".

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/services/connector_sync_state.py`
- Modify: `app/services/web_crawler.py`
- Add: `tests/test_web_crawl_delta_sync.py`

**Acceptance:**
- Crawled pages carry stable source identity and source manifest entries.
- No-op reruns skip unchanged pages.
- Full reconcile can soft-disable missing pages when listing completeness is known.

**Verify:**
- `pytest -q tests/test_web_crawl_delta_sync.py tests/test_connector_saved_state_resume.py`

---

## Workstream B: Retrieval and Rerank Productionization

### Task 6: Declare the supported production rerank profiles

**Priority:** P0  
**Outcome:** Stop treating every reranker as equally production-ready.

**Files:**
- Modify: `app/rag/reranker/factory.py`
- Modify: `app/core/config.py`
- Modify: `docs/guides/reranking_colbert.md`
- Modify: `docs/guides/reranking_ltr.md`

**Acceptance:**
- Config/docs classify rerankers as `prod`, `experimental`, or `offline-only`.
- Default production profile is explicit.
- Risky providers require feature flags.

**Verify:**
- `pytest -q tests/test_cross_encoder_reranker_scaffold.py tests/test_evidence_post_rerank_ltr.py`

### Task 7: Add a first-class retrieval profile for `hybrid + cross_encoder`

**Priority:** P0  
**Outcome:** Establish one strong, measurable production baseline path before pushing ColBERT further.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/api/v1/rag.py`
- Modify: `app/api/v1/chat.py`
- Add: `tests/test_retrieval_profile_cross_encoder.py`

**Acceptance:**
- One named retrieval profile routes to hybrid recall plus bounded cross-encoder post-rerank.
- Profile is visible in traces and regression runs.
- Offline eval artifacts can compare this profile against current default.

**Verify:**
- `pytest -q tests/test_retrieval_profile_cross_encoder.py tests/test_regression_run_runtime_wiring.py`

### Task 8: Productionize ColBERT rerank provider behind strict flags

**Priority:** P1  
**Outcome:** Keep the deterministic scaffold but add a real provider path that is explicitly experimental and benchmarkable.

**Files:**
- Modify: `app/rag/reranker/colbert.py`
- Modify: `app/rag/reranker/factory.py`
- Modify: `docs/guides/reranking_colbert.md`
- Add: `tests/test_colbert_provider_modes.py`

**Acceptance:**
- Deterministic mode remains CI-safe.
- HF-backed mode is load-tested and bounded by config.
- Metrics and traces distinguish deterministic vs HF provider clearly.

**Verify:**
- `pytest -q tests/test_colbert_provider_modes.py tests/test_eval_rerank_pipeline_offline.py`

### Task 9: Add field-aware recall signals

**Priority:** P1  
**Outcome:** Improve recall quality for heading/title-heavy corpora without fully replacing current embeddings.

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `app/services/indexer.py`
- Modify: `app/models/document.py`
- Add: `tests/test_field_aware_recall.py`

**Acceptance:**
- Retrieval can consider title/heading/body signal families separately.
- Trace output shows when field-aware boosts influenced rank.
- Rollout is guarded by a feature flag.

**Verify:**
- `pytest -q tests/test_field_aware_recall.py tests/test_retriever_debug_metrics_shape.py`

### Task 10: Add per-candidate channel attribution to traces and UI

**Priority:** P1  
**Outcome:** Make recall and rerank behavior explainable without reading raw logs.

**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/trace_schema.py`
- Modify: `web/components/rag-trace/*`
- Add: `tests/test_candidate_channel_attribution.py`

**Acceptance:**
- Each retrieved candidate exposes channel/source contribution in a bounded, PII-safe way.
- Trace UI shows contribution breakdown.
- Attribution survives replay/export.

**Verify:**
- `pytest -q tests/test_candidate_channel_attribution.py`
- `pnpm -C web test`

---

## Workstream C: Evaluation and Learning Loop Automation

### Task 11: Expand ablation matrix to match runtime retrieval knobs

**Priority:** P0  
**Outcome:** Align nightly and CI eval with the actual runtime configuration surface.

**Files:**
- Modify: `scripts/retrieval_ablation.py`
- Modify: `scripts/run_nightly_ablations.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `docs/guides/retrieval_ablation.md`

**Acceptance:**
- Ablations cover retrieval profile, query rewrite, multi-query, sparse, fusion strategy, and reranker variants.
- CI still runs a bounded deterministic subset.
- Nightly covers at least one strong hybrid+r rerank profile.

**Verify:**
- `pytest -q tests/test_run_nightly_ablations.py tests/test_ci_retrieval_gate_workflow.py`

### Task 12: Auto-materialize approved Evidence suites into training bundles

**Priority:** P0  
**Outcome:** Remove manual glue steps between reviewed evidence and LTR training inputs.

**Files:**
- Modify: `app/api/v1/evidence.py`
- Modify: `app/services/ltr_rollout_workflow.py`
- Add: `tests/test_evidence_suite_training_bundle.py`

**Acceptance:**
- Approved EvidenceSuite items can be exported as a versioned training bundle with lineage metadata.
- Bundle creation is auditable and tenant-scoped.
- Output schema is stable and reusable by train/eval scripts.

**Verify:**
- `pytest -q tests/test_evidence_suite_training_bundle.py tests/test_regression_case_bundle_export.py`

### Task 13: Auto-materialize selected feedback into Evidence and regression seeds

**Priority:** P0  
**Outcome:** Turn negative feedback into governed hardcase discovery instead of ad hoc manual work.

**Files:**
- Modify: `app/api/v1/feedback.py`
- Modify: `app/services/hardcase_discovery_service.py`
- Add: `tests/test_feedback_hardcase_materialization.py`

**Acceptance:**
- Feedback can be batched into draft Evidence items or regression seeds with dedupe.
- Request is bounded and PII-safe in exported summaries.
- Reviewer workflow remains explicit before promotion.

**Verify:**
- `pytest -q tests/test_feedback_hardcase_materialization.py tests/test_feedback_to_evidence_item.py`

### Task 14: Persist training/eval lineage into the LTR registry

**Priority:** P0  
**Outcome:** Make every candidate model reproducible from source bundles and retrieval settings.

**Files:**
- Modify: `app/services/ltr_model_registry.py`
- Modify: `scripts/train_ltr_from_regression_cases.py`
- Modify: `scripts/prepare_ltr_rollout.py`
- Add: `tests/test_ltr_registry_lineage_enrichment.py`

**Acceptance:**
- Model manifests include data hash, retrieval config fingerprint, feature spec, and source bundle references.
- Candidate vs baseline comparisons are stored as artifacts.
- Registry listing exposes enough metadata for rollback decisions.

**Verify:**
- `pytest -q tests/test_train_ltr_manifest_lineage.py tests/test_ltr_registry_lineage_enrichment.py`

### Task 15: Add explicit promotion and rollback workflow APIs

**Priority:** P1  
**Outcome:** Replace loose script choreography with one bounded approval path.

**Files:**
- Modify: `app/api/v1/ltr.py`
- Modify: `app/services/ltr_model_registry.py`
- Add: `tests/test_ltr_promotion_workflow.py`

**Acceptance:**
- Candidate model promotion requires explicit compare artifact reference.
- Rollback is one-step and tested.
- Promotion API is auditable and rejects invalid manifests.

**Verify:**
- `pytest -q tests/test_ltr_promotion_workflow.py tests/test_ltr_feature_spec_fingerprint.py`

---

## Workstream D: Cache, Routing, and Runtime Safety

### Task 16: Make evidence post-rerank cache shared and version-aware by default

**Priority:** P0  
**Outcome:** Avoid repeated expensive reranking across replicas while preventing stale reuse.

**Files:**
- Modify: `app/rag/rerank_result_cache.py`
- Modify: `app/core/config.py`
- Add: `tests/test_evidence_rerank_cache_redis_keying.py`

**Acceptance:**
- Redis backend is fully supported and tested.
- Cache key includes provider/model/feature version and corpus invalidation when needed.
- Metrics distinguish hit, miss, disabled, and stale-skip cases.

**Verify:**
- `pytest -q tests/test_evidence_rerank_cache_redis_keying.py tests/test_evidence_post_rerank_ltr.py`

### Task 17: Add cache observability and skip-reason telemetry

**Priority:** P1  
**Outcome:** Turn cache behavior into something operators can reason about.

**Files:**
- Modify: `app/rag/retrieval_candidate_cache.py`
- Modify: `app/services/chat_response_cache.py`
- Modify: `app/rag/rerank_result_cache.py`
- Modify: `app/api/v1/observability.py`

**Acceptance:**
- Cache metrics expose hit/miss/skip reasons.
- Observability API/UI can show top skip reasons by cache family.
- No raw query text or document text appears in cache metrics.

**Verify:**
- `pytest -q tests/test_chat_cache_corpus_invalidation.py tests/test_observability_rag_metrics.py`

### Task 18: Add dataset routing policy for open-scope retrieval

**Priority:** P1  
**Outcome:** Reduce recall noise and cost when chat runs without explicit `document_ids`.

**Files:**
- Modify: `app/api/v1/chat.py`
- Modify: `app/rag/policy/intent_router.py`
- Modify: `app/services/dataset_profile_service.py`
- Add: `tests/test_dataset_routing_policy.py`

**Acceptance:**
- Open-scope chat can optionally route into a bounded dataset subset before full retrieval.
- Route decision is visible in metrics/traces.
- ACL remains authoritative after routing.

**Verify:**
- `pytest -q tests/test_dataset_routing_policy.py tests/test_tools_require_dataset_scope.py`

### Task 19: Upgrade intent routing from regex-only to policy-backed routing

**Priority:** P1  
**Outcome:** Keep deterministic behavior while allowing learned/configured policy overlays.

**Files:**
- Modify: `app/rag/policy/intent_router.py`
- Modify: `app/api/v1/rag_config_templates.py`
- Add: `tests/test_intent_router_policy_overlays.py`

**Acceptance:**
- Regex classification remains fallback.
- Admin-configurable routing policy can override retrieval presets in bounded ways.
- Regression traces can report which routing layer made the decision.

**Verify:**
- `pytest -q tests/test_intent_router_policy_overlays.py tests/test_recall_bucket_routing.py`

### Task 20: Remove legacy document-scope security debt

**Priority:** P1  
**Outcome:** Stop allowing legacy no-dataset documents to quietly participate in access decisions.

**Files:**
- Modify: `app/services/document_access.py`
- Add: `scripts/audit_legacy_document_scope.py`
- Add: `tests/test_legacy_document_scope_migration.py`

**Acceptance:**
- Legacy docs are first audited, then migrated, then blockable behind a feature flag.
- Production default can remain compatible until audit is complete.
- Final mode supports fail-closed enforcement.

**Verify:**
- `pytest -q tests/test_legacy_document_scope_migration.py tests/test_visible_evidence_only.py`

---

## Workstream E: Enterprise Identity, RBAC, and ACL Hardening

### Task 21: Add external identity binding records for SAML/OIDC accounts

**Priority:** P1  
**Outcome:** Move from "best-effort account match" to durable external identity mapping.

**Files:**
- Modify: `app/services/saml_service.py`
- Modify: `app/core/jwt_verify.py`
- Add: `app/models/external_identity.py`
- Add: `tests/test_external_identity_binding.py`

**Acceptance:**
- External identity bindings can record provider, subject, issuer, and local user mapping.
- Login flow can resolve by binding before fallback email/name matching.
- Audit records exist for binding creation/update.

**Verify:**
- `pytest -q tests/test_external_identity_binding.py tests/test_auth_saml_exchange_endpoint.py`

### Task 22: Add group reconciliation modes for JWT/SAML/SCIM

**Priority:** P1  
**Outcome:** Support both conservative add-only sync and mirror-style enterprise sync.

**Files:**
- Modify: `app/services/jwt_group_sync_service.py`
- Modify: `app/api/v1/scim.py`
- Modify: `docs/guides/oidc_groups_claim.md`
- Add: `tests/test_group_reconciliation_modes.py`

**Acceptance:**
- Modes include at least `add_only`, `mirror`, and `dry_run`.
- Dangerous removal paths require explicit opt-in.
- Drift summary is observable before enablement.

**Verify:**
- `pytest -q tests/test_group_reconciliation_modes.py tests/test_scim_v2_api.py`

### Task 23: Expand RBAC from tenant-global to resource-scoped roles

**Priority:** P1  
**Outcome:** Introduce dataset/connector/resource roles closer to enterprise expectations.

**Files:**
- Modify: `app/services/rbac_service.py`
- Modify: `app/api/v1/rbac.py`
- Modify: `web/app/settings/rbac/page.tsx`
- Add: `tests/test_resource_scoped_rbac.py`

**Acceptance:**
- Roles can be evaluated at least for dataset and connector operations.
- Existing admin paths remain backward compatible.
- UI can display role scope clearly.

**Verify:**
- `pytest -q tests/test_resource_scoped_rbac.py tests/test_rbac_settings_requires_admin.py`
- `pnpm -C web test`

### Task 24: Tighten source ACL fidelity reporting

**Priority:** P1  
**Outcome:** Make it obvious when source ACL inheritance was exact, mapped, fallback, or degraded.

**Files:**
- Modify: `app/services/connector_source_acl_mapping.py`
- Modify: `app/api/v1/connectors.py`
- Modify: `web/components/knowledge/*`
- Add: `tests/test_source_acl_fidelity_reporting.py`

**Acceptance:**
- Source ACL application records fidelity mode in metadata and run stats.
- UI shows when inheritance fell back to owner-only or coarse group mapping.
- Operators can export ACL provenance safely.

**Verify:**
- `pytest -q tests/test_source_acl_fidelity_reporting.py tests/test_connector_acl_delta_sync_unit.py`

### Task 25: Add session-hardening pass for SSO and API auth flows

**Priority:** P2  
**Outcome:** Raise the floor on auth/session handling without changing the core login model.

**Files:**
- Modify: `web/app/api/saml/acs/route.ts`
- Modify: `web/app/api/oidc/*`
- Modify: `app/api/v1/auth.py`
- Add: `tests/test_session_hardening_flows.py`

**Acceptance:**
- Session bridge cookies and auth redirects have consistent no-store semantics and bounded lifetime.
- Security-sensitive error paths are normalized.
- Tests cover token exchange edge cases and replay/timeout handling.

**Verify:**
- `pytest -q tests/test_session_hardening_flows.py tests/test_saml_auth_exchange.py`
- `pnpm -C web test`

---

## Workstream F: Frontend Workbench Hardening

### Task 26: Add browser E2E coverage for connector import flows

**Priority:** P0  
**Outcome:** Validate real user workflows instead of only source-shape tests.

**Files:**
- Add: `web/e2e/connectors/*.spec.ts`
- Modify: `web/package.json`
- Add: E2E config under `web/`

**Acceptance:**
- E2E covers at least URL batch, web crawl, and Jira/Confluence config form flows.
- Mocked backend fixtures keep tests deterministic.
- CI can run a smoke subset.

**Verify:**
- `pnpm -C web test:e2e`

### Task 27: Add browser E2E for Evidence and regression workflows

**Priority:** P0  
**Outcome:** Protect the strongest product differentiator with real workflow tests.

**Files:**
- Add: `web/e2e/evidence/*.spec.ts`
- Add: `web/e2e/evaluations/*.spec.ts`

**Acceptance:**
- E2E covers EvidenceSuite review, sync to regression, leaderboard, and diff page.
- Flow is stable with mocked artifacts and fixed seed data.

**Verify:**
- `pnpm -C web test:e2e`

### Task 28: Break up the KG graph mega-page into bounded feature containers

**Priority:** P1  
**Outcome:** Reduce regression surface and improve maintainability of the most complex operator page.

**Files:**
- Modify: `web/app/graph/page.tsx`
- Create: `web/components/graph/*`
- Add: `web/components/graph/*.test.tsx`

**Acceptance:**
- Graph page becomes a thin container delegating to focused feature modules.
- Alias management, merge/split, explain mode, and import mode are separable units.
- Existing behavior stays intact.

**Verify:**
- `pnpm -C web test`
- `pnpm -C web typecheck`

### Task 29: Replace source-string UI tests with behavior tests for critical workbenches

**Priority:** P1  
**Outcome:** Shift the frontend suite from structural guardrails toward user-visible correctness.

**Files:**
- Modify: selected `web/components/**/*.source.test.ts`
- Add: behavior tests for knowledge, trace, graph snapshots, and reports

**Acceptance:**
- At least 10 source-string tests are replaced or supplemented by rendered interaction tests.
- Critical flows assert state transitions and rendered data, not just string presence.

**Verify:**
- `pnpm -C web test`

### Task 30: Add guided UX for graph diagnostics and snapshots

**Priority:** P2  
**Outcome:** Move graph workbenches from "internal expert tool" toward "operator-ready workflow".

**Files:**
- Modify: `web/components/graph/kg-diagnostics-page.tsx`
- Modify: `web/components/graph/kg-snapshots-page.tsx`
- Modify: `web/lib/api-client.ts`

**Acceptance:**
- Dataset/pipeline selection is discoverable and prefilled when possible.
- Common comparisons require fewer manual IDs.
- Empty states explain what prerequisite data is missing.

**Verify:**
- `pnpm -C web test`
- `pnpm -C web typecheck`

---

## Workstream G: Ops, Scheduler, and Lifecycle Governance

### Task 31: Move connector scheduling from tick hook toward managed queue semantics

**Priority:** P0  
**Outcome:** Replace ad hoc external "tick" orchestration with a more platform-like scheduler path.

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/tasks/jobs.py`
- Add: `app/services/connector_scheduler_service.py`
- Add: `tests/test_connector_scheduler_service.py`

**Acceptance:**
- Scheduler can enqueue due runs under a service identity or explicit scheduler actor.
- Duplicate due-run creation is prevented.
- Operator-visible run reason distinguishes manual, scheduled, retry, and resume.

**Verify:**
- `pytest -q tests/test_connector_scheduler_service.py tests/test_connector_schedule_due.py`

### Task 32: Add suppression/error counters for best-effort code paths

**Priority:** P1  
**Outcome:** Turn silent resilience behavior into measurable reliability signals.

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/services/retention_jobs.py`
- Modify: `app/api/v1/documents.py`
- Modify: `app/api/v1/observability.py`

**Acceptance:**
- Best-effort failure paths emit counters with bounded labels.
- Operators can distinguish "success with suppression" from clean success.
- No raw PII enters these counters.

**Verify:**
- `pytest -q tests/test_observability_rag_metrics.py tests/test_periodic_audit_jobs.py`

### Task 33: Finish full knowledge-asset lifecycle retention verification

**Priority:** P1  
**Outcome:** Prove that retention deletes docs/chunks/KG/vectors/object assets coherently.

**Files:**
- Modify: `app/services/retention_jobs.py`
- Modify: `app/api/v1/documents.py`
- Add: `tests/test_retention_jobs_knowledge_assets.py`

**Acceptance:**
- End-to-end retention path is tested against document lifecycle delegates.
- Dry-run/apply summaries are auditable.
- Retention docs explain failure handling and reconciliation steps.

**Verify:**
- `pytest -q tests/test_retention_jobs_knowledge_assets.py tests/test_run_retention_jobs_cli.py`

### Task 34: Add scheduler and ingestion control-plane report surfaces

**Priority:** P2  
**Outcome:** Give operators a coherent view of connector health, backlog, and failure taxonomy.

**Files:**
- Modify: `app/api/v1/reports.py`
- Modify: `web/app/reports/page.tsx`
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Acceptance:**
- Reports surface summarizes scheduled runs, stale configs, error groups, and retry hotspots.
- Ingestion UI can pivot to connector health details.

**Verify:**
- `pytest -q tests/test_report_html_redaction.py`
- `pnpm -C web test`

### Task 35: Add rollout guardrails for risky retrieval/provider changes

**Priority:** P1  
**Outcome:** Make provider/rerank/route changes deployable with bounded blast radius.

**Files:**
- Modify: `scripts/release_gate.py`
- Modify: `docs/guides/release_gate.md`
- Modify: `app/api/v1/observability.py`

**Acceptance:**
- Release gate can compare baseline vs candidate on bounded traffic or replay artifacts.
- Risky retrieval changes require comparison evidence before activation.
- Rollback instructions are one-screen obvious.

**Verify:**
- `pytest -q tests/test_regression_gate_run_payload.py tests/test_release_gate_workflow.py`

---

## Workstream H: Documentation, Drift Control, and Release Discipline

### Task 36: Reconcile plan docs with implemented SAML and connector reality

**Priority:** P0  
**Outcome:** Remove stale plan guidance that now contradicts the codebase.

**Files:**
- Modify: `docs/plans/2026-03-07-top-tier-gap-closure-plan.md`
- Modify: `docs/guides/saml_sso.md`
- Modify: `docs/guides/connectors.md`

**Acceptance:**
- Docs no longer describe SAML ACS as unimplemented.
- Connector capability language matches current code.
- Remaining gaps are stated as true remaining gaps, not historical ones.

**Verify:**
- Manual review plus doc lint if available.

### Task 37: Add a single "current platform maturity" source of truth

**Priority:** P1  
**Outcome:** Make roadmap, wave status, and current implementation state converge.

**Files:**
- Modify: `docs/waves/status.md`
- Create: `docs/status/platform-maturity.md`

**Acceptance:**
- One file states what is production-ready, experimental, or planned.
- Links point to the owning code/docs/tests.
- Future planning references this file instead of restating stale assumptions.

**Verify:**
- Manual review.

### Task 38: Add docs drift checks to CI for a few high-risk areas

**Priority:** P1  
**Outcome:** Catch obvious code/doc contradictions before they linger.

**Files:**
- Add: lightweight drift check script under `scripts/`
- Modify: `.github/workflows/ci.yml`

**Acceptance:**
- CI can flag a bounded set of contradictions for high-risk areas such as auth, connectors, and release-gate docs.
- Checks are narrow and deterministic, not brittle prose lint.

**Verify:**
- `pytest -q tests/test_docs_drift_checks.py`

### Task 39: Create a 90-day execution dashboard tied to `bd`

**Priority:** P2  
**Outcome:** Turn this plan into a shippable program with visible sequencing.

**Files:**
- Update via `bd`: one epic per workstream, one child issue per task
- Modify: `docs/waves/status.md`

**Acceptance:**
- `bd` reflects the exact 40-task structure.
- Blockers mirror only real dependencies from this plan.
- Status file points to owning epics.

**Verify:**
- `bd ready`
- `bd show <epic-id>`

### Task 40: Add a top-tier optimization entrypoint doc for future sessions

**Priority:** P2  
**Outcome:** Make future contributors immediately see where the platform is strong and where it still needs closure.

**Files:**
- Create: `docs/guides/top_tier_optimization.md`
- Modify: `docs/README.md`
- Modify: `README.md`

**Acceptance:**
- The guide explains the active optimization program, success metrics, and current priorities.
- It links to this 40-task plan, key guides, and major dashboards.

**Verify:**
- Manual review.

---

## Suggested Execution Order

### Phase 1: Correctness First

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 36

### Phase 2: Strongest Retrieval Path

1. Task 6
2. Task 7
3. Task 8
4. Task 9
5. Task 10
6. Task 16
7. Task 17

### Phase 3: Eval and Learning Closure

1. Task 11
2. Task 12
3. Task 13
4. Task 14
5. Task 15
6. Task 35

### Phase 4: Scope, Auth, and Security Tightening

1. Task 18
2. Task 19
3. Task 20
4. Task 21
5. Task 22
6. Task 23
7. Task 24
8. Task 25

### Phase 5: Product Hardening

1. Task 26
2. Task 27
3. Task 28
4. Task 29
5. Task 30

### Phase 6: Platform Ops Closure

1. Task 31
2. Task 32
3. Task 33
4. Task 34
5. Task 37
6. Task 38
7. Task 39
8. Task 40

---

## Success Metrics

- Connector sync correctness:
  - No known incremental boundary-loss bugs in Jira/Confluence.
  - At least 3 high-value connectors support true source delta semantics.
- Retrieval quality:
  - One clearly defined production retrieval+r rerank profile with stable regression gains.
  - CI/nightly coverage matches the real runtime matrix.
- Learning loop:
  - Evidence/feedback can produce training bundles without manual glue scripts.
  - Candidate-vs-baseline comparisons are recorded before activation.
- Runtime safety:
  - Shared caches are version-aware and observable.
  - Open-scope retrieval is reduced or routed more intelligently.
- Enterprise controls:
  - External identity mapping and group reconciliation modes are explicit.
  - Resource-scoped RBAC is in place for datasets/connectors.
- Product maturity:
  - Browser E2E exists for the top operator workflows.
  - Critical workbenches have behavior tests, not just source-string tests.

---

## Notes for Execution

- Prefer landing one workstream slice at a time rather than scattering partial implementation across all 40 tasks.
- The highest ROI sequence is:
  - A1-A5
  - B6-B10
  - C11-C15
  - D16-D20
  - F26-F29
- Do not start adding more connectors before A1-A5 are stable.
- Do not promote stronger adaptive routing or rerank paths before C11-C15 and D16-D17 are in place.

