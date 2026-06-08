# Retrieval Planner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move retrieval scope and budget decisions out of interface adapters and into a reusable platform planner.

**Architecture:** The platform owns a small planner module under `app/rag/retrieval` that converts caller hints into a bounded retrieval plan. Business plugins may emit metadata, aliases, KG relations, and route hints, but the planner decides how those hints affect candidate scope, internal recall budget, strict filters, and diagnostics.

**Tech Stack:** Python, FastAPI, Pydantic config, pytest, existing MimirQ RAG retrieval stack.

---

## Design Principles

- Platform code must not contain business-only shortcuts. It can consume generic hints such as dataset route hints, metadata anchors, KG entity aliases, and evaluation requirements.
- Adapters such as Dify should translate external payloads into planner inputs, not own routing policy.
- Retrieval should optimize for effective evidence in topK, not exact record identity unless an evaluation explicitly asks for record identity.
- KG should assist RAG by expanding/querying/prioritizing evidence candidates. It should not bypass evidence retrieval or answer directly in platform code.
- Business plugins own governance, chunking, metadata shape, KG extraction hints, and golden cases.

## Phase 1: Extract Dataset Scope And TopK Budget Planner

**Files:**
- Create: `app/rag/retrieval/planner.py`
- Create: `tests/test_retrieval_planner.py`
- Modify: `app/api/v1/integrations_dify.py`
- Modify: `tests/test_dify_external_knowledge_adapter.py`

**Behavior:**
- `resolve_internal_candidate_top_k()` clamps internal candidate recall with requested topK, minimum, multiplier, and maximum.
- `plan_dataset_scope()` treats non-strict route hints as recall hints by default: all route datasets are eligible primary candidates, and matched routes only reorder candidate scope.
- Strict mode remains available for true hard scope filters. Do not use ordinary route hints as implicit filters, because a high-scoring but wrong base dataset can otherwise block FAQ/department evidence.
- Dify adapter keeps the same external API and response shape, but delegates route and topK policy to the planner.

**Verification:**
- `pytest tests/test_retrieval_planner.py tests/test_dify_external_knowledge_adapter.py -q`
- `make changzhou-dify-mimirq-direct-gate`
- 100-case Changzhou eval should keep answer grounding/key point recall at 1.0.

**Status 2026-06-08:**
- Implemented planner extraction and Dify adapter integration.
- Fixed regression where `changzhou_city_service` FAQ queries were gated behind the base 01 service-item dataset. Before the fix, current-code 100-case eval dropped to `hit@1=0.72`, `misses=25`, `retrieval_noise_rate=0.396`.
- After making non-strict routes true hints instead of implicit filters, 100-case eval returned to `hit@1=0.95`, `hit@3=0.99`, `hit@5=0.99`, `misses=1`, `answer_grounding_rate=1.0`, `answer_key_point_recall=1.0`, `retrieval_noise_rate=0.061`.

## Phase 2: Effective Retrieval Metrics

**Files:**
- Modify: `scripts/changzhou_gov_golden_eval.py`
- Add focused tests under `tests/test_changzhou_gov_golden_eval.py`

**Behavior:**
- Keep source/record hit metrics as secondary diagnostics.
- Promote evidence effectiveness metrics: key point recall, grounded answer support, and optional noise ratio.
- Record topK evidence diagnostics so regressions show whether the failure is scope, ranking, or chunk quality.
- Provide a named quality profile that can be reused by direct eval, Dify full gate, readiness gate, and saved-report rechecks.

**Status 2026-06-08:**
- Added `changzhou-retrieval` quality profile with hit-rate, grounded-answer, key-point recall, effective-context, noise-rate, and expected-metadata coverage/match checks.
- Added expected-metadata coverage and match rates for cases that declare `expected.metadata`, so golden reports can separately measure whether the case set covers metadata scope and whether top evidence stays inside the expected region, knowledge type, or business metadata scope.
- Added existing-report gate mode so saved eval JSON can be rechecked without rerunning retrieval or requiring tokens.
- Wired the same profile into `make changzhou-dify-mimirq-direct-gate`, `make changzhou-dify-full-gate`, and `make changzhou-dify-readiness-gate`.
- Verified the regressed 100-case report exits with gate failure (`rc=3`) and the fixed report passes (`rc=0`).

