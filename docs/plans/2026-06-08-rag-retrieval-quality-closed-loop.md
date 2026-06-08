# RAG Retrieval Quality Closed Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make MimirQ's RAG platform prove retrieval quality through generic plugin contracts, live ingestion/retrieval gates, KG on/off comparison, and Dify-compatible evidence delivery.

**Architecture:** MimirQ remains the generic platform: it validates plugin contracts, runs governance/chunk/KG stages, indexes evidence chunks, applies shared retrieval policy, and exposes diagnostics. Business-specific behavior stays in plugin packages such as `plugins/pipelines/changzhou-gov-service-knowledge`, while Dify only passes dataset scope and receives retrieved evidence.

**Tech Stack:** Python, FastAPI, pytest, Makefile readiness gates, MimirQ plugin registry, Milvus-backed retrieval, existing Dify external knowledge adapter.

---

## Requirements Summary

- Preserve the platform/plugin boundary: no Changzhou-specific routing, section intent, or answer fast path in platform core or Dify adapter.
- Treat chunking as retrieval-asset design, not token splitting: chunks need answer-unit content, stable record identity, metadata views, and source provenance.
- Keep KG as optional retrieval assist: query expansion, aliases, relation-neighborhood hints, and explainable boosts only; KG must not bypass chunk evidence.
- Make retrieval quality measurable before production handoff: chunk report, plugin test report, direct MimirQ golden gate, KG off/on compare, Dify boundary probe, and full readiness summary.
- Let future business packages provide their own metadata schema and retrieval policy without code changes in MimirQ core.

## Acceptance Criteria

- `rg -n "经开区|天宁区|新北区|高效办成一件事|政务服务事项|常见问题|操作步骤" app/api app/rag --glob '!**/__pycache__/**'` finds no business-specific platform shortcuts outside generic docs/comments that are explicitly justified.
- `python scripts/changzhou_gov_dify_knowledge_map_check.py --env-file .env --out /tmp/changzhou_gov_dify_knowledge_map_check.json` passes with valid dataset routes and plugin refs.
- `make changzhou-gov-plugin-chunk-report` writes a report with all expected knowledge sections and representative chunk examples.
- `make changzhou-gov-plugin-corpus-closed-loop-smoke` can ingest the real corpus through the plugin and produce a sanitized evidence report.
- `make changzhou-dify-mimirq-direct-gate` passes the `changzhou-retrieval` quality profile against the same MimirQ service Dify will call.
- `make changzhou-dify-kg-on-off-gate` passes saved-report comparison before KG is enabled by default.
- `make changzhou-dify-external-probe` proves Dify external knowledge routes to MimirQ and gets non-empty effective evidence for golden cases.
- `make changzhou-dify-readiness-gate-quiet` produces a fresh readiness summary with no failed stages before delivery.

## Phase 1: Boundary And Contract Freeze

**Files:**
- Modify: `tests/test_pipeline_plugin_boundary.py`
- Modify: `tests/test_pipeline_plugin_registry.py`
- Modify: `tests/test_dify_external_knowledge_adapter.py`
- Inspect only: `app/api/v1/integrations_dify.py`
- Inspect only: `app/rag/retrieval/planner.py`
- Inspect only: `app/rag/retrieval/plugin_policy.py`

**Step 1: Write or tighten boundary tests**

Add tests that scan platform code for business-only terms and assert retrieval policy behavior comes from plugin data. Keep allowed paths limited to tests, docs, scripts, and `plugins/pipelines/changzhou-gov-service-knowledge`.

**Step 2: Run the boundary tests and confirm failure if a shortcut exists**

Run:

```bash
pytest tests/test_pipeline_plugin_boundary.py tests/test_pipeline_plugin_registry.py tests/test_dify_external_knowledge_adapter.py -q
```

Expected: pass after existing generic policy extraction; fail if platform code reintroduces Changzhou-specific fast paths.

**Step 3: Fix only generic contract issues**

If a failure exists, move business terms into `metadata_schema.json`, `retrieval_policy.json`, plugin Python code, or golden cases. Do not add platform constants for Changzhou sections, districts, or FAQ intent.

