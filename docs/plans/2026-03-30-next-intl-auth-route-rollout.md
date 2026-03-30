# Next-Intl Auth Route Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware routing for auth entry points by switching auth redirects and callback pages to the shared `next-intl` navigation helper and adding locale wrappers for callback routes.

**Architecture:** Keep auth behavior unchanged. Swap `useRouter`/`usePathname` in `web/components/auth-guard.tsx`, `web/app/auth/page.tsx`, `web/app/auth/oidc/callback/page.tsx`, and `web/app/auth/saml/callback/page.tsx` to `@/i18n/navigation`, while leaving `useSearchParams` on `next/navigation` where required. Add thin `[locale]` wrappers for the OIDC and SAML callback routes so locale-prefixed auth callbacks resolve to real app routes.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware auth routing wiring

**Files:**
- Create: `web/i18n/auth-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/auth-guard.tsx` to import `usePathname` and `useRouter` from `@/i18n/navigation`
- `web/app/auth/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/auth/oidc/callback/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/auth/saml/callback/page.tsx` to import `useRouter` from `@/i18n/navigation`
- locale wrappers to exist for:
  - `web/app/[locale]/auth/oidc/callback/page.tsx`
  - `web/app/[locale]/auth/saml/callback/page.tsx`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/auth-routing.source.test.ts`

Expected: FAIL because the auth routing files still use `next/navigation` and the callback wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch the four auth routing files to the shared locale-aware helper and add the callback wrappers.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/auth-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify auth routing rollout does not regress existing navigation guards

**Files:**
- Modify: `web/components/auth-guard.tsx`
- Modify: `web/app/auth/page.tsx`
- Modify: `web/app/auth/oidc/callback/page.tsx`
- Modify: `web/app/auth/saml/callback/page.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/auth-routing.source.test.ts components/command-menu.source.test.ts components/navbar.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/auth-guard.tsx app/auth/page.tsx app/auth/oidc/callback/page.tsx app/auth/saml/callback/page.tsx i18n/auth-routing.source.test.ts 'app/[locale]/auth/oidc/callback/page.tsx' 'app/[locale]/auth/saml/callback/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the auth slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the auth route migration and callback wrapper coverage, plus what still remains (not-found/error entry points, broader message catalogs, deeper dynamic page coverage).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl auth route coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
