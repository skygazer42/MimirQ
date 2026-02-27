# Top-Tier Enterprise RAG Roadmap (Wave13→Wave23)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the gap between MimirQ and top-tier enterprise RAG systems by strengthening **KG**, **retrieval**, **chunking/document understanding**, and **visualization/observability**, while hardening production controls (governance, security, and operations).

**Architecture:** We keep MimirQ’s current “ingest → govern → chunk → embed/index → retrieve/fuse → rerank → cite → generate” pipeline and evolve it along four axes:
1) **Structure-first** (KG + provenance + versioning), 2) **Search excellence** (hybrid recall + deterministic rerank + continuous eval),
3) **Explainability** (UI + traces + diff tooling), 4) **Enterprise controls** (ACL, audit, retention, compliance).

**Tech Stack:** FastAPI + SQLAlchemy/Alembic + Postgres, Milvus, Redis/arq, MinIO, LangChain/LangGraph, Next.js (App Router) + React Query + shadcn/ui, OpenTelemetry/Prometheus.

---

## Where We Are Today (Strengths)

MimirQ already has many “top-tier” building blocks:
- Hybrid retrieval (vector + BM25) + fusion (RRF/linear), plus optional sparse channel scaffolding.
- Reranking options (LLM / ColBERT-style scaffold / XGBoost LTR / KG signals).
- Chunk preview UI + multiple chunk strategies (including semantic/outline/parent-child).
- Knowledge Graph (events/entities/relations/skills) + KG search diagnostics + KG-assisted query expansion + chunk injection.
- Evidence API + retrieval-only regression gate + deterministic offline replay.
- Observability: trace schema + history replay and metrics logging; OTel integration.
- Enterprise baseline: document ACL security trimming, connectors, pipeline versions, Docker deploy.

**Key remaining gaps** vs “best-in-class” RAG platforms are mostly around:
- **Versioned KG & drift control** (KG currently document/chunk scoped; needs pipeline-aware versioning and safe migration paths).
- **Human-in-the-loop structure management** (entity alias/merge/split/ontology UX; governed KG edits with audit).
- **Graph reasoning quality** (graph embeddings, relation expansion safety, provenance-first path injection).
- **Operational excellence at scale** (tenant quotas, cost controls, SLO dashboards, lifecycle policies).
- **Visualization that closes the loop** (diff tools, diagnostics workbenches, “why this chunk” explainers).

---

## Execution Rules (Non-negotiable)

1) **Wave-based delivery:** implement Wave13→Wave23 in order.
2) **Every wave ends with:** tests/lints + a single commit (`waveXX: ...`).
3) **Fail-closed governance/security:** never widen access scope by accident.
4) **Determinism for quality gates:** anything used in CI must be deterministic (seeded or offline providers).

---

## Roadmap Overview (100 Tasks)

We run **10 waves × 10 tasks** = **100 tasks**:
- Wave13: Roadmap + gap instrumentation + “diff-first” tooling baseline
- Wave14: KG versioning & pipeline-aware provenance
- Wave15: Entity resolution (aliases/merge/split) + ontology governance
- Wave16: KG reasoning & graph retrieval (embeddings/path/provenance injection)
- Wave17: Retrieval excellence v2 (cross-encoder + better fusion + caching)
- Wave18: Chunking/document understanding v2 (layout-aware + table/image grounding)
- Wave19: Multi-modal RAG (image/table evidence, UI citations, safety)
- Wave20: Visualization & explainability workbenches (KG/retrieval/eval)
- Wave21: Continuous evaluation & CI gates (answer + retrieval + KG)
- Wave22: Governance/security/compliance hardening (enterprise knobs)

Wave23 is reserved for **operations & scale** (throughput, jobs, quotas, cost, SLO) and is intentionally last so it hardens the proven product surface.

---

## Wave13 (T001–T010): Gap Baseline + “Diff-First” Tooling

### Wave13-T001: Publish top-tier gap map (this doc)
**Files:** Create `docs/plans/2026-02-27-top-tier-rag-roadmap.md`  
**Acceptance:** 10 waves × 10 tasks defined with concrete deliverables and owners (backend/frontend/docs).  

### Wave13-T002: Add a “RAG Excellence” meta checklist in docs
**Files:** Modify `docs/guides/rag_optimization.md`  
**Acceptance:** A single page linking chunking/retrieval/rerank/eval/KG + recommended order of operations.  

### Wave13-T003: Add KG snapshot/diff endpoints to KG guide
**Files:** Modify `docs/guides/knowledge_graph.md`  
**Acceptance:** Document `/kg/snapshots/export|compare|diff` usage + safety notes.  

### Wave13-T004: Frontend: Add a minimal KG snapshot compare page (inputs + diff JSON)
**Files:** Create `web/app/graph/snapshots/page.tsx`, modify nav if needed  
**Test:** `pnpm -C web test` (add a smoke test for rendering + request shaping)  

