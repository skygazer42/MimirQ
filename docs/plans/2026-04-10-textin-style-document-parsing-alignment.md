# TextIn-Style Document Parsing Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Align MimirQ's document parsing stack toward TextIn-style document understanding by adding a normalized element layer, structured seal/signature signals, extraction-oriented APIs, richer workbench visualization, and seal-aware quality/reparse loops without replacing the current multi-parser architecture.

**Architecture:** Keep the current `parser_factory -> processor -> quality -> workspace/retrieval` pipeline intact, but introduce a stable "document elements" contract between parser output and downstream consumers. Normalize parser/enrichment artifacts into `elements[]`, thread that contract through parse APIs and UI, then use the same data to drive quality scoring, extraction, comparison, and benchmark/regression gates.

**Tech Stack:** FastAPI, Pydantic, LangChain `Document`, existing parsing processors and enrichers, React/Next.js, Zod, Vitest, Pytest, current parser benchmark and parse-risk tooling.

---

## Requirements Summary

- Preserve existing parser diversity and routing instead of swapping to a single external engine.
- Make parser output structurally richer and more stable for seals, formulas, tables, images, headings, and future specialty detectors.
- Promote seal handling from "best-effort extra chunk" to a first-class parse element with multiple candidates, bbox metadata, and quality signals.
- Surface element data in the parsing workbench so operators can inspect and verify parse results visually.
- Add extraction-oriented APIs so downstream workflows can request JSON outputs with evidence locations instead of only markdown.
- Feed new parsing signals into parse quality, dataset health, and repair/reparse workflows.

## Non-Goals

- Do not replace all existing parsers with a TextIn API dependency.
- Do not attempt full contract review/business rule automation in the first pass.
- Do not redesign the entire parsing UI before the normalized backend contract exists.

## Existing Anchors

- Parsing workspace API and preview quality gate already exist in [app/api/v1/parsing.py](../../app/api/v1/parsing.py).
- Parse quality scoring currently combines `pdf_quality` and `parsed_text_quality` in [app/parsing/quality/document_quality.py](../../app/parsing/quality/document_quality.py).
- Seal enrichment currently runs as a DeepDoc-only best-effort append path in [app/parsing/enrich/seal_recognition.py](../../app/parsing/enrich/seal_recognition.py) and [app/parsing/parsers/deepdoc_parser.py](../../app/parsing/parsers/deepdoc_parser.py).
- Document health and dataset profile already expose parse quality and parser routing hints in [app/api/schemas/document_health.py](../../app/api/schemas/document_health.py), [app/api/v1/documents.py](../../app/api/v1/documents.py), and [app/services/dataset_profile_service.py](../../app/services/dataset_profile_service.py).
- The parsing workbench already supports bbox overlays, A/B compare, and run state in [web/components/parsing/bbox-overlay.tsx](../../web/components/parsing/bbox-overlay.tsx), [web/components/parsing/parse-compare-dialog.tsx](../../web/components/parsing/parse-compare-dialog.tsx), [web/components/parsing/parsing-active-file-pane.tsx](../../web/components/parsing/parsing-active-file-pane.tsx), and [web/lib/api/parsing.ts](../../web/lib/api/parsing.ts).
- Parse-risk diagnostics, repair scheduling, and benchmark docs already exist in [docs/guides/parse_quality_retrieval_diagnostics.md](../guides/parse_quality_retrieval_diagnostics.md) and [docs/guides/parser_benchmark.md](../guides/parser_benchmark.md).

## Acceptance Criteria

- `POST /api/v1/parsing/documents/{id}/parse` and workspace content APIs return a stable `elements` payload with at least `paragraph`, `heading`, `table`, `image`, `equation`, and `seal` kinds when available.
- Seal parsing supports multiple candidates per page, stable bbox payloads, and explicit confidence metadata instead of only one appended text chunk.
- Document health, parse quality, and dataset profile expose seal-sensitive signals and can identify low-confidence signed documents.
- The parsing workbench can filter/highlight normalized elements and visually inspect seal/equation/table regions on top of the PDF.
- A new extraction workflow can return JSON data plus evidence page/bbox references derived from normalized elements.
- Benchmark/CI artifacts cover at least one seal-heavy, one table-heavy, and one formula-heavy fixture and can detect regressions.

