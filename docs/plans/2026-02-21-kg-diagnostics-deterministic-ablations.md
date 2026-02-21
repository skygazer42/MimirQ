# KG Diagnostics Deterministic Hardcases + Ablations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `hardcase_mode=deterministic` and attribution ablations for `/evaluations/kg/search/diagnostics` to improve KG extraction/search debugging for RAG.

**Architecture:** Add small per-call overrides to `SearchConfig` (thread-safe) so diagnostics can flip relation expansion and skill nodes without mutating global settings. Implement a deterministic hardcase generator driven by KG-derived aliases/skills/tags. Run bounded ablation searches on baseline failures and write compact results into `attribution.signals`.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, pytest.

---

### Task 1: Add Per-Call Override Fields To `SearchConfig`

**Files:**
- Modify: `app/rag/kg/search/config.py`
- Test: `tests/test_kg_search_config_overrides.py` (new)

**Step 1: Write failing test**

Create `tests/test_kg_search_config_overrides.py` asserting:
- `SearchConfig(...).relation_expansion_enabled is None`
- `SearchConfig(...).include_skill_entities is True`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_search_config_overrides.py -q`  
Expected: FAIL (fields not present)

**Step 3: Implement minimal fields**

Add to `SearchConfig`:
- `relation_expansion_enabled: Optional[bool] = None`
- `include_skill_entities: bool = True`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_search_config_overrides.py -q`  
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/kg/search/config.py tests/test_kg_search_config_overrides.py
git commit -m "feat(kg): add per-call search override toggles"
```

---

### Task 2: Make Recall Respect `relation_expansion_enabled`

**Files:**
- Modify: `app/rag/kg/search/recall.py`
- Test: `tests/test_kg_recall_relation_expansion.py` (extend)

**Step 1: Write failing test**

Extend `tests/test_kg_recall_relation_expansion.py` with a new test:
- Enable global settings for relation expansion
- Set `SearchConfig(relation_expansion_enabled=False)`
- Assert relation repo is not called and result only contains baseline entity events.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_recall_relation_expansion.py -q`  
Expected: FAIL (relation repo still called)

**Step 3: Implement override in recall**

In `recall.py` Step1.5 gating, use:
- If config override is `None`, keep existing behavior
- If override is `False`, skip relation expansion
- If override is `True`, attempt relation expansion even if settings flag is off (best-effort; handle exceptions)

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_recall_relation_expansion.py -q`  
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/kg/search/recall.py tests/test_kg_recall_relation_expansion.py
git commit -m "feat(kg): allow per-call relation expansion override in recall"
```

---

### Task 3: Make Recall Respect `include_skill_entities`

**Files:**
- Modify: `app/rag/kg/search/recall.py`
- Test: `tests/test_kg_recall_skill_filtering.py` (new)

**Step 1: Write failing test**

Create a fake `EntityRepository.search_similar` returning:
- one `Skill` entity (high similarity)
- one normal entity (slightly lower similarity)

Ensure:
- with `include_skill_entities=True`, skill is present in `key_final`
- with `include_skill_entities=False`, skill is filtered out

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_recall_skill_filtering.py -q`  
Expected: FAIL (skill not filtered)

**Step 3: Implement filtering**

Filter out entities with `type in {"Skill","SkillTag","SkillCategory"}` when `include_skill_entities=False`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_recall_skill_filtering.py -q`  
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/kg/search/recall.py tests/test_kg_recall_skill_filtering.py
git commit -m "feat(kg): support skill node filtering in recall"
```

---

### Task 4: Make Expand Respect Overrides (Relation + Skill Filtering)

**Files:**
- Modify: `app/rag/kg/search/expand.py`
- Test: `tests/test_kg_expand_skill_filtering.py` (new)

**Step 1: Write failing test**

Build an `ExpandSearcher.expand(...)` test with fakes so that:
- an expanded event has a normal entity and a `Skill` entity
- with `include_skill_entities=False`, the skill is not added into `key_final`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_expand_skill_filtering.py -q`  
Expected: FAIL

