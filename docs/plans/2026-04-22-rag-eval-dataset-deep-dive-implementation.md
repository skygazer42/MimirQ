# RAG Evaluation Dataset Deep Dive Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the first production-grade evaluation dataset and runner framework for the full RAG system described in `plans/rag-eval-dataset-deep-dive-2026-q2.md`, starting with Stage 1 real-traffic seed evaluation and a minimal runner, then expanding later to synthetic generation, larger datasets, and continuous evaluation.

**Architecture:** Treat evaluation as a first-class system capability. Use file-based datasets plus file-based result artifacts with explicit schema/version metadata. Stage 1 focuses on a structured real-traffic seed set, deterministic validation, a unified runner/result schema, and parallel comparison of the three initial execution routes (`retrieval`, `kg`, `hybrid`) while reserving `agentic` in schemas and runner contracts for Batch B.

**Tech Stack:** Python 3.11+, existing `app/rag/evaluation/*`, existing `ragas` integration, pytest, JSONL/JSON file artifacts, file-based manifests/validators, backend services under `app/services/`.

---

## Confirmed Product Decisions

- This evaluation system is a permanent capability for the full RAG platform, not a temporary benchmark tool.
- It must explicitly serve the system's major routes:
  - normal retrieval
  - KG route
  - hybrid/fused route
  - agentic route
- Keep the staged roadmap. Distinguish:
  - **stage** = capability maturity
  - **batch** = implementation sequence
- Stage 1 must prioritize real traffic / real queries.
- Stage 1 must include a small manually labeled seed set.
- Stage 1 must include unanswerable / no-answer / out-of-scope samples.
- Stage 1 must retain query-type slicing.
- Stage 1 query types are narrowed to:
  - `factual`
  - `multi_hop`
  - `structured`
  - `unanswerable`
- `structured` remains a first-class type.
- Stage 1 includes a small amount of adversarial samples.
- Route evaluation is retained.
- Hybrid/fusion evaluation is retained.
- Agentic evaluation is retained as a direction, but **Batch A only reserves the schema/runner slot** and does not execute it yet.
- Stage 1 uses the same sample set for route comparisons.
- Answer evaluation keeps a complete stack in Batch A:
  - deterministic metrics
  - direct reuse of existing `RAGAS`
- Retain cost and latency dimensions.
- Retain explicit refusal / unanswerable handling metrics.
- Public benchmarks may inform dataset design, but the first dataset is primarily based on internal real samples.
- Keep a structured annotation schema with:
  - minimal annotation/review state
  - source type labels
  - evidence/gold chunk references
  - optional `expected_route`
- Stage 1 labeling flow is:
  - single primary annotator
  - focused review on high-risk samples
- Batch A for this MD is **Stage 1 + minimal runner only**.
- Batch B adds Stage 2 synthetic expansion.
- Keep a unified runner framework and unified result schema.
- Keep file-based datasets and file-based result artifacts.
- Keep explicit schema versions for datasets and outputs.
- Keep a dataset validator before runner execution.
- Result artifacts must include:
  - detail results
  - summary results
  - run metadata
- Preserve route config snapshots in run metadata/results.

## Explicitly Not In Batch A

- Full Stage 2 synthetic generation pipeline
- Large-scale synthetic critique/filtering pipeline
- Dynamic shadow eval and continual generation
- Dashboard-first platform work
- Full multi-user labeling platform
- Full agentic execution runner

## Execution Structure

- **Batch A:** Stage 1 seed dataset + minimal unified runner for `retrieval`, `kg`, `hybrid`, with `agentic` reserved.
- **Batch B:** Stage 2 synthetic pipeline, route expansion, and agentic execution integration.
- **Later:** Stage 3 domain expansion, Stage 4 dynamic/shadow/continuous evaluation.

## Shared Rules For Every Task

- [ ] Follow TDD: write the test first, confirm it fails, then implement the minimum code.
- [ ] Keep dataset schemas and result schemas versioned and explicit.
- [ ] Prefer file artifacts over database-first evaluation infrastructure in Batch A.
- [ ] Distinguish clearly between sample metadata, runner results, and run metadata.
- [ ] Update this file from `[ ]` to `[x]` as each task is verified complete.
- [ ] Do not start Batch B until Batch A is verified.

## Batch A: Stage 1 Seed Dataset + Minimal Runner

### Task A1: Stage 1 Dataset Schema And Validator

**Files:**
- Create: `app/rag/evaluation/datasets/schema.py`
- Create: `app/rag/evaluation/datasets/validator.py`
- Test: `tests/test_eval_dataset_schema.py`
- Test: `tests/test_eval_dataset_validator.py`