## Delivery Order

- `P0`: normalized element contract, structured seals, seal-aware quality, workbench overlays
- `P1`: extraction API, element-aware compare UI, parse-repair integration
- `P2`: preprocessing upgrades and specialty enrichers (handwriting/noise cleanup, chart/QR/barcode, stronger cross-page structure)

## Task 1: Introduce a normalized document-elements contract (`P0`)

**Files:**
- Create: `app/parsing/utils/document_elements.py`
- Modify: `app/parsing/processors/processor.py:785-838`
- Modify: `app/api/v1/parsing.py:81-110,185-239`
- Modify: `web/lib/api/parsing.ts:7-80`
- Test: `tests/test_parsing_document_elements.py`

**Step 1: Write the failing backend contract test**

```python
def test_normalize_document_elements_emits_stable_kinds_and_bbox():
    docs = [
        Document(page_content="Title", metadata={"doc_type_kwd": "heading", "page": 1}),
        Document(page_content="印章识别：甲方公章", metadata={"doc_type_kwd": "seal", "page": 2, "seal_bbox": {"x0": 10, "y0": 20, "x1": 40, "y1": 60}}),
    ]

    out = normalize_document_elements(docs)

    assert [item["kind"] for item in out] == ["heading", "seal"]
    assert out[1]["page"] == 2
    assert out[1]["bbox"]["x0"] == 10
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parsing_document_elements.py`

Expected: `ImportError` or missing `elements` contract failure.

**Step 3: Implement the normalized contract**

- Add a utility that maps existing `Document.metadata` into a stable payload:

```python
{
    "id": "...",
    "kind": "seal",
    "page": 2,
    "text": "甲方公章",
    "bbox": {"x0": 10, "y0": 20, "x1": 40, "y1": 60},
    "confidence": 0.97,
    "attributes": {...},
}
```

- Start with these kinds only: `heading`, `paragraph`, `list`, `table`, `image`, `equation`, `seal`, `unknown`.
- Thread `elements` through parsing responses without breaking the current `markdown_content` contract.

**Step 4: Wire the API types**

- Extend [app/api/v1/parsing.py](../../app/api/v1/parsing.py) response models with `elements`.
- Extend [web/lib/api/parsing.ts](../../web/lib/api/parsing.ts) Zod schemas and TypeScript interfaces to parse the new shape safely.

**Step 5: Re-run tests**

Run: `pytest -q tests/test_parsing_document_elements.py`

Expected: PASS.

**Step 6: Commit**

Use Lore protocol:

```bash
git add app/parsing/utils/document_elements.py app/parsing/processors/processor.py app/api/v1/parsing.py web/lib/api/parsing.ts tests/test_parsing_document_elements.py
git commit
```

Intent line example:

```text
Establish a stable parse-elements contract for downstream parsing workflows
```

## Task 2: Promote seal parsing from extra chunk to structured seal objects (`P0`)

**Files:**
- Modify: `app/parsing/enrich/seal_recognition.py:24-39,157-216,219-326`
- Modify: `app/parsing/parsers/deepdoc_parser.py:233-250`
- Create: `tests/test_seal_recognition_structured_output.py`
- Modify: `tests/test_deepdoc_seal_recognition.py`
- Modify: `tests/test_seal_recognition_detector.py`

**Step 1: Write failing tests for multi-candidate seal output**

```python
def test_extract_seal_documents_from_pdf_emits_candidates_and_primary_result():
    docs = extract_seal_documents_from_pdf(...)
    seal_doc = docs[0]
    assert seal_doc.metadata["doc_type_kwd"] == "seal"
    assert len(seal_doc.metadata["seal_candidates"]) == 2
    assert seal_doc.metadata["seal_primary"]["text"] == "杭州测试科技有限公司"
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_deepdoc_seal_recognition.py tests/test_seal_recognition_detector.py tests/test_seal_recognition_structured_output.py`

Expected: missing `seal_candidates` / `seal_primary` / multi-region behavior.

**Step 3: Implement structured seal metadata**