**Step 3: Implement filtering in expand**

- Skip `Skill`-like entities when collecting `new_entities` if `include_skill_entities=False`
- Filter them out from `key_final` output too
- Respect `relation_expansion_enabled` override for relation-driven neighbor expansion

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_expand_skill_filtering.py -q`  
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/kg/search/expand.py tests/test_kg_expand_skill_filtering.py
git commit -m "feat(kg): support search overrides in expand stage"
```

---

### Task 5: Implement Deterministic Hardcase Generator (Pure, Unit-Testable)

**Files:**
- Create: `app/rag/evaluation/kg_hardcase_deterministic.py`
- Test: `tests/test_kg_hardcase_deterministic.py`

**Step 1: Write failing test**

Test cases:
- 2+2 split with `max_items=4`
- Dedupe behavior
- Spillover when alias candidates are missing
- Stable ordering

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kg_hardcase_deterministic.py -q`  
Expected: FAIL (module missing)

**Step 3: Implement generator**

Expose:
- `generate_hardcases_deterministic(question, alias_pairs, skills, tags, max_items)` -> `list[Hardcase]`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kg_hardcase_deterministic.py -q`  
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/evaluation/kg_hardcase_deterministic.py tests/test_kg_hardcase_deterministic.py
git commit -m "feat(eval): add deterministic KG hardcase generator"
```

---

### Task 6: Wire `hardcase_mode=deterministic` Into Diagnostics Runner

**Files:**
- Modify: `app/rag/evaluation/kg_search_diagnostics.py`

**Step 1: Add KG-derived candidate collection**

Implement helper(s) to collect, for a case:
- alias pairs from `KgRelation` (`alias_of` / `same_as`) around ground-truth event entities
- skills linked to ground-truth events (`KgEntity.type == "Skill"`)
- tags/categories via `belong_to` edges

**Step 2: Generate + evaluate deterministic hardcases**

When `hardcase_mode=="deterministic"`:
- generate hardcases per failed case (bounded)
- run KG search for each hardcase query
- attach to response items + compute hardcase metrics summary

**Step 3: Commit**

```bash
git add app/rag/evaluation/kg_search_diagnostics.py
git commit -m "feat(eval): add deterministic hardcases for KG diagnostics"
```

---

### Task 7: Add Attribution Ablations (Relation / Skill / Rerank)

**Files:**
- Modify: `app/rag/evaluation/kg_search_diagnostics.py`

**Step 1: Add ablation runs**

For baseline failures with ground truth present, run up to 3 searches:
- relation expansion toggled (force on/off)
- skill nodes disabled (`include_skill_entities=False`)
- rerank strategy toggled (`PAGERANK <-> RRF`)

**Step 2: Write compact results into signals**

Add:
`item.attribution.signals["ablations"] = {...}`

Include only compact fields (Hit@K, MRR, Recall, first_hit_rank, returned_events, selected_entities, relation debug).

**Step 3: Adjust primary_cause**

If an ablation flips to Hit@K=true:
- rerank toggle fixes => `rerank_cutoff`
- relation toggle fixes => `relation`
- skills_off fixes => `skill`

Else fall back to the existing heuristic `_pick_primary_cause(...)`.

**Step 4: Commit**

```bash
git add app/rag/evaluation/kg_search_diagnostics.py
git commit -m "feat(eval): add KG diagnostics ablation attribution"
```

---

### Task 8: Quality Gates

**Step 1: Run unit tests**

Run: `pytest -q`

Expected: PASS (integration tests may be skipped)

**Step 2: Run lint (if configured)**

Run: `ruff check .`

Expected: PASS

**Step 3: Commit fixes if needed**

---

### Task 9: Close Issue + Push

**Step 1: Update bd issue**

Run:
```bash
bd close MimirQ-4i1
```

**Step 2: Sync + Push (MANDATORY)**

Run:
```bash
git pull --rebase
bd sync
git push
git status
```

Expected: `git status` shows “up to date with origin”.

