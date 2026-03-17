# Selective Hierarchical Recall Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Selectively integrate the highest-value KohakuRAG-style recall ideas into MimirQ without replacing the existing retrieval stack, parser stack, or storage model.

**Architecture:** Keep the current MimirQ retrieval engine, retrieval profiles, must-recall contracts, evidence trace, rerank stack, and evaluation tooling. Add an optional hierarchical recall overlay on top of existing chunk metadata and retrieval orchestration: family-aware recall keys, multi-query family aggregation, tree-style deduplication, bounded parent/sibling context expansion, and new recall-oriented metrics. Do not rebuild the system around a new four-level tree database; reuse current chunks, indices, and traces.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, Milvus, existing sparse/vector retrieval paths, pytest, scripts-based offline evaluation, Next.js + Vitest frontend, bd issue tracking.

---

## Recommendation

Recommended option: **Hierarchy as a retrieval overlay, not a storage rewrite.**

Why:

- MimirQ already has strong foundations: query rewrite, bounded multi-query, retrieval profiles, must-recall, explain endpoints, regression gates, and chunk preview.
- KohakuRAG is most useful here as a **retrieval-control pattern**, not as a parser or persistence template.
- Replacing current ingestion/indexing with a new document/section/paragraph/sentence database would create a large migration surface with unclear upside.

Not recommended in this wave:

- Rebuilding parsers around page-based or heuristic-only document trees.
- Replacing Milvus/Redis/Postgres with a new single-file store.
- Making hierarchy mandatory for every dataset and every retrieval path.

## Selective Cut Lines

- **Cut Line A (Tasks 1-15):** Safe foundation. Adds config, metadata contract, traceability, and family-aware recall without changing answer behavior.
- **Cut Line B (Tasks 16-25):** Highest-ROI online quality wave. Adds family aggregation, tree dedup, and bounded context expansion.
- **Cut Line C (Tasks 26-35):** Evaluation, operator tooling, and UI support.
- **Cut Line D (Tasks 36-40):** Experimental/late-stage rollout and profile productization.

## Recall Strategy To Compute

This wave should compute and compare the following recall signals, not just `hit@k`:

- `chunk_hit_at_k`: existing exact-chunk retrieval success.
- `family_hit_at_k`: whether any retrieved chunk from the same hierarchy family hits.
- `doc_hit_at_k`: whether the correct document is present even when the exact chunk drifts.
- `must_recall_pass_rate`: existing contract pass rate.
- `anchor_field_pass_rate`: whether required citation anchor fields remain present after expansion.
- `expansion_yield_rate`: how often parent/sibling expansion recovers an otherwise missed answer.
- `tree_dedup_saved_slots`: how many context slots are recovered by ancestor/child collapse.
- `multi_query_family_overlap`: how often the same family is hit across query variants.

## Task Breakdown (40)

### Workstream A: Config and Contract Foundations (Tasks 1-5)

### Task 1: Add hierarchy recall request knobs to runtime schemas
**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/schemas/dataset.py`
- Modify: `app/api/schemas/regression.py`
- Test: `tests/test_hierarchy_recall_request_schema.py`
**Verification:** `pytest -q tests/test_hierarchy_recall_request_schema.py`

### Task 2: Add hierarchy recall settings with safe-off defaults
**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`
**Verification:** `pytest -q tests/test_settings_retrieval_validation.py`

### Task 3: Add hierarchy recall profile ids and validation
**Files:**
- Modify: `app/rag/core/retrieval_profiles.py`
- Test: `tests/test_retrieval_profile_schema.py`
**Verification:** `pytest -q tests/test_retrieval_profile_schema.py`

### Task 4: Add hierarchy recall fields to retrieval config fingerprint
**Files:**
- Modify: `app/rag/core/retrieval_config_fingerprint.py`
- Modify: `app/api/v1/retrieval_config_hash.py`
- Test: `tests/test_retrieval_config_fingerprint_helper.py`
**Verification:** `pytest -q tests/test_retrieval_config_fingerprint_helper.py`

