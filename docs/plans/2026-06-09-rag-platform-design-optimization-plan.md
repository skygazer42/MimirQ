# RAG Platform Design Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn MimirQ's current plugin/RAG work into an evidence-first platform design where business plugins improve retrieval quality without specializing the platform core.

**Architecture:** MimirQ owns generic contracts, execution, storage, retrieval, diagnostics, and gates. Pipeline plugins own business governance, chunking, metadata schema, KG events, retrieval hints, and golden cases. Dify and other integrations pass dataset scope and receive evidence; they must not contain business ranking shortcuts or answer fast paths.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, Makefile gates, MimirQ pipeline plugin registry, regression evaluation, existing dataset report/RAG audit export, Next.js/React report and evaluation pages.

---

## Current Diagnosis

MimirQ already has the right foundation:

- `docs/guides/pipeline_plugins.md` defines registered governance/chunk/KG plugins as the business-extension mechanism.
- `app/rag/pipeline_plugins/reports.py` can build generic plugin chunk reports without learning business field meanings.
- `app/rag/retrieval/plugin_policy.py` applies plugin retrieval-policy signals through a shared platform helper.
- `scripts/changzhou_gov_golden_eval.py` already measures hit rate, expected metadata, effective context, noise, and KG diagnostics.
- `app/api/schemas/report.py` and `app/services/report_service.py` already have dataset report and RAG audit surfaces.
- `docs/deployment/changzhou_dify_readiness_runbook.md` already describes delivery gates for plugin, MimirQ direct retrieval, KG compare, Dify boundary, and full workflow checks.

The remaining design risk is not lack of algorithms. The risk is that the best evidence still lives across scripts, `/tmp` artifacts, readiness runbooks, and plugin-specific commands. Production operators need a first-class retrieval audit trail inside the platform, and future business plugins need the same gates without changing platform code.

## Design Philosophy Decision Matrix

Use this matrix when deciding whether a behavior belongs in MimirQ core, a
pipeline plugin, or a deployment adapter.

| Decision Area | Platform Core Responsibility | Plugin Package Responsibility | Deployment / Adapter Responsibility | Primary Optimization Lever |
| --- | --- | --- | --- | --- |
| Business record interpretation | Validate contracts, execute stages, persist standard assets. Platform core must not learn business meanings. | Plugin packages own business interpretation, record boundaries, normalization, aliases, and business metadata. | Bind the selected plugin refs to the target dataset and record package provenance. | Improve plugin governance fixtures and `metadata_schema.json`. |
| Chunk granularity | Store chunks, metadata views, provenance, index state, and audit evidence without knowing the business type. | Decide whether a source becomes one chunk, several evidence chunks, FAQ pairs, table records, or workflow steps. | Run plugin chunk reports and corpus gates before publishing. | Optimize chunk completeness and answer-bearing evidence coverage. |
| Retrieval policy | Apply a generic policy helper for candidate sources, metadata filters, boosts, and rerank features. | Declare query expansion fields, filter fields, anchors, boost fields, and fallback hints in `retrieval_policy.json`. | Pass dataset scope and optional runtime profile; do not add business ranking code. | Tune retrieval policy and Golden thresholds before touching adapter code. |
| KG assist | Consume generic KG events as expansion, injection, or ranking features; never return final answers directly from KG. | Emit evidence-backed entities, aliases, relations, and event provenance from chunked documents. | Enable KG only after KG-off/KG-on comparison proves no quality regression. | Reduce KG noise and require evidence-linked relations. |
| External workflow integration | Return evidence chunks, scores, safe metadata, and trace. | Stay unaware of Dify or other external workflow implementations. | Deployment adapters own external binding and network evidence, including knowledge-id to dataset-id mapping. | Fix boundary, timeout, auth, and scope issues without adding fast paths. |
| Release quality | Assemble generic retrieval audit snapshots, regression summaries, and failure categories. | Provide Golden cases or Golden-generation rules that express the business expected evidence. | Publish delivery packs and readiness summaries from persisted gate evidence. | Optimize evidence retrieval before answer generation. |

The deciding question is: "Would a second unrelated business need this exact
branch in platform code?" If no, it belongs in a plugin package or deployment
configuration. If yes, it should be expressed as a stable contract or shared
executor behavior, not as a business-specific shortcut.

