# Neutral White Theme Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion while implementing this plan.

**Goal:** Add a professional, globally accessible neutral-white appearance that removes blue visual dominance without flattening hierarchy or hiding semantic status colors.

**Architecture:** Keep the existing surface-theme and accent-color model, but add a first-class `neutral` surface preset whose defaults come from CSS tokens instead of an inline color override. Persist surface and optional accent choices in local storage plus cookies so the server can render the selected surface before hydration. Reuse the existing theme customizer from the global navigation rather than adding a second settings system.

**Tech Stack:** Next.js 16, React 19, next-themes, Tailwind CSS v4, CSS custom properties, chroma-js, Vitest, Playwright.

---

## Design Intent

- **Domain:** document evidence, retrieval traces, knowledge assets, audit trails, indexes, and quality gates.
- **Color world:** porcelain white, archival paper, graphite, steel gray, charcoal ink, and restrained semantic pigments.
- **Signature:** the workspace remains visually neutral until a real system state or evidence signal deserves color.
- **Defaults to avoid:** generic SaaS blue gradients, blue navigation selection everywhere, and page-local hard-coded sky colors.
- **Depth:** white canvas and cards separated by quiet gray borders and small elevation changes, not tinted panels.
- **Typography:** preserve the established application typography so the theme changes color hierarchy rather than product identity.
- **Spacing:** preserve the existing 4px-derived spacing system.

## Task 1: Lock Theme Semantics

**Files:**
- Create: `web/lib/theme-surface.test.ts`
- Modify: `web/lib/theme-surface.ts`

1. Add failing tests proving `neutral` is a valid surface theme.
2. Add a failing test proving a surface preset with no explicit accent does not leave stale inline color tokens behind.
3. Add a failing test proving a valid explicit accent still produces readable primary tokens.
4. Run `pnpm vitest run lib/theme-surface.test.ts` and confirm the new assertions fail for the missing behavior.
5. Implement explicit accent overrides separately from surface defaults.
6. Re-run the focused test until it passes.

## Task 2: Add Neutral Surface Tokens

**Files:**
- Modify: `web/app/globals.css`
- Modify: `web/scripts/check-theme-contrast.mjs`
- Modify: `web/i18n/messages/zh-CN/common.ts`

1. Add light neutral tokens using white surfaces, graphite controls, gray borders, and zero decorative orb opacity.
2. Add a neutral dark counterpart so switching display mode remains readable.
3. Extend the contrast checker to validate every surface preset in light and dark modes.
4. Run `pnpm ui-check`; all foreground/background pairs must meet WCAG AA.

## Task 3: Make Appearance Global and First-Paint Safe

**Files:**
- Modify: `web/components/theme-customizer.tsx`
- Modify: `web/components/theme-appearance-provider.tsx`
- Modify: `web/components/navbar.tsx`
- Modify: `web/components/navbar.behavior.test.ts`
- Modify: `web/i18n/messages/zh-CN/chat.ts`
- Modify: `web/app/layout.tsx`

1. Add a failing navbar behavior test requiring a global appearance trigger.
2. Render the existing customizer beside the display-mode control in the global navigation.
3. Persist the surface preset and optional accent in both local storage and cookies.
4. Read sanitized appearance cookies in the root layout and render the selected surface on `<html>` before hydration.
5. Keep cross-tab storage synchronization through the existing appearance provider.
6. Run focused navbar and theme tests.

## Task 4: Remove Theme-Blocking Blue Chrome

**Files:**
- Modify only shared shell and reusable surface components that contain raw sky/blue presentation values.

1. Replace raw blue navigation and shared-shell colors with `primary`, `info`, `border`, and surface tokens.
2. Do not neutralize semantic chart series, success, warning, destructive, or evidence-state colors.
3. Run the design-token checker and inspect remaining raw blue usages; remaining cases must be data-semantic rather than application chrome.

## Task 5: Verify Both Themes

1. Run focused Vitest tests, `pnpm typecheck`, `pnpm ui-check`, and `pnpm build`.
2. Start the production frontend and verify `/`, `/knowledge`, `/datasets`, `/evaluations`, and `/settings` at desktop and narrow widths.
3. Switch Ocean -> Neutral White -> Ocean and reload after each switch.
4. Confirm the selected theme persists, no blue flash appears after persistence, navigation remains legible, and status colors remain distinguishable.
5. Capture screenshots for visual comparison and run the visual-verdict workflow before completion.
