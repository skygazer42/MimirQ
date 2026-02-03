# UI + API Polish (20 Commits) Verification

Date: 2026-02-03

## Checks

```bash
make openapi-check
make enterprise-checks
```

Result: ✅ PASS

## Notes

- Added `cd web && pnpm run verify` (one-command web checks) and `cd web && pnpm run api-ping` (backend health/ready reachability).
- Removed layout animation on document viewer margin shifts (`AppFrame` no longer animates `margin`).
- `make openapi-check` emitted a warning about `MINERU_API_TOKEN` being expired; MinerU stayed disabled and OpenAPI export/typegen still succeeded.
- `pnpm run test` emitted a Vite CJS Node API deprecation warning; Vitest still passed.
- Backend tests emitted a `pynvml` deprecation warning from torch; tests still passed.
- Some integration tests are intentionally skipped unless `MIMIRQ_INTEGRATION_TESTS=1` is set.
