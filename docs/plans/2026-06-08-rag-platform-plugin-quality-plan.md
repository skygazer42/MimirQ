# RAG Platform And Plugin Quality Plan

## Goal

Keep MimirQ as a generic RAG platform while allowing each business package to
ship its own governance, chunking, metadata, KG, retrieval policy, and golden
evaluation rules. The platform should improve retrieval quality by consuming
standard plugin contracts, not by embedding Changzhou government service
shortcuts in core code or Dify adapters.

## Current Evidence

- `docs/guides/pipeline_plugins.md:3` defines plugins as governance, chunking,
  and KG packages where domain rules live outside backend application code.
- `docs/guides/pipeline_plugins.md:35` states one complex business package should
  normally be one plugin, not one plugin per region or file type.
- `app/rag/pipeline_plugins/registry.py:50` keeps manifest top-level fields
  closed and generic: `metadata_schema`, `retrieval_text_schema`,
  `golden_rules`, `retrieval_policy`, `processing_templates`, and entries.
- `app/rag/pipeline_plugins/contracts.py:157` validates declared metadata schema
  without learning business field meanings.
- `app/rag/pipeline_plugins/contracts.py:598` validates retrieval policy fields
  against plugin metadata schema.
- `app/rag/retrieval/planner.py:196` already has generic policy scoring helpers
  for boost fields, anchor mismatch, rerank features, and fallback multiplier.
- The current business plugin manifest declares one package with metadata,
  retrieval text, retrieval policy, golden rules, governance, chunk, and KG
  entries.
- The current business plugin retrieval policy declares plugin-owned retrieval
  hints without dataset IDs or Dify workflow logic.
- `scripts/changzhou_gov_golden_eval.py:62` defines a named
  `changzhou-retrieval` quality profile with hit-rate, grounding, key-point,
  metadata, and noise thresholds.

## Design Principles

1. Platform owns contracts and execution. It validates plugin packages, runs
   governance/chunk/KG stages, indexes chunks, runs retrieval, applies rerank,
   exposes diagnostics, and gates quality.
2. Plugins own business semantics. Fields such as district, department, service
   name, aliases, materials, and FAQ intent belong in plugin metadata and plugin
   code.
3. Chunking is answer-unit first. Token windows are fallback mechanics; business
   chunks should be built around records that can answer one user intent with
   minimal unrelated context.
4. KG assists retrieval but does not bypass RAG. KG may provide aliases, entity
   anchors, relation hints, and explainable boosts; final evidence must still be
   retrieved chunks.
5. Dify is an adapter, not a policy engine. It should translate external payloads
   to platform retrieval inputs and return evidence. Ranking policy should live
   in the platform retrieval layer.
6. Evaluation is part of ingestion readiness. A plugin is not production-ready
   because it can run; it is ready only when chunk reports and golden retrieval
   gates prove effective evidence, low noise, and acceptable latency.

## Acceptance Criteria

- Platform code does not contain Changzhou-specific terms except in explicitly
  allowed tests, scripts, docs, and plugin package paths.
- A business plugin can define new metadata fields without changing platform
  schemas or Dify adapter code.
- Retrieval policy application is shared by native retrieval and Dify external
  knowledge flows; no policy scoring remains as Dify-only logic.
- Plugin chunk reports show, per knowledge section, governed record count, chunk
  count, KG event count, chunk kinds, metadata fields, and representative
  examples before production ingestion.
- Changzhou golden gates keep `hit_at_1 >= 0.95`, `hit_at_3 >= 0.98`,
  `answer_key_point_recall = 1.0`, `retrieval_effective_context_rate >= 0.9`,
  `expected_metadata_case_rate = 1.0`, and `retrieval_noise_rate <= 0.1`.
- KG hints are disabled by default unless a plugin golden gate proves they
  improve or preserve retrieval quality and latency.

## Implementation Plan

### Phase 1: Freeze Platform/Plugin Boundary

Strengthen the existing boundary tests so platform packages cannot introduce
business-specific defaults or metadata strings. Keep contract constants such as
`METADATA_SCHEMA_VIEW_KEYS` and `RESERVED_PLATFORM_METADATA_VIEW_KEYS` as the
single source for platform-owned metadata views.

Files:
- `app/rag/pipeline_plugins/contracts.py`
- `tests/test_pipeline_plugin_boundary.py`
- `tests/test_pipeline_plugin_registry.py`
- `docs/guides/pipeline_plugins.md`

Verification:
- `pytest tests/test_pipeline_plugin_boundary.py tests/test_pipeline_plugin_registry.py -q`
- `ruff check app/rag/pipeline_plugins/contracts.py tests/test_pipeline_plugin_boundary.py tests/test_pipeline_plugin_registry.py`

### Phase 2: Move Retrieval Policy Out Of Dify Adapter

Extract the Dify-only policy scoring path into a platform retrieval policy
service, likely under `app/rag/retrieval/`. Dify should resolve plugin refs and
pass policies or policy refs into the shared retrieval path; native API
retrieval, Dify external knowledge, and future integrations should receive the
same boost, anchor, rerank-feature, and fallback behavior.