## Optimization Priority Ladder

When retrieval quality is poor, fix layers in this order. Later layers cannot
repair missing or badly structured evidence from earlier layers.

1. Corpus fit: verify that the answer really exists in the selected dataset and
   that the dataset scope is correct.
2. Record identity and metadata schema: make sure the plugin emits stable
   `record_identity`, filterable fields, display fields, and evaluable fields.
3. Chunk evidence completeness: ensure chunks contain self-contained answer
   evidence, source provenance, and parent record linkage.
4. Hybrid retrieval policy: tune vector, BM25, sparse, metadata filters, anchors,
   and boosts through generic `retrieval_policy.json` hints.
5. Rerank: improve ordering after recall is sufficient; do not use rerank to
   hide missing candidate evidence.
6. KG assist: enable query expansion, chunk injection, or KG boost only when
   saved KG-on/off evidence shows hit, metadata match, and noise stay within
   thresholds.
7. External adapter latency and binding: tune top-k limits, timeouts, streaming,
   and Dify knowledge mapping after native MimirQ retrieval is proven.
8. Answer generation: adjust prompt or downstream chat behavior only after the
   retrieved evidence is correct.

This order is intentional: answer quality should be downstream of retrieval
evidence quality. If a question has an answer in the knowledge base, the primary
platform obligation is to retrieve strongly related answer-bearing chunks.

## Options Considered

### Option A: Platform-specialized business routes

Put government-specific records, districts, FAQ categories, workflow terms, or
known aliases directly into `app/` and Dify adapter code. This can improve one
demo quickly, but it makes MimirQ a business application instead of a reusable
RAG platform. It also makes future domains compete for runtime branches and
prevents neutral evaluation.

### Option B: Raw generic splitter and generic retrieval only

Avoid plugin behavior and rely on default parsing, generic chunk sizes, vector
search, and rerank. This keeps the platform simple, but it loses the business
record boundaries and metadata needed for precise recall, scope filtering,
Golden evaluation, and explainable KG assist.

### Option C: Contract-first plugin system

Use plugins for business governance, chunking, metadata, KG events, retrieval
hints, and Golden cases; keep the platform responsible for validation,
execution, indexing, retrieval, audit, and release gates. This is the recommended
design because it preserves platform neutrality while still allowing each
business package to encode the information needed for high-quality recall.

## Design Principles To Enforce

1. Platform code must stay business-neutral. Any terms like districts, service items, FAQ sections, department categories, or one-thing guides belong in plugin packages, tests, scripts, or docs.
2. Ingestion must produce inspectable retrieval assets, not just chunks. The system should preserve governed record counts, chunk kinds, metadata coverage, KG event coverage, golden provenance, and plugin package hash.
3. Retrieval quality must be measured before answer generation. A dataset is ready only when retrieved chunks contain the expected answer-bearing evidence with low noise.
4. KG is an explainable retrieval hint, not a bypass. KG may expand queries, add entity anchors, and boost relation-neighborhood evidence only when KG-on gates do not regress quality.
5. Dify is a compatibility adapter. It should map external knowledge IDs to MimirQ dataset IDs and return evidence. It should not own business policy, chunk shortcuts, or custom answer logic.
6. Plugin schemas are extensible; platform schemas are stable. Each business package can define its own metadata fields, but platform storage, filtering, display, and evaluation consume those fields through generic contracts.

## Non-Goals

- Do not add a Changzhou-specific route, service, or fast path in `app/`.
- Do not make Dify workflow logic part of the platform retrieval policy.
- Do not require every future plugin to copy the Changzhou metadata fields.
- Do not replace existing regression evaluation with a second incompatible metric system.
- Do not enable KG by default unless a saved KG-on/off comparison proves quality is preserved.

## Acceptance Criteria

- Platform boundary tests fail if business-specific terms are introduced into `app/api`, `app/rag`, or shared retrieval modules outside explicit allowlists.
- Every published executable plugin can produce a chunk/KG/golden-readiness report from registered plugin refs without arbitrary host-path execution.
- Dataset report output includes a normalized retrieval audit snapshot assembled from existing plugin report, latest regression run, KG diagnostics, and Dify readiness artifacts when available.
- The report UI exposes retrieval-readiness status with enough drill-down to identify whether a failure is caused by scope, chunking, metadata, KG, ranking, or Dify binding.
- Dify external retrieval and native MimirQ retrieval use the same plugin retrieval-policy scoring helpers.
- A new business plugin can add metadata fields and golden cases without platform code changes.

