# KG-Centric Retrieval Parity Sweep (20 Tasks) Implementation Plan

> **Note:** This plan is executed in one sweep with **one final git commit** (per user request), even though the house style usually prefers frequent commits.

**Date:** 2026-02-24

**Goal:** Close key gaps vs top-tier retrieval-first RAG systems by hardening Evidence API regression gating and adding optional high-recall / high-precision ranking components, with **KG signals as first-class features** (query expansion + chunk injection + role attribution).

**Architecture:** Keep production defaults unchanged. Add new capabilities behind flags and ensure every new behavior has deterministic unit/regression tests that do not require external model downloads.

**Tech Stack:** FastAPI, Pydantic, pytest, HybridRetriever, KG search, xgboost (already in deps), sentence-transformers/torch (optional, lazy), Postgres/Milvus (not required for tests).

---

## 20 Tasks (In Order)

1. **Baseline + gaps snapshot (doc):** Document the delta vs “top RAG retrieval platforms” specifically for retrieval-only Evidence API and KG-assisted retrieval.
2. **Config surface (code):** Add settings flags for:
   - Evidence retrieval regression gate (thresholds + K).
   - SPLADE sparse retrieval enable/provider selection.
   - ColBERT late-interaction reranker enable/provider selection.
   - LTR reranker enable/model path.
3. **Evidence API regression gate runner (code):** Add a runner that executes retrieval-only (`run_retrieval` / Evidence API contract) for regression cases and computes Hit@K/MRR/Recall (plus NDCG where useful).
4. **Metrics unit tests (tests):** Add unit tests for retrieval metrics computation (chunk-id / provenance matching).
5. **Offline regression gate (tests):** Add a deterministic offline test that exercises the Evidence API retrieval orchestrator and fails when retrieval SLO regresses.
6. **Docs (docs):** Document how to run the evidence retrieval gate locally and in CI.

7. **Sparse retrieval interface (code):** Define a sparse embedding interface and an index abstraction that supports:
   - upsert documents
   - query scoring
   - per-tenant/dataset scoping
8. **Deterministic sparse provider (code):** Provide a deterministic “hash/lexicon” sparse backend for tests (no downloads).
9. **HybridRetriever integration (code):** Add an optional “sparse” channel (SPLADE-style) behind a flag and integrate into fusion (`linear` + `rrf`).
10. **Sparse-win test (tests):** Add a regression test where sparse retrieval recovers an acronym/synonym case that BM25 misses (vector disabled).
11. **Docs (docs):** Add a short guide for enabling sparse retrieval and tradeoffs.

12. **ColBERT reranker (code):** Add a local late-interaction reranker implementation behind a flag/provider.
13. **Factory wiring (code):** Expose ColBERT as a reranker provider in `app/rag/reranker/factory.py`.
14. **ColBERT unit test (tests):** Deterministic test for ranking correctness with a stub embedder.
15. **Docs (docs):** Document ColBERT reranker use, latency tradeoffs, and recommended placement (rerank-only).

16. **LTR feature schema (code):** Define a stable feature vector derived from retrieval + KG signals (vector/bm25/lexical/sparse scores, retrieval_role, kg-injected, etc.).
17. **LTR training script (scripts):** Add an offline training script that produces an xgboost model artifact from labeled pairs derived from regression cases/evidence pointers.
18. **LTR inference reranker (code):** Add an online reranker provider that loads the model artifact and predicts scores for candidates.
19. **LTR unit tests (tests):** Deterministic tests for:
   - feature extraction
   - model loading/inference (tiny trained model or fixture)
20. **Hardening + close-out (ops):**
   - Update docs/CHANGELOG if needed
   - Run quality gates (`make enterprise-checks` when feasible)
   - Close bd issues `MimirQ-xp7`, `MimirQ-23q`, `MimirQ-43t`, `MimirQ-pkp`
   - Single final commit + push

