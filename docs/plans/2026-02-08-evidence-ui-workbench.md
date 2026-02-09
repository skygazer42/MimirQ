# Evidence API UI Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add a first-class UI workbench to call the retrieval-only Evidence API (`POST /api/v1/rag/retrieve`) and visualize citations + `has_evidence` / abstain signals, optimized for recall debugging and dataset-scoped evidence discovery.

**Architecture:** Add a Next.js route under `/knowledge/evidence` rendering an `EvidenceWorkbench` client component. The workbench calls `ragApi.retrieveEvidence(...)` (added to `web/lib/api-client.ts`) and renders: scope controls (dataset), query input, retrieval profile presets, metrics summary, and citation list. Provide an "Export Evidence Pack" JSON download for regression authoring.

**Tech Stack:** Next.js App Router, React, axios client (`web/lib/api-client.ts`), Tailwind UI primitives, Vitest.

---

### Task 1: Add Evidence API Method to Web API Client (and unit test)

**Files:**
- Modify: `web/types/index.ts`
- Modify: `web/lib/api-client.ts`
- Test: `web/lib/api-client.rag-evidence.test.ts` (new)

**Step 1: Write failing test**

Create a Vitest test that asserts `web/lib/api-client.ts` contains a `ragApi.retrieveEvidence` method calling `'/rag/retrieve'`.

Run:
```bash
pnpm -C web test -- web/lib/api-client.rag-evidence.test.ts
```
Expected: FAIL (missing method).

**Step 2: Add request/response types**

Add:
- `EvidenceRetrieveRequest` (alias of `RetrievePreviewRequest`)
- `EvidenceRetrieveResponse` (extends `RetrievePreviewResponse` with `has_evidence`, `abstain_triggered`, `abstain_reason`)

**Step 3: Implement `ragApi.retrieveEvidence`**

Add method:
```ts
await apiClient.post('/rag/retrieve', params)
```

**Step 4: Re-run test**

Expected: PASS.

**Step 5: Commit**

```bash
git add web/types/index.ts web/lib/api-client.ts web/lib/api-client.rag-evidence.test.ts
git commit -m "feat(web): add evidence api client method"
```

---

### Task 2: Build Evidence Workbench UI Page

**Files:**
- Add: `web/app/knowledge/evidence/page.tsx`
- Add: `web/components/ragviz/evidence-workbench.tsx`
- Modify (optional): `web/components/navbar.tsx`

**Step 1: Implement page**

Add a route under `/knowledge/evidence` using `AppFrame`.

**Step 2: Implement workbench**

UI sections:
- Dataset selector (load via `datasetApi.list({limit: 200})`)
- Query input
- Retrieval profile select: `recall50` (default), `coverage80`, `recall20`
- Run button (calls `ragApi.retrieveEvidence`)
- Summary panel: `has_evidence`, `abstain_*`, top relevance score, elapsed seconds
- Citation list: doc name, chunk index/page, header path, scores, content
- Export button: download an Evidence Pack JSON `{ dataset_id, query, citations, metrics }`

**Step 3: Manual smoke (dev)**

Run:
```bash
pnpm -C web dev
```

Navigate to `/knowledge/evidence` and run a query for a known dataset.

**Step 4: Commit**

```bash
git add web/app/knowledge/evidence/page.tsx web/components/ragviz/evidence-workbench.tsx web/components/navbar.tsx
git commit -m "feat(web): add evidence workbench page"
```

