# Baseline Dialog Sweep (20 Commits) Verification

Date: 2026-02-03

## Scope

- Replace remaining native dialogs (`confirm()` / `prompt()`) with Baseline UI dialogs
- Add `ui-check` guard for native dialogs

## Verification Commands

From repo root:

```bash
make enterprise-checks
make openapi-check
```

## Results

- `make enterprise-checks`: OK
  - ruff: OK
  - api-check (contract/coverage): OK
  - web: lint OK, ui-check OK (design-tokens + native-dialogs), typecheck OK
  - python: 568 passed, 3 skipped
  - vitest: 72 passed
- `make openapi-check`: OK (`web/openapi.json` + `web/types/openapi.ts` regenerated)
  - Note: MinerU token warning printed, but MinerU is disabled in this environment.