### Task 5: Add hierarchy recall fields to retrieval trace payload
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_trace_schema_v1.py`
**Verification:** `pytest -q tests/test_retrieval_trace_schema_v1.py`

### Workstream B: Hierarchy Metadata Overlay on Existing Chunks (Tasks 6-10)

### Task 6: Extend hierarchy utility to emit stable family keys and adjacency keys
**Files:**
- Modify: `app/rag/chunking/utils/hierarchical.py`
- Test: `tests/test_chunk_structure_inference.py`
- Test: `tests/test_parent_child_chunker_deterministic_parent_id.py`
**Verification:** `pytest -q tests/test_chunk_structure_inference.py tests/test_parent_child_chunker_deterministic_parent_id.py`

### Task 7: Persist hierarchy metadata during indexing
**Files:**
- Modify: `app/services/indexer.py`
- Test: `tests/test_indexer_source_metadata.py`
- Test: `tests/test_chunk_postprocessing_dedup_and_metadata.py`
**Verification:** `pytest -q tests/test_indexer_source_metadata.py tests/test_chunk_postprocessing_dedup_and_metadata.py`

### Task 8: Add contiguous sibling metadata for retrieval-time expansion
**Files:**
- Modify: `app/services/indexer.py`
- Test: `tests/test_chunk_adjacency_and_retrieval_stitching.py`
**Verification:** `pytest -q tests/test_chunk_adjacency_and_retrieval_stitching.py`

### Task 9: Add optional hierarchy basis to document chunk preview response
**Files:**
- Modify: `app/api/v1/documents.py`
- Test: `tests/test_documents_chunk_preview_response_fields.py`
**Verification:** `pytest -q tests/test_documents_chunk_preview_response_fields.py`

### Task 10: Document hierarchy overlay semantics for chunking strategies
**Files:**
- Modify: `docs/guides/chunking_playbook.md`
- Modify: `docs/guides/chunk_preview.md`
**Verification:** `ruff check docs/guides/chunking_playbook.md docs/guides/chunk_preview.md`

### Workstream C: Family-Aware Retrieval Candidate Handling (Tasks 11-15)

### Task 11: Add family collapse key resolution in retriever output normalization
**Files:**
- Modify: `app/rag/retriever.py`
- Test: `tests/test_retriever_parent_child_auto_merge.py`
**Verification:** `pytest -q tests/test_retriever_parent_child_auto_merge.py`

### Task 12: Add overfetch-then-collapse option for recall-first profiles
**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `app/rag/core/retrieval_profiles.py`
- Test: `tests/test_retrieval_defaults_are_reasonable.py`
- Test: `tests/test_retriever_metadata_filter_overfetch.py`
**Verification:** `pytest -q tests/test_retrieval_defaults_are_reasonable.py tests/test_retriever_metadata_filter_overfetch.py`

### Task 13: Add family hit attribution into citation metadata
**Files:**
- Modify: `app/rag/core/citations.py`
- Test: `tests/test_evidence_includes_retrieval_trace.py`
**Verification:** `pytest -q tests/test_evidence_includes_retrieval_trace.py`

### Task 14: Add family-level collapse mode to evidence retrieval path
**Files:**
- Modify: `app/api/v1/rag.py`
- Modify: `app/api/v1/chat.py`
- Test: `tests/test_rag_retrieve_endpoints.py`
- Test: `tests/test_chat_default_retrieval_profile.py`
**Verification:** `pytest -q tests/test_rag_retrieve_endpoints.py tests/test_chat_default_retrieval_profile.py`

### Task 15: Add recall-first family-collapse regression fixture
**Files:**
- Add: `ci/retrieval_hierarchy_family_fixture.v1.json`
- Test: `tests/test_retrieval_hierarchy_family_collapse.py`
**Verification:** `pytest -q tests/test_retrieval_hierarchy_family_collapse.py`

### Workstream D: Multi-Query Family Aggregation (Tasks 16-20)

### Task 16: Record per-variant family hits before fusion
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_multi_query_diversify_retrieval_config_hash.py`
**Verification:** `pytest -q tests/test_multi_query_diversify_retrieval_config_hash.py`

### Task 17: Add family aggregation strategies `frequency|score|combined`
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retrieval_family_rerank.py`
**Verification:** `pytest -q tests/test_retrieval_family_rerank.py`

### Task 18: Add family aggregation knobs to explain/config-hash endpoints
**Files:**
- Modify: `app/api/v1/retrieval_explain.py`
- Modify: `app/api/v1/retrieval_config_hash.py`
- Test: `tests/test_retrieval_explain_endpoint.py`
- Test: `tests/test_retrieval_config_hash_endpoint.py`
**Verification:** `pytest -q tests/test_retrieval_explain_endpoint.py tests/test_retrieval_config_hash_endpoint.py`

### Task 19: Coordinate multi-query diversify budget with family aggregation
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_rerank_budget_governance.py`
**Verification:** `pytest -q tests/test_rerank_budget_governance.py`

