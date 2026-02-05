# RAG Quality Loop (Per-Dataset Regression + Evidence Sources) Implementation Plan (20 Tasks)

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 把现有回归评测（RAGAS）升级为“企业级可审计、可回归、可门禁”的 RAG 质量闭环：**按 dataset 管理评测集**、**每条用例强制证据来源**、**覆盖 unanswerable 拒答能力**、并把评测结果集成到 dataset health/report 与 CI gate。

**Architecture:** 以 FastAPI + SQLAlchemy 为主，在后端补齐回归用例的 evidence source 与导入/导出/更新接口；在 regression runner 中把 `expected_answer/reference_sources/citations/abstain` 统一写入 RAGAS dataset 与结果存储；前端补齐“按 dataset 管理用例 + 一键检索选证据 + 分桶指标展示”；最后把最新回归摘要落到 dataset health/report。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, RAGAS 0.4.1, Next.js 14 + TypeScript + Vitest.

**Constraints / Guardrails:**
- Corridor MCP 未配置：以人工安全审计替代（权限校验、最小暴露、失败显式返回）。
- 回归用例强制 `reference_sources[]`（至少 1 条）；每条 source 必须有 `document_id` + `chunk_id`。
- 回归运行强制 `dataset_id`（或校验 case_ids 同属一个 dataset）。
- `unanswerable` 用例以 `abstain_triggered` 派生指标做门禁，不以“答案文本相似度”作为主评判。

---

### Task 1: Add design doc (DONE)

**Files:**
- Added: `docs/plans/2026-02-05-rag-quality-loop-20-design.md`

**Commit:** already done.

---

### Task 2: Add this plan doc

**Files:**
- Create: `docs/plans/2026-02-05-rag-quality-loop-20.md`

**Commit:**
```bash
git add docs/plans/2026-02-05-rag-quality-loop-20.md
git commit -m "docs(plans): add RAG quality loop plan (20 tasks)"
```

---

### Task 3: Add ReferenceSource schema + enforce dataset_id + reference_sources in case create (TDD)

**Files:**
- Modify: `app/api/schemas/regression.py`
- Test: `tests/test_regression_case_reference_sources_schema.py`

**Step 1: Write failing tests**
```py
from uuid import uuid4
import pytest

from app.api.schemas.regression import RagasRegressionCaseCreateRequest

def test_case_create_requires_dataset_id():
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(question="q", dataset_id=None, reference_sources=[])

def test_case_create_requires_reference_sources():
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(question="q", dataset_id=uuid4(), reference_sources=[])

def test_reference_source_requires_doc_and_chunk():
    ds = uuid4()
    with pytest.raises(Exception):
        RagasRegressionCaseCreateRequest(
            question="q",
            dataset_id=ds,
            reference_sources=[{"document_id": str(uuid4())}],  # missing chunk_id
        )
```

**Step 2: Run tests (expect FAIL)**
Run: `PYTHONPATH=. pytest -q tests/test_regression_case_reference_sources_schema.py`

**Step 3: Implement minimal schema changes**
- Add `ReferenceSource` model and `reference_sources: List[ReferenceSource]`
- Require `dataset_id` for create

**Step 4: Run tests (expect PASS)**
Run: `PYTHONPATH=. pytest -q tests/test_regression_case_reference_sources_schema.py`

**Step 5: Commit**
```bash
git add app/api/schemas/regression.py tests/test_regression_case_reference_sources_schema.py
git commit -m "feat(evaluation): require dataset_id + reference_sources for regression cases"
```

---

### Task 4: Persist reference_sources on regression cases (DB model + runtime migration)

**Files:**
- Modify: `app/models/evaluation.py`
- Modify: `app/core/migrations.py`

**Steps:**
1. Add `reference_sources = Column(JSONB, default=list)` to `RagasRegressionCase`.
2. Add runtime migration:
   - `ALTER TABLE ragas_regression_cases ADD COLUMN IF NOT EXISTS reference_sources JSONB DEFAULT '[]'::jsonb;`
3. Keep backward compatibility: if column missing, create_all + runtime migration should handle.