---

### Task 1: Freeze Platform/Plugin Boundary

**Files:**
- Modify: `tests/test_pipeline_plugin_boundary.py`
- Modify: `tests/test_dify_external_knowledge_adapter.py`
- Inspect: `app/api/v1/integrations_dify.py`
- Inspect: `app/rag/retrieval/plugin_policy.py`
- Inspect: `app/rag/retrieval/planner.py`
- Modify if wording changes: `docs/guides/pipeline_plugins.md`

**Step 1: Add a source guard for platform business leakage**

Extend the existing boundary test with an allowlist-based scan:

```python
BUSINESS_TERMS = (
    "经开区",
    "天宁区",
    "新北区",
    "高效办成一件事",
    "政务服务事项",
    "常州市常见问题",
    "业务部门常见问题",
)
PLATFORM_PATHS = (Path("app/api"), Path("app/rag"))
ALLOWED_PLATFORM_FILES = {
    Path("app/rag/pipeline_plugins/contracts.py"),
}
```

The test should fail when a term appears in platform runtime code unless the file is explicitly documented as a generic contract example.

**Step 2: Prove Dify has no business fast path**

Add or keep assertions in `tests/test_dify_external_knowledge_adapter.py` that:

- Dify resolves `plugin_refs` from `DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON`.
- Dify calls shared retrieval policy helpers instead of applying local business rules.
- No adapter test fixture requires Changzhou-specific terms to pass generic retrieval behavior.

**Step 3: Run boundary tests**

Run:

```bash
pytest tests/test_pipeline_plugin_boundary.py tests/test_dify_external_knowledge_adapter.py tests/test_retrieval_plugin_policy.py -q
```

Expected: pass. If it fails because a real shortcut exists, move that logic into plugin files such as `plugins/pipelines/<plugin>/retrieval_policy.json`, `metadata_schema.json`, or `plugin.py`.

**Step 4: Lint touched runtime files**

Run:

```bash
ruff check app/api/v1/integrations_dify.py app/rag/retrieval/plugin_policy.py app/rag/retrieval/planner.py tests/test_pipeline_plugin_boundary.py tests/test_dify_external_knowledge_adapter.py tests/test_retrieval_plugin_policy.py
```

Expected: pass.

### Task 2: Define A Generic Retrieval Audit Snapshot Schema

**Files:**
- Modify: `app/api/schemas/report.py`
- Modify: `app/services/report_service.py`
- Test: `tests/test_reports_dataset_report.py`
- Test: `tests/test_report_html_includes_retrieval_slices_dims.py`
- Test: `tests/test_rag_audit_html_redaction.py`

**Step 1: Add report schema models**

Add generic report models such as:

```python
class DatasetRetrievalAuditGateOut(BaseModel):
    name: str
    status: str = "unavailable"
    metrics: dict[str, Any] = Field(default_factory=dict)
    failed_conditions: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None
    source: str | None = None


class DatasetRetrievalAuditOut(BaseModel):
    status: str = "unavailable"
    plugin_refs: list[str] = Field(default_factory=list)
    plugin_package_hashes: list[str] = Field(default_factory=list)
    gates: list[DatasetRetrievalAuditGateOut] = Field(default_factory=list)
    failure_categories: dict[str, int] = Field(default_factory=dict)
    recommended_next_action: str | None = None
```

Then add `retrieval_audit: DatasetRetrievalAuditOut | None = None` to `DatasetReportOut`.

**Step 2: Write a failing dataset report test**

In `tests/test_reports_dataset_report.py`, build a dummy report with `retrieval_audit` and assert the JSON response includes:

- `status`
- `gates`
- `plugin_refs`
- `failure_categories`
- no raw document content
- no secret-like values

**Step 3: Populate an initial snapshot from latest regression run**

In `app/services/report_service.py`, derive a first version from `latest_regression_run.summary`:

