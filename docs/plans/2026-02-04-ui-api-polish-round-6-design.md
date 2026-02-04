# UI + API Polish (Round 6) Design Notes

Date: 2026-02-04

## Goal

Ship another focused round of frontend polish that:

- Improves baseline UI consistency (shadow tokens, motion durations).
- Fixes keyboard focus visibility regressions (no focus-ring suppression in search/filter toolbars).
- Improves FE/BE integration debugging (error toasts should surface `request_id` when available).

## Design System Anchors (ui-ux-pro-max)

Project context: knowledge base / RAG platform, app-style dashboard (not a marketing page).

- Style intent: **Data-dense dashboard** (fast, information-first, WCAG-friendly).
- Motion intent: micro-interactions should stay **<= 200ms**, and transitions should respect `prefers-reduced-motion`.
- A11y intent: **visible focus** on all interactive controls; no removal of focus rings unless replaced by a stronger equivalent (e.g. `focus-within` ring on the container).

## Scope

### UI / UX

- Replace remaining heavy Tailwind shadows (`shadow-xl`, `shadow-2xl`) with token shadows (`shadow-soft`, `shadow-strong`).
- Tune a few long entry animations (`duration-500`) down to a snappier default (`duration-300`) where it improves perceived responsiveness.
- Fix focus visibility in several knowledge-module toolbars by removing `focus-visible:ring-0` / `focus:ring-0` overrides and applying a visible container focus ring.
- Reduce token drift in the feedback triage header/toolbar by replacing a few `text-slate-*` usages with semantic tokens (`text-muted-foreground`, etc.).

### FE/BE Integration Ergonomics

- Migrate remaining API failure toasts to `formatApiError(...)` so `request_id` is visible when backend provides it (header or JSON body).
- Small a11y improvements for icon-only actions (add `aria-label` where needed).

## Constraints / Non-goals

- No backend behavior changes in this round.
- Avoid broad refactors; keep edits localized and low-risk.
- Do not introduce new dependencies.

## Verification Gates (end of round)

```bash
make api-check
cd web && pnpm run verify
make verify
```

Notes:
- Corridor MCP tool is not available in this environment; perform manual review for security-sensitive changes (no new SSRF surfaces, no new unsafe URL handling).

