# Chunking Excellence: Structure-Aware Chunking + KG Extraction Linkage Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Maximize recall and citation quality by producing "retrieval-grade" chunks:
- structure-aware boundaries (headings, sections, tables, code blocks)
- stable provenance (doc_id, page, heading path, offsets)
- optional knowledge-graph (KG) facts linked back to exact evidence spans

**Non-Goal:** Full graph reasoning. We only require KG extraction to improve retrieval/coverage and evidence navigation.

---

### Task 1: Define a chunk contract (metadata + provenance)

**Files:**
- Modify: `app/db/models/document_chunk.py` (or chunk schema)
- Modify: `app/api/schemas/document.py` (or chunk response schema)
- Test: `tests/test_chunk_provenance_contract.py` (new)

**Step 1: Write failing contract test**

Assert each chunk has:
- `doc_id`, `chunk_index`
- `source: { page_start, page_end, char_start, char_end }` (nullable when unknown)
- `path: { headings: [..], section_id }` (nullable)
- `content_sha256` (for stability debugging)

Run:
```bash
python -m pytest -q tests/test_chunk_provenance_contract.py
```
Expected: FAIL.

**Step 2: Implement minimal fields**

Prefer storing provenance in chunk metadata JSON to avoid migrations unless necessary.

**Step 3: Commit**

```bash
git add app/db/models/document_chunk.py app/api/schemas/document.py tests/test_chunk_provenance_contract.py
git commit -m "feat(chunking): add chunk provenance metadata contract"
```

---

### Task 2: Implement structure-aware chunker (Markdown-first)

**Files:**
- Add: `app/chunking/markdown_chunker.py`
- Modify: `app/ingest/chunking.py` (or pipeline hook)
- Test: `tests/test_markdown_chunker_boundaries.py` (new)

**Step 1: Write failing boundary tests**

Create tests that ensure:
- Do not split inside fenced code blocks.
- Keep tables as atomic units (or row-group units) with stable serialization.
- Prefer splitting on heading boundaries.
- Enforce max token size with "soft" split rules first, then hard split with overlap.

Run:
```bash
python -m pytest -q tests/test_markdown_chunker_boundaries.py
```
Expected: FAIL.

**Step 2: Implement chunker**

Approach:
- Parse Markdown into a lightweight block structure (headings, paragraphs, code blocks, tables).
- Build chunks by accumulating blocks under the current heading path.
- When exceeding `max_tokens`, back off to paragraph boundaries; only then hard split with overlap.

Persist heading path + block offsets into chunk provenance metadata.

**Step 3: Verify**

Expected: PASS.

**Step 4: Commit**

```bash
git add app/chunking/markdown_chunker.py app/ingest/chunking.py tests/test_markdown_chunker_boundaries.py
git commit -m "feat(chunking): add structure-aware markdown chunker"
```

---

### Task 3: Add chunk-level extractive "anchors" for better recall

**Files:**
- Add: `app/chunking/anchors.py`
- Modify: `app/ingest/chunking.py`
- Test: `tests/test_chunk_anchor_generation.py` (new)

**Step 1: Implement anchor generation**

Generate deterministic anchor fields stored in chunk metadata:
- `keyphrases` (TF-IDF-ish or RAKE-like deterministic)
- `entities` (regex + small dictionary + optional model)
- `canonical_title` (top heading path)

These anchors can be used for lexical fallback and for UI display.

**Step 2: Add tests**

Verify anchors are stable across re-runs for identical content.

**Step 3: Commit**

```bash
git add app/chunking/anchors.py app/ingest/chunking.py tests/test_chunk_anchor_generation.py
git commit -m "feat(chunking): add deterministic chunk anchors"
```

---

### Task 4: KG extraction (triples) with evidence linkage

**Files:**
- Add: `app/kg/extract.py`
- Add: `app/kg/models.py`
- Modify: `app/ingest/pipeline.py` (hook after chunking; before indexing)
- Test: `tests/test_kg_triples_link_to_chunks.py` (new)

**Step 1: Define KG data model**

Define:
- `Entity { id, name, type }`
- `Triple { subject_id, predicate, object_id, chunk_id, span, confidence, extractor_version }`

Store triples in Postgres (preferred) for joinability, and optionally embed a "fact text" into the vector index as an additional collection.

**Step 2: Implement extractor**

Start with a deterministic extractor:
- Patterns for "X is Y", "X uses Y", "X version is Y", etc.
- Pull from headings + bold/definition lists.

Optional next step: add an LLM extractor behind a feature flag, but persist evidence spans and require strict schema validation.

**Step 3: Tests**

Verify that extracted triples always reference:
- an existing `chunk_id`
- a valid `span` inside the chunk content

**Step 4: Commit**

```bash
git add app/kg/extract.py app/kg/models.py app/ingest/pipeline.py tests/test_kg_triples_link_to_chunks.py
git commit -m "feat(kg): extract triples linked to chunk evidence"
```

---

### Task 5: Retrieval integration (KG as an additional recall channel)

**Files:**
- Modify: `app/rag/retriever.py`
- Add: `app/rag/kg_retriever.py`
- Test: `tests/test_retriever_kg_channel_fusion.py` (new)

**Step 1: Implement KG retriever**

Given a query:
- extract candidate entities/keyphrases
- retrieve matching triples and their linked chunks
- return chunk citations with a KG score channel

**Step 2: Fuse with existing channels**

Add KG as an optional channel in the existing merge/fusion layer (keep deterministic weights and thresholds).

**Step 3: Verify**

Run:
```bash
python -m pytest -q tests/test_retriever_kg_channel_fusion.py
```

**Step 4: Commit**

```bash
git add app/rag/retriever.py app/rag/kg_retriever.py tests/test_retriever_kg_channel_fusion.py
git commit -m "feat(retrieval): add kg recall channel and fuse results"
```

