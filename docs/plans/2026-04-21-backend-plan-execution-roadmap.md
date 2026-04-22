# Backend Plan Execution Roadmap

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver the backend backlog from `/plans` one source plan at a time on `feat/backend`, skipping items that are already implemented and updating checkbox status after every verified batch.

**Architecture:** This roadmap is the control document for backend execution. Each source plan is treated as an isolated lane: audit current code, identify the smallest missing slice, implement it with TDD, verify it, then mark the checklist before moving to the next source plan.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, pytest, existing `app/rag/*`, `app/parsing/*`, `app/services/*`, and `app/api/*` modules.

---

## Global Rules

- [ ] Always work in `/data/temp34/MimirQ/.worktrees/feat-backend` on branch `feat/backend`
- [ ] Only one source plan may be active at a time
- [ ] Before coding any source plan, audit what is already implemented and skip completed items
- [ ] Start from the smallest missing P0 slice, not the largest architectural item
- [ ] Use TDD for every new behavior: write failing test, confirm red, implement minimum code, confirm green
- [ ] After each verified batch, update this file from `[ ]` to `[x]` for completed items
- [ ] Do not start the next source plan until the current plan slice is implemented and verified

## Execution Order

### 1. `rag-poc-attribution-framework-2026-q2.md`

- [x] Audit current `app/rag/evaluation/` and confirm missing `poc_runner` modules
- [x] Implement `app/rag/evaluation/poc_runner/attribution_classifier.py`
- [x] Implement `app/rag/evaluation/poc_runner/out_of_scope_verifier.py`
- [x] Implement `app/rag/evaluation/poc_runner/query_pattern_miner.py`
- [x] Decide whether `app/rag/industry_rules/` needs a bootstrap slice now or should wait for a later batch
- [x] Add targeted tests for the implemented `poc_runner` modules
- [x] Run targeted pytest verification for the completed slice
- [x] Complete Batch B for reports, heatmaps, HTML, and PNG export from the per-MD plan

### 2. `rag-eval-dataset-deep-dive-2026-q2.md`

- [x] Audit existing evaluation dataset builders and reuse current scaffolding where possible
- [x] Implement Stage 1 minimal evaluation dataset scaffold under `app/rag/evaluation/`
- [x] Add runner and fixture support for a 50-200 sample MVP batch
- [x] Add targeted tests for the new dataset scaffold
- [x] Run targeted pytest verification for the completed slice
- [ ] Complete Batch B for synthetic expansion and agentic execution from the per-MD plan

### 3. `rag-pre-poc-scanner-2026-q2.md`

- [ ] Audit whether current ingestion and analytics endpoints already cover any scanner signals
- [ ] Implement the smallest backend scanner slice that produces actionable pre-POC findings
- [ ] Add tests for scanner summary output and false-positive-safe behavior
- [ ] Run targeted pytest verification for the completed slice

### 4. `rag-context-expansion-rerank-2026-q2.md`

- [ ] Audit current neighbor expansion, rerank, and retrieval stitching behavior
- [ ] Implement the smallest missing P0 retrieval expansion improvement
- [ ] Add tests for retrieval expansion and rerank interaction
- [ ] Run targeted pytest verification for the completed slice

### 5. `rag-poc-to-mvp-delivery-2026-q2.md`

- [ ] Audit whether metadata enrichment, sibling expansion, and feedback infrastructure already exist
- [ ] Implement the smallest missing P0 lane with the fewest external dependencies
- [ ] Add tests for the selected MVP delivery slice
- [ ] Run targeted pytest verification for the completed slice

### 6. `rag-agentic-reasoning-deep-dive-2026-q2.md`

- [ ] Audit current `app/rag/workflows/`, `app/rag/tools/`, and routing support
- [ ] Implement the smallest missing P0 agentic slice with minimal external dependency risk
- [ ] Add tests for the selected workflow or tool slice
- [ ] Run targeted pytest verification for the completed slice

### 7. `rag-kg-deep-research-2026-q2.md`

- [ ] Audit current `app/rag/kg/search/` capabilities and skip anything already present
- [ ] Implement one missing P0 KG search slice
- [ ] Add tests for the selected KG search slice
- [ ] Run targeted pytest verification for the completed slice

### 8. `rag-parsing-chunking-deep-dive-2026-q2.md`

- [ ] Audit parser benchmark, chunking benchmark, and semantic chunk floor support
- [ ] Implement one benchmark or chunking P0 slice only
- [ ] Add tests for the selected parsing or chunking slice
- [ ] Run targeted pytest verification for the completed slice

### 9. `rag-ibm-champion-blueprint-2026-q2.md`

- [ ] Audit prompt management, structured output, and rerank weighting support
- [ ] Implement one missing P0 blueprint slice
- [ ] Add tests for the selected blueprint slice
- [ ] Run targeted pytest verification for the completed slice

### 10. `rag-safety-compliance-deep-dive-2026-q2.md`

- [ ] Audit current `app/rag/safety/`, output guard, and audit coverage
- [ ] Implement one missing P0 safety slice
- [ ] Add tests for the selected safety slice
- [ ] Run targeted pytest verification for the completed slice

## Reference-Only Plans

- [ ] `rag-capability-gap-2026-q2.md` is used as a gap index, not an execution lane
- [ ] `rag-deep-research-2026-q2.md` is used as a strategic overview, not an execution lane

## Batch Completion Checklist

- [x] The active source plan was re-audited before coding
- [x] Only missing items were implemented
- [x] New behavior was covered by failing-then-passing tests
- [x] Targeted verification passed
- [x] This roadmap was updated to reflect the new status