## Phase 3: KG As Planner Hints

**Files:**
- Extend: `app/rag/retrieval/planner.py`
- Integrate with existing KG search/alias modules in `app/rag/kg`
- Extend plugin contracts with a generic `retrieval_policy.json` declaration

**Behavior:**
- KG emits query expansion terms, entity aliases, relation-neighborhood dataset/metadata hints, and explainable boosts.
- Planner uses KG hints to prioritize candidate channels or metadata filters under a latency budget.
- KG output remains evidence-linked; final answers still cite chunks.
- Business plugins may declare query-expansion fields, filter fields, boost fields, anchor fields, rerank features, and fallback tolerance through `mimirq.retrieval_policy.v1`. The platform validates field references but does not learn business-specific field names.

**Status 2026-06-08:**
- Dify KG assistance is wired as explicit opt-in settings for query expansion, chunk injection, and chunk boost.
- Defaults remain off for Dify external knowledge until plugin-level golden gates prove KG improves retrieval. A prior 13-case run with Dify KG enabled regressed evidence quality, so KG must not be enabled by default.
- Added the `retrieval_policy` plugin contract and wired the Changzhou government plugin to declare platform-consumable retrieval fields without dataset IDs or Dify routing.
- Added planner helpers that consume `mimirq.retrieval_policy.v1` as pure data: query expansion terms can be extracted from declared metadata fields, boost scores can be computed from declared boost fields, anchor mismatch penalties can demote conflicting declared anchors, fallback candidate-window multipliers can be read, and rerank-feature scores can be computed without platform business defaults.
- Dify external knowledge ranking now reads `chunk_python_plugin` / `governance_python_plugin`, resolves the registered plugin descriptor, and applies the plugin retrieval policy as a generic rank bonus.
- Dify external knowledge diagnostics now report how many candidate records had an active plugin retrieval policy, how many received any policy rank signal, how many matched boost fields, query-expansion fields, or rerank features, and which plugin refs contributed policy.
- Dify knowledge map entries may declare `plugin_refs`; when present, the adapter uses the referenced plugin policies' `filter_fields` as an allowlist for `metadata_condition` pushdown. This keeps metadata filters plugin-owned instead of platform-owned.
- Dify knowledge map entries with `plugin_refs` also apply enabled `fallback.expand_top_k_multiplier` values to the internal candidate window, bounded by `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX` and without changing the external returned `top_k`.
- Dify external knowledge ranking now consumes `rerank_features` as weaker bounded rank hints when declared metadata values match the query; stronger weighted intent remains in `boost_fields`.
- The Changzhou Dify knowledge-map preflight now validates declared `plugin_refs` and fails early when a referenced plugin cannot provide `mimirq.retrieval_policy.v1`, so delivery catches policy binding mistakes before remote Dify probes.
- Extracted record-level retrieval policy scoring and diagnostics into
  `app/rag/retrieval/plugin_policy.py`.
- Native `HybridRetriever` now preserves plugin provenance metadata for BM25
  candidates and applies the same shared policy scoring after channel fusion, so
  policy behavior is no longer Dify-only.

## Phase 4: Runtime Quality And Latency Controls

**Files:**
- Existing retrieval orchestrator and metrics modules under `app/rag/retrieval` and `app/services`

**Behavior:**
- Add budget diagnostics: dataset count, route hints matched, candidate topK, final topK, fallback usage, latency by stage.
- Add a production policy for fallback expansion when first-pass evidence quality is weak.
- Close BM25 runtime gap so hybrid retrieval is actually hybrid when enabled.

**Status 2026-06-08:**
- Added Dify retrieval diagnostics for dataset scope, route counts, primary/expansion counts, candidate topK, citation counts, and retrieval path.
- Added retriever BM25 debug status so hybrid retrieval can show whether BM25 was disabled, missing cache, lazy-built, or actually participated.

## Non-Goals

- Do not add government-specific shortcuts to platform retrieval.
- Do not bypass RAG with direct business answers.
- Do not force every plugin to use the Changzhou metadata schema.