- Keep the current best result for backward compatibility.
- Add:
  - `seal_candidates: list[dict]`
  - `seal_primary: dict`
  - `seal_kind` (`round_stamp`, `oval_stamp`, `seam_stamp`, `unknown`)
  - `seal_page_index`
  - `seal_bbox_list`
- Return all kept regions instead of only one result.

**Step 4: Preserve backward compatibility**

- Continue emitting `seal_text`, `seal_score`, and `seal_bbox` for existing consumers.
- Keep `page_content` concise (`印章识别：...`) so current chunking/retrieval behavior remains deterministic.

**Step 5: Re-run tests**

Run: `pytest -q tests/test_deepdoc_seal_recognition.py tests/test_seal_recognition_detector.py tests/test_seal_recognition_structured_output.py`

Expected: PASS.

**Step 6: Commit**

Intent line example:

```text
Preserve seal provenance as structured parse metadata instead of a single best-effort hit
```

## Task 3: Add seal-aware parse quality, document health, and dataset-profile signals (`P0`)

**Files:**
- Modify: `app/parsing/quality/document_quality.py:34-93`
- Modify: `app/parsing/processors/processor.py:807-838`
- Modify: `app/api/schemas/document_health.py:16-25`
- Modify: `app/api/v1/documents.py:5139-5155`
- Modify: `app/services/dataset_profile_service.py:97-100,1260-1263`
- Test: `tests/test_document_parse_quality.py`
- Create: `tests/test_document_health_api_seal_signals.py`
- Create: `tests/test_dataset_profile_seal_risk.py`

**Step 1: Write failing quality tests**

```python
def test_score_document_parse_quality_penalizes_low_confidence_seal_document():
    out = score_document_parse_quality(
        pdf_quality={"score": 0.91},
        parsed_text_quality={"density": 0.8, "replacement_ratio": 0.0},
        specialty_signals={"seal_expected": True, "seal_confidence": 0.22},
    )
    assert out["score"] < 0.7
    assert "seal_confidence" in out["components"]
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_document_parse_quality.py tests/test_document_health_api_seal_signals.py tests/test_dataset_profile_seal_risk.py`

Expected: unsupported signature / missing seal fields.

**Step 3: Implement specialty parse signals**

- Extend parse quality scoring with an optional `specialty_signals` payload.
- Persist at least:
  - `seal_confidence`
  - `seal_detected`
  - `seal_expected`
  - `seal_candidate_count`
- Expose a small `seal_summary` object in document health and document detail parsing metadata.

**Step 4: Add dataset-profile finding buckets**

- Add a new low-signal bucket such as `seal_low_confidence` or `signed_doc_needs_review`.
- Keep the label/operator experience consistent with the existing `parse_low_quality` bucket.

**Step 5: Re-run tests**

Run: `pytest -q tests/test_document_parse_quality.py tests/test_document_health_api_seal_signals.py tests/test_dataset_profile_seal_risk.py`

Expected: PASS.

**Step 6: Commit**

Intent line example:

```text
Make signed-document parse quality observable and actionable
```

## Task 4: Expose normalized elements and specialty overlays in the parsing workbench (`P0`)

**Files:**
- Modify: `web/components/parsing/parsing-types.ts:7-16,32-55`
- Modify: `web/components/parsing/parsing-active-file-pane.tsx:95-124,159-320`
- Modify: `web/components/parsing/bbox-overlay.tsx:14-80`
- Modify: `web/components/parsing/parsing-right-panel.tsx`
- Create: `web/components/parsing/parsing-elements-sidebar.tsx`
- Test: `web/components/parsing/parsing-active-file-pane.behavior.test.ts`
- Create: `web/components/parsing/parsing-elements-sidebar.source.test.ts`
- Modify: `web/components/parsing/pdf-viewer.source.test.ts`

**Step 1: Write failing UI tests**

```ts
it('renders seal and equation element groups with overlay toggles', () => {
  // render active file pane with elements payload
  expect(screen.getByText('印章')).toBeInTheDocument()
  expect(screen.getByText('公式')).toBeInTheDocument()
})
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd web
pnpm vitest run components/parsing/parsing-active-file-pane.behavior.test.ts components/parsing/pdf-viewer.source.test.ts components/parsing/parsing-elements-sidebar.source.test.ts
```

