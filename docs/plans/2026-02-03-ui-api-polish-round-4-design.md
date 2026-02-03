# UI + API Polish (Round 4) Design Notes

Date: 2026-02-03

## Goal

Ship another 20 small commits focused on:

- Baseline UI compliance: remove remaining `transition-all`, and replace `window.confirm()` with accessible `AlertDialog` for destructive / irreversible actions.
- FE/BE integration ergonomics: keep quick reachability checks easy (`api-ping`, diagnostics links) and avoid breaking contract checks.

## Scope

### UI / UX (Baseline UI)

- Destructive confirmations:
  - Replace `confirm(...)` calls with `AlertDialog` in high-traffic views.
  - Keep interactions accessible: keyboard, focus trap, `aria-label` on icon-only controls.
- Motion:
  - Prefer targeted transitions (`transition-colors`, `transition-shadow`, `transition-opacity`, `transition-transform`).
  - Avoid layout animations (no `transition-all`, no animating margin/width/max-width).

### Backend Integration

- No backend behavior changes.
- Keep frontend-to-backend reachability scripts and diagnostics stable.

## Constraints

- Minimize behavior changes: only confirmation UX is updated (confirm -> AlertDialog).
- Keep verification green: `make enterprise-checks`.

## Verification Gates (end of round)

```bash
make openapi-check
make enterprise-checks
```