### Wave13-T005: Backend: Add snapshot export/compare unit coverage for pipeline hash selection
**Files:** Add tests under `tests/` for KG snapshot export selection edge cases  
**Test:** `pytest -q`  

### Wave13-T006: Add “retrieval_config_hash” to UI trace cards
**Files:** Modify trace UI components to show config hash for A/B comparisons  
**Test:** `pnpm -C web test && pnpm -C web typecheck`  

### Wave13-T007: Add a “diff” export helper for retrieval traces (PII-safe)
**Files:** Add helper endpoint or script under `scripts/` exporting compact trace diffs  
**Test:** `pytest -q`  

### Wave13-T008: Add beads issues for Wave14–Wave23
**Files:** `.beads/beads.db` (via `bd create`)  
**Acceptance:** 9 issues created (Wave14..Wave23), each contains task list and success criteria.  

### Wave13-T009: Add a CI-readable “wave status” file
**Files:** Create `docs/waves/status.md`  
**Acceptance:** Contains a single table “Wave / status / last commit / next” for fast progress.  

### Wave13-T010: Run enterprise checks once
**Command:** `make enterprise-checks`  
**Acceptance:** green or known failures are filed as beads issues (Wave22/23).  

---

## Wave14 (T011–T020): KG Versioning & Pipeline-Aware Provenance

### Wave14-T011: Add `pipeline_hash` columns to KG tables (migrations)
**Files:** Alembic migration under `alembic/versions/`, models in `app/rag/kg/models.py`  
**Test:** `pytest -q tests/test_kg_*` + migration smoke  

### Wave14-T012: Make KG extraction write per `pipeline_hash` (idempotent)
**Files:** KG extract pipeline + persistence layer  
**Acceptance:** Re-extracting a document for the same pipeline overwrites only that pipeline slice.  

### Wave14-T013: Update KG APIs to accept/select `pipeline_hash`
**Files:** `app/rag/kg/api/routes.py`  
**Acceptance:** graph/search/stats/export scoped by (document_ids + pipeline_hash).  

### Wave14-T014: Update KG chunk injection to respect active pipeline hash
**Files:** `app/rag/retrieval/orchestrator.py`  
**Test:** retrieval regression cases remain stable.  

### Wave14-T015: Add KG drift audit by pipeline hash
**Files:** new eval helper under `app/rag/evaluation/`  
**Acceptance:** outputs delta summary + links to docs affected.  

### Wave14-T016: UI: Pipeline hash switcher for KG graph
**Files:** `web/app/graph/page.tsx` + API calls  

### Wave14-T017: UI: KG snapshot compare (diff cards + histogram)
**Files:** `web/app/graph/snapshots/page.tsx` (upgrade)  

### Wave14-T018: Retention job: prune old KG pipeline slices
**Files:** `app/core/jobs/` + retention runner  

### Wave14-T019: Backfill tool: migrate existing KG rows to active pipeline hash
**Files:** `scripts/migrate_kg_pipeline_hash.py`  

### Wave14-T020: Docs + runbook for KG versioning
**Files:** `docs/guides/knowledge_graph.md`  

---

## Wave15 (T021–T030): Entity Resolution + Ontology Governance

### Wave15-T021: Add `kg_entity_aliases` table (canonical_id + alias)
### Wave15-T022: Entity merge API (with audit log + reversible)
### Wave15-T023: Entity split API (safety rails)
### Wave15-T024: Alias-aware KG search (query expansion via aliases)
### Wave15-T025: Alias suggestions (embedding similarity, offline deterministic mode)
### Wave15-T026: UI: entity detail shows aliases + merge/split actions
### Wave15-T027: UI: conflict resolution workflow (preview affected edges/events)
### Wave15-T028: Ontology allowlist for predicates + UI editor
### Wave15-T029: Evidence-required enforcement for alias-induced relations
### Wave15-T030: Regression suite for entity resolution actions

---

## Wave16 (T031–T040): KG Reasoning & Graph Retrieval

### Wave16-T031: Graph embeddings (node2vec) for entity recall (offline provider)
### Wave16-T032: Relation expansion safety (caps + confidence bucketing + provenance)
### Wave16-T033: Shortest-path provenance injection into RAG trace citations
### Wave16-T034: KG-aware reranking features v3 (stable, low-cardinality)
### Wave16-T035: “Entity-centric” vs “Event-centric” KG search strategies (A/B)
### Wave16-T036: Multi-hop KG query decomposition (LLM optional, deterministic fallback)
### Wave16-T037: UI: path explorer shows provenance excerpts
### Wave16-T038: KG diagnostics runner supports relation/path ablations
### Wave16-T039: Add KG search regression gate (Hit/MRR/Recall @K)
### Wave16-T040: Docs: KG reasoning cookbook

---

## Wave17 (T041–T050): Retrieval Excellence v2

