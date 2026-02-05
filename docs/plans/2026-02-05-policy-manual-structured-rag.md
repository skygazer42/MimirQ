# Policy/Manual Structured RAG Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make enterprise policy/manual PDFs & DOCX produce clause-addressable chunks + first-class retrieval diagnostics so that (a) questions covered by the library are recalled precisely, and (b) anything not supported is refused (no hallucinations).

**Architecture:** Parse -> Governance (canonical Markdown) -> Policy structure extraction (chapters/sections/articles/clauses) -> Structured parent/child chunking with stable IDs -> Hybrid retrieval (BM25 + vector + rerank) with a clause-number fast lane -> Retrieval preview/diagnosis UI -> Regression gates (recall + faithfulness).

**Tech Stack:** FastAPI, SQLAlchemy (Postgres), LangChain, Milvus, Next.js 14, Tailwind, shadcn/ui, pytest.

---

## Success Criteria (Definition of “Top-Level”)

- **Clause addressability:** users can retrieve “Article/Section/Clause” by number reliably (e.g. “第 12 条”, “3.2.1”, “Article 7”).
- **Stable chunk IDs:** re-processing the same version of a document yields stable `policy_clause_id`/`parent_id` (no random UUIDs).
- **Retrieval diagnostics:** operators can see *why* a clause was (not) retrieved: vector/BM25/rerank scores, trimming/dedup/drop reasons, neighbor expansion and parent-child merge effects.
- **Refuse-over-hallucinate:** when evidence is weak or missing, system abstains with actionable guidance (what to upload / how to narrow question).
- **Measurable gates:** promotion of a dataset/index requires passing recall@K + faithfulness checks on a curated regression set (policy/manual domain).

## Non-Goals (This Plan)

- Database connectors (MySQL/SQLServer) and NL2SQL (covered in a separate plan).
- Full multi-version document lifecycle UX (we’ll store version metadata, but not build a full “effective date” UI yet).

## Key Data Contracts

We will enrich `DocumentChunk.doc_metadata` (JSONB) with stable policy structure fields; no DB schema changes required.

Required metadata for policy/manual chunks:
- `policy_clause_id`: stable ID (deterministic) for a clause/article node
- `policy_clause_number`: raw number marker (e.g. "第十二条", "3.2.1", "Article 7")
- `policy_path`: list of headings from root to node (chapter/section/article)
- `policy_path_str`: joined string for embedding prefixing / UI display
- `chunk_role`: `parent` | `child` (to work with existing parent/child auto merge)
- `parent_id`: stable ID for the parent node (article/section)

Optional (but recommended):
- `policy_kind`: `chapter|section|article|clause`
- `policy_lang`: `zh|en|mixed` (best-effort)

---

## Baseline Verification (run once before starting implementation)

Run:
```bash
pytest -q
cd web && pnpm -s lint && pnpm -s typecheck
```
Expected: PASS.

---

### Task 1: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-05-policy-manual-structured-rag.md`

**Steps:**
1. Add the plan file (this document).
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-05-policy-manual-structured-rag.md
git commit -m "docs(plans): add policy/manual structured RAG plan"
```

---

### Task 2: Implement policy clause reference parsing (number/heading extraction)

**Why:** We need a single, tested source of truth for identifying clause markers (CN/EN) and producing a canonical “clause ref” used by chunking + query fast lane.

**Files:**
- Create: `app/rag/policy/clause_refs.py`
- Test: `tests/test_policy_clause_refs.py`

**Step 1: Write the failing test**

`tests/test_policy_clause_refs.py`
```python
from app.rag.policy.clause_refs import extract_clause_refs, normalize_clause_ref


def test_extract_clause_refs_cn_article_and_clause():
    q = "请按第十二条（3）说明例外条件"
    refs = extract_clause_refs(q)
    assert "第十二条" in refs
    assert "（3）" in refs


def test_extract_clause_refs_en_article_section():
    q = "What does Article 7 say? See Section 3.2.1 for exceptions."
    refs = extract_clause_refs(q)
    assert "Article 7" in refs
    assert "Section 3.2.1" in refs


def test_normalize_clause_ref_is_stable_and_safe():
    assert normalize_clause_ref(" 第十二条 ") == "第十二条"
    assert normalize_clause_ref("SECTION 3.2.1") == "Section 3.2.1"
