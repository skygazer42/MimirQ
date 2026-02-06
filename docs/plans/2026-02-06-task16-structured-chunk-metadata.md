# Task 16: Structured Chunk Metadata (Heading/List/Table Context)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure chunks carry stable structural metadata (heading path, list nesting signals, table title/sheet) so retrieval can filter/inspect it and rerankers can use it.

**Architecture:** Centralize enrichment in `ChunkAssetStage` (post-chunking, pre-indexing) and `normalize_section_metadata()` so every chunker benefits. Keep metadata small and deterministic; avoid adding new DB columns by storing in chunk JSON metadata.

**Tech Stack:** Python, FastAPI ingestion pipeline, SQLAlchemy JSONB metadata, existing chunkers + `normalize_section_metadata`.

**Status:** DONE (2026-02-06)

## Scope (This Task)

- Ensure `header_path` is filled for chunkers that already emit structure via:
  - `header_1..header_6` (LangChain MarkdownHeaderTextSplitter)
  - `outline_path` / `outline_path_str`
  - `minutes_section_title` (meeting_minutes)
  - `sheet_name` (spreadsheet_sheet)
  - `table_title` (derived/truncated)
- Add lightweight structure signals:
  - `structure.list`: item_count + min/max nesting level (best-effort)
  - `structure.table`: title (best-effort) + sheet_name (if present)
- Include safe structural fields in LLM reranker candidate JSON (no extra text).

## Task 1: Extend `normalize_section_metadata` for minutes/sheet/table

**Files:**
- Modify: `app/rag/core/metadata.py`
- Test: `tests/test_normalize_section_metadata_extended.py`

**Step 1: Write failing test**

- `minutes_section_title` -> `header_path`
- `sheet_name` -> `header_path`
- `table_title` -> `header_path` (when nothing else exists)

**Step 2: Implement minimal mapping**

Keep current priority for explicit header_path / outline / header_1..6; add:
- `minutes_section_title`
- `sheet_name` (skip `_meta`)
- `table_title` (truncate)

**Step 3: Run**

Run: `python -m pytest -q tests/test_normalize_section_metadata_extended.py`

## Task 2: Infer list/table structure metadata in ChunkAssetStage

**Files:**
- Modify: `app/parsing/processors/processor.py`
- Modify: `app/rag/core/metadata.py`
- Test: `tests/test_chunk_structure_inference.py`

**Step 1: Write failing tests**

- List content -> structure.list fields exist with expected counts/levels
- Table chunk metadata (`table_header` or `sheet_name`) -> structure.table.title set (bounded)

**Step 2: Implement**

- Add `infer_chunk_structure(meta, content)` helper in `app/rag/core/metadata.py`
- Call it in `ChunkAssetStage` before hashing/indexing

**Step 3: Run**

Run: `python -m pytest -q tests/test_chunk_structure_inference.py`

## Task 3: Add structural fields into LLM reranker candidates

**Files:**
- Modify: `app/rag/reranker/llm_based.py`
- Test: `tests/test_llm_reranker_candidate_payload.py`

**Step 1: Write failing test**

- candidate payload includes `header_path` and `structure` (bounded)

**Step 2: Implement**

- Extract `_build_candidate_payload(...)` helper and use it in the reranker

**Step 3: Run**

Run: `python -m pytest -q tests/test_llm_reranker_candidate_payload.py`

## Task 4: Verify

Run:
- `python -m pytest -q`
- `pnpm -C web run typecheck`