- `retrieval_effective_context_rate`
- `retrieval_noise_rate`
- `expected_metadata_hit_rate`
- `expected_metadata_recall`
- `hit_at_1`, `hit_at_3`, `mrr`, `ndcg`
- available KG diagnostic summary fields

Do not parse `/tmp` files in the service. If external artifacts are needed later, import them through explicit APIs or persisted run metadata.

**Step 4: Verify report tests**

Run:

```bash
pytest tests/test_reports_dataset_report.py tests/test_report_html_includes_retrieval_slices_dims.py tests/test_rag_audit_html_redaction.py -q
```

Expected: pass.

### Task 3: Add Retrieval Audit HTML Export Section

**Files:**
- Modify: `app/services/report_html.py`
- Test: `tests/test_dataset_report_html_includes_eval_summary.py`
- Test: `tests/test_rag_audit_html_redaction.py`

**Step 1: Add redacted HTML rendering**

Render a compact section after the existing regression/governance sections:

- readiness status
- latest gate names and statuses
- key retrieval metrics
- expected metadata hit/recall
- effective context and noise
- KG status if available
- next action

Avoid raw chunk text, raw query text, secret env values, or full Dify payloads.

**Step 2: Add a redaction regression test**

Add a test with a fake `retrieval_audit` containing secret-looking strings in ignored fields. Assert the HTML does not contain those strings and still contains the safe aggregate metrics.

**Step 3: Run HTML tests**

Run:

```bash
pytest tests/test_dataset_report_html_includes_eval_summary.py tests/test_rag_audit_html_redaction.py tests/test_reports_dataset_report.py -q
```

Expected: pass.

### Task 4: Productize Plugin Readiness As A Generic API

**Files:**
- Modify: `app/api/v1/pipeline.py`
- Modify: `app/api/schemas/pipeline.py`
- Modify: `app/rag/pipeline_plugins/reports.py`
- Test: `tests/test_pipeline_plugin_chunk_report_api.py`
- Test: `tests/test_pipeline_plugin_chunk_report.py`
- Test: `tests/test_pipeline_plugin_closed_loop_docs.py`
- Docs: `docs/guides/pipeline_plugins.md`

**Step 1: Keep `chunk-report` generic but add readiness status**

Extend the existing report builder so it can emit a generic readiness block:

```json
{
  "readiness": {
    "status": "passed",
    "checks": [
      {"name": "governance_records_present", "passed": true},
      {"name": "chunks_present", "passed": true},
      {"name": "metadata_fields_present", "passed": true},
      {"name": "kg_events_present", "passed": true}
    ]
  }
}
```

The checks must be structural and plugin-neutral. Do not require Changzhou section names.

**Step 2: Add tests with a fake plugin**

Use a synthetic plugin fixture that has custom metadata fields unrelated to government data. Assert readiness works without platform changes.

**Step 3: Verify plugin report paths**

Run:

```bash
pytest tests/test_pipeline_plugin_chunk_report.py tests/test_pipeline_plugin_chunk_report_api.py tests/test_pipeline_plugin_closed_loop_docs.py -q
```

Expected: pass.

### Task 5: Connect Golden/Regression Evidence To Retrieval Audit

**Files:**
- Modify: `app/rag/evaluation/regression_sample_builder.py`
- Modify if needed: `app/rag/evaluation/ragas.py`
- Modify: `app/services/report_service.py`
- Test: `tests/test_regression_sample_evaluation_signals.py`
- Test: `tests/test_regression_run_metrics.py`
- Test: `tests/test_ragas_regression_summary_metrics.py`
- Test: `tests/test_reports_dataset_report.py`

**Step 1: Confirm expected metadata metrics are persisted**

Use existing tests to verify these fields remain available in regression summaries:

- `expected_metadata_hit_rate`
- `expected_metadata_recall`
- `expected_metadata_cases_total`
- `expected_metadata_fields_total`
- `expected_metadata_fields_matched`
- `retrieval_effective_context_rate`
- `retrieval_noise_rate`

**Step 2: Map regression summary to failure categories**

In `report_service`, categorize failures without business knowledge:

- `scope`: expected metadata mismatch
- `chunking`: low effective context with correct hit
- `ranking`: `hit_at_3` passes but `hit_at_1` fails
- `absence`: recall fails
- `kg_noise`: KG noise exceeds threshold
- `adapter`: Dify gate missing while MimirQ direct gate passes, when that status is available

