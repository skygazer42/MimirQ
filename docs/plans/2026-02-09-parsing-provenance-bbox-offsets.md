# Parsing Provenance: Page Numbers, BBox, and Char Offsets Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Every returned evidence chunk must be locatable in the original document. Parsing must produce provenance that can be carried through governance and chunking:
- page number(s)
- bounding boxes (bbox) for text blocks when available
- start/end char offsets into the governed markdown
- heading/section path where possible

**Non-Goal:** Pixel-perfect PDF rendering. We only require stable provenance adequate for audit and "jump to source".

---

### Task 1: Define a normalized parse artifact schema

**Files:**
- Add: `app/parsing/artifacts/schema.py`
- Modify: `app/parsing/backends/*` (emit schema)
- Test: `tests/test_parse_artifact_schema_validation.py` (new)

**Step 1: Schema**

Define block-level artifacts:
- `DocumentArtifact { pages: [PageArtifact], blocks: [BlockArtifact] }`
- `PageArtifact { page_number: int, width: float?, height: float? }`
- `BlockArtifact { id: str, page_number: int?, bbox: [x0,y0,x1,y1]?, text: str, role: str?, order: int }`

**Step 2: Validation**

Use Pydantic validation and reject artifacts with invalid page/bbox ranges.

**Step 3: Tests**

Add a unit test that validates a sample artifact json and rejects malformed bbox.

**Step 4: Commit**

```bash
git add app/parsing/artifacts/schema.py tests/test_parse_artifact_schema_validation.py
git commit -m "feat(parsing): add normalized parse artifact schema for provenance"
```

---

### Task 2: Build governed markdown with stable offset mapping

**Files:**
- Add: `app/parsing/artifacts/markdown_builder.py`
- Modify: `app/parsing/pipeline.py` (use builder output)
- Test: `tests/test_markdown_offset_map_stable.py` (new)

**Step 1: Markdown builder**

Given ordered `BlockArtifact` list, build:
- `governed_markdown` string
- `offset_map` mapping each block id to `{ char_start, char_end }` in the markdown

Rules:
- Use only `\n` newlines
- Deterministic separators between blocks
- Preserve page boundaries via lightweight markers in metadata (not visible to users)

**Step 2: Persist mapping**

Persist mapping in doc metadata (or separate table) keyed by block id.

**Step 3: Tests**

Test that for identical blocks, offsets are identical across runs.

**Step 4: Commit**

```bash
git add app/parsing/artifacts/markdown_builder.py app/parsing/pipeline.py tests/test_markdown_offset_map_stable.py
git commit -m "feat(parsing): build markdown with stable block offset mapping"
```

---

### Task 3: Carry provenance into chunks and citations

**Files:**
- Modify: `app/ingest/chunking.py` (attach provenance)
- Modify: `app/rag/retriever.py` (return provenance in citations)
- Test: `tests/test_citations_include_provenance.py` (new)

**Step 1: Chunk provenance**

Each chunk should carry:
- `page_start/page_end` (from underlying blocks)
- `char_start/char_end` (from markdown offsets)
- `bbox_list` optional (list of bboxes or a per-page aggregate)
- `heading_path` if available

**Step 2: Retrieval output**

Citations returned by retrieval must include provenance fields and a stable `content_sha256`.

**Step 3: Tests**

Add a test that retrieval citations include these fields when artifacts exist.

**Step 4: Commit**

```bash
git add app/ingest/chunking.py app/rag/retriever.py tests/test_citations_include_provenance.py
git commit -m "feat(retrieval): include provenance in citations for evidence localization"
```

