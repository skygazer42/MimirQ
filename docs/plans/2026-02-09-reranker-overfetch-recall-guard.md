# Reranker Excellence: Overfetch + Recall Guard + Diagnostics Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Improve precision without sacrificing recall:
- always overfetch before rerank
- enforce a recall guard (never drop known-evidence hits due to reranking)
- keep reranker behavior diagnosable and versioned

---

### Task 1: Rerank contract and configuration

**Files:**
- Add: `app/rag/rerank/config.py`
- Modify: `app/core/config.py`
- Test: `tests/test_rerank_config_contract.py` (new)

**Step 1: Config knobs**

Add:
- `RERANK_ENABLED`
- `RERANK_MODEL_ID`
- `RERANK_OVERFETCH_K` (must be >= requested `top_k`)
- `RERANK_RETURN_K`

**Step 2: Tests**

Assert config validation:
- overfetch >= return_k
- return_k >= top_k for evidence mode (or enforce separate evidence_k)

**Step 3: Commit**

```bash
git add app/rag/rerank/config.py app/core/config.py tests/test_rerank_config_contract.py
git commit -m "feat(rerank): add rerank config contract with overfetch requirement"
```

---

### Task 2: Implement rerank with overfetch and channel-preserving diagnostics

**Files:**
- Add: `app/rag/rerank/reranker.py`
- Modify: `app/rag/retriever.py`
- Test: `tests/test_rerank_overfetch_keeps_recall.py` (new)

**Step 1: Overfetch**

Retriever returns `candidate_k = max(top_k, RERANK_OVERFETCH_K)` candidates.
Reranker scores and returns top `RERANK_RETURN_K`.

**Step 2: Diagnostics**

For each citation, include:
- pre-rerank score (dense/bm25/lexical/kg)
- rerank score
- rank before/after

**Step 3: Tests**

Test that a known relevant chunk in the overfetch set is not dropped when recall guard is enabled (see next task).

**Step 4: Commit**

```bash
git add app/rag/rerank/reranker.py app/rag/retriever.py tests/test_rerank_overfetch_keeps_recall.py
git commit -m "feat(rerank): add overfetch reranking with diagnostics"
```

---

### Task 3: Recall guard for evidence mode

**Files:**
- Add: `app/rag/rerank/recall_guard.py`
- Modify: `app/api/v1/rag.py` (evidence mode uses guard)
- Test: `tests/test_rerank_recall_guard_evidence_mode.py` (new)

**Step 1: Guard policy**

In evidence mode:
- if a chunk is a "must keep" based on deterministic signals (e.g., lexical exact match, high bm25, or prior gold evidence), it cannot be dropped below `top_k`.
- guard should be transparent: return `guarded=true` and reasons.

**Step 2: Tests**

Test that:
- guarded candidates remain in final top_k
- guard does not increase result count beyond configured k (it can swap out weaker results)

**Step 3: Commit**

```bash
git add app/rag/rerank/recall_guard.py app/api/v1/rag.py tests/test_rerank_recall_guard_evidence_mode.py
git commit -m "feat(rerank): add recall guard for evidence mode"
```

