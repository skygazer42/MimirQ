# Evidence Retrieval Platform Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `POST /api/v1/rag/retrieve` (retrieval-only Evidence API) a stable, enterprise-grade contract with better decoupling, observability, and recall safety without requiring answer orchestration.

**Architecture:** Extract the retrieval-orchestration logic used by LangGraph into a dedicated module, then reuse it from both LangGraph and the Evidence API. Add a schema version to the Evidence API response, optional iterative fallback retrieval, and Prometheus metrics with low-cardinality labels.

**Tech Stack:** FastAPI, Pydantic, LangChain `Document`, Prometheus client, existing HybridRetriever + RRF fusion.

---

## Scope (This Sweep)

This sweep focuses on the **retrieval-only** platform contract. Chat answer generation/workflow orchestration is explicitly *out of scope* except where shared retrieval code is reused.

Key deliverables:
- Evidence API response contract stabilized (`schema` field, bounded `query_debug`).
- API layer no longer imports LangGraph private retrieval node.
- Retrieval orchestration extracted to `app/rag/retrieval/orchestrator.py` and reused by LangGraph.
- Optional iterative fallback retrieval for evidence discovery (bounded extra pass).
- Prometheus metrics for evidence retrieval (SLO-friendly).
- Tests updated/added to lock behaviors.
- OpenAPI types regenerated.

Non-goals (tracked as follow-ups):
- Training/serving LTR models end-to-end.
- Shipping SPLADE/ColBERT models end-to-end (we add scaffolding only).
- Full connector ACL inheritance across all sources.

## High-Level Tasks

1. Create `app/rag/retrieval/orchestrator.py` by extracting `_retrieve_node` logic from `app/rag/pipelines/langgraph.py`.
2. Refactor `app/rag/pipelines/langgraph.py` so `_retrieve_node` delegates to the orchestrator.
3. Refactor `app/api/v1/rag.py` to call the orchestrator (no direct `_retrieve_node` import).
4. Add `schema="mimirq.evidence.v1"` to `EvidenceRetrieveResponse`.
5. Add optional iterative fallback pass for `POST /api/v1/rag/retrieve` (config-gated).
6. Add Prometheus metrics (low cardinality) for evidence retrieval outcomes/latency.
7. Update docs: `docs/guides/evidence_api.md`.
8. Update/add tests for contract + query_debug.
9. Regenerate OpenAPI types: `make openapi-check`.
10. Run quality gates: `make lint-py`, `make test`, `make verify`.

Note: user requested **one final commit** for the whole sweep.