### Task 20: Add family-overlap metrics to retrieval debug output
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_retriever_debug_metrics_shape.py`
**Verification:** `pytest -q tests/test_retriever_debug_metrics_shape.py`

### Workstream E: Tree Dedup and Context Expansion (Tasks 21-25)

### Task 21: Add ancestor-wins tree dedup after retrieval fusion
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_paragraph_dedup.py`
**Verification:** `pytest -q tests/test_paragraph_dedup.py`

### Task 22: Add bounded parent/sibling expansion utility
**Files:**
- Modify: `app/rag/retrieval/contextual_followup.py`
- Add: `app/rag/retrieval/hierarchy_expand.py`
- Test: `tests/test_hierarchy_context_expansion.py`
**Verification:** `pytest -q tests/test_hierarchy_context_expansion.py`

### Task 23: Add expansion-aware citation span merging
**Files:**
- Modify: `app/rag/core/citations.py`
- Test: `tests/test_retrieval_contract_strict_evidence.py`
**Verification:** `pytest -q tests/test_retrieval_contract_strict_evidence.py`

### Task 24: Add expansion-aware anchor-field validation
**Files:**
- Modify: `app/rag/core/evidence_expectations.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_tag_citation_evidence_keys.py`
**Verification:** `pytest -q tests/test_tag_citation_evidence_keys.py`