**Step 3: Add tests for category mapping**

Create small fake summaries and assert deterministic categories.

**Step 4: Run regression/report tests**

Run:

```bash
pytest tests/test_regression_sample_evaluation_signals.py tests/test_regression_run_metrics.py tests/test_ragas_regression_summary_metrics.py tests/test_reports_dataset_report.py -q
```

Expected: pass.

### Task 6: Make KG Enablement A Dataset/Plugin Decision

**Files:**
- Modify: `app/rag/retrieval/planner.py`
- Modify: `app/api/v1/integrations_dify.py`
- Modify: `app/services/report_service.py`
- Test: `tests/test_retrieval_planner.py`
- Test: `tests/test_changzhou_gov_golden_eval.py`
- Test: `tests/test_changzhou_gov_dify_readiness_summary.py`
- Docs: `docs/deployment/changzhou_dify_readiness_runbook.md`

**Step 1: Keep KG default-off unless proven**

Confirm default behavior remains:

- KG query expansion off unless configured.
- KG chunk injection off unless configured.
- KG boost off unless configured.

**Step 2: Surface KG proof in retrieval audit**

When a saved KG compare exists in persisted readiness data or regression metadata, show:

- baseline gate status
- candidate gate status
- compared metric count
- `kg_noise_rate`
- regressions
- recommendation: enable none, query expansion only, boost only, or full KG assist

**Step 3: Verify KG diagnostics**

Run:

```bash
pytest tests/test_retrieval_planner.py tests/test_changzhou_gov_golden_eval.py tests/test_changzhou_gov_dify_readiness_summary.py -q
```

Expected: pass.

### Task 7: Add Frontend Retrieval Audit Surface To Existing Reports Page

**Files:**
- Modify: `web/types/datasets.ts`
- Modify: `web/app/reports/page-client.tsx`
- Modify: `web/lib/api/reports.ts` only if response typing requires it
- Test: `web/app/reports/page.real-data.source.test.ts`
- Test: `web/lib/api-client-management-surfaces.test.ts`

**Step 1: Extend TypeScript report types**

Add `retrieval_audit` to the dataset report type with the same generic fields as the backend schema.

**Step 2: Add a compact audit card**

Place the card near existing regression/governance report sections. It should show:

- status
- latest retrieval metrics
- gate failures
- plugin package hash short values
- next action

Do not show raw chunks by default. Link users to evaluation/regression detail for deeper evidence.

**Step 3: Add source tests**

Assert the page reads `report.retrieval_audit`, displays status, and does not depend on Changzhou-specific labels.

**Step 4: Run frontend tests**

Run:

```bash
pnpm --dir web vitest run web/app/reports/page.real-data.source.test.ts web/lib/api-client-management-surfaces.test.ts
pnpm --dir web run typecheck
```

Expected: pass.

### Task 8: Add A Generic Plugin Release Gate Command

**Files:**
- Modify: `Makefile`
- Create: `scripts/plugin_release_gate.py`
- Test: `tests/test_plugin_release_gate.py`
- Docs: `docs/guides/pipeline_plugins.md`

**Step 1: Write a generic gate script**

The script should accept:

```bash
python scripts/plugin_release_gate.py \
  --plugin-dir plugins/pipelines/changzhou-gov-service-knowledge \
  --sample plugins/pipelines/changzhou-gov-service-knowledge/sample.json \
  --out /tmp/plugin_release_gate.json
```

It should run:

- plugin manifest validation
- local plugin runner test report hash check
- generic chunk report
- golden draft structural check when declared
- metadata schema validation
- retrieval policy schema validation

**Step 2: Add Makefile target**

Add:

```make
plugin-release-gate:
	python scripts/plugin_release_gate.py --plugin-dir "$(PLUGIN_DIR)" --sample "$(PLUGIN_SAMPLE)" --out "$(PLUGIN_RELEASE_GATE_OUT)"
```

Keep Changzhou targets as wrappers around the generic gate where possible.

**Step 3: Test with synthetic plugin data**

Write tests that use a temporary plugin with non-government metadata fields.

**Step 4: Run tests**

Run:

