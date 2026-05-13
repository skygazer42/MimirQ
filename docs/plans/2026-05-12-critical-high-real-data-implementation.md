# Critical High Real Data Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the remaining open Critical and High audit items that are still real gaps, then remove non-demo frontend mock/data branches so production pages and buttons all round-trip against real backend APIs.

**Architecture:** Work in vertical slices. First land low-risk cross-cutting Critical fixes that improve safety and correctness without changing product behavior broadly. Then tackle API-heavy backend/router refactors and frontend real-data migrations by domain, using existing `web/lib/api/*`, TanStack Query, and source/live tests as regression gates.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Next.js 16, React 19, TypeScript, TanStack Query, Vitest source tests, Playwright live smoke.

---

## Scope Checklist

- [ ] Critical security/config/repo items still open in `plans/fullstack-code-audit-60items-2026-q2.md`
- [ ] High frontend/backend engineering items still open in `plans/fullstack-code-audit-60items-2026-q2.md`
- [ ] Remaining partial/open items in `plans/fullstack-code-quality-top15-2026-q2.md`
- [ ] Non-demo frontend buttons and data surfaces stop relying on local demo/mock/hardcoded data
- [ ] Frontend surfaces use real backend responses except explicit demo routes
- [ ] Verification artifacts prove touched flows use real APIs

## Task 1: Land Critical Batch 1

**Files:**
- Modify: `web/next.config.mjs`
- Modify: `web/next.config.test.ts`
- Modify: `app/api/v1/settings.py`
- Modify: `app/core/config.py`
- Modify: `.gitattributes`
- Modify: git index entries under `web/.playwright-mcp/*.png`

**Steps:**
1. Add `headers()` to `web/next.config.mjs` for baseline response hardening without breaking proxy-based CSP nonce wiring.
2. Update `web/next.config.test.ts` to assert the new headers contract.
3. Centralize settings-page `api_base` defaults through `app.core.config.settings.LLM_API_BASE` instead of repeating the OpenAI base literal inside request/response models.
4. Add `*.onnx filter=lfs diff=lfs merge=lfs -text` to `.gitattributes`.
5. Remove tracked `web/.playwright-mcp/*.png` artifacts from git index while preserving local files.
6. Re-check `git ls-files 'web/.playwright-mcp/*.png'` and `git ls-files '*.onnx'`.

## Task 2: Verify Alembic Index Reality Before Writing New Migration

**Files:**
- Inspect: `app/models/*.py`
- Inspect: `alembic/versions/*.py`
- Create only if missing indexes are real: `alembic/versions/0015_*.py`

**Steps:**
1. Diff model-defined `Index(...)` names against existing migration SQL/index creation.
2. If missing names remain, add a new migration only for the true delta.
3. If no delta remains, update the audit docs later instead of shipping a no-op migration.

## Task 3: Backend Critical Refactor Wave

**Files:**
- Modify: `app/api/v1/chat.py`
- Create/modify: `app/services/chat/*.py`
- Modify: `app/api/v1/documents.py`
- Modify: `app/api/v1/connectors.py`
- Modify: `app/api/dependencies/auth.py`
- Modify: other logger callsites as needed

**Steps:**
1. Extract `chat.py` stream orchestration helpers into `app/services/chat/*`.
2. Continue shrinking `documents.py` by moving the next largest cohesive blocks out.
3. Continue shrinking `connectors.py` by moving schema/sample/oauth logic out of router code.
4. Normalize logger acquisition toward `get_logger(...)`.

## Task 4: High Frontend Real-Data Alignment Wave

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx`
- Modify: `web/app/knowledge/quarantine/page.tsx`
- Modify: `web/app/knowledge/feedback/page.tsx`
- Modify: `web/lib/api/*.ts`
- Modify: `web/lib/query-keys.ts`
- Modify: related source tests and Playwright specs

**Steps:**
1. Inventory all non-demo branches that still synthesize records, metrics, or button actions locally.
2. Keep explicit demo routes/flags only on demo pages.
3. For non-demo pages, route buttons through real backend mutations and replace synthesized summaries with query-backed data.
4. Add source tests to prevent regression to local mock branches on non-demo routes.
5. Disable `?demo=1` on normal knowledge pages; only explicit `/demo` routes may enable demo branches in the future.

## Task 5: Remaining High Engineering Debt

**Files:**
- Modify: `web/components/**`
- Modify: `web/app/**`
- Modify: `app/services/**`
- Modify: `tests/**`

**Steps:**
1. Continue TanStack Query migration for remaining hot-path pages.
2. Reduce explicit `any` in graph/detail hotspots.
3. Rebuild e2e coverage for datasets/knowledge/ingestion flows using real backend data.
4. Add missing happy-path tests for oversized backend services touched by the work.

## Verification

Run the narrowest useful verification after each slice, then broader checks after each wave:

- `cd web && pnpm test next.config.test.ts`
- `pytest tests/test_env_example_split.py -q`
- `git ls-files 'web/.playwright-mcp/*.png'`
- `git ls-files '*.onnx'`
- `cd web && pnpm test -- --runInBand`
- `make test`
- `PLAYWRIGHT_PORT=3000 pnpm --dir web exec playwright test web/e2e/document-chat.smoke.spec.ts --project=chromium`
- `PLAYWRIGHT_PORT=3000 pnpm --dir web exec playwright test web/e2e/live-stack.smoke.spec.ts --project=chromium`

## Execution Order

1. Critical batch 1 (`headers`, `api_base`, tracked artifacts, LFS attributes)
2. Index reality check before any new Alembic migration
3. `chat.py` stream refactor
4. `documents.py` / `connectors.py` continued extraction
5. `knowledge/*` non-demo real-data cleanup
6. Remaining High items and regression expansion
