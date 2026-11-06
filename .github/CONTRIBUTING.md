# Contributing

Thanks for your interest in contributing to MimirQ!

Please read and follow our [Code of Conduct](./CODE_OF_CONDUCT.md).

## Development Setup

Use `feat/ragvia-ui` for ongoing development and push it to `origin/feat/ragvia-ui`. Keep `main` as the baseline.

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
cd web
pnpm install
pnpm dev
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

Common subsets:
```bash
python -m pytest -q
python -m ruff check app tests scripts main.py
python -m ruff format --check app tests scripts main.py
pnpm -C web run lint
pnpm -C web run format:check
pnpm -C web run typecheck
```

Notes:
- We enforce LF line endings via `.gitattributes` (important for Docker/shell scripts).
- If you don't have `make` on Windows, prefer the PowerShell scripts under `scripts/`.

## Code conventions

- Use PEP 8 and the repository's Ruff configuration for Python, with a target line length of 120.
  Put types in function signatures. Comments should explain business rules, constraints and reasons.
- Ordinary Python services are module functions with explicit dependencies. Keep classes for state,
  resource lifecycles, framework requirements and meaningful domain objects.
- Business functions raise specific domain exceptions. Convert them at API, task or CLI boundaries,
  reusing existing exceptions where their response semantics match. Preserve public status codes,
  error payloads and authentication headers when changing internal exception types.
- Validate external input, authentication, tenant scope and transactions at their owning boundaries.
  Check callers and types before removing repeated internal coercions or fallbacks. Unexpected failures
  must remain visible; retries and degradation need an established business contract.
- Keep React components cohesive. Extract a Hook or child component for reuse or an independent responsibility,
  rather than splitting a readable sequence into forwarding functions.
- Declare ordinary named components with `export function`. Keep framework exports, `memo`/`forwardRef`
  wrappers and callback arrow functions where their contracts require them. Private local components may stay private.
- Prefer TypeScript `type` for application objects, Props and unions. Keep `interface` for declaration merging
  and library augmentation.
- ESLint owns code rules. Prettier owns frontend layout: two spaces, single quotes, no trailing semicolons,
  target width 120 and double quotes for JSX attributes. Use the single configuration at the repository root.
- Keep formatting and semantic refactors in separate commits. Migrate a definition and every caller in the
  same batch, and verify real behavior when changing types, exceptions or call boundaries.
- Preserve vendored code, generated files, released migrations and static assets. Record deliberate exceptions
  and file coverage in `docs/maintenance/style-unification/coverage.csv` during this migration.

### Refactoring verification

Run the affected checks and existing tests for each business slice. Before completing a repository-wide change, run:

```bash
python -m ruff check app tests scripts main.py
python -m ruff format --check app tests scripts main.py
python -m pytest -q
pnpm -C web run lint
pnpm -C web run format:check
pnpm -C web run typecheck
pnpm -C web run test
pnpm -C web run ui-check
pnpm -C web run api-check
pnpm -C web run build
```

Use the existing fixed RAG fixtures to check results, ranking and configuration fingerprints.
For local UI/API verification, run only the frontend, API and required PostgreSQL. Leave integration checks
that require parser or model services to the existing CI, and record unavailable checks explicitly.

## Pull Requests

- Keep changes focused and include tests for behavior changes.
- Update docs (`docs/`) when adding or changing user-facing behavior.
- Avoid committing secrets (see `.env.example` templates and CI secret scanning).
- If the PR changes retrieval/ranking behavior, follow the retrieval checklist:
  [`docs/contributing/retrieval_pr_checklist.md`](../docs/contributing/retrieval_pr_checklist.md).

### Commit hygiene (recommended)

- Prefer small, reviewable commits.
- If you touch API contracts, run `make openapi-check` (or the equivalent commands) so `web/types/openapi.ts` stays in sync.