**Intent:** Define the structured sample schema for Stage 1 and validate file-based datasets before any runner executes.

**Batch A requirements:**
- Sample schema must support:
  - `sample_id`
  - `query`
  - `query_type`
  - `source_type`
  - `gold_answer`
  - `gold_chunk_ids` and/or evidence references
  - `is_unanswerable`
  - optional `expected_route`
  - `annotation_status`
  - `review_status`
  - optional notes / tags
- Include schema version fields.
- Validator must check:
  - required fields
  - enum values
  - evidence field structure
  - manifest consistency basics

- [ ] Step 1: Write failing tests for sample schema validation and manifest consistency validation.
- [ ] Step 2: Run `pytest -q tests/test_eval_dataset_schema.py tests/test_eval_dataset_validator.py` and confirm red.
- [ ] Step 3: Implement schema definitions and the minimal dataset validator.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_dataset_schema.py tests/test_eval_dataset_validator.py` until green.
- [ ] Step 5: Commit the task.

### Task A2: Stage 1 File Layout And Dataset Manifest

**Files:**
- Create: `app/rag/evaluation/datasets/stage1/README.md`
- Create: `app/rag/evaluation/datasets/stage1/schema.json`
- Create: `app/rag/evaluation/datasets/stage1/manifest.json`
- Create: `app/rag/evaluation/datasets/stage1/seed.jsonl`
- Test: `tests/test_eval_stage1_manifest.py`

**Intent:** Establish the file-based dataset structure for Stage 1.

**Batch A requirements:**
- Keep a clear directory layout.
- Keep `manifest.json` separate from `schema.json`.
- Manifest must at least track:
  - `dataset_name`
  - `schema_version`
  - `dataset_version`
  - `sample_count`
  - `source_type_counts`
  - `query_type_counts`
  - `generated_at`
- Seed dataset can be a bootstrap fixture set in-repo for tests and runner wiring.

- [ ] Step 1: Write failing tests for manifest shape and count consistency.
- [ ] Step 2: Run `pytest -q tests/test_eval_stage1_manifest.py` and confirm red.
- [ ] Step 3: Create the Stage 1 dataset layout, manifest, schema, and seed bootstrap file.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_stage1_manifest.py` until green.
- [ ] Step 5: Commit the task.

### Task A3: Unified Result Schema And Artifact Layout

**Files:**
- Create: `app/rag/evaluation/results/schema.py`
- Create: `app/rag/evaluation/results/artifacts.py`
- Test: `tests/test_eval_result_schema.py`
- Test: `tests/test_eval_result_artifacts.py`

**Intent:** Define the shared result schema and file artifact layout for the minimal runner.

**Batch A requirements:**
- Unified result schema must support:
  - `sample_id`
  - `route_id`
  - `query_type`
  - `source_type`
  - `expected_route`
  - `actual_route`
  - answer payload
  - evidence/citation payload
  - refusal flags
  - latency/cost fields
  - route config snapshot
  - evaluator outputs
  - route-specific extension fields
- Reserve agentic fields in schema, even though Agentic is not executed in Batch A.
- Artifact layout must include at least:
  - `results.jsonl`
  - `summary.json`
  - `run_meta.json`

- [ ] Step 1: Write failing tests for unified result schema and artifact-path generation.
- [ ] Step 2: Run `pytest -q tests/test_eval_result_schema.py tests/test_eval_result_artifacts.py` and confirm red.
- [ ] Step 3: Implement the result schema and artifact layout helpers.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_result_schema.py tests/test_eval_result_artifacts.py` until green.
- [ ] Step 5: Commit the task.

### Task A4: Deterministic Answer Evaluators

**Files:**
- Create: `app/rag/evaluation/metrics/answer_det.py`
- Test: `tests/test_eval_answer_det_metrics.py`

**Intent:** Provide deterministic answer-level metrics as the stable baseline layer.

**Batch A requirements:**
- Include:
  - `answer_em`
  - `answer_f1`
  - unanswerable/refusal correctness
  - obvious hallucination / unsupported-answer heuristic
- Outputs must fit the unified evaluator result structure.

- [ ] Step 1: Write failing tests for deterministic answer metrics.
- [ ] Step 2: Run `pytest -q tests/test_eval_answer_det_metrics.py` and confirm red.
- [ ] Step 3: Implement the deterministic answer evaluator layer.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_answer_det_metrics.py` until green.
- [ ] Step 5: Commit the task.