Files:
- `app/rag/retrieval/planner.py`
- New: `app/rag/retrieval/plugin_policy.py` or equivalent
- `app/api/v1/integrations_dify.py`
- `tests/test_retrieval_planner.py`
- `tests/test_dify_external_knowledge_adapter.py`

Verification:
- Dify adapter tests prove it delegates to platform retrieval policy helpers.
- Native retrieval tests prove the same policy signals are available outside
  Dify.
- `pytest tests/test_retrieval_planner.py tests/test_dify_external_knowledge_adapter.py -q`

Status 2026-06-08:
- Added `app/rag/retrieval/plugin_policy.py` as the shared record-level policy
  application layer for boost, query expansion, rerank feature, anchor mismatch,
  score bonus, and diagnostics.
- Dify external knowledge now delegates record policy scoring and diagnostics to
  the shared module.
- Native `HybridRetriever` now preserves plugin provenance metadata on BM25
  candidates and applies the same shared policy module after result fusion, with
  diagnostics under retriever channel metrics.

### Phase 3: Make Chunk Quality Visible Before Ingestion

Promote the existing Changzhou chunk report from a local script-only artifact
into a reusable plugin inspection workflow. The operator should see how each
knowledge section is governed, chunked, and converted into KG events before
running full ingestion.

Files:
- `scripts/changzhou_gov_plugin_chunk_report.py`
- `app/api/v1/pipeline.py`
- Frontend chunk preview or ingestion inspection surfaces
- `tests/test_changzhou_gov_plugin_chunk_report.py`

Verification:
- Script report covers all configured sample sections.
- UI/API exposes section-level chunk examples without leaking platform reserved
  metadata views.
- `pytest tests/test_changzhou_gov_plugin_chunk_report.py -q`

Status 2026-06-08:
- Added `app/rag/pipeline_plugins/reports.py` as a generic plugin chunk
  inspection builder. It runs governance, chunk, and optional KG stages from a
  plugin package, summarizes section counts, hides platform reserved metadata
  views, records metadata fields, captures chunk examples, and lists KG entity
  types without embedding business field meanings.
- The existing business chunk report script now delegates stage execution and
  generic aggregation to the platform builder while retaining only its report
  schema, default paths, title fields, highlight fields, and compatibility field
  mapping.
- Added generic tests proving an arbitrary plugin can produce a section-level
  report and that reserved platform metadata views do not leak into metadata
  fields or examples.
- Added `POST /api/v1/pipeline/plugins/chunk-report` so authenticated callers
  can build the same review-only report from a registered plugin sample. The
  endpoint accepts a registered chunk plugin ref and a sample JSON path scoped
  to the plugin directory instead of arbitrary host paths.
- Wired the chunk preview Python plugin panel to the chunk-report endpoint. The
  UI can now generate a sample-based pre-ingestion report for the selected
  chunk plugin and display governed record, chunk, KG-event, and section
  summaries without dumping raw JSON into the sidebar.
- Regenerated frontend OpenAPI artifacts so the new endpoint is represented in
  `web/openapi.json` and `web/types/openapi.ts`.

### Phase 4: Expand Golden Coverage By Knowledge Section

Treat the Changzhou knowledge package as one business plugin but verify each
section independently: service items, one-thing guides, city FAQ, topic FAQ,
department FAQ, district FAQ, regulations, and table-like source files. Every
case should declare expected metadata so misses can be attributed to scope,
chunking, ranking, or content absence.

Files:
- Business plugin `golden_eval_cases.json`
- Business plugin `golden_rules.json`
- `scripts/changzhou_gov_golden_eval.py`
- `tests/test_changzhou_gov_golden_eval.py`

Verification:
- Saved-report gate can fail old bad reports without rerunning retrieval.
- Live gate passes the named `changzhou-retrieval` quality profile.
- `pytest tests/test_changzhou_gov_golden_eval.py -q`
- `make changzhou-dify-mimirq-direct-gate`

Status 2026-06-08:
- The named retrieval profile now requires every golden case to carry expected
  metadata and `knowledge_section`, so misses can be traced to a concrete
  plugin-owned scope rather than only to title/content matching.
- The profile defines the required section set for the business package and
  gates `required_section_coverage_rate = 1.0` plus
  `section_expected_metadata_case_rate = 1.0`.
- Current golden cases cover all six required sections: service items,
  one-thing guides, city FAQ, topic FAQ, department FAQ, and district FAQ.
- Saved-report mode can re-run the quality gate without a token, which makes old
  or regressed reports fail fast in readiness automation.

### Phase 5: Gate KG As Retrieval Hints

Keep KG opt-in until measured. Add diagnostics that show when KG expanded query
terms, matched entity anchors, boosted relation-neighborhood evidence, or
introduced noise. Enable KG only when the golden gate proves no drop in effective
context, metadata match, or latency.