Expected: missing element filters/sidebar/overlay labels.

**Step 3: Implement element-aware workbench state**

- Add `elements` to `ParseRun` and `ParsedFile`.
- Add sidebar/grouping by `kind`.
- Extend `bbox-overlay` rendering so `seal` and `equation` get distinct visual treatments.
- Keep current block navigation intact; do not regress `buildParsingLayoutEntries(...)`.

**Step 4: Make the evidence human-reviewable**

- Show a compact inspector row for a selected element:
  - `kind`
  - `page`
  - `confidence`
  - `bbox`
  - specialty summary (`seal_text`, `equation_latex`, etc.)

**Step 5: Re-run tests**

Run:

```bash
cd web
pnpm vitest run components/parsing/parsing-active-file-pane.behavior.test.ts components/parsing/pdf-viewer.source.test.ts components/parsing/parsing-elements-sidebar.source.test.ts
```

Expected: PASS.

**Step 6: Commit**

Intent line example:

```text
Make structured parsing elements reviewable inside the workspace
```

## Task 5: Make parser strategy and parse-repair planning specialty-aware (`P1`)

**Files:**
- Modify: `app/services/parser_strategy_policy.py:81-173`
- Modify: `scripts/plan_parse_quality_reparse.py`
- Modify: `app/rag/retrieval/orchestrator.py` (parse-risk recommendation plumbing)
- Modify: `docs/guides/parse_quality_retrieval_diagnostics.md`
- Test: `tests/test_parser_strategy_policy.py`
- Modify: `tests/test_plan_parse_quality_reparse.py`
- Create: `tests/test_retrieval_parse_quality_seal_signals.py`

**Step 1: Write failing strategy tests**

```python
def test_recommend_parser_strategy_prefers_full_layout_when_signed_pdf_has_low_seal_confidence():
    out = recommend_parser_strategy({
        "mime_type": "application/pdf",
        "file_extension": "pdf",
        "page_count": 12,
        "ocr_ratio": 0.1,
        "image_ratio": 0.2,
        "seal_expected": True,
        "seal_confidence": 0.18,
    })
    assert out["strategy"] == "pdf_ocr_layout"
    assert "low_seal_confidence" in out["reason_codes"]
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_parser_strategy_policy.py tests/test_plan_parse_quality_reparse.py tests/test_retrieval_parse_quality_seal_signals.py`

Expected: no specialty-aware reason codes or repair scheduling.

**Step 3: Extend strategy input and repair signals**

- Add optional profile keys:
  - `seal_expected`
  - `seal_confidence`
  - `equation_density`
  - `image_noise_ratio`
- Update parse repair planning so low-confidence signed documents can be scheduled even when plain text density is acceptable.

**Step 4: Keep the rollout narrow**

- Do not block retrieval on specialty signals in the first commit.
- Start with `warn`/recommendation-only behavior, then promote to stronger gates once benchmark data is available.

**Step 5: Re-run tests**

Run: `pytest -q tests/test_parser_strategy_policy.py tests/test_plan_parse_quality_reparse.py tests/test_retrieval_parse_quality_seal_signals.py`

Expected: PASS.

**Step 6: Commit**

Intent line example:

```text
Teach parse-repair planning about specialty parsing failures instead of plain text loss only
```

## Task 6: Add extraction-first parsing APIs (`P1`)

**Files:**
- Create: `app/services/parsing_extract_service.py`
- Modify: `app/api/v1/parsing.py`
- Create: `tests/test_parsing_extract_service.py`
- Create: `tests/test_parsing_extract_api.py`
- Create: `docs/guides/parsing_extract.md`

**Step 1: Write failing extraction tests**

```python
def test_extract_endpoint_returns_json_with_evidence_boxes(client):
    res = client.post(
        "/api/v1/parsing/documents/{id}/extract",
        json={"mode": "schema", "schema": {"company_name": {"type": "string"}}},
    )
    body = res.json()
    assert body["result"]["company_name"]["value"] == "杭州测试科技有限公司"
    assert body["result"]["company_name"]["evidence"][0]["page"] == 2
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_parsing_extract_service.py tests/test_parsing_extract_api.py`

Expected: route/service missing.

**Step 3: Implement a narrow extraction contract**

