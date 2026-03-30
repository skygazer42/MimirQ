# Next-Intl Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce `next-intl` with a real `web/app/[locale]` route layer, migrate the current shared UI copy to translation hooks, and keep legacy non-migrated routes working during rollout.

**Architecture:** Add `next-intl` request/routing/proxy infrastructure in `web/i18n/*` plus `web/app/[locale]` wrappers for the home and history entry points. Keep the existing root app tree in place for compatibility, but provide a root-level `NextIntlClientProvider` so shared client components can read the active locale while the first localized routes move behind `[locale]`.

**Tech Stack:** Next.js 16 App Router, `next-intl`, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard the locale routing skeleton

**Files:**
- Create: `web/i18n/request.source.test.ts`
- Modify: `web/app/layout.source.test.ts`

**Step 1: Write the failing test**

Add source assertions for:
- `web/i18n/routing.ts` using `defineRouting`
- `web/i18n/request.ts` using `getRequestConfig`
- `web/proxy.ts` using `createMiddleware`
- `web/app/[locale]/layout.tsx` validating locale params and calling `setRequestLocale`
- `web/app/layout.tsx` mounting `NextIntlClientProvider`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/request.source.test.ts app/layout.source.test.ts`

Expected: FAIL because the locale routing files and provider wiring do not exist yet.

**Step 3: Write minimal implementation**

Add the missing locale routing/request/proxy/layout files and root provider wiring.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/request.source.test.ts app/layout.source.test.ts`

Expected: PASS.

### Task 2: Guard the message-hook migration

**Files:**
- Modify: `web/lib/messages-rollout.source.test.ts`
- Modify: `web/lib/long-term-cleanup.source.test.ts`

**Step 1: Write the failing test**

Update the source guards to require:
- `web/components/chat-area.tsx` to use `useTranslations`
- `web/app/history/page-client.tsx` to use `useTranslations` / locale-aware formatting
- `web/components/document-detail-dialog.tsx` to stop importing `@/lib/messages`
- translation messages to live under `web/i18n/messages/`

**Step 2: Run test to verify it fails**

Run: `pnpm test lib/messages-rollout.source.test.ts lib/long-term-cleanup.source.test.ts`

Expected: FAIL because the app still imports `@/lib/messages`.

**Step 3: Write minimal implementation**

Move the catalog to the i18n layer and switch the guarded components to translation hooks.

**Step 4: Run test to verify it passes**

Run: `pnpm test lib/messages-rollout.source.test.ts lib/long-term-cleanup.source.test.ts`

Expected: PASS.

### Task 3: Install and wire `next-intl`

**Files:**
- Modify: `web/package.json`
- Modify: `web/next.config.mjs`
- Create: `web/i18n/routing.ts`
- Create: `web/i18n/request.ts`
- Create: `web/i18n/messages/zh-CN.ts`
- Create: `web/proxy.ts`

**Step 1: Install dependency**

Run: `pnpm add next-intl`

**Step 2: Implement request/routing glue**

Use the official App Router locale-routing setup:
- define supported locales + default locale
- register request config
- wrap Next config with the `next-intl` plugin
- expose a proxy matcher only for the localized rollout surface (`/` and `/history`)

**Step 3: Run focused verification**

Run: `pnpm test i18n/request.source.test.ts lib/messages-rollout.source.test.ts lib/long-term-cleanup.source.test.ts`

Expected: PASS.

### Task 4: Migrate the first localized routes and shared copy

**Files:**
- Create: `web/app/[locale]/layout.tsx`
- Create: `web/app/[locale]/page.tsx`
- Create: `web/app/[locale]/history/page.tsx`
- Modify: `web/app/layout.tsx`
- Modify: `web/components/app-frame.tsx`
- Modify: `web/components/chat-area.tsx`
- Modify: `web/app/history/page-client.tsx`
- Modify: `web/components/document-detail-dialog.tsx`

**Step 1: Switch guarded components to `next-intl` hooks**

Replace direct catalog imports with `useTranslations` namespaces and locale-aware date/time formatting.

**Step 2: Keep route behavior stable**

Ensure `/`, `/history`, `/<locale>`, and `/<locale>/history` all resolve through the new locale infrastructure without breaking existing query-param behavior.

**Step 3: Run focused tests**

Run: `pnpm test app/history/page.source.test.ts app/history/page.a11y.test.ts app/history/page.empty-state.test.ts lib/messages-rollout.source.test.ts lib/long-term-cleanup.source.test.ts i18n/request.source.test.ts`

Expected: PASS.

### Task 5: Verify and land

**Files:**
- Modify: `plans/globalization-safety-a11y.md`

**Step 1: Run quality gates**

Run:
- `pnpm exec eslint app/layout.tsx app/[locale]/layout.tsx app/[locale]/page.tsx app/[locale]/history/page.tsx app/history/page-client.tsx components/app-frame.tsx components/chat-area.tsx components/document-detail-dialog.tsx i18n/request.ts i18n/routing.ts proxy.ts lib/messages-rollout.source.test.ts lib/long-term-cleanup.source.test.ts i18n/request.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`
- `pnpm run build`

**Step 2: Update tracking artifacts**

If the rollout is truly complete, check off the `next-intl` item in `plans/globalization-safety-a11y.md` and update `bd` notes accordingly.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Introduce next-intl locale routing foundation"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch up to date with `origin/main`.
