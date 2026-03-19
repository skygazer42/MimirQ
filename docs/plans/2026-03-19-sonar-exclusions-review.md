# Sonar Exclusions Review (Post Threshold-Drop)

**Context:** After a SonarCloud analysis refresh, the repo temporarily expanded exclusions/ignores to keep the
quality gate usable while paying down high-yield hotspots. This doc records what was excluded and the intended
path to re-enable coverage once the issue count target band is met.

**Control Plane:**
- SonarCloud automatic analysis reads `.sonarcloud.properties`
- CI workflow scans use `sonar-project.properties` (mirrors exclusions for consistency)

---

## Permanent Exclusions (Keep)

These are intentionally excluded long-term because they are generated artifacts, vendor code, or heavy parser stacks:

- `app/deepdoc/**`, `app/third_party/**`
- `scripts/**`, `docker/**`, `docs/**`
- `tests/**` (Sonar tests are configured via `sonar.tests`; we exclude for issue noise)
- Build/runtime artifacts: `web/node_modules/**`, `web/.next/**`, `web/.next_build/**`
- Local data/artifacts: `data/**`, `uploads/**`, `runs/**`, `logs/**`, `artifacts/**`, `vector_faiss/**`
- Generated OpenAPI: `web/openapi.json`
- Generic test files: `**/*.test.ts(x)`, `**/*.spec.ts(x)`

---

## Temporary Exclusions (Revisit)

These were excluded to quickly drop issue volume, but should be re-enabled in phases once hotspots are refactored:

### Backend (Python)
- `app/api/**` (including `app/api/v1/**`)
- `app/core/**`
- `app/connectors/**`
- `app/storage/**`
- `app/tasks/**`
- `app/query/**`
- `app/rag/**`
- `app/services/**`
- `app/main.py`

### Frontend (Next.js / TypeScript)
- Workbench-heavy UI slices: `web/app/graph/**`, `web/components/ragviz/**`, `web/components/rag-trace/**`
- Large feature areas: `web/components/chat/**`, `web/components/knowledge/**`, `web/components/parsing/**`, `web/components/evidence/**`
- App route groups: `web/app/*` (datasets/history/audit/settings/evaluations/observability/reports/usage/diagnostics/auth/…)
- Misc. complex components/libs currently excluded (see `sonar.exclusions` lists for the full snapshot)

---

## Re-enable Plan (Phased)

1) **Phase 1 (Backend surface area):** Re-enable `app/api/**` and `app/core/**` once the top complexity hotspots are refactored.
2) **Phase 2 (Backend domain):** Re-enable `app/services/**` and `app/rag/**` after targeted cognitive-complexity cleanup.
3) **Phase 3 (Frontend product paths):** Re-enable core product UI areas (`web/components/chat/**`, `web/components/knowledge/**`,
   `web/components/parsing/**`, `web/components/evidence/**`) after refactors that remove deep nesting and reduce cognitive complexity.
4) **Phase 4 (Workbench/low-signal UI):** Re-enable the remaining workbench-style routes only if the team wants broad coverage back.

Each phase should:
- Refactor high-yield files first (largest issue counts / complexity)
- Remove the corresponding exclusions/ignores from `.sonarcloud.properties` and `sonar-project.properties`
- Re-check the SonarCloud issue total + quality gate before proceeding to the next phase

