# LangChain / LangGraph Architecture Notes

This document explains how MimirQ's chat/RAG pipeline is structured today and how it relates to the earlier "agent-style" approach.

## Current State (Recommended)

MimirQ keeps the RAG pipeline explicit and debuggable:

- **LangChain (chain-style) pipeline**
  - Primary implementation: `app/rag/engine.py`
  - Focus: predictable retrieval + prompt + answer generation, with citations

- **LangGraph (graph-style) pipeline (optional)**
  - Used to expose richer step events for UI/debugging and to support checkpointing
  - Related modules: `app/rag/pipelines/langgraph.py`, `app/rag/checkpointer/*`
  - API integration: `app/api/v1/chat.py` (streaming events include optional `graph` events)

In addition, MimirQ exposes a **workflow mode** concept for advanced orchestration features (see `WORKFLOW_MODE` in `app/core/config.py`).

## Why Not a Classic “Tool-Calling Agent” Everywhere?

For a knowledge base QA product, the dominant failure modes are:
- retrieving the wrong context
- overlong/irrelevant context
- hallucinations and weak grounding
- inconsistent output formats

An explicit RAG pipeline (retrieval → rerank/fusion → context construction → answer) makes it easier to:
- control cost/latency
- enforce citation and “no fabricate” rules
- add governance (redaction, quality filters)
- debug with stable intermediate artifacts

## Config Switches

Configuration is driven by environment variables / `.env` and centralized in `app/core/config.py`.

Common related settings:
- `USE_LANGGRAPH_PIPELINE` (enable graph pipeline for chat)
- `WORKFLOW_MODE` (select orchestration mode)
- `LLM_*`, `EMBEDDING_*` (model/provider)
- Retrieval knobs: `RETRIEVAL_*`, `BM25_*`, `VECTOR_*`

For a runnable system-wide status check, see:
- `GET /api/v1/health` and `GET /api/v1/health/ready`