- Support two modes:
  - `schema`: caller provides field schema
  - `prompt`: caller provides prompt + optional field hints
- Use normalized `elements` plus markdown content as inputs.
- Return:

```json
{
  "result": {
    "company_name": {
      "value": "杭州测试科技有限公司",
      "confidence": 0.92,
      "evidence": [{"page": 2, "bbox": {...}, "element_id": "seal-1"}]
    }
  }
}
```

**Step 4: Document the contract**

- Add request/response examples and explicit non-goals in `docs/guides/parsing_extract.md`.
- Note that v1 is evidence-first and deterministic where possible; business-rule review stays out of scope.

**Step 5: Re-run tests**

Run: `pytest -q tests/test_parsing_extract_service.py tests/test_parsing_extract_api.py`

Expected: PASS.

**Step 6: Commit**

Intent line example:

```text
Expose parsing results as extraction-ready JSON with traceable evidence
```

## Task 7: Upgrade the parse compare workflow from raw diff to element-aware diff (`P1`)

**Files:**
- Create: `web/lib/parsing-element-diff.ts`
- Modify: `web/components/parsing/parse-compare-dialog.tsx:18-87,89-210`
- Create: `web/lib/parsing-element-diff.test.ts`
- Modify: `web/components/parsing/parsing-active-file-pane.source.test.ts`

**Step 1: Write failing compare tests**

```ts
it('summarizes added and removed seals separately from markdown diff', () => {
  const diff = diffParsingElements(baseRun, compareRun)
  expect(diff.addedByKind.seal).toBe(1)
  expect(diff.removedByKind.table).toBe(0)
})
```

**Step 2: Run tests to verify failure**

Run:

```bash
cd web
pnpm vitest run lib/parsing-element-diff.test.ts components/parsing/parsing-active-file-pane.source.test.ts
```

Expected: diff utility missing; dialog only shows raw patch text.

**Step 3: Implement element-aware summaries**

- Keep the raw patch textarea.
- Add a structured summary above it:
  - element counts by kind
  - added/removed/high-confidence-changed seals
  - changed table/equation/image counts
- Do not add backend persistence in this pass; keep it client-side.

**Step 4: Re-run tests**

Run:

```bash
cd web
pnpm vitest run lib/parsing-element-diff.test.ts components/parsing/parsing-active-file-pane.source.test.ts
```

Expected: PASS.

**Step 5: Commit**

Intent line example:

```text
Show parser run differences as document-structure changes instead of plain text only
```

## Task 8: Expand preprocessing and specialty enrichers behind a normalized contract (`P2`)

**Files:**
- Modify: `app/parsing/preprocess/image_preprocess.py`
- Modify: `app/parsing/preprocess/deskew.py`
- Modify: `app/parsing/preprocess/watermark.py`
- Create: `app/parsing/preprocess/handwriting_cleanup.py`
- Modify: `app/parsing/enrich/formula_ocr.py`
- Create: `tests/test_image_preprocess_handwriting_cleanup.py`
- Create: `tests/test_formula_elements.py`

**Step 1: Write failing preprocessing tests**

```python
def test_preprocess_pipeline_records_handwriting_cleanup_warning_when_model_unavailable():
    out = preprocess_image(...)
    assert "handwriting_cleanup_model_missing" in out.warnings
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_image_preprocess_handwriting_cleanup.py tests/test_formula_elements.py`

Expected: missing preprocessing stage / missing normalized formula element payload.

**Step 3: Add narrow preprocessing hooks**

- Keep all new preprocess steps feature-flagged.
- Record applied steps/warnings in metadata so benchmark/debug flows can explain quality changes.
- Normalize formula OCR output into `elements` instead of ad hoc text-only metadata.

**Step 4: Re-run tests**

Run: `pytest -q tests/test_image_preprocess_handwriting_cleanup.py tests/test_formula_elements.py`

Expected: PASS.

**Step 5: Commit**

Intent line example:

```text
Make image preprocessing and formula enrichment measurable specialty stages
```

## Task 9: Build a focused golden set and strict regression gate for TextIn-style capabilities (`P2`)

