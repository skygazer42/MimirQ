# UI + API Polish (Round 5) Design Notes

Date: 2026-02-04

## Goal

Ship another 20 small commits focused on:

- Baseline UI compliance: reduce heavy blur usage (especially `backdrop-blur-xl`), avoid slow (>200ms) interaction transitions, and keep surfaces token-first.
- A11y + consistency: migrate any remaining custom "modal" overlays to Radix/shadcn `Dialog` for focus management and keyboard support.
- FE/BE integration ergonomics: make it easier to spot backend failures (request_id surfaced in toasts) and document the fastest local ping workflow.

## Scope

### UI / UX

- Reduce `backdrop-blur-xl` in dataset-related dialogs (profile / ingestion / precheck).
- Tighten micro-interactions:
  - Prefer `transition-colors|shadow|opacity|transform`.
  - Keep interaction durations <= 200ms.
- Token-first tweaks:
  - Replace remaining `*-slate-*` class usage in UI surfaces where appropriate (prefer `border-border`, `text-muted-foreground`, etc.).
- Improve error surfaces:
  - Use `formatApiError(...)` so request_id is visible when backend provides it.

### Backend Integration

- No backend behavior changes.
- Keep existing verification gates green:
  - API contract & coverage scripts
  - OpenAPI export + typegen
  - Combined CI-like checks
- Update docs to include `make web-api-ping` as the quickest reachability check.

## Constraints / Non-goals

- No API shape changes; only frontend calls / error handling / UI polish.
- Avoid broad refactors; prefer localized, low-risk edits.
- Do not introduce new dependencies.

## Verification Gates (end of round)

```bash
make openapi-check
make enterprise-checks
```

