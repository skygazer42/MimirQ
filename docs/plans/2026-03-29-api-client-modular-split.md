# API Client Modular Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split `web/lib/api-client.ts` into real domain modules under `web/lib/api/*` while preserving `@/lib/api` and `@/lib/api-client` compatibility exports.

**Architecture:** `web/lib/api/core.ts` remains the shared transport layer. Every `*Api` implementation moves into a domain file under `web/lib/api/*`, `web/lib/api/index.ts` becomes an explicit no-cycle barrel, and `web/lib/api-client.ts` becomes a thin compatibility layer that only re-exports domain APIs, helpers, and domain-local types.

**Tech Stack:** TypeScript, Axios, Next.js, Vitest, pnpm

---

### Task 1: Lock the intended module boundaries with failing source guards

**Files:**
- Modify: `web/lib/api-domain-extraction.source.test.ts`
- Create: `web/lib/api-client-modular-split.source.test.ts`
- Verify: `web/lib/api-domain-extraction.source.test.ts`, `web/lib/api-client-modular-split.source.test.ts`

**Step 1: Write failing tests**

Add source-guard assertions that:
- `web/lib/api/index.ts` does not contain `export * from '@/lib/api-client'`
- `web/lib/api/auth.ts`, `web/lib/api/connectors.ts`, `web/lib/api/datasets.ts`, `web/lib/api/evaluation.ts`, `web/lib/api/graph.ts`, `web/lib/api/observability.ts`, `web/lib/api/pipeline.ts`, `web/lib/api/reports.ts`, and `web/lib/api/settings.ts` do not contain `from '@/lib/api-client'`
- `web/lib/api-client.ts` re-exports those APIs instead of defining them inline

**Step 2: Run tests to verify RED**

Run:
```bash
cd web && pnpm vitest run lib/api-domain-extraction.source.test.ts lib/api-client-modular-split.source.test.ts
```

Expected:
- Fail because current stub domain files still re-export from `@/lib/api-client`
- Fail because `web/lib/api/index.ts` still uses `export * from '@/lib/api-client'`

**Step 3: Implement minimal guard helpers if needed**

Use small local `read()` / `expectFile()` helpers in the test file rather than duplicating path logic.

**Step 4: Re-run the tests and keep them failing for the right reason**

Run the same command again and confirm the failures still point at the current circular boundary.

### Task 2: Extract auth, pipeline, connectors, and small transport-adjacent APIs

**Files:**
- Modify: `web/lib/api/auth.ts`
- Modify: `web/lib/api/pipeline.ts`
- Modify: `web/lib/api/connectors.ts`
- Create: `web/lib/api/health.ts`
- Create: `web/lib/api/parsing.ts`
- Create: `web/lib/api/system.ts`
- Modify: `web/lib/api/index.ts`
- Modify: `web/lib/api-client.ts`
- Verify: `web/lib/api-client-auth.test.ts`, `web/lib/api-client-connectors-validate.test.ts`

**Step 1: Write the failing tests**

Reuse the Task 1 source guards and run a focused subset that should remain red until these modules are real:
```bash
cd web && pnpm vitest run lib/api-client-modular-split.source.test.ts lib/api-client-auth.test.ts lib/api-client-connectors-validate.test.ts
```

Expected:
- Source guard fails before extraction
- Runtime API tests still pass or remain neutral

**Step 2: Move the implementations**

Move these exports out of `web/lib/api-client.ts`:
- `authApi`
- `pipelineApi`
- `connectorApi`
- `healthApi`
- `parsingApi`
- `metaApi`

Move any related domain-local interfaces with them:
- parsing request/response types
- governance normalization helpers

**Step 3: Make `api/index.ts` explicit**

Replace the wildcard re-export with direct exports from:
- `./core`
- `./auth`
- `./chat`
- `./connectors`
- `./documents`
- `./health`
- `./parsing`
- `./pipeline`
- `./rag`
- `./system`

**Step 4: Make `api-client.ts` a compatibility layer**

Leave only:
- imports needed for default `apiClient`
- named re-exports from `web/lib/api/*`
- exported domain types re-exported from their new homes
- `export default apiClient`

**Step 5: Verify**

Run:
```bash
cd web && pnpm vitest run lib/api-domain-extraction.source.test.ts lib/api-client-modular-split.source.test.ts lib/api-client-auth.test.ts lib/api-client-connectors-validate.test.ts
```