```

**Step 2: Run test to verify it fails**

Run:
```bash
pytest -q tests/test_policy_clause_refs.py
```
Expected: FAIL (module/function missing).

**Step 3: Write minimal implementation**

`app/rag/policy/clause_refs.py`
```python
from __future__ import annotations

import re

_CN_ARTICLE = re.compile(r"(第[0-9一二三四五六七八九十百千]+条)")
_CN_CLAUSE = re.compile(r"([（(][0-9一二三四五六七八九十]+[)）])")
_EN_ARTICLE = re.compile(r"\\barticle\\s+\\d{1,4}\\b", flags=re.IGNORECASE)
_EN_SECTION = re.compile(r"\\bsection\\s+\\d{1,4}(?:\\.\\d{1,4}){0,4}\\b", flags=re.IGNORECASE)


def normalize_clause_ref(ref: str) -> str:
    s = (ref or "").strip()
    if not s:
        return ""
    # Canonicalize english prefix casing only (keep the numeric part).
    low = s.lower()
    if low.startswith("article "):
        return "Article " + s.split(None, 1)[1].strip()
    if low.startswith("section "):
        return "Section " + s.split(None, 1)[1].strip()
    return s


def extract_clause_refs(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(x: str) -> None:
        v = normalize_clause_ref(x)
        if not v:
            return
        key = v.casefold() if v.isascii() else v
        if key in seen:
            return
        seen.add(key)
        out.append(v)

    for m in _CN_ARTICLE.finditer(raw):
        _add(m.group(1))
    for m in _CN_CLAUSE.finditer(raw):
        _add(m.group(1))
    for m in _EN_ARTICLE.finditer(raw):
        _add(m.group(0))
    for m in _EN_SECTION.finditer(raw):
        _add(m.group(0))
    return out
```

**Step 4: Run test to verify it passes**

Run:
```bash
pytest -q tests/test_policy_clause_refs.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/rag/policy/clause_refs.py tests/test_policy_clause_refs.py
git commit -m "feat(policy): add clause reference extraction utilities"
```

---

### Task 3: Add a structured policy/manual chunker with stable parent/child IDs

**Why:** Current `laws_structured` is a great start, but it does not create stable IDs nor a parent/child hierarchy optimized for policy manuals. We will add a new strategy that:
- splits by chapter/section/article markers
- emits one **parent** chunk per article (bounded)
- emits multiple **child** chunks inside the article (precise retrieval)
- uses deterministic IDs derived from `(document_id, normalized clause ref, content_hash)`

**Files:**
- Create: `app/rag/chunking/strategies/policy_manual_structured.py`
- Modify: `app/rag/chunking/strategies/__init__.py`
- Modify: `app/rag/chunking/factory.py`
- Test: `tests/test_policy_manual_structured_chunker.py`

**Step 1: Write the failing test**

`tests/test_policy_manual_structured_chunker.py`
```python
from langchain_core.documents import Document

from app.rag.chunking.strategies.policy_manual_structured import (
    PolicyManualStructuredChunker,
    looks_like_policy_manual,
)


def test_looks_like_policy_manual_detects_articles():
    text = \"\"\"第一章 总则
第一条【目的】 本制度用于……
第二条 适用范围……
（一）子款……
\"\"\"
    assert looks_like_policy_manual(text) is True


def test_policy_chunker_emits_parent_and_child_with_stable_ids():
    doc = Document(page_content=\"\"\"第一章 总则
第一条【目的】 AAAAA
（一）BBBBB
第二条 CCCCC
\"\"\", metadata={"document_id": "doc-1", "source": "policy.pdf"})
    chunker = PolicyManualStructuredChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.split_documents([doc])

    assert any((c.metadata or {}).get("chunk_role") == "parent" for c in chunks)
    assert any((c.metadata or {}).get("chunk_role") == "child" for c in chunks)

    # Stable ids exist
    for c in chunks:
        meta = c.metadata or {}
        assert meta.get("policy_clause_id")
        assert meta.get("policy_path_str") or meta.get("policy_path")
```

**Step 2: Run test to verify it fails**

Run:
```bash
pytest -q tests/test_policy_manual_structured_chunker.py
```
Expected: FAIL (missing chunker).

**Step 3: Write minimal implementation**

Implementation guidelines (keep it simple first, iterate later):
- Reuse `laws_structured` heading regexes where possible.
- Use SHA256 for stable IDs:
  - `policy_clause_id = sha256(f\"{doc_id}:{clause_number}:{content_hash}\")[:24]`
  - `parent_id = sha256(f\"{doc_id}:{article_number}\")[:24]`
- Always set `start_char/end_char` using offsets from the original text (like `laws_structured`).

**Step 4: Run test to verify it passes**

Run:
```bash
pytest -q tests/test_policy_manual_structured_chunker.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/rag/chunking/strategies/policy_manual_structured.py app/rag/chunking/strategies/__init__.py app/rag/chunking/factory.py tests/test_policy_manual_structured_chunker.py
git commit -m "feat(chunking): add policy/manual structured parent-child chunker"
```

---

### Task 4: Update auto chunking to prefer policy/manual structured strategy

**Why:** Users should not have to know which chunker to pick; `chunk_strategy=auto` should reliably route policy/manual documents to the new chunker.

**Files:**
- Modify: `app/rag/chunking/strategies/auto.py`
- Test: `tests/test_chunker_auto_policy_manual.py`

**Step 1: Write the failing test**

`tests/test_chunker_auto_policy_manual.py`
```python
from app.rag.chunking.strategies.auto import auto_pick_strategy


def test_auto_strategy_prefers_policy_manual():
    text = \"\"\"第一章 总则
第一条【目的】 ...
第二条 ...
\"\"\"
    picked = auto_pick_strategy(text, filename="制度.pdf")
    assert picked in {"policy_manual_structured", "laws_structured"}
    # Prefer the new one when available.
    assert picked == "policy_manual_structured"
```

**Step 2: Run test to verify it fails**
```bash
pytest -q tests/test_chunker_auto_policy_manual.py
```
Expected: FAIL (auto_pick_strategy not updated).

**Step 3: Implement minimal change**
- Import `looks_like_policy_manual` and route before generic markdown chunkers.
- Keep backward compatibility: if detection fails, fall back to existing heuristics.

**Step 4: Run test to verify it passes**
```bash
pytest -q tests/test_chunker_auto_policy_manual.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/rag/chunking/strategies/auto.py tests/test_chunker_auto_policy_manual.py
git commit -m "feat(chunking): route policy/manual docs in auto strategy"
```

---

### Task 5: Add a built-in governance profile tuned for policy/manual PDFs

**Why:** Policy PDFs often include headers/footers, page numbers, and repeated boilerplate that hurts recall. We will ship a conservative built-in profile that improves canonical Markdown quality without deleting real content.

**Files:**
- Modify: `app/services/governance_profiles.py`
- Modify (docs): `docs/data-governance-profiles.md`
- Test: `tests/test_builtin_governance_profiles.py`

**Step 1: Write the failing test**

`tests/test_builtin_governance_profiles.py` (extend)
```python
from app.services.governance_profiles import get_builtin_governance_profiles


def test_policy_manual_profile_exists():
    keys = {p.key for p in get_builtin_governance_profiles()}
    assert "builtin:policy_manual_pdf" in keys
```

**Step 2: Run test to verify it fails**
```bash
pytest -q tests/test_builtin_governance_profiles.py::test_policy_manual_profile_exists
```
Expected: FAIL.

**Step 3: Implement the profile**
- Name: `builtin:policy_manual_pdf`
- Patch:
  - `governance_enabled=true`
  - `governance_remove_common_lines=true`
  - `governance_unwrap_lines=true`
  - `governance_normalize_tables=true`
  - `governance_drop_duplicate_paragraphs=true` (tuned thresholds)
  - Keep `parse_fallback_enabled` off by default (handled by scanned/OCR profile)

**Step 4: Run test to verify it passes**
```bash
pytest -q tests/test_builtin_governance_profiles.py::test_policy_manual_profile_exists
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/services/governance_profiles.py docs/data-governance-profiles.md tests/test_builtin_governance_profiles.py
git commit -m "feat(governance): add builtin policy/manual PDF profile"
```

---

### Task 6: Clause-number “fast lane” retrieval query expansion (no LLM)

**Why:** For policy/manual questions, users often reference clause numbers directly. We will add deterministic query expansion that boosts exact clause-number hits without relying on the LLM.

**Files:**
- Create: `app/rag/policy/query_expansion.py`
- Modify: `app/rag/engine.py`
- Test: `tests/test_policy_query_expansion.py`

**Step 1: Write the failing test**

`tests/test_policy_query_expansion.py`
```python
from app.rag.policy.query_expansion import build_clause_fastlane_queries


def test_clause_fastlane_queries_include_refs():
    q = "按第十二条说明例外"
    extra = build_clause_fastlane_queries(q)
    assert any("第十二条" in x for x in extra)
```

**Step 2: Run test to verify it fails**
```bash
pytest -q tests/test_policy_query_expansion.py
```
Expected: FAIL.

**Step 3: Implement minimal expansion + wire into engine**
- Use `extract_clause_refs()` to build additional retrieval queries of kind `"clause"`.
- Insert before HyDE queries so the fusion sees them early.
- Do not change default behavior for non-policy questions.

**Step 4: Run test to verify it passes**
```bash
pytest -q tests/test_policy_query_expansion.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/rag/policy/query_expansion.py app/rag/engine.py tests/test_policy_query_expansion.py
git commit -m "feat(retrieval): add clause-number fast lane query expansion"
```

---

### Task 7: Retrieval diagnosis UX: make “retrieve preview” operator-grade

**Why:** Backend already exposes `/api/v1/rag/retrieve-preview`; the current UI shows results but not in a way that supports systematic tuning. We will upgrade the UI to show:
- fusion components (vector/BM25/rerank/retrieval_score)
- `retrieval_role` (main/mq/subq/hyde/neighbor/tag)
- `chunk_role` (parent/child)
- `policy_clause_number`/`policy_path_str` when present
- key trimming counters from `metrics.retriever_debug` (if present)

**Files:**
- Modify: `web/app/knowledge/page.tsx` (retrieval test panel)
- Create: `web/components/rag/retrieve-preview-panel.tsx`
- Verify: `web/lib/api-client.ts` already has `ragApi.retrievePreview`

**Steps:**
1. Extract the existing “检索测试” block into `RetrievePreviewPanel`.
2. Add a compact table view + expandable detail drawer per hit.
3. Add copy buttons: “copy chunk_id”, “copy doc_pipeline_key”, “copy matched terms”.
4. Verify:
   - `cd web && pnpm -s lint`
   - `cd web && pnpm -s typecheck`
5. Commit.

**Commit:**
```bash
git add web/app/knowledge/page.tsx web/components/rag/retrieve-preview-panel.tsx
git commit -m "feat(web): upgrade retrieve-preview diagnostics UI"
```

---

### Task 8: Add a small policy/manual regression set scaffold (no LLM required)

**Why:** We need a place to store “golden queries -> expected clause refs” so recall improvements are measurable and don’t regress.

**Files:**
- Create: `tests/fixtures/policy_manual_cases.jsonl`
- Create: `tests/test_policy_manual_regression_scaffold.py`

**Step 1: Write the failing test**

`tests/test_policy_manual_regression_scaffold.py`
```python
import json
from pathlib import Path

from app.rag.policy.clause_refs import extract_clause_refs


def test_policy_regression_cases_file_is_valid_jsonl():
    path = Path("tests/fixtures/policy_manual_cases.jsonl")
    assert path.exists()
    for line in path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert "question" in obj
        assert "expected_refs" in obj
        refs = extract_clause_refs(obj["question"])
        assert isinstance(refs, list)
```

**Step 2: Run test to verify it fails**
```bash
pytest -q tests/test_policy_manual_regression_scaffold.py
```
Expected: FAIL (fixture missing).

**Step 3: Add the fixture file**

`tests/fixtures/policy_manual_cases.jsonl`
```jsonl
{"question":"按第十二条说明例外","expected_refs":["第十二条"]}
{"question":"What does Article 7 require?","expected_refs":["Article 7"]}
```

**Step 4: Run test to verify it passes**
```bash
pytest -q tests/test_policy_manual_regression_scaffold.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add tests/fixtures/policy_manual_cases.jsonl tests/test_policy_manual_regression_scaffold.py
git commit -m "test(policy): add regression scaffold for policy/manual queries"
```

---

## Rollout Notes

- Default this behavior per-dataset:
  - set dataset `default_chunk_strategy=auto` (auto routes to policy/manual chunker)
  - optionally recommend `builtin:policy_manual_pdf` governance profile in dataset pipeline defaults
- Keep feature flags conservative where needed (e.g. neighbor window, parent/child auto merge).