**Verify:**
- `python -m compileall -q app`

**Commit:**
```bash
git add app/models/evaluation.py app/core/migrations.py
git commit -m "feat(evaluation): persist reference_sources for regression cases"
```

---

### Task 5: Add PATCH update API for regression case (server-side validation)

**Files:**
- Modify: `app/api/schemas/regression.py`
- Modify: `app/api/v1/evaluations.py`
- Test: `tests/test_regression_case_patch_schema.py`

**Steps:**
1. Add `RagasRegressionCasePatchRequest` (allow patch question/expected_answer/tags/reference_sources/extra/document_ids).
2. Add endpoint: `PATCH /api/v1/evaluations/ragas/regression/cases/{case_id}`.
3. Enforce: patch cannot make `reference_sources` empty; dataset_id immutable.

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_regression_case_patch_schema.py`

**Commit:**
```bash
git add app/api/schemas/regression.py app/api/v1/evaluations.py tests/test_regression_case_patch_schema.py
git commit -m "feat(evaluation): add regression case patch endpoint"
```

---

### Task 6: Add export endpoint for regression cases (dataset-scoped bundle)

**Files:**
- Modify: `app/api/v1/evaluations.py`
- Add helper: `app/services/regression_case_bundle.py`
- Test: `tests/test_regression_case_bundle_export.py`

**Bundle format (v1):**
```json
{
  "schema": "mimirq.regression_cases.v1",
  "dataset_id": "<uuid>",
  "items": [ { "question": "...", "expected_answer": "...", "tags": [], "reference_sources": [...] } ]
}
```

**Steps:**
1. Implement helper `export_case_bundle(cases, dataset_id)` (pure).
2. Add endpoint: `GET /api/v1/evaluations/ragas/regression/cases/export?dataset_id=...`
3. Ensure it omits internal ids/tenant_id.

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_regression_case_bundle_export.py`

**Commit:**
```bash
git add app/api/v1/evaluations.py app/services/regression_case_bundle.py tests/test_regression_case_bundle_export.py
git commit -m "feat(evaluation): add regression case export endpoint"
```

---

### Task 7: Add import endpoint for regression cases (upsert by dataset_id + question)

**Files:**
- Modify: `app/api/v1/evaluations.py`
- Modify: `app/api/schemas/regression.py`
- Modify: `app/services/regression_case_bundle.py`
- Test: `tests/test_regression_case_bundle_import.py`

**Steps:**
1. Add schema `RagasRegressionCaseImportRequest`:
   - `dataset_id`, `overwrite`, `max_items`, `items[]`
2. Implement pure upsert planner:
   - normalize key = `(dataset_id, question.strip())`
   - return `{created, updated, skipped, errors[]}`
3. Integrate with DB in API:
   - validate reference_sources
   - upsert by query

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_regression_case_bundle_import.py`

**Commit:**
```bash
git add app/api/v1/evaluations.py app/api/schemas/regression.py app/services/regression_case_bundle.py tests/test_regression_case_bundle_import.py
git commit -m "feat(evaluation): add regression case import endpoint"
```

---

### Task 8: Make regression runs dataset-scoped (store dataset_id + validate)

**Files:**
- Modify: `app/models/evaluation.py`
- Modify: `app/core/migrations.py`
- Modify: `app/api/schemas/regression.py`
- Modify: `app/api/v1/evaluations.py`
- Test: `tests/test_regression_run_dataset_scope.py`

**Steps:**
1. Add `dataset_id` column to `RagasRegressionRun` (nullable in DB, required by API).
2. Runtime migration:
   - `ALTER TABLE ragas_regression_runs ADD COLUMN IF NOT EXISTS dataset_id UUID;`
   - index optional: `CREATE INDEX IF NOT EXISTS ix_ragas_regression_runs_tenant_dataset_created_at ...`
3. API create run:
   - require `dataset_id`
   - if `case_ids` present, ensure cases all belong to this dataset
   - persist `run.dataset_id`

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_regression_run_dataset_scope.py`

