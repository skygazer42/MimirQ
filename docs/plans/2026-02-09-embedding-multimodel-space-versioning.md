# Embedding Excellence: Multi-Model Routing + Space Versioning Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Avoid "one model fits all" embeddings and make embedding changes safe:
- route content to different embedding models by content type/language
- optionally inject lightweight structure context (section path) into embedding text
- make all embedding spaces versioned and rollbackable (no silent mixing)

---

### Task 1: Define embedding space id and persistence (no mixing)

**Files:**
- Add: `app/embeddings/space.py`
- Modify: `app/ingest/embedding.py` (or vector indexing entrypoint)
- Modify: `app/db/models/document_chunk.py` (store `embedding_space_id` in metadata)
- Test: `tests/test_embedding_space_id_no_mixing.py` (new)

**Step 1: Space id**

Define `embedding_space_id` as a stable string:
- `model_id`
- `model_version` (or provider version)
- `dim`
- `text_canonicalization_version`
- `context_injection_version`
- `routing_version`

Compute a hash and persist it on every embedded chunk.

**Step 2: Retrieval filter**

Ensure vector retrieval always filters by `embedding_space_id` (or collection partition keyed by it).
Fail-closed if the requested space is unknown.

**Step 3: Tests**

Test that:
- writing embeddings stores `embedding_space_id`
- retrieval rejects or separates chunks from different spaces

**Step 4: Commit**

```bash
git add app/embeddings/space.py app/ingest/embedding.py app/db/models/document_chunk.py tests/test_embedding_space_id_no_mixing.py
git commit -m "feat(embeddings): add embedding space id and prevent mixing"
```

---

### Task 2: Multi-model routing by content type and language

**Files:**
- Add: `app/embeddings/router.py`
- Modify: `app/ingest/embedding.py`
- Test: `tests/test_embedding_router.py` (new)

**Step 1: Routing policy**

Given a chunk with metadata:
- role: `code/table/...`
- language: `zh/en/mixed/unknown`
Return an `EmbeddingRoute` selecting:
- model_id
- preprocessing (e.g., code-specific normalization)

Start with rules only; add ML/LLM later behind flags.

**Step 2: Tests**

Test routing decisions for:
- Chinese prose
- English prose
- code chunks
- table chunks

**Step 3: Commit**

```bash
git add app/embeddings/router.py app/ingest/embedding.py tests/test_embedding_router.py
git commit -m "feat(embeddings): add multi-model routing for chunks"
```

---

### Task 3: Optional structure context injection with rollback

**Files:**
- Add: `app/embeddings/context_injection.py`
- Modify: `app/core/config.py` (flags)
- Modify: `app/ingest/embedding.py`
- Test: `tests/test_context_injection_toggle_and_version.py` (new)

**Step 1: Context injection**

If enabled, embed text as:
- `path: <heading path>\nrole: <role>\n\n<chunk content>`

If disabled, embed raw chunk content only.

**Step 2: Versioning**

Bump `context_injection_version` when format changes and ensure it contributes to `embedding_space_id`.

**Step 3: Tests**

Test that toggling injection changes `embedding_space_id` and does not write into the old space.

**Step 4: Commit**

```bash
git add app/embeddings/context_injection.py app/core/config.py app/ingest/embedding.py tests/test_context_injection_toggle_and_version.py
git commit -m "feat(embeddings): add context injection with versioned space id"
```