```bash
pytest tests/test_plugin_release_gate.py tests/test_pipeline_plugin_registry.py tests/test_pipeline_plugin_chunk_report.py -q
```

Expected: pass.

### Task 9: Update Dify Readiness To Consume Generic Audit

**Files:**
- Modify: `scripts/changzhou_gov_dify_readiness_summary.py`
- Modify: `docs/deployment/changzhou_dify_readiness_runbook.md`
- Test: `tests/test_changzhou_gov_dify_readiness_summary.py`
- Test: `tests/test_changzhou_gov_dify_readiness_status.py`

**Step 1: Preserve Changzhou-specific workflow checks**

Keep Changzhou Dify workflow checks as deployment scripts, not platform runtime logic.

**Step 2: Export a generic retrieval audit fragment**

Make the readiness summary include a sanitized `retrieval_audit` block compatible with `DatasetRetrievalAuditOut`. This lets the platform import or display the same gate evidence later.

**Step 3: Verify status output**

Run:

```bash
pytest tests/test_changzhou_gov_dify_readiness_summary.py tests/test_changzhou_gov_dify_readiness_status.py -q
```

Expected: pass.

### Task 10: End-To-End Verification

**Files:**
- No new files unless previous tasks require fixes.

**Step 1: Run focused backend test group**

Run:

```bash
pytest \
  tests/test_pipeline_plugin_boundary.py \
  tests/test_retrieval_plugin_policy.py \
  tests/test_pipeline_plugin_chunk_report.py \
  tests/test_pipeline_plugin_chunk_report_api.py \
  tests/test_regression_run_metrics.py \
  tests/test_reports_dataset_report.py \
  tests/test_changzhou_gov_golden_eval.py \
  -q
```

Expected: pass.

**Step 2: Run plugin sample gates**

Run:

```bash
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-chunk-report
```

Expected: plugin executable report and chunk report are regenerated successfully.

**Step 3: Run direct retrieval gate against local backend**

Run only when backend `8000` is running:

```bash
make changzhou-dify-mimirq-direct-gate CHANGZHOU_DIFY_MIMIRQ_BASE_URL=http://127.0.0.1:8000
```

Expected: gate passes the configured quality profile. If it fails, inspect failure categories before changing plugin rules.

**Step 4: Run frontend checks**

Run:

```bash
pnpm --dir web run typecheck
pnpm --dir web vitest run web/app/reports/page.real-data.source.test.ts web/lib/api-client-management-surfaces.test.ts
```

Expected: pass.

**Step 5: Commit with Lore protocol**

Use a decision-oriented commit message:

```text
Make retrieval readiness visible as platform evidence

The platform already had plugin reports, regression metrics, and Dify readiness
scripts, but operators had to stitch those artifacts together manually. This
adds a generic retrieval audit snapshot to dataset reports so plugin quality,
retrieval quality, KG proof, and integration readiness can be reviewed without
specializing platform runtime code.

Constraint: Business-specific rules must stay inside plugin packages and deployment scripts.
Rejected: Add Changzhou-specific report fields | would make future business plugins depend on government metadata.
Confidence: medium
Scope-risk: moderate
Directive: Do not add business terms to platform report schemas; expose plugin metadata through generic maps and gate metrics.
Tested: <commands run>
Not-tested: <gaps>
```

## Rollout Order

1. Boundary tests first, because they protect the platform from drifting into business code.
2. Backend retrieval audit schema and report service, because frontend and Dify evidence need a stable contract.
3. HTML/report UI, because operators need the audit in the product.
4. Generic plugin release gate, because future business packages need the same process.
5. KG/Dify readiness integration, because those are deployment gates and should consume the generic audit instead of defining platform behavior.

## Completion Definition

This design optimization is complete when a new plugin can be tested, reported, indexed, retrieved, and audited through generic MimirQ contracts, and the operator can answer these questions from the dataset report without reading scripts or raw `/tmp` artifacts:

- Which plugin package and hash produced the retrieval assets?
- What records, chunks, metadata fields, and KG events were produced?
- Did golden retrieval hit answer-bearing chunks?
- Did metadata scope match the expected business scope?
- Did KG help without adding noise?
- Is Dify receiving the same evidence that native MimirQ retrieval would return?
- If readiness failed, is the failure scope, chunking, ranking, KG, content absence, or adapter binding?