### Task A5: RAGAS Evaluator Adapter

**Files:**
- Create: `app/rag/evaluation/metrics/ragas_adapter.py`
- Test: `tests/test_eval_ragas_adapter.py`

**Intent:** Reuse the existing `RAGAS` integration through a pluggable evaluator adapter rather than embedding it directly in the runner.

**Batch A requirements:**
- Must wrap and reuse existing `app/rag/evaluation/ragas.py`.
- Must map results into the unified evaluator schema.
- Must coexist with deterministic answer evaluators in the same result payload.

- [ ] Step 1: Write failing tests for the RAGAS adapter contract.
- [ ] Step 2: Run `pytest -q tests/test_eval_ragas_adapter.py` and confirm red.
- [ ] Step 3: Implement the adapter over existing `RAGAS`.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_ragas_adapter.py` until green.
- [ ] Step 5: Commit the task.

### Task A6: Retrieval/Evidence Metrics

**Files:**
- Create: `app/rag/evaluation/metrics/retrieval.py`
- Test: `tests/test_eval_retrieval_metrics.py`

**Intent:** Evaluate evidence-quality, not just final answers.

**Batch A requirements:**
- Include at least:
  - `recall_at_k`
  - `citation_coverage`
- Use `gold_chunk_ids` / evidence references when available.
- Output in the unified result schema.

- [ ] Step 1: Write failing tests for recall and citation coverage metrics.
- [ ] Step 2: Run `pytest -q tests/test_eval_retrieval_metrics.py` and confirm red.
- [ ] Step 3: Implement the retrieval/evidence metric helpers.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_retrieval_metrics.py` until green.
- [ ] Step 5: Commit the task.

### Task A7: Route Comparison Metrics

**Files:**
- Create: `app/rag/evaluation/metrics/routing.py`
- Create: `app/rag/evaluation/metrics/fusion.py`
- Test: `tests/test_eval_routing_metrics.py`
- Test: `tests/test_eval_fusion_metrics.py`

**Intent:** Measure route choice quality and hybrid value directly.

**Batch A requirements:**
- `routing_accuracy`
  - computed only when `expected_route` is present
- `conflict_rate`
  - minimal, first-version conflict metric for hybrid/fusion
- `net_gain_over_best_single`
  - minimal first-version hybrid uplift metric

- [ ] Step 1: Write failing tests for routing accuracy, conflict rate, and net gain.
- [ ] Step 2: Run `pytest -q tests/test_eval_routing_metrics.py tests/test_eval_fusion_metrics.py` and confirm red.
- [ ] Step 3: Implement the route comparison metrics.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_routing_metrics.py tests/test_eval_fusion_metrics.py` until green.
- [ ] Step 5: Commit the task.

### Task A8: Unified Runner Framework

**Files:**
- Create: `app/rag/evaluation/runners/base.py`
- Create: `app/rag/evaluation/runners/retrieval_runner.py`
- Create: `app/rag/evaluation/runners/kg_runner.py`
- Create: `app/rag/evaluation/runners/hybrid_runner.py`
- Create: `app/rag/evaluation/runners/registry.py`
- Test: `tests/test_eval_runner_registry.py`
- Test: `tests/test_eval_runner_result_shape.py`

**Intent:** Execute the same Stage 1 sample set across the three active routes, with `agentic` reserved in the registry and schemas.

**Batch A requirements:**
- Unified runner input schema.
- Unified result schema.
- Route adapters for:
  - `retrieval`
  - `kg`
  - `hybrid`
- `agentic` reserved in registry/result contracts, but not executed yet.
- Persist route config snapshots in run metadata/results.

- [ ] Step 1: Write failing tests for runner registry behavior and unified result shape.
- [ ] Step 2: Run `pytest -q tests/test_eval_runner_registry.py tests/test_eval_runner_result_shape.py` and confirm red.
- [ ] Step 3: Implement the unified runner framework and route adapters.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_runner_registry.py tests/test_eval_runner_result_shape.py` until green.
- [ ] Step 5: Commit the task.

### Task A9: Stage 1 Minimal Batch Runner

**Files:**
- Create: `app/rag/evaluation/runners/stage1_batch_runner.py`
- Test: `tests/test_eval_stage1_batch_runner.py`

**Intent:** Run the Stage 1 file-based seed set through the three active routes and emit file artifacts.

**Batch A requirements:**
- Consume Stage 1 dataset files.
- Validate dataset before execution.
- Run shared samples across:
  - `retrieval`
  - `kg`
  - `hybrid`