**Files:**
- Modify: `scripts/parser_benchmark.py`
- Modify: `docs/guides/parser_benchmark.md`
- Create: `tests/fixtures/parsing_golden/seal_invoice/`
- Create: `tests/fixtures/parsing_golden/formula_pdf/`
- Create: `tests/fixtures/parsing_golden/table_scan/`
- Modify: `ci/parser_benchmark_baseline.v1.json`
- Modify: `ci/parser_strict_profile.v1.json`
- Create: `tests/test_parser_benchmark_specialty_fixtures.py`

**Step 1: Write failing benchmark fixture test**

```python
def test_parser_benchmark_reports_specialty_element_counts(tmp_path):
    report = run_benchmark(...)
    assert report["summary"]["deepdoc"]["mean_seal_recall"] >= 0.0
    assert "specialty_elements" in report["cases"][0]["attempts"][0]
```

**Step 2: Run tests to verify failure**

Run: `pytest -q tests/test_parser_benchmark_specialty_fixtures.py`

Expected: specialty metrics missing.

**Step 3: Extend benchmark output**

- Track counts/coverage for `seal`, `equation`, `table`, and `image` elements when golden annotations exist.
- Keep missing annotation behavior best-effort and non-blocking.

**Step 4: Re-run tests**

Run: `pytest -q tests/test_parser_benchmark_specialty_fixtures.py`

Expected: PASS.

**Step 5: Commit**

Intent line example:

```text
Prevent specialty parsing regressions from hiding behind average markdown quality
```

## Verification Matrix

### Backend

Run:

```bash
pytest -q \
  tests/test_parsing_document_elements.py \
  tests/test_deepdoc_seal_recognition.py \
  tests/test_seal_recognition_detector.py \
  tests/test_seal_recognition_structured_output.py \
  tests/test_document_parse_quality.py \
  tests/test_document_health_api_seal_signals.py \
  tests/test_dataset_profile_seal_risk.py \
  tests/test_parser_strategy_policy.py \
  tests/test_plan_parse_quality_reparse.py \
  tests/test_retrieval_parse_quality_seal_signals.py \
  tests/test_parsing_extract_service.py \
  tests/test_parsing_extract_api.py \
  tests/test_image_preprocess_handwriting_cleanup.py \
  tests/test_formula_elements.py \
  tests/test_parser_benchmark_specialty_fixtures.py
```

Expected: all targeted parsing/specialty tests PASS.

### Frontend

Run:

```bash
cd web
pnpm vitest run \
  components/parsing/parsing-active-file-pane.behavior.test.ts \
  components/parsing/parsing-active-file-pane.source.test.ts \
  components/parsing/pdf-viewer.source.test.ts \
  components/parsing/parsing-elements-sidebar.source.test.ts \
  lib/parsing-element-diff.test.ts
pnpm typecheck
pnpm lint
```

Expected: all targeted workbench tests PASS; no TypeScript or lint errors.

### Contract / Docs

Run:

```bash
pnpm -C web run api-check
pytest -q tests/test_document_health_api.py
```

Expected: OpenAPI/client contract stays aligned; document health remains backward compatible.

## Risks and Mitigations

- **Risk:** normalized element schema grows too broad too early.
  - **Mitigation:** keep `kind` enum intentionally small in `P0`; add future kinds behind tests and feature flags.
- **Risk:** seal-aware quality penalties create false positives on non-signed PDFs.
  - **Mitigation:** require `seal_expected` or equivalent document-class hint before applying penalties.
- **Risk:** UI overlay work regresses current block navigation.
  - **Mitigation:** preserve existing `ParsingBlock` flow; layer `elements` alongside blocks instead of replacing them in the first pass.
- **Risk:** extraction API becomes an unbounded LLM wrapper.
  - **Mitigation:** keep v1 evidence-first, schema-constrained, and scoped to normalized parser outputs.
- **Risk:** specialty benchmarks become flaky.
  - **Mitigation:** use small static fixtures with deterministic golden annotations; keep CI thresholds narrow and explicit.

## Follow-up Notes

- If `P0` lands cleanly, the most valuable next execution lane is `Task 6` rather than more parser integrations.
- Do not introduce a new vendor dependency until the normalized element layer proves where current in-house gaps still remain.
- Every commit in this plan must follow the repo's Lore commit protocol.