**Step 4: Verify lint**

Run:

```bash
ruff check app/api/v1/integrations_dify.py app/rag/retrieval/planner.py app/rag/retrieval/plugin_policy.py tests/test_pipeline_plugin_boundary.py tests/test_pipeline_plugin_registry.py tests/test_dify_external_knowledge_adapter.py
```

Expected: pass.

## Phase 2: Chunk Asset Inspection Before Ingestion

**Files:**
- Modify: `app/rag/pipeline_plugins/reports.py`
- Modify: `app/api/v1/pipeline.py`
- Modify: `scripts/changzhou_gov_plugin_chunk_report.py`
- Modify: `tests/test_pipeline_plugin_chunk_report.py`
- Modify: `tests/test_pipeline_plugin_chunk_report_api.py`
- Modify if needed: `web/components/chunk-preview/components/workbench/sidebar-client.tsx`

**Step 1: Lock generic report behavior**

Add or keep tests proving the report builder:

- Runs governance, chunk, and optional KG stage in plugin order.
- Groups by plugin-owned section metadata without hardcoded section names.
- Hides reserved platform metadata view keys.
- Includes representative chunk text, record identity, source path, metadata fields, and KG event summaries.

**Step 2: Verify current generic report tests**

Run:

```bash
pytest tests/test_pipeline_plugin_chunk_report.py tests/test_pipeline_plugin_chunk_report_api.py tests/test_changzhou_gov_plugin_chunk_report.py -q
```

Expected: pass.

**Step 3: Run the Changzhou report on local samples**

Run:

```bash
make changzhou-gov-plugin-chunk-report
```

Expected: report contains 01-06 section coverage, chunk examples, KG event counts, metadata fields, and no raw reserved metadata views.

**Step 4: Preserve the UI as inspection only**

If frontend changes are needed, keep the chunk-preview panel as a pre-ingestion review surface. It must not upload arbitrary Python or execute browser-submitted code; it selects a registered plugin ref and server-side sample.

## Phase 3: Real Corpus Closed Loop

**Files:**
- Inspect/modify: `scripts/plugin_corpus_closed_loop_smoke.py`
- Inspect/modify: `scripts/plugin_corpus_closed_loop_evidence.py`
- Inspect/modify: `Makefile`
- Inspect/modify: `docs/deployment/changzhou_dify_readiness_runbook.md`

**Step 1: Confirm local service readiness**

Run:

```bash
ss -ltnp | rg ':8000|:3000'
curl -fsS http://127.0.0.1:8000/health || curl -fsS http://127.0.0.1:8000/api/v1/health
```

Expected: backend on `8000` is reachable. Frontend on `3000` is optional for this phase.

**Step 2: Validate `.env` without printing secrets**

Run:

```bash
python scripts/changzhou_gov_dify_knowledge_map_check.py --env-file .env --out /tmp/changzhou_gov_dify_knowledge_map_check.json
```

Expected: plugin refs are valid, dataset route map is valid, and no missing retrieval policy refs.

**Step 3: Ingest the real corpus through the plugin**

Run with the real corpus path and selected dataset id:

```bash
make changzhou-gov-plugin-corpus-closed-loop-smoke \
  CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://127.0.0.1:8000 \
  CHANGZHOU_GOV_CORPUS_SOURCE_DIR="/data/temp50/20260522政务服务智能客服知识" \
  CHANGZHOU_GOV_CORPUS_DATASET_ID="<target-dataset-id>" \
  CHANGZHOU_GOV_CORPUS_EXTRA_ARGS="--include-source-root-name --overwrite-goldens"
```

Expected: governance/chunk/KG path runs through the registered plugin, chunks are indexed, and golden cases are imported or refreshed for the dataset.

**Step 4: Sanitize evidence**

Run:

```bash
make changzhou-gov-plugin-corpus-closed-loop-evidence
```

Expected: `/tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.json` and `.md` contain section-level counts, chunk counts, KG event counts, and retrieval metrics without dumping raw corpus content.

