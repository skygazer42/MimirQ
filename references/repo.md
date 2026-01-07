# MimirQ repo notes

## Common commands

- Start infra deps (Postgres/Milvus/Redis) only: `docker compose up -d postgres etcd minio milvus redis`
- Full stack (needs Docker build): `docker compose up -d --build`
- Backend local run: `python main.py`

## Verification

- Linux/macOS: `make verify` or `scripts/run_verify.sh`
- Windows PowerShell: `scripts/run_verify.ps1`

## OpenAPI -> web types

- Export OpenAPI JSON: `python scripts/export_openapi.py --out web/openapi.json`
- Generate TS types: `cd web && pnpm run gen:api-types`

