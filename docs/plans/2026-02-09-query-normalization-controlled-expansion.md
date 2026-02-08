# Query Excellence: Normalization + Controlled, Auditable Expansion Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make queries "retrieval-ready" deterministically and auditable:
- normalization (numbers, units, versions, paths, identifiers)
- controlled expansion (synonyms, abbreviations) without combinatorial explosion
- every rewrite/expansion is traceable and measurable

**Principle:** Expansion must be bounded, explainable, and reversible. Never hide rewritten queries.

---

### Task 1: Query normalization pipeline (deterministic)

**Files:**
- Add: `app/query/normalize.py`
- Modify: `app/rag/retriever.py` (apply normalization upstream of all channels)
- Test: `tests/test_query_normalization.py` (new)

**Step 1: Normalization rules**

Implement:
- whitespace canonicalization
- full-width/half-width normalization (ASCII fallback when possible)
- number formats: `1,000` -> `1000`
- version formats: `v1.2.3` -> `1.2.3`
- path normalization: `\\` -> `/` for display and matching
- optional unit normalization (limited set, explicit)

Return `NormalizedQuery` including:
- `normalized_text`
- `applied_rules: list[str]`

**Step 2: Tests**

Add tests for each rule with stable outputs.

**Step 3: Commit**

```bash
git add app/query/normalize.py app/rag/retriever.py tests/test_query_normalization.py
git commit -m "feat(query): add deterministic query normalization"
```

---

### Task 2: Controlled expansion (synonyms and abbreviations) with audit trail

**Files:**
- Add: `app/query/expand.py`
- Add: `app/query/dictionaries/base.yaml`
- Modify: `app/rag/retriever.py` (fan-out strategy)
- Test: `tests/test_query_expansion_bounded.py` (new)

**Step 1: Dictionary-backed expansion**

Create a yaml dictionary for:
- abbreviations (e.g., "SLO" -> "service level objective")
- domain synonyms (dataset-specific later)

**Step 2: Bounded fan-out**

Generate at most:
- `max_expansions_total` (e.g., 5)
- `max_expansions_per_rule` (e.g., 2)

Return expansions with provenance:
- `source_rule_id`
- `weight`
- `expanded_text`

**Step 3: Tests**

Assert:
- expansion count is capped
- provenance is present
- no duplicate expansions

**Step 4: Commit**

```bash
git add app/query/expand.py app/query/dictionaries/base.yaml app/rag/retriever.py tests/test_query_expansion_bounded.py
git commit -m "feat(query): add bounded, auditable query expansion"
```

---

### Task 3: Metrics and debugging output for expansions

**Files:**
- Modify: `app/api/v1/rag.py` (evidence endpoint includes query debug)
- Modify: `app/api/schemas/chat.py`
- Test: `tests/test_evidence_includes_query_debug.py` (new)

**Step 1: Add query_debug**

Include in evidence response:
- original query
- normalized query
- expansions list (with provenance)
- per-expansion contribution summary (e.g., which citations were found by which expansion)

**Step 2: Tests**

Add a test asserting query_debug exists and is well-formed.

**Step 3: Commit**

```bash
git add app/api/v1/rag.py app/api/schemas/chat.py tests/test_evidence_includes_query_debug.py
git commit -m "feat(query): expose query normalization/expansion debug in evidence api"
```