### Task 3: Extract datasets and reports domains

**Files:**
- Modify: `web/lib/api/datasets.ts`
- Modify: `web/lib/api/reports.ts`
- Modify: `web/lib/api/index.ts`
- Modify: `web/lib/api-client.ts`
- Verify: `web/lib/api-client-dataset-health.test.ts`, `web/lib/api-client-dataset-categories.test.ts`

**Step 1: Write the failing test**

Run the source guards first:
```bash
cd web && pnpm vitest run lib/api-client-modular-split.source.test.ts lib/api-client-dataset-health.test.ts lib/api-client-dataset-categories.test.ts
```

Expected:
- Source guard remains red until the datasets/report modules are real

**Step 2: Move implementations**

Move these exports into `web/lib/api/datasets.ts`:
- `datasetApi`
- `datasetCategoryApi`

Move these domain-local interfaces with them:
- settings-free dataset profile/precheck helper types still defined in `api-client.ts`

Move this export into `web/lib/api/reports.ts`:
- `reportApi`

**Step 3: Re-export from `api/index.ts` and `api-client.ts`**

Keep the named exports stable for:
- `datasetApi`
- `datasetCategoryApi`
- `reportApi`

**Step 4: Verify**

Run:
```bash
cd web && pnpm vitest run lib/api-client-modular-split.source.test.ts lib/api-client-dataset-health.test.ts lib/api-client-dataset-categories.test.ts
```

### Task 4: Extract graph, observability, settings, evaluation, and admin/support domains

**Files:**
- Modify: `web/lib/api/graph.ts`
- Modify: `web/lib/api/observability.ts`
- Modify: `web/lib/api/settings.ts`
- Modify: `web/lib/api/evaluation.ts`
- Create: `web/lib/api/admin.ts`
- Modify: `web/lib/api/index.ts`
- Modify: `web/lib/api-client.ts`
- Verify: `web/lib/api-client-observability.test.ts`, `web/lib/api-client-governance-profiles.test.ts`, `web/lib/api-client.rag-evidence.test.ts`, `web/lib/api-client.regression-run-bundle.test.ts`

**Step 1: Write the failing tests**

Run:
```bash
cd web && pnpm vitest run lib/api-client-modular-split.source.test.ts lib/api-client-observability.test.ts lib/api-client-governance-profiles.test.ts lib/api-client.rag-evidence.test.ts lib/api-client.regression-run-bundle.test.ts
```

Expected:
- Source guard red until these modules are real

**Step 2: Move implementations**

Move these exports:
- `kgApi` -> `web/lib/api/graph.ts`
- `observabilityApi` -> `web/lib/api/observability.ts`
- `settingsApi` -> `web/lib/api/settings.ts`
- `evaluationApi` -> `web/lib/api/evaluation.ts`

Group the remaining small APIs into `web/lib/api/admin.ts`:
- `usageApi`
- `auditApi`
- `rbacApi`
- `groupApi`
- `scimApi`
- `ltrApi`
- `promptTemplateApi`
- `ragConfigTemplateApi`
- `ragvizApi`
- `feedbackApi`
- `sseApi`
- `governanceApi`
- `chunkPresetApi`
- `retrievalApi`
- `ingestionRunApi`
- `evidenceApi`

**Step 3: Export compatibly**

Re-export everything from `web/lib/api/index.ts` and `web/lib/api-client.ts` so existing imports remain valid.

**Step 4: Verify**

Run:
```bash
cd web && pnpm vitest run lib/api-domain-extraction.source.test.ts lib/api-client-modular-split.source.test.ts lib/api-client-governance-profiles.test.ts lib/api-client-observability.test.ts lib/api-client.rag-evidence.test.ts lib/api-client.regression-run-bundle.test.ts
```

### Task 5: Run the full verification set required by the issue

**Files:**
- Verify only

**Step 1: Run focused web lint**

Run:
```bash
cd web && pnpm run lint
```

**Step 2: Run focused web tests**

Run:
```bash
cd web && pnpm run test
```

**Step 3: Run repo verification**

Run:
```bash
make verify
```

**Step 4: Investigate and fix fallout**

If a command fails:
- fix the narrowest issue
- rerun the same command
- do not claim success until fresh output is green

**Step 5: Final review prep**

Collect:
- changed file list
- new module boundaries
- compatibility story for `@/lib/api` and `@/lib/api-client`
- exact verification commands and results
