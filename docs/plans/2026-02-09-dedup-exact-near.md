# Pre-Index Dedup: Exact + Near Dedup (SimHash/MinHash) Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Reduce index pollution and retrieval noise by enforcing dedup before chunking/indexing:
- exact dedup (byte-identical or canonical-text-identical)
- near dedup (high overlap, minor edits) using SimHash or MinHash/LSH

**Principle:** Dedup must be explainable and reversible (never delete raw sources).

---

### Task 1: Canonical text fingerprint for exact dedup

**Files:**
- Add: `app/dedup/fingerprints.py`
- Modify: `app/parsing/pipeline.py` (compute fingerprints)
- Test: `tests/test_exact_dedup_fingerprints.py` (new)

**Step 1: Implement fingerprints**

Compute and persist:
- `source_sha256` (raw bytes)
- `canonical_text_sha256` (normalized markdown with whitespace normalization)

**Step 2: Tests**

Test:
- identical inputs produce identical fingerprints
- whitespace-only changes do not change canonical fingerprint

**Step 3: Commit**

```bash
git add app/dedup/fingerprints.py app/parsing/pipeline.py tests/test_exact_dedup_fingerprints.py
git commit -m "feat(dedup): add canonical fingerprints for exact dedup"
```

---

### Task 2: Near dedup using SimHash (fast baseline)

**Files:**
- Add: `app/dedup/simhash.py`
- Add: `app/dedup/service.py`
- Modify: `app/ingest/indexer.py` (gate indexing)
- Test: `tests/test_near_dedup_simhash.py` (new)

**Step 1: Implement simhash**

Compute simhash over token shingles of governed markdown.
Persist:
- `simhash64` for each document
- optional `simhash_blocks` for per-section dedup later

**Step 2: Candidate search**

Use one of:
- pg `bigint` + banding table
- or `pg_trgm` on token signatures (fallback)

Define near-dup threshold in Hamming distance (e.g., <= 3).

**Step 3: Indexing policy**

If near-dup detected:
- mark document as `duplicate_of_doc_id`
- skip chunk/vector indexing by default (configurable)
- still allow "link-only" mode so UI can show duplicates grouped

**Step 4: Tests**

Test that minor edits are detected as near-dup and indexing is skipped.

**Step 5: Commit**

```bash
git add app/dedup/simhash.py app/dedup/service.py app/ingest/indexer.py tests/test_near_dedup_simhash.py
git commit -m "feat(dedup): add simhash near-dedup and indexing gate"
```

---

### Task 3: Dataset-level dedup reporting and overrides

**Files:**
- Modify: `app/services/dataset_profile_service.py` (dedup counts)
- Add: `app/api/v1/dedup.py` (list groups, override)
- Test: `tests/test_dedup_reporting.py` (new)

**Step 1: Reporting**

Expose:
- exact dup count
- near dup count
- largest duplicate clusters

**Step 2: Overrides**

Allow operators to:
- force index a duplicate (override)
- mark false positive (increase threshold or pin a whitelist)

**Step 3: Commit**

```bash
git add app/services/dataset_profile_service.py app/api/v1/dedup.py tests/test_dedup_reporting.py
git commit -m "feat(dedup): add dedup reporting and override endpoints"
```

