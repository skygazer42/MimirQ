# Frontend Backend Full API Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every backend v1 route represented in the frontend API layer, refresh OpenAPI-derived types, and close the visible UI flows for the currently missing product surfaces.

**Architecture:** Treat backend OpenAPI as the source of truth. Keep low-level endpoint wrappers in `web/lib/api/*`, then connect only user-facing capabilities to pages/components with explicit loading, error, empty, and success states. Static API contract checks must prove frontend calls exist in backend and backend routes are represented in the web API layer.

**Tech Stack:** FastAPI OpenAPI, Next.js 16, React 19, TypeScript, `openapi-typescript`, axios/openapi request helpers, Vitest/source tests, Playwright/live smoke where needed.

---

## Current Evidence

- Running backend OpenAPI exposes 330 paths.
- `web/openapi.json` currently has 302 paths, so it is stale.
- `web/scripts/check-api-contract.mjs` passes: current frontend calls resolve to backend routes.
- `web/scripts/check-api-coverage.mjs` fails with 28 backend routes missing from `web/lib/api/*`.
- `web/scripts/check-openapi-coverage.mjs` fails with the same 28-route class because `web/openapi.json` is stale.
- `plans/STATUS_AUDIT_DETAILED_2026-04-23.md` says no `plans/*.md` document can be marked fully complete as a whole; many backend capability points are implemented, but productized frontend closure is still incomplete.

## Task 1: Refresh OpenAPI And Generated Types

**Files:**
- Modify: `web/openapi.json`
- Modify: `web/types/openapi.ts`

**Steps:**
1. Run `make openapi-export`.
2. Run `make openapi-types`.
3. Verify live backend and generated spec both expose the 28 previously missing routes.
4. Run `cd web && node scripts/check-openapi-coverage.mjs`.

## Task 2: Add API Layer Wrappers For Missing Routes

**Files:**
- Modify: `web/lib/api/documents.ts`
- Modify: `web/lib/api/datasets.ts`
- Modify: `web/lib/api/graph.ts`
- Create or modify: `web/lib/api/industry-rules.ts`
- Create or modify: `web/lib/api/lineage.ts`
- Create or modify: `web/lib/api/rtbf.ts`
- Modify: `web/lib/api-client.ts`
- Modify: `web/lib/api/index.ts` if needed

**Steps:**
1. Add typed wrappers using `openapiRequest` for all 28 missing routes.
2. Use names grouped by product domain, not raw route names.
3. Export new API clients from `web/lib/api-client.ts`.
4. Run `cd web && node scripts/check-api-coverage.mjs`.
5. Add or update source tests if the existing API coverage script does not catch exports.

## Task 3: Productize Dataset Analysis

**Files:**
- Modify: `web/app/reports/page-client.tsx` or create focused dataset analysis components under `web/components/reports/`
- Modify: `web/lib/api/datasets.ts`

**Steps:**
1. Connect dashboard, summary, examples, rule suggestions, exports, glossary writeback, and PNG export task polling.
2. Add clear empty state when no feedback/chat data exists.
3. Add success/error toasts for export and glossary writeback.
4. Smoke with one existing dataset and an empty dataset.

## Task 4: Productize KG Network Tools

**Files:**
- Modify: `web/lib/api/graph.ts`
- Modify: `web/app/graph/page.tsx` or graph action/dialog components

**Steps:**
1. Add UI actions for k-hop neighbors, shortest path, paths between, centrality, community, and connected component.
2. Reuse existing graph canvas/dialog patterns.
3. Show request payload, result summary, and graph overlay where possible.
4. Ensure empty/no-path responses are explicit, not silent.

## Task 5: Productize Industry Rules

**Files:**
- Create or modify: `web/lib/api/industry-rules.ts`
- Modify: `web/components/governance-common-lines/` or `web/components/governance-profiles/`

**Steps:**
1. Add ruleset listing and detail loading.
2. Add glossary/pattern/intent update actions.
3. Add preview rewrite form.
4. Confirm changes round-trip through backend reload/list/detail.

## Task 6: Productize Lineage And RTBF

**Files:**
- Create or modify: `web/lib/api/lineage.ts`
- Create or modify: `web/lib/api/rtbf.ts`
- Modify document detail, evidence, or observability pages where these actions belong.

**Steps:**
1. Add chunk lineage and answer lineage viewers.
2. Add RTBF request/status surface with confirmation copy.
3. Make destructive RTBF actions explicit and auditable.
4. Smoke status polling against a created request.

## Task 7: Clean DOCX Closure

**Files:**
- Modify: `web/lib/api/documents.ts`
- Modify: citation/document detail actions that offer Clean DOCX.

**Steps:**
1. Add clean DOCX wrapper.
2. Wire download/open action into the document/citation UI.
3. Confirm success path and backend error path.

## Task 8: Verification Gate

**Commands:**
- `cd web && node scripts/check-api-contract.mjs`
- `cd web && node scripts/check-api-coverage.mjs`
- `cd web && node scripts/check-openapi-coverage.mjs`
- `cd web && pnpm typecheck`
- `cd web && pnpm test -- --runInBand` if supported; otherwise `cd web && pnpm test`
- `make api-ping`
- Targeted Playwright/live smoke for pages touched in Tasks 3-7.

**Completion Criteria:**
- API contract passes.
- API coverage passes: zero backend routes missing in web API layer.
- OpenAPI coverage passes.
- Typecheck passes.
- Key UI flows perform real backend requests and expose loading/error/empty/success states.
- `plans/` status is reported as “backend capability mostly implemented by item, but no plan fully complete as a whole unless front-end/product closure is included.”