## Phase 4: Retrieval Quality Gate

**Files:**
- Modify if needed: `scripts/changzhou_gov_golden_eval.py`
- Modify if needed: `plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json`
- Modify if needed: `plugins/pipelines/changzhou-gov-service-knowledge/retrieval_policy.json`
- Modify if needed: `tests/test_changzhou_gov_golden_eval.py`

**Step 1: Keep golden cases section-aware**

Every case must declare expected metadata, including `knowledge_section` or equivalent plugin-owned scope. Cases should test 01 service items, 02 one-thing guides, 03 city FAQ, 04 topic FAQ, 05 department FAQ, and 06 district FAQ.

**Step 2: Run direct MimirQ retrieval gate**

Run:

```bash
make changzhou-dify-mimirq-direct-gate CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://127.0.0.1:8000
```

Expected: `hit_at_1`, `hit_at_3`, grounding, key-point recall, expected metadata rate, effective context rate, and noise rate satisfy `changzhou-retrieval`.

**Step 3: Diagnose failures by category**

Use the report failure type:

- Scope miss: fix Dify knowledge map, dataset selection, plugin metadata, or route hints.
- Ranking miss: fix retrieval policy, rerank features, topK budget, or KG boost.
- Chunk miss: fix plugin governance/chunking so a user question maps to a compact answer-bearing chunk.
- Content absence: add or correct source data/golden expectation.

**Step 4: Re-run saved-report gate**

Run:

```bash
python scripts/changzhou_gov_golden_eval.py \
  --report /tmp/changzhou_gov_dify_mimirq_direct_gate.json \
  --quality-profile changzhou-retrieval
```

Expected: pass without calling MimirQ.

**Status 2026-06-08:**

- Current local `8000` direct gate now retrieves correct evidence for all 13
  Changzhou golden cases: `hit_at_1=1.0`, `hit_at_3=1.0`, `hit_at_5=1.0`,
  `answer_grounding_rate=1.0`, and `answer_key_point_recall=1.0`.
- Remaining direct-gate failures are context noise only:
  `retrieval_effective_context_rate=0.75` and `retrieval_noise_rate=0.25`.
  The noisy cases already have correct top evidence, but extra top3 records from
  the same topic/file are not answer-bearing enough.
- One stale golden expectation was corrected: the emergency-account password
  reset case no longer requires unstable `category_leaf=用户管理`; the live chunk
  uses source-derived category metadata while preserving section/topic/chunk
  scope.
- The local `.env` knowledge map currently has valid dataset routes but no
  `plugin_refs`; in-memory preflight with
  `plugin:changzhou-gov-service-knowledge@1.0.0:chunk` attached to all
  Changzhou knowledge ids passes with 9 checked plugin refs. The actual `.env`
  still needs to be updated and the backend restarted before measuring plugin
  retrieval-policy effects in the live Dify adapter.

## Phase 5: KG On/Off Decision Gate

**Files:**
- Modify if needed: `app/rag/retrieval/planner.py`
- Modify if needed: `app/rag/retrieval/orchestrator.py`
- Modify if needed: `scripts/changzhou_gov_golden_eval.py`
- Modify if needed: `tests/test_retrieval_planner.py`
- Modify if needed: `tests/test_citations_include_kg_path.py`

**Step 1: Run KG off/on comparison**

Run:

```bash
make changzhou-dify-kg-on-off-gate CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://127.0.0.1:8000
```

Expected: KG-on candidate passes the same quality profile and does not regress hit, grounding, effective-context, metadata-match, or noise thresholds.

**Step 2: Keep KG disabled if it regresses**

If KG-on fails, leave KG default off for Dify external knowledge and use diagnostics to fix:

- Query expansion terms too broad.
- KG candidate injection adds wrong-section chunks.
- KG boost changes top evidence to weaker chunks.
- Entity aliases collide across districts/departments.

**Step 3: Enable only proven KG knobs**

If only query expansion passes but chunk injection regresses, enable query expansion only. Do not enable all KG assist knobs as a bundle.

