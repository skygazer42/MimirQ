# A11y + Motion + Integration DX (20 Commits) Verification

Date: 2026-02-03

## Scope

- Accessibility fixes (native button/label semantics) + reduced-motion/perf baseline tweaks
- Frontend/backend integration DX: toast errors include backend `request_id`

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
  - vitest: 80 passed
- `make openapi-check`: OK (`web/openapi.json` + `web/types/openapi.ts` regenerated)

## Notes

- `make openapi-check` emitted a warning about `MINERU_API_TOKEN` being expired; MinerU stayed disabled and OpenAPI export/typegen still succeeded.
- `pnpm run test` emitted a Vite CJS Node API deprecation warning; Vitest still passed.
- Backend tests emitted a `pynvml` deprecation warning from torch; tests still passed.
- Some integration tests are intentionally skipped unless `MIMIRQ_INTEGRATION_TESTS=1` is set.