Files:
- `app/rag/retrieval/planner.py`
- KG integration modules under `app/rag/kg/`
- `tests/test_citations_include_kg_path.py`
- Changzhou readiness scripts under `scripts/changzhou_gov_*`

Verification:
- Golden eval can run with KG off and KG on and compare metrics.
- KG-on must not reduce the quality profile below thresholds.
- Diagnostics include policy/KG contribution counts.

Status 2026-06-08:
- Added a generic platform KG hint diagnostic helper that summarizes KG-query
  expansion records, KG candidate records, entity-anchor matches,
  relation-neighborhood evidence, KG score-bearing records, retrieval-role
  counts, and expected-scope noise from stable expected metadata or, when
  available, expected chunk/document ids.
- The golden retrieval report now includes per-case KG hint diagnostics and
  summary-level KG counts, so KG-on runs can be compared against KG-off runs
  without reading raw retrieval traces.
- The named retrieval profile now gates `kg_noise_rate <= 0.1`. Current golden
  cases all carry expected metadata, so KG candidates can be checked against
  plugin-owned scope even when ingestion-generated ids are unstable.
- Golden eval now has a saved-report comparison mode:
  `--baseline-report <kg-off.json> --candidate-report <kg-on.json>`. The
  candidate report must pass the selected quality profile and must not regress
  baseline hit, grounding, effective-context, or metadata-match metrics. KG
  noise remains an absolute candidate gate rather than being compared against a
  KG-off zero baseline.
- KG hints should still remain opt-in until a real KG-on run proves the same
  quality profile passes with acceptable latency.

### Phase 6: Production Readiness Gate

Make readiness a repeatable command path: plugin package hash, local plugin test
report, chunk report, golden retrieval gate, Dify knowledge-map preflight, and
remote Dify probe all produce machine-readable artifacts.

Files:
- `Makefile`
- `scripts/changzhou_gov_dify_full_gate.py`
- `scripts/changzhou_gov_dify_knowledge_map_check.py`
- `scripts/changzhou_gov_dify_readiness_status.py`
- `docs/deployment/changzhou_dify_readiness_runbook.md`

Verification:
- A single readiness command fails with actionable reasons.
- Artifacts include plugin refs, package hash, dataset scope, topK budget,
  policy signals, KG signals, latency, and quality metrics.
- KG-on readiness can consume the golden comparison report as an artifact
  instead of duplicating regression logic in readiness scripts.

Status 2026-06-08:
- Added a `changzhou-dify-kg-compare-gate` Make target that wraps the golden
  saved-report comparison mode and writes a reusable comparison artifact.
- Added request-level KG overrides to the MimirQ Dify adapter via optional
  retrieval setting fields. Standard Dify payloads can omit them; direct gates
  can force KG-off/KG-on without changing process environment.
- Added `--kg-mode default|off|on` to the Changzhou live golden evaluator and
  `changzhou-dify-kg-on-off-gate` to generate KG-off/KG-on direct reports before
  running the saved-report comparison.
- Moved section-intent fallback out of the Dify adapter and into generic
  `retrieval_policy.query_expansion_values`, so business packages can map their
  own metadata values to query terms without platform code changes.
- Extended plugin contract validation and API summaries for
  `query_expansion_values`: referenced metadata fields must be declared in
  `metadata_schema` and available at chunk stage, and plugin summaries expose
  `query_expansion_value_fields`.
- Readiness summary accepts an optional `kg_compare` artifact. When present, it
  becomes a first-class stage after direct MimirQ retrieval and before remote
  Dify stages; failures block downstream stages with actionable root-cause
  conditions such as `quality_gate_failed:kg_noise_rate` or
  `metric_regressed:hit_at_1`.
- Readiness status and Markdown evidence now display KG comparison status,
  candidate-gate result, compared metric count, and `kg_noise_rate`.

## ADR

Decision: Use plugin contracts as the only extension mechanism for business RAG
behavior, and move retrieval policy consumption into shared platform retrieval.

Drivers:
- Avoid turning MimirQ into a Changzhou-specific system.
- Keep Dify workflows stable while still exposing MimirQ's retrieval advantage.
- Make retrieval quality measurable before production ingestion.
- Support future business packages with different metadata schemas.

Alternatives considered:
- Put fast paths in Dify adapter. Rejected because it bypasses RAG, hides
  ranking problems, and cannot generalize to other integrations.
- Create one plugin per section or district. Rejected because the knowledge
  package is one business domain with shared metadata and retrieval policy.
- Depend on fixed token chunking. Rejected because it creates noisy context for
  structured service records and FAQ data.

Consequences:
- Plugin authors must maintain metadata schema, retrieval policy, and golden
  cases as first-class delivery artifacts.
- Platform retrieval needs one more shared policy application layer.
- Quality gates become stricter, but failures will be diagnosable by section,
  metadata scope, and retrieval stage.

Follow-ups:
- Implement Phase 2 first; it removes the largest remaining architecture smell.
- Then expose chunk reports in the operator workflow so chunk design can be
  reviewed visually before ingestion.
- Finally expand section-level golden cases and gate KG-on behavior separately.
