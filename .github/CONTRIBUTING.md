# Contributing

Thanks for your interest in contributing to MimirQ!

Please read and follow our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Development Setup

Prerequisites:
- Python 3.11+
- Node.js 20+ and pnpm (see `web/package.json` for the pinned pnpm version)
- Docker + Docker Compose (recommended for running dependencies)

Bootstrap env files (non-destructive):
```bash
make init
# Windows (no make):
python scripts/init_env.py
```

## Run Locally

Backend (local Python):
```bash
python main.py
```

Windows helper (starts web in a separate PowerShell window):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev_all.ps1
```

Frontend (local):
```bash
pnpm -C web install
pnpm -C web dev
```

Docker (recommended one‑command stack):
```bash
make up
make up-web
```

## Quality Checks

Run the full repo verification:
```bash
make verify

# Windows (no make):
powershell -File scripts/verify.ps1
```

Pre-commit (recommended):
```bash
python -m pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Common subsets:
```bash
python -m pytest -q
python -m ruff check app tests scripts main.py
pnpm -C web run lint
pnpm -C web run typecheck
```

Notes:
- We enforce LF line endings via `.gitattributes` (important for Docker/shell scripts).
- If you don't have `make` on Windows, prefer the PowerShell scripts under `scripts/`.

## Pull Requests

- Keep changes focused and include tests for behavior changes.
- Update docs (`docs/`) when adding or changing user-facing behavior.
- Avoid committing secrets (see `.env.example` templates and CI secret scanning).
- If the PR changes retrieval/ranking behavior, follow the retrieval checklist:
  [`docs/contributing/retrieval_pr_checklist.md`](../docs/contributing/retrieval_pr_checklist.md).

### Commit hygiene (recommended)

- Prefer small, reviewable commits.
- If you touch API contracts, run `make openapi-check` (or the equivalent commands) so `web/types/openapi.ts` stays in sync.
