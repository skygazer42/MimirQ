# Milvus native BM25 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 知识库 BM25 下沉 Milvus，退出进程内索引和 rank-bm25，同时保留现有权限、融合、可选后端和有界聊天记忆。

**Architecture:** 已有 pymilvus 驱动独立的原生全文集合，CorpusIndex 统一读写与回填；原有通道融合保持。聊天记忆直接查询 PostgreSQL，已有向量集合保持。

**Tech Stack:** Python 3.11、pymilvus 2.6.11、Milvus 2.6.11、SQLAlchemy、pytest。

**Spec:** [.agents/notes/implemented/architecture/2026-11-05-milvus-native-bm25.md](../../../.agents/notes/implemented/architecture/2026-11-05-milvus-native-bm25.md)

## Global Constraints

- 用户已确认上一条设计并要求实施，按原生方式连续执行，不重复要求批准计划。
- 当前隔离工作树基线 `201202385c7e9094e6d1966bc7ae7b190f83334f` 包含已交付本地模型退出和主项目至 `7e545fa31` 的并行修改。
- 不删除现有向量、文档或环境包，不启动服务，不执行线上回填。
- 仅复用 pymilvus；Chroma/FAISS 保留向量能力，不能退回 Python BM25。
- 租户与删除范围必须严格，故障不能作为健康空结果；历史 DTO 和最终 ACL 不放宽。

## Review Focus

- BM25-only 文档、不同向量维度和非 Milvus 部署：不依赖隐式 Embedding，不创建本地 BM25。
- 旧语义集合没有 BM25 function：不能静默创建空全文集合并宣称已迁移。
- 复杂元数据、同租户不可读文档、恶意过滤文本：查询与删除不可扩大作用域。
- 读取后的更新、删除和回填：真实通道必须看见服务端变化，不能读取另一份本地缓存。
- 聊天记忆中文、通配符和会话隔离：数据库排序不能泄漏或回传无匹配历史。

### Task 1: Native Milvus full-text owner

**Files:** Create `app/storage/bm25/milvus.py`; modify `app/core/config.py`; test `tests/test_milvus_native_bm25.py`.

**Interfaces:** `MilvusBM25Store.search(query, *, tenant_id, dataset_ids=(), document_ids=(), metadata_filter=None, top_k=10)` returns scored chunk dicts. `upsert(documents, *, tenant_id)` and `delete(*, tenant_id, metadata_filter)` are the only write surfaces. Constructor accepts a client for protocol tests; normal access lazily imports pymilvus.

- [x] Write failing schema, raw-text search, scoped CRUD, metadata trimming, missing/incompatible collection and error propagation tests.
- [x] Run focused tests and inspect intended failures.
- [x] Implement native collection/function/analyzer/index, tenant-prefixed primary keys and strict scope/filter handling; no model invocation.
- [x] Verify with pinned SDK schema and focused tests; commit the owner with its decision record.

### Task 2: Corpus, indexing and retrieval cutover

**Files:** Rewrite `app/rag/retrieval/corpus_index.py` and `app/rag/retrieval/hybrid/bm25_index.py`; modify actual callers in `app/rag/retriever.py`, `app/services/indexer.py`, document mutation/retention/QA and retrieval channel configuration, startup/config settings. Test `tests/test_milvus_bm25_cutover.py` and related existing contracts.

**Interfaces:** Keep actual public CorpusIndex and operational rebuild interfaces; route all BM25 writes/reads/deletes to Task 1. Optional deterministic corpus snapshots and cache tokens retain their owners. Rebuild is an explicit, bounded backfill, not request-time cache warming.

- [x] Write failing tests proving actual corpus/channel/writer use native storage and non-Milvus availability is explicit.
- [x] Implement shared owner cutover, remove local builders/caches and startup build knobs, preserve final ACL and observable failures.
- [x] Exercise updates/deletes, metadata filters, bounded published-only snapshots/backfills and existing fusion/diagnostics.
- [x] Commit the integrated cutover after focused tests pass.

### Task 3: Memory, dependency removal and migration delivery

**Files:** Modify `app/services/chat_memory_runtime.py`, `requirements.txt`, dependency/docs/CI contracts, `scripts/rebuild_retrieval_indexes.py` or a dedicated native backfill entry, `.env.example` and installation guides. Test `tests/test_chat_memory_keyword_search.py` and native backfill CLI contracts.

- [x] Write failing database memory tests for tenant/conversation isolation, caps, Chinese, wildcard literals and no-match; write backfill dry-run/no-Embedding tests.
- [x] Implement PostgreSQL keyword ranking and remove all production BM25Retriever imports and rank-bm25 declarations.
- [x] Provide explicit backfill with dry-run/apply and migration limitations; synchronize decision note and generated contracts when needed.
- [ ] Run selected backend/static/frontend contract checks, perform one independent whole-change review and one focused fix pass.
- [ ] Commit only task paths, transfer the task patch to E:/MimirQ while preserving concurrent edits, and verify the integrated tree.