### Task 25: Expose expanded context origin in retrieval trace and citations
**Files:**
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/core/citations.py`
- Test: `tests/test_rag_trace_schema.py`
**Verification:** `pytest -q tests/test_rag_trace_schema.py`

### Workstream F: Recall Metric Computation and Gates (Tasks 26-30)

### Task 26: Add family/doc/anchor recall metrics to evidence gate
**Files:**
- Modify: `app/rag/evaluation/evidence_retrieve_gate.py`
- Test: `tests/test_retrieval_coverage_proxy_metrics.py`
- Test: `tests/test_regression_run_metrics.py`
**Verification:** `pytest -q tests/test_retrieval_coverage_proxy_metrics.py tests/test_regression_run_metrics.py`

### Task 27: Add hierarchy-aware reference expectations to regression cases
**Files:**
- Modify: `app/api/schemas/regression.py`
- Modify: `app/services/regression_case_bundle.py`
- Test: `tests/test_regression_retrieval_only_mode.py`
**Verification:** `pytest -q tests/test_regression_retrieval_only_mode.py`

### Task 28: Add hierarchy ablation matrix entries
**Files:**
- Modify: `scripts/retrieval_ablation.py`
- Test: `tests/test_retrieval_ablation.py`
**Verification:** `pytest -q tests/test_retrieval_ablation.py`

### Task 29: Add hierarchy metrics to sample benchmark output
**Files:**
- Modify: `scripts/run_sample_retrieval_benchmark.py`
- Test: `tests/test_run_sample_retrieval_benchmark.py`
**Verification:** `pytest -q tests/test_run_sample_retrieval_benchmark.py`

### Task 30: Add must-recall provenance proof fields for family expansion
**Files:**
- Modify: `app/rag/policy/recall_obligation.py`
- Test: `tests/test_recall_obligation.py`
- Test: `tests/test_replay_from_evidence_capsule.py`
**Verification:** `pytest -q tests/test_recall_obligation.py tests/test_replay_from_evidence_capsule.py`

### Workstream G: Operator and API Tooling (Tasks 31-35)

### Task 31: Add hierarchy sections to retrieval explain response
**Files:**
- Modify: `app/api/v1/retrieval_explain.py`
- Test: `tests/test_retrieval_explain_endpoint.py`
**Verification:** `pytest -q tests/test_retrieval_explain_endpoint.py`

### Task 32: Add hierarchy recall profile examples to API docs
**Files:**
- Modify: `docs/examples/retrieval_api_examples.md`
- Modify: `docs/examples/retrieval_api_examples.http`
- Test: `tests/test_retrieval_api_examples_docs.py`
**Verification:** `pytest -q tests/test_retrieval_api_examples_docs.py`

### Task 33: Add hierarchy debugging notes to retrieval cookbook
**Files:**
- Modify: `docs/guides/retrieval_debugging.md`
- Modify: `docs/guides/retrieval_fusion.md`
**Verification:** `ruff check docs/guides/retrieval_debugging.md docs/guides/retrieval_fusion.md`

### Task 34: Add hierarchy recall counters to report service
**Files:**
- Modify: `app/services/report_service.py`
- Modify: `app/api/v1/reports.py`
- Test: `tests/test_dataset_report_html_includes_eval_summary.py`
**Verification:** `pytest -q tests/test_dataset_report_html_includes_eval_summary.py`

### Task 35: Add hierarchy recall audit notes to retrieval debt audit script
**Files:**
- Modify: `scripts/generate_retrieval_debt_audit.py`
- Modify: `docs/templates/retrieval_debt_audit_template.md`
- Test: `tests/test_release_gate_docs.py`
**Verification:** `pytest -q tests/test_release_gate_docs.py`

### Workstream H: Frontend Explainability and Review UX (Tasks 36-40)

### Task 36: Show hierarchy recall signals in RAG trace panel
**Files:**
- Modify: `web/components/rag-trace/rag-trace-panel.tsx`
- Test: `web/components/rag-trace/rag-trace-panel.channel-scores.test.ts`
- Test: `web/components/rag-trace/rag-trace-panel.retrieval-config-hash.test.ts`
**Verification:** `pnpm --dir web vitest run web/components/rag-trace/rag-trace-panel.channel-scores.test.ts web/components/rag-trace/rag-trace-panel.retrieval-config-hash.test.ts`

### Task 37: Show expanded/family-hit badges in retrieve preview panel
**Files:**
- Modify: `web/components/rag/retrieve-preview-panel.tsx`
- Test: `web/components/rag/retrieve-preview-panel.source.test.ts`
- Test: `web/components/rag/retrieve-preview-panel.image-citations.test.ts`
**Verification:** `pnpm --dir web vitest run web/components/rag/retrieve-preview-panel.source.test.ts web/components/rag/retrieve-preview-panel.image-citations.test.ts`

### Task 38: Add hierarchy review signals to chunk preview utilities
**Files:**
- Modify: `web/components/chunk-preview/utils/review-signals.ts`
- Test: `web/components/chunk-preview/utils/review-signals.test.ts`
**Verification:** `pnpm --dir web vitest run web/components/chunk-preview/utils/review-signals.test.ts`

### Task 39: Add hierarchy recall cues to evidence-missed analysis
**Files:**
- Modify: `web/lib/evidence-why-missed.ts`
- Test: `web/lib/evidence-suggestions.test.ts`
**Verification:** `pnpm --dir web vitest run web/lib/evidence-suggestions.test.ts`

### Task 40: Add frontend workbench support for hierarchy basis in chunk compare
**Files:**
- Modify: `web/components/chunk-preview/components/chunk-compare-dialog.tsx`
- Modify: `web/components/chunk-preview/index.tsx`
- Test: `web/components/workbench/workbench.index.test.ts`
**Verification:** `pnpm --dir web vitest run web/components/workbench/workbench.index.test.ts`

## Execution Notes

- Start with **Tasks 1-15** only. They are the safest additive layer and give enough surface to run offline comparisons.
- Only proceed to **Tasks 16-25** if ablations show `family_hit_at_k` or `must_recall_pass_rate` improvement without materially hurting latency.
- Keep **Tasks 36-40** behind the backend trace contract; do not build frontend affordances before the trace schema is stable.
- Do **not** change parser backends or ingest format in this wave. Hierarchy here is derived from chunk metadata and adjacency, not a mandate to reparse everything into a new tree.

## Expected Success Criteria

- New hierarchy-aware retrieval configs are reproducible via `retrieval_config_hash`.
- Offline ablations can compare baseline vs hierarchy-enhanced recall using `chunk_hit_at_k`, `family_hit_at_k`, `doc_hit_at_k`, and `must_recall_pass_rate`.
- Online retrieval explain/debug payloads can show:
  - query variant family overlap
  - tree dedup savings
  - parent/sibling expansion usage
  - anchor-field preservation after expansion
- The feature remains default-off and rollback is config-only.
