# API Client Modular Split Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the `web/lib/api-client.ts` modular split so runtime API implementations live in `web/lib/api/*` domain modules while `api-client.ts` remains a compatibility barrel.

**Architecture:** Keep `api-client.ts` as a re-export layer for backwards compatibility and move each remaining runtime API plus its local domain types into dedicated files under `web/lib/api/`. Keep `web/lib/api/index.ts` pointed at domain modules so production imports no longer flow back through the legacy monolith.

**Tech Stack:** TypeScript, Vitest, Axios/OpenAPI helpers, Next.js frontend module barrels

---

### Task 1: Lock the desired boundary with failing source tests

**Files:**
- Modify: `web/lib/api-client-modular-split.source.test.ts`
- Modify: `web/lib/api-domain-extraction.source.test.ts`

**Step 1: Write the failing test**

Add source guards that require:
- `web/lib/api-client.ts` to re-export every remaining API from a dedicated `web/lib/api/*` module instead of defining `export const ...Api =`.
- `web/lib/api/index.ts` to export those APIs from domain modules rather than from `@/lib/api-client`.

**Step 2: Run test to verify it fails**

Run: `pnpm vitest run web/lib/api-client-modular-split.source.test.ts web/lib/api-domain-extraction.source.test.ts`
Expected: FAIL because `api-client.ts` still defines multiple runtime APIs directly and `web/lib/api/index.ts` still re-exports some APIs from `@/lib/api-client`.

### Task 2: Extract remaining runtime APIs into domain modules

**Files:**
- Create: `web/lib/api/health.ts`
- Create: `web/lib/api/parsing.ts`
- Create: `web/lib/api/governance.ts`
- Create: `web/lib/api/evidence.ts`
- Create: `web/lib/api/meta.ts`
- Create: `web/lib/api/audit.ts`
- Create: `web/lib/api/usage.ts`
- Create: `web/lib/api/access.ts`
- Create: `web/lib/api/scim.ts`
- Create: `web/lib/api/ltr.ts`
- Create: `web/lib/api/prompts.ts`
- Modify: `web/lib/api/connectors.ts`
- Modify: `web/lib/api/rag.ts`
- Modify: `web/lib/api/evaluation.ts`

**Step 1: Copy domain types and implementations into the new module files**

Move each API implementation and its local interfaces/types out of `web/lib/api-client.ts`, preserving public names such as `healthApi`, `parsingApi`, `evaluationApi`, `promptTemplateApi`, `ragvizApi`, `groupApi`, `rbacApi`, and `TenantMember`.

**Step 2: Keep modules importing only shared helpers or source types**

Ensure the new modules depend on shared utilities such as `@/lib/api/core`, `@/lib/env`, `@/lib/request-id`, and backend/openapi types, but never import from `@/lib/api-client`.

**Step 3: Run targeted source tests**

Run: `pnpm vitest run web/lib/api-client-modular-split.source.test.ts web/lib/api-domain-extraction.source.test.ts`
Expected: PASS after the extraction is complete.

### Task 3: Collapse `api-client.ts` into a compatibility barrel

**Files:**
- Modify: `web/lib/api-client.ts`
- Modify: `web/lib/api/index.ts`

**Step 1: Replace inline runtime implementations with re-exports**

Re-export runtime APIs from their domain files and re-export any moved domain types from those modules so imports from `@/lib/api-client` and `@/lib/api` remain stable.

**Step 2: Point `web/lib/api/index.ts` directly at the domain modules**

Make the public `@/lib/api` barrel export runtime APIs from `./health`, `./parsing`, `./governance`, `./evidence`, `./meta`, `./audit`, `./usage`, `./access`, `./scim`, `./ltr`, and `./prompts` instead of routing those through `@/lib/api-client`.

**Step 3: Run targeted API regression tests**

Run: `pnpm vitest run web/lib/api-client*.test.ts web/lib/api-domain-extraction.source.test.ts web/lib/api-import-boundary.source.test.ts web/lib/api-documents-source.test.ts`
Expected: PASS with no modular-boundary regressions.

### Task 4: Verify and land the session cleanly

**Files:**
- Modify: `.beads/issues.jsonl` (via `bd close` / `bd update` if needed)

**Step 1: Run the relevant verification commands**

Run:
- `pnpm vitest run web/lib/api-client*.test.ts web/lib/api-domain-extraction.source.test.ts web/lib/api-import-boundary.source.test.ts web/lib/api-documents-source.test.ts`
- Any follow-up targeted test required by touched modules

**Step 2: Sync issue tracking and git state**

Run:
- `bd sync`
- `git status --short`

**Step 3: Commit and push**

Run:
- `git add docs/plans/2026-03-29-api-client-modular-split.md web/lib/api-client.ts web/lib/api/index.ts web/lib/api/*.ts web/lib/*.test.ts`
- `git commit -m "refactor: finish api-client modular split"`
- `git pull --rebase`
- `bd sync`
- `git push`

**Step 4: Verify final state**

Run: `git status`
Expected: clean working tree and branch up to date with origin.