**Commit:**
```bash
git add app/models/evaluation.py app/core/migrations.py app/api/schemas/regression.py app/api/v1/evaluations.py tests/test_regression_run_dataset_scope.py
git commit -m "feat(evaluation): scope regression runs by dataset_id"
```

---

### Task 9: Build RAGAS samples with reference + context ids + abstain meta (unit-testable)

**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Test: `tests/test_ragas_regression_sample_builder.py`

**Steps:**
1. Factor a helper (pure-ish) like:
   - `_build_regression_sample(case, item, reference_context_ids, retrieved_context_ids, reference_contexts)`
2. Set `SingleTurnSample.reference = case.expected_answer or ""`
3. Set:
   - `reference_context_ids = [src.chunk_id]`
   - `retrieved_context_ids = [citation.chunk_id]`
4. Capture abstain fields into `item_meta`:
   - `abstain_triggered`, `abstain_reason`, `top_relevance_score`

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_ragas_regression_sample_builder.py`

**Commit:**
```bash
git add app/rag/evaluation/ragas.py tests/test_ragas_regression_sample_builder.py
git commit -m "feat(evaluation): include reference + context ids in regression RAGAS samples"
```

---

### Task 10: Expand supported RAGAS metrics (answer + context + id-based) with tests

**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Test: `tests/test_ragas_metric_resolver.py`

**Supported metric keys (target):**
- `faithfulness`, `response_relevancy`
- `answer_similarity`, `answer_correctness`
- `context_recall`, `context_precision`
- `id_based_context_recall`, `id_based_context_precision`

**Verify:**
- `PYTHONPATH=. pytest -q tests/test_ragas_metric_resolver.py`

**Commit:**
```bash
git add app/rag/evaluation/ragas.py tests/test_ragas_metric_resolver.py
git commit -m "feat(evaluation): support more RAGAS regression metrics"
```

---

### Task 11: Persist per-item meta (abstain + ids + reference_sources snapshot)

**Files:**
- Modify: `app/models/evaluation.py`
- Modify: `app/core/migrations.py`
- Modify: `app/rag/evaluation/ragas.py`

**Steps:**
1. Add `meta = Column(JSONB, default=dict)` to `RagasRegressionItem`
2. Runtime migration:
   - `ALTER TABLE ragas_regression_items ADD COLUMN IF NOT EXISTS meta JSONB DEFAULT '{}'::jsonb;`
3. Store:
   - `reference_context_ids`, `retrieved_context_ids`
   - `abstain_triggered`, `abstain_reason`, `top_relevance_score`

**Verify:** `python -m compileall -q app`

**Commit:**
```bash
git add app/models/evaluation.py app/core/migrations.py app/rag/evaluation/ragas.py
git commit -m "feat(evaluation): persist regression item meta for audit"
```

---

### Task 12: Update web types + API client for new case fields and endpoints

**Files:**
- Modify: `web/types/index.ts`
- Modify: `web/lib/api-client.ts`

**Steps:**
1. Add `reference_sources` to `RegressionCase`/`RegressionCaseCreate`.
2. Add `patchRegressionCase`, `exportRegressionCases`, `importRegressionCases`.

**Verify:**
- `pnpm -C web run typecheck`

**Commit:**
```bash
git add web/types/index.ts web/lib/api-client.ts
git commit -m "feat(web): add regression case evidence sources types + api methods"
```

---

### Task 13: Add ReferenceSourcesPicker UI (retrieve-preview → select citations)

**Files:**
- Create: `web/components/evaluation/reference-sources-picker.tsx`
- Create: `web/lib/reference-sources.ts`
- Test: `web/lib/reference-sources.test.ts`

**Verify:**
- `pnpm -C web run test -- lib/reference-sources.test.ts`

**Commit:**
```bash
git add web/components/evaluation/reference-sources-picker.tsx web/lib/reference-sources.ts web/lib/reference-sources.test.ts
git commit -m "feat(web): add reference sources picker for regression cases"
```

---

### Task 14: Make TestCaseManager dataset-scoped + require evidence sources for create/edit

**Files:**
- Modify: `web/components/test-case-manager.tsx`
- Modify: `web/components/evaluation/regression-tab.tsx`

**Steps:**
1. Add dataset selector (use `datasetApi.list`).
2. List cases with `dataset_id` filter.
3. Create case must select `reference_sources` (open picker).
4. Add edit flow (PATCH) for expected_answer/tags/sources.

**Verify:**
- `pnpm -C web run typecheck`

**Commit:**
```bash
git add web/components/test-case-manager.tsx web/components/evaluation/regression-tab.tsx
git commit -m "feat(web): dataset-scoped regression cases with mandatory evidence"
```

---

### Task 15: Upgrade RegressionTestTab metrics UI (answerable vs unanswerable buckets + abstain KPI)

**Files:**
- Modify: `web/components/evaluation/regression-tab.tsx`

**Steps:**
1. Expand metric options list to include new metrics.
2. Show derived KPIs:
   - `abstain_success_rate` for unanswerable
   - id-based recall/precision
3. Add “按 tag 分组”小表（可选：只做 `unanswerable` 分桶）

**Verify:** `pnpm -C web run typecheck`

**Commit:**
```bash
git add web/components/evaluation/regression-tab.tsx
git commit -m "feat(web): show unanswerable abstain KPI in regression runs"
```

---

### Task 16: Auto-save generated doc questions with evidence sources

**Files:**
- Modify: `app/api/v1/evaluations.py`

**Steps:**
1. When saving `from-documents` questions:
   - set `reference_sources=[{document_id, chunk_id, quote}]` using generator metadata
2. Enforce dataset_id present in request when auto_save_as_cases=true.
3. For `from-conversations` auto_save:
   - return 400 with guidance (must manually attach evidence) OR require citations mapping (future).

**Verify:** `python -m compileall -q app`

**Commit:**
```bash
git add app/api/v1/evaluations.py
git commit -m "feat(evaluation): auto-save generated cases with reference_sources"
```

---

### Task 17: Update regression_gate.py to handle dataset-scoped suite + new metrics

**Files:**
- Modify: `scripts/regression_gate.py`
- Modify: `docs/guides/regression_gate.md`

**Steps:**
1. Detect dataset_id from cases bundle; enforce single dataset.
2. Pass dataset_id when creating regression run.
3. Allow thresholds for `abstain_success_rate` and id-based metrics.

**Verify:** `python scripts/regression_gate.py --help`

**Commit:**
```bash
git add scripts/regression_gate.py docs/guides/regression_gate.md
git commit -m "feat(ci): dataset-scoped regression gate + abstain thresholds"
```

---

### Task 18: Expose latest regression summary in DatasetHealthResponse

**Files:**
- Modify: `app/api/schemas/dataset_health.py`
- Modify: `app/api/v1/datasets.py`

**Steps:**
1. Add `evaluation: { latest_regression_run?: {...} }` to health schema.
2. Query latest run by `dataset_id` (tenant isolated) and attach summary.

**Verify:** `python -m compileall -q app`

**Commit:**
```bash
git add app/api/schemas/dataset_health.py app/api/v1/datasets.py
git commit -m "feat(dataset): include latest regression summary in health"
```

---

### Task 19: Include regression summary in dataset report export (JSON + HTML)

**Files:**
- Modify: `app/api/schemas/report.py`
- Modify: `app/services/report_service.py`
- Modify: `app/services/report_html.py`

**Steps:**
1. Extend report schema with optional `evaluation` section.
2. Populate from latest regression run (same as health).
3. Render a compact card in HTML report.

**Verify:** `python -m compileall -q app`

**Commit:**
```bash
git add app/api/schemas/report.py app/services/report_service.py app/services/report_html.py
git commit -m "feat(reports): include regression evaluation summary"
```

---

### Task 20: Frontend dataset health page shows evaluation card + deep link

**Files:**
- Modify: `web/app/datasets/[id]/health/page.tsx`
- Modify: `web/types/index.ts` (DatasetHealthResponse type)

**Verify:**
- `pnpm -C web run typecheck`

**Commit:**
```bash
git add web/app/datasets/[id]/health/page.tsx web/types/index.ts
git commit -m "feat(web): show regression summary on dataset health page"
```