### Wave17-T041: Add cross-encoder reranker provider (sentence-transformers)
### Wave17-T042: Add “candidate set cache” (PII-safe hash + TTL)
### Wave17-T043: Add weighted fusion (learned weights per dataset)
### Wave17-T044: Add field-aware embeddings (title/heading/body) for recall
### Wave17-T045: Add query intent router (faq/howto/api/log) → retrieval presets
### Wave17-T046: Add query-time diversity caps by doc/page (avoid near-dup)
### Wave17-T047: Add LTR training data export UI (hard negatives + slices)
### Wave17-T048: Add LTR model registry + rollback
### Wave17-T049: Add retrieval “budget explain” UI (why clipped)
### Wave17-T050: Retrieval-only CI gate on golden suites

---

## Wave18 (T051–T060): Chunking / Document Understanding v2

### Wave18-T051: Layout-aware PDF chunking (bbox + columns)
### Wave18-T052: Table grounding improvements (table store selection + citations)
### Wave18-T053: Image/OCR chunk roles + dedup (hash-based)
### Wave18-T054: Adaptive chunk sizes (by doc type + density metrics)
### Wave18-T055: Chunk quality scoring (noise/boilerplate detection)
### Wave18-T056: Chunk adjacency graph (prev/next) + retrieval stitching
### Wave18-T057: Chunk preview: “coverage heatmap” + AB diff export
### Wave18-T058: Chunk strategy presets per dataset with governance
### Wave18-T059: Chunking regression suites (deterministic fixtures)
### Wave18-T060: Docs: chunking playbook + anti-patterns

---

## Wave19 (T061–T070): Multi-Modal RAG

### Wave19-T061: Image embedding index (CLIP) + citations
### Wave19-T062: PDF figure extraction + linking to chunks
### Wave19-T063: Multi-modal query routing (text vs image vs table)
### Wave19-T064: UI: show image citations inline (safe thumbnail)
### Wave19-T065: Safety: PII redaction in OCR outputs (policy-driven)
### Wave19-T066: Multi-modal evaluation harness (image/table questions)
### Wave19-T067: Add “evidence viewer” for image/table provenance
### Wave19-T068: Add content-based dedup across modalities
### Wave19-T069: Add bandwidth-aware serving (range requests/caching)
### Wave19-T070: Docs: multimodal ingest & debug guide

---

## Wave20 (T071–T080): Visualization & Explainability Workbenches

### Wave20-T071: KG snapshots UI (diff cards + export)
### Wave20-T072: KG diagnostics UI (run/list/compare)
### Wave20-T073: Retrieval ablation UI (run/leaderboard/diff)
### Wave20-T074: Evidence suite workbench: “why missed?” explanations
### Wave20-T075: Trace viewer: per-channel scores + rerank reasons
### Wave20-T076: Graph UI: filter by predicate/type/conf bucket
### Wave20-T077: Graph UI: “hover provenance” for relations
### Wave20-T078: Admin dashboard: ingestion throughput + error taxonomy
### Wave20-T079: Export/shareable HTML reports for quality runs
### Wave20-T080: Docs: explainability workflows

---

## Wave21 (T081–T090): Continuous Evaluation & CI Gates

### Wave21-T081: Answer-level regression gate (faithfulness + refusal correctness)
### Wave21-T082: Synthetic hardcase generation (PII-safe) for KG + retrieval
### Wave21-T083: Continuous ablation runner nightly (scheduled)
### Wave21-T084: Dataset slice taxonomy v3 (stable + actionability)
### Wave21-T085: Add “golden questions” per dataset + governance
### Wave21-T086: Eval artifacts bundling + retention policies
### Wave21-T087: Model/provider parity checks (OpenAI-compatible)
### Wave21-T088: Add “eval diff” scoring (baseline vs candidate)
### Wave21-T089: CI: fail on quality regression beyond threshold
### Wave21-T090: Docs: evaluation maturity model

---

## Wave22 (T091–T100): Enterprise Governance / Security / Compliance

### Wave22-T091: Audit log expansion for KG edits + ingestion ops
### Wave22-T092: RBAC roles (admin/editor/viewer) for datasets/connectors
### Wave22-T093: OIDC/SSO (optional) + session hardening
### Wave22-T094: Tenant quotas (storage/docs/embedding tokens/qps)
### Wave22-T095: Cost attribution (per request: retrieval/llm/embeddings)
### Wave22-T096: Data retention policies (docs/chunks/KG/evals) enforced by jobs
### Wave22-T097: Secrets hygiene + config validation (prod-safe defaults)
### Wave22-T098: Rate limiting + abuse prevention for public endpoints
### Wave22-T099: Compliance report bundle (PII-safe) + export
### Wave22-T100: Runbook: incident response + rollback playbook

---

## Wave23 (Post-100): Ops & Scale (Reserved)

Wave23 is intentionally “after the 100” to harden what proved valuable:
throughput scaling, queue partitioning, shard plans, cold storage, and SLO dashboards.