## Phase 6: Dify Compatibility And Readiness

**Files:**
- Inspect/modify: `scripts/changzhou_gov_dify_external_knowledge_probe.py`
- Inspect/modify: `scripts/changzhou_gov_dify_full_gate.py`
- Inspect/modify: `scripts/changzhou_gov_dify_readiness_summary.py`
- Inspect/modify: `scripts/changzhou_gov_dify_readiness_status.py`
- Inspect/modify: `Makefile`
- Inspect/modify: `docs/deployment/changzhou_dify_readiness_runbook.md`

**Step 1: Confirm Dify routes to the same MimirQ instance**

Set:

```bash
export CHANGZHOU_DIFY_MIMIRQ_BASE_URL="http://<mimirq-host-reachable-by-dify>:8000"
```

Expected: direct gate and Dify external probe compare the same backend, not two stale or different services.

**Step 2: Run boundary probe**

Run:

```bash
make changzhou-dify-external-probe CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

Expected: `boundary.verdict=dify_external_boundary_ok`; Dify external hit-testing and direct MimirQ retrieval agree enough for golden cases.

**Step 3: Run full readiness gate**

Run:

```bash
make changzhou-dify-readiness-gate-quiet CHANGZHOU_DIFY_MIMIRQ_BASE_URL="$CHANGZHOU_DIFY_MIMIRQ_BASE_URL"
```

Expected: readiness summary is fresh, failed stages are empty, root cause is empty, and evidence markdown points to current artifacts.

**Step 4: Generate delivery pack**

Run:

```bash
make changzhou-gov-delivery-pack
```

Expected: combined handoff references plugin chunk evidence, plugin test evidence, and Dify/MimirQ readiness evidence.

## Phase 7: Submit Only After Evidence

**Files:**
- All modified files from `git status --short`

**Step 1: Run focused unit verification**

Run:

```bash
pytest \
  tests/test_retrieval_planner.py \
  tests/test_retrieval_plugin_policy.py \
  tests/test_retriever_plugin_policy.py \
  tests/test_pipeline_plugin_registry.py \
  tests/test_pipeline_plugin_boundary.py \
  tests/test_dify_external_knowledge_adapter.py \
  tests/test_changzhou_gov_golden_eval.py \
  -q
```

Expected: pass.

**Step 2: Run lint/compile over changed backend files**

Run:

```bash
ruff check app/rag app/api/v1/integrations_dify.py scripts/changzhou_gov_golden_eval.py scripts/changzhou_gov_dify_*.py tests/test_retrieval_planner.py tests/test_retrieval_plugin_policy.py tests/test_dify_external_knowledge_adapter.py
python -m py_compile app/rag/retrieval/planner.py app/rag/retrieval/plugin_policy.py app/api/v1/integrations_dify.py scripts/changzhou_gov_golden_eval.py
```

Expected: pass.

**Step 3: Check diff hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; status reviewed so unrelated user changes are not included accidentally.

**Step 4: Commit with Lore protocol**

Use a commit message that records the platform/plugin boundary decision, KG opt-in constraint, verification evidence, and any gates not run.

## Risks And Mitigations

- Risk: Real corpus gate fails because backend or vector services are not running. Mitigation: verify service health before live gates and keep failure artifacts.
- Risk: Dify points to a different MimirQ instance than local direct gate. Mitigation: readiness summary compares direct base URL and external endpoint host.
- Risk: KG improves some queries but adds cross-section noise. Mitigation: KG on/off comparison gates noise and metadata match before enabling defaults.
- Risk: Plugin metadata becomes too Changzhou-specific for future reuse. Mitigation: allow specificity inside plugin package only; keep platform validators generic.
- Risk: Golden cases overfit the current corpus. Mitigation: include all knowledge sections and diagnose by key points, metadata scope, and effective evidence rather than exact wording only.

## Non-Goals

- Do not rewrite chat or Dify workflow logic as the primary intelligence layer.
- Do not add direct business-answer fast paths.
- Do not require every future business plugin to use Changzhou metadata.
- Do not enable KG by default until live quality gates prove it.
