# Strict Dataset Scope (Disable Open-Scope Chat) Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` + `superpowers:verification-before-completion` while implementing.

**Goal:** Require `dataset_id` (or explicit `document_ids`) for chat retrieval so tenant-level "open scope" retrieval is disabled by default.

**Architecture:** Enforce scope at the chat API boundary (fast fail), and push `dataset_id` into retrieval metadata filters so vector/BM25 filtering is pushed down where possible (Milvus expr + BM25 metadata filter), reducing recall loss due to post-filter trimming.

**Tech Stack:** FastAPI, Pydantic settings, pytest, Milvus metadata expr builder, hybrid retriever (vector + BM25).

---

### Task 1: Add failing tests for strict scope requirement (chat + stream)

**Files:**
- Create: `tests/test_chat_requires_dataset_scope.py`

**Step 1: Write the failing tests**

- `POST /api/v1/chat` with `{message}` only should return **400** when open-scope is disabled.
- `POST /api/v1/chat/stream` with `{message}` only should return **400** when open-scope is disabled.

**Step 2: Run tests to verify they fail**

Run: `make test tests/test_chat_requires_dataset_scope.py -q`
Expected: FAIL (current behavior allows open-scope).

---

### Task 2: Enforce dataset/doc scope in chat endpoints (configurable)

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/api/v1/chat.py`

**Step 1: Minimal implementation**

- Add `CHAT_ALLOW_OPEN_SCOPE: bool = False` to settings.
- In both non-streaming and streaming chat endpoints, reject requests that have:
  - no `document_ids`
  - no `request.dataset_id`
  - no `conversation.dataset_id` (when continuing a conversation)
  - and open-scope is not allowed by settings

**Step 2: Run the new tests**

Run: `make test tests/test_chat_requires_dataset_scope.py -q`
Expected: PASS

**Step 3: Run full test suite**

Run: `make test`
Expected: PASS

**Step 4: Commit**

Commit message: `feat(chat): require dataset scope (disable open-scope by default)`

---

### Task 3: Add failing test for Milvus metadata expr pushdown (dataset_id)

**Files:**
- Modify: `tests/test_milvus_metadata_expr.py`

**Step 1: Write failing test**

- `_build_milvus_metadata_expr({"dataset_id": {"$eq": "d1"}})` should produce `dataset_id == "d1"`.

**Step 2: Run test**

Run: `make test tests/test_milvus_metadata_expr.py -q`
Expected: FAIL (dataset_id not in allowlist yet).

---

### Task 4: Enable dataset_id pushdown + auto-inject into retrieval metadata_filter

**Files:**
- Modify: `app/storage/vector/milvus.py`
- Modify: `app/rag/retriever.py`

**Step 1: Minimal implementation**

- Add `dataset_id` to Milvus filter allowlists:
  - `_MILVUS_STRING_FIELDS`
  - `_DOC_VECTOR_METADATA_FIELDS`
- In `HybridRetriever._hybrid_search`, if `self.dataset_id` is set, ensure `metadata_filter` includes `dataset_id` as a top-level AND clause (preserves user filters and enables Milvus pushdown).
- Add `dataset_id` to the retriever's `vector_allowed` filter mapping so the filter is passed to vector search.

**Step 2: Run tests**

Run: `make test tests/test_milvus_metadata_expr.py -q`
Expected: PASS

**Step 3: Run full test suite**

Run: `make test`
Expected: PASS

**Step 4: Commit**

Commit message: `feat(retrieval): push down dataset_id filter to vector/BM25`