- Generate:
  - detailed results artifact
  - summary artifact
  - run metadata artifact
- Persist evaluator list and route config snapshots.

- [ ] Step 1: Write failing tests for stage1 batch execution and artifact creation.
- [ ] Step 2: Run `pytest -q tests/test_eval_stage1_batch_runner.py` and confirm red.
- [ ] Step 3: Implement the Stage 1 minimal batch runner.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_stage1_batch_runner.py` until green.
- [ ] Step 5: Commit the task.

### Task A10: Summary And Slice Aggregation

**Files:**
- Create: `app/rag/evaluation/reports/stage1_summary.py`
- Test: `tests/test_eval_stage1_summary.py`

**Intent:** Produce aggregate and sliced summaries from detailed runner results.

**Batch A requirements:**
- Aggregate overall metrics.
- Slice by query type:
  - `factual`
  - `multi_hop`
  - `structured`
  - `unanswerable`
- Include:
  - route comparison
  - routing accuracy
  - conflict rate
  - net gain
  - latency
  - cost
  - refusal handling stats

- [ ] Step 1: Write failing tests for Stage 1 summary aggregation and slicing.
- [ ] Step 2: Run `pytest -q tests/test_eval_stage1_summary.py` and confirm red.
- [ ] Step 3: Implement the summary/slicing layer.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_stage1_summary.py` until green.
- [ ] Step 5: Commit the task.

### Batch A Verification Gate

- [ ] Run the complete Batch A targeted suite.

  ```bash
  pytest -q \
    tests/test_eval_dataset_schema.py \
    tests/test_eval_dataset_validator.py \
    tests/test_eval_stage1_manifest.py \
    tests/test_eval_result_schema.py \
    tests/test_eval_result_artifacts.py \
    tests/test_eval_answer_det_metrics.py \
    tests/test_eval_ragas_adapter.py \
    tests/test_eval_retrieval_metrics.py \
    tests/test_eval_routing_metrics.py \
    tests/test_eval_fusion_metrics.py \
    tests/test_eval_runner_registry.py \
    tests/test_eval_runner_result_shape.py \
    tests/test_eval_stage1_batch_runner.py \
    tests/test_eval_stage1_summary.py
  ```

- [ ] Update `docs/plans/2026-04-21-backend-plan-execution-roadmap.md` after Batch A is verified.

## Batch B: Stage 2 Synthetic Expansion

### Task B1: Synthetic Sample Schema Extensions

**Files:**
- Extend: dataset schema files from Batch A
- Test: `tests/test_eval_synthetic_schema.py`

- [ ] Step 1: Write failing tests for Stage 2 synthetic schema extensions.
- [ ] Step 2: Run `pytest -q tests/test_eval_synthetic_schema.py` and confirm red.
- [ ] Step 3: Implement synthetic-specific schema fields and manifest handling.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_synthetic_schema.py` until green.
- [ ] Step 5: Commit the task.

### Task B2: Synthetic Generation Pipeline

**Files:**
- Create: `app/rag/evaluation/synthetic/generator.py`
- Create: `app/rag/evaluation/synthetic/critic.py`
- Create: `app/rag/evaluation/synthetic/pipeline.py`
- Test: `tests/test_eval_synthetic_pipeline.py`

- [ ] Step 1: Write failing tests for synthetic generation pipeline contracts.
- [ ] Step 2: Run `pytest -q tests/test_eval_synthetic_pipeline.py` and confirm red.
- [ ] Step 3: Implement Stage 2 synthetic generation and filtering pipeline.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_synthetic_pipeline.py` until green.
- [ ] Step 5: Commit the task.

### Task B3: Agentic Runner Integration

**Files:**
- Extend: runner registry/framework from Batch A
- Test: `tests/test_eval_agentic_runner.py`

- [ ] Step 1: Write failing tests for agentic runner integration.
- [ ] Step 2: Run `pytest -q tests/test_eval_agentic_runner.py` and confirm red.
- [ ] Step 3: Implement agentic execution in the unified runner framework.
- [ ] Step 4: Re-run `pytest -q tests/test_eval_agentic_runner.py` until green.
- [ ] Step 5: Commit the task.

### Batch B Verification Gate

- [ ] Run the Batch B targeted suite.
- [ ] Update the master roadmap after Batch B is verified.

## Deferred Items Beyond Batch B

- Full shadow evaluation pipeline
- Dynamic sample regeneration
- Large-scale adversarial mining
- Dashboard-first evaluation platform
- Multi-user labeling platform

