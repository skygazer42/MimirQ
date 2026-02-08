# Chunk Semantics: Role Labels + Multi-Granularity + Neighbor Windows Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Improve evidence completeness and controllability without sacrificing recall:
- chunk role labels (definition/procedure/policy/example/table/code/faq/etc)
- parent-child multi-granularity (retrieve small, return merged parent)
- neighbor windows that respect structure boundaries (not blind index +/-N)

**Pre-req:** Structure-aware chunker exists (see `docs/plans/2026-02-09-structure-aware-chunking-kg-extraction.md`).

---

### Task 1: Define and persist chunk role labels

**Files:**
- Add: `app/chunking/roles.py`
- Modify: `app/ingest/chunking.py`
- Test: `tests/test_chunk_role_labels.py` (new)

**Step 1: Role taxonomy**

Define role enum (start minimal, extend later):
- `definition`, `procedure`, `policy`, `example`, `table`, `code`, `faq`, `reference`, `unknown`

**Step 2: Deterministic role classifier**

Heuristics (no LLM by default):
- markdown cues: code fences -> `code`, tables -> `table`
- heading keywords: "Definitions" -> `definition`, "Procedure/Steps" -> `procedure`, "Policy" -> `policy`, "FAQ" -> `faq`
- list patterns: numbered steps -> `procedure`

Persist role in chunk metadata for filtering and reranking.

**Step 3: Tests**

Provide a markdown fixture and assert expected roles per chunk.

**Step 4: Commit**

```bash
git add app/chunking/roles.py app/ingest/chunking.py tests/test_chunk_role_labels.py
git commit -m "feat(chunking): add deterministic chunk role labels"
```

---

### Task 2: Parent-child chunk graph (section parent)

**Files:**
- Modify: `app/db/models/document_chunk.py` (or metadata schema)
- Modify: `app/ingest/chunking.py`
- Test: `tests/test_chunk_parent_child_graph.py` (new)

**Step 1: Parent definition**

Define parent chunk types:
- `section_parent` representing a heading section (bounded size; may be synthesized)

Each leaf chunk stores:
- `parent_chunk_id`
- `sibling_rank` within parent

**Step 2: Tests**

Assert that all leaf chunks under the same heading share a parent and stable order.

**Step 3: Commit**

```bash
git add app/db/models/document_chunk.py app/ingest/chunking.py tests/test_chunk_parent_child_graph.py
git commit -m "feat(chunking): add parent-child graph for multi-granularity evidence"
```

---

### Task 3: Retrieval-time merging: retrieve leaf, return merged parent window

**Files:**
- Modify: `app/rag/retriever.py`
- Add: `app/rag/postprocess/merge_parent.py`
- Test: `tests/test_retrieval_parent_merge.py` (new)

**Step 1: Merge policy**

Given top leaf chunks, return citations as:
- leaf citation(s) (for exact match)
- plus a merged parent citation (for readability) if within size cap

Ensure dedup:
- do not return the same parent multiple times

**Step 2: Tests**

Test that retrieval returns merged parent when enabled and keeps recall unchanged.

**Step 3: Commit**

```bash
git add app/rag/retriever.py app/rag/postprocess/merge_parent.py tests/test_retrieval_parent_merge.py
git commit -m "feat(retrieval): add parent merge postprocess for evidence readability"
```

---

### Task 4: Neighbor windows respecting structure boundaries

**Files:**
- Add: `app/rag/postprocess/neighbor_window.py`
- Modify: `app/rag/retriever.py`
- Test: `tests/test_neighbor_window_respects_boundaries.py` (new)

**Step 1: Window policy**

Window expansion should:
- expand within the same parent section by `sibling_rank`
- never cross heading boundaries
- cap total tokens/characters

**Step 2: Tests**

Assert that neighbors added are from the same parent and ordered correctly.

**Step 3: Commit**

```bash
git add app/rag/postprocess/neighbor_window.py app/rag/retriever.py tests/test_neighbor_window_respects_boundaries.py
git commit -m "feat(retrieval): add structure-aware neighbor windows"
```

