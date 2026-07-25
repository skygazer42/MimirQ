.PHONY: help init models up up-web up-lite up-retrieval-dev up-etl4llm up-marker up-paddlevl up-mineru up-mineru-vlm up-olmocr up-qianfanocr up-dev up-dev-web up-prod up-prod-web infra-up infra-up-etl4llm infra-up-marker infra-up-paddlevl infra-up-mineru infra-up-mineru-vlm infra-up-olmocr infra-up-qianfanocr infra-ps infra-down down down-lite down-retrieval-dev ps ps-lite ps-retrieval-dev logs logs-lite restart backend backend-no-reload web test test-full test-web test-web-full test-web-e2e test-management-smoke test-matrix perf-smoke api-check api-ping web-api-ping api-smoke typecheck ui-check lint-py lint-py-docker compileall-docker verify-docker audit-py audit-web audit-docs audit openapi-export openapi-types openapi-validate openapi-check api-docs-build api-docs-build-static diagnostics db-upgrade db-revision verify enterprise-checks parser-status dify-console-login dify-console-check dify-console-ensure plugin-release-gate mixed-rag-quality check-retrieval-profile-compat check-queryset-health-policy check-parsing-proof-governance check-parsing-proof-rollout compose-diagnostics helm-template helm-lint clean doctor

# Prefer project venv when available so local dev doesn't depend on global tooling.
PY := python3
VENV_PY := .venv/bin/python
VENV_READY := $(shell if [ -x "$(VENV_PY)" ]; then "$(VENV_PY)" -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('pytest') and u.find_spec('sqlalchemy') and u.find_spec('fastapi') else 1)" >/dev/null 2>&1; echo $$?; else echo 1; fi)
ifeq ($(wildcard $(VENV_PY)),$(VENV_PY))
ifeq ($(VENV_READY),0)
PY := $(VENV_PY)
endif
endif
ifeq ($(OS),Windows_NT)
PY := python
VENV_PY := .venv/Scripts/python.exe
VENV_READY := $(shell if exist "$(VENV_PY)" ("$(VENV_PY)" -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('pytest') and u.find_spec('sqlalchemy') and u.find_spec('fastapi') else 1)" >NUL 2>&1 & echo %ERRORLEVEL%) else echo 1)
ifeq ($(wildcard $(VENV_PY)),$(VENV_PY))
ifeq ($(VENV_READY),0)
PY := $(VENV_PY)
endif
endif
endif

# `PYTHONPYCACHEPREFIX=... cmd` is POSIX-only; keep `make verify` working on Windows.
COMPILEALL_VERIFY := PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache $(PY) -m compileall -q app
ifeq ($(OS),Windows_NT)
COMPILEALL_VERIFY := $(PY) -m compileall -q app
endif

COMPOSE := docker compose --env-file .env -f docker/docker-compose.yml
COMPOSE_INFRA := docker compose --env-file .env -f docker/docker-compose.infra.yml
COMPOSE_PARSERS := docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml
COMPOSE_INFRA_PARSERS := docker compose --env-file .env -f docker/docker-compose.infra.yml -f docker/docker-compose.parsers.yml
COMPOSE_WEB := docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.web.yml
COMPOSE_LITE := docker compose --env-file .env -f docker/docker-compose.lite.yml
COMPOSE_RETRIEVAL_DEV := docker compose --env-file .env -f docker/docker-compose.retrieval-dev.yml
QUERYSET_HEALTH_POLICY ?= ci/queryset_health_policy.v1.json
DIFY_CONSOLE_BASE_URL ?= https://dify.example.com:5001/console/api
DIFY_CONSOLE_ORIGIN ?= https://dify.example.com:3000
DIFY_CONSOLE_UI_BASE_URL ?= https://dify.example.com:3000/brainai
DIFY_CONSOLE_EMAIL ?=
DIFY_CONSOLE_PASSWORD_FILE ?=
DIFY_CONSOLE_MIN_TTL_SECONDS ?= 900
DIFY_CONSOLE_CHECK_OUT ?= /tmp/dify_console_check.json
DIFY_CONSOLE_STORAGE_STATE ?= /tmp/dify_console_storage_state.json
PLUGIN_RELEASE_GATE_PLUGIN_DIR ?=
PLUGIN_RELEASE_GATE_SAMPLE ?=
PLUGIN_RELEASE_GATE_OUT ?= /tmp/mimirq_plugin_release_gate.json
PLUGIN_RELEASE_GATE_EXTRA_ARGS ?=
MIXED_RAG_RUNS ?=
MIXED_RAG_OUT ?= /tmp/mixed_rag_quality_report.json
MIXED_RAG_MD ?= /tmp/mixed_rag_quality_report.md
MIXED_RAG_EXTRA_ARGS ?=
MIMIRQ_TENANT_ID ?= 00000000-0000-0000-0000-000000000000
MIMIRQ_ACCOUNT_ID ?= demo
MIMIRQ_USER_ID ?= demo
MIMIRQ_API_TOKEN ?= $(AUTH_TOKEN)
MIMIRQ_API_TIMEOUT ?= 60
CORE_E2E_BASE_URL ?= http://127.0.0.1:8000
CORE_E2E_OUT ?= artifacts/core-e2e.json
CORE_E2E_BOOTSTRAP_REGISTER ?= 0
CORE_E2E_EXTRA_ARGS ?=
RAG_CONCURRENCY_BASELINE ?=
RAG_CONCURRENCY_CANDIDATE ?=
RAG_CONCURRENCY_OUT ?= artifacts/rag-concurrency-gate.json
RAG_CONCURRENCY_MIN_RETRIEVE_RATIO ?= 1.0
RAG_CONCURRENCY_MIN_CHAT_RATIO ?= 1.0
PYTEST_ARGS ?=
VITEST_ARGS ?=
PLUGIN_HELP_TARGETS ?=
CHANGZHOU_GOV_PLUGIN_MAKEFILE := plugins/pipelines/changzhou-gov-service-knowledge/changzhou-gov-service-knowledge.mk

-include $(wildcard $(CHANGZHOU_GOV_PLUGIN_MAKEFILE))

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make init      - create local env files if missing (.env, web/.env.local)"
	@echo "  make models    - download and verify the pinned DeepDoc model bundle"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make up-web    - initialize local env and start backend + infra + frontend"
	@echo "  make up-lite   - docker compose up (lite: no milvus/minio; chroma by default)"
	@echo "  make up-retrieval-dev - start minimal retrieval-only stack (postgres+redis+api; no parser services)"
	@echo "  make up-etl4llm - docker compose up + ETL4LLM parser (profile etl4llm)"
	@echo "  make up-marker - docker compose up + Marker parser (profile marker)"
	@echo "  make up-paddlevl - docker compose up + PaddleOCR-VL parser (profile paddlevl)"
	@echo "  make up-mineru - docker compose up + MinerU local API (profile mineru)"
	@echo "  make up-mineru-vlm - docker compose up + MinerU API and VLM server (profiles mineru, mineru-vlm)"
	@echo "  make up-olmocr - docker compose up + olmOCR parser (profile olmocr)"
	@echo "  make up-qianfanocr - docker compose up + Qianfan-OCR parser (profile qianfanocr)"
	@echo "  make up-dev    - alias of up (set UVICORN_RELOAD in .env)"
	@echo "  make up-dev-web - alias of up-web"
	@echo "  make up-prod   - run Docker Compose with ENV=production after config preflight"
	@echo "  make up-prod-web - run Docker Compose (backend+web) with ENV=production after config preflight"
	@echo "  make infra-up  - start infra only (ports exposed)"
	@echo "  make infra-up-etl4llm - infra-up + ETL4LLM parser (profile etl4llm)"
	@echo "  make infra-up-marker - infra-up + Marker parser (profile marker)"
	@echo "  make infra-up-paddlevl - infra-up + PaddleOCR-VL parser (profile paddlevl)"
	@echo "  make infra-up-mineru - infra-up + MinerU local API (profile mineru)"
	@echo "  make infra-up-mineru-vlm - infra-up + MinerU API and VLM server (profiles mineru, mineru-vlm)"
	@echo "  make infra-up-olmocr - infra-up + olmOCR parser (profile olmocr)"
	@echo "  make infra-up-qianfanocr - infra-up + Qianfan-OCR parser (profile qianfanocr)"
	@echo "  make infra-ps  - infra docker compose ps"
	@echo "  make infra-down - stop infra only"
	@echo "  make down      - docker compose down"
	@echo "  make down-retrieval-dev - stop retrieval-dev compose stack"
	@echo "  make ps        - docker compose ps"
	@echo "  make ps-retrieval-dev - retrieval-dev docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make restart   - docker compose restart mimirq-api"
	@echo "  make backend   - run backend locally from the project venv (uvicorn --reload)"
	@echo "  make backend-no-reload - run backend locally from the project venv without file watching"
	@echo "  make web       - run web locally (pnpm dev)"
	@echo "  make test      - run all backend tests"
	@echo "  make test-full - compatibility alias for test"
	@echo "  make test-web  - run all frontend unit/integration tests"
	@echo "  make test-web-full - compatibility alias for test-web"
	@echo "  make test-management-smoke - run Playwright smoke against management surfaces"
	@echo "  make test-core-browser-smoke - run upload/parse/chat UI + live backend browser smoke"
	@echo "  make test-matrix - generate full-stack test inventory artifacts"
	@echo "  make perf-smoke - run perf harness in LLM mock mode (writes runs/perf/perf-smoke.json)"
	@echo "  make api-check - verify web routes exist in backend"
	@echo "  make api-ping  - ping backend health endpoints (quick reachability check)"
	@echo "  make web-api-ping - ping backend endpoints using frontend URL logic (NEXT_PUBLIC_API_URL)"
	@echo "  make api-smoke - smoke-test all OpenAPI endpoints on the running backend"
	@echo "  make core-e2e  - verify ready -> ingest -> retrieval against a running host or Docker API"
	@echo "  make rag-concurrency-gate - compare serial and concurrent RAG load reports"
	@echo "  make typecheck - run web TypeScript typecheck"
	@echo "  make ui-check  - verify web UI design tokens (no hard-coded white/cyan etc)"
	@echo "  make lint-py   - run Python lint (ruff)"
	@echo "  make lint-py-docker - run Python lint in Docker (when local env isn't set up)"
	@echo "  make verify-docker - run verify checks using Docker for Python"
	@echo "  make audit-py  - audit Python deps (pip-audit)"
	@echo "  make audit-web - audit web deps (pnpm audit)"
	@echo "  make audit-docs - audit handbook deps (npm audit)"
	@echo "  make audit     - run all dependency audits"
	@echo "  make openapi-export - write web/openapi.json"
	@echo "  make openapi-types  - generate web/types/openapi.ts"
	@echo "  make openapi-validate - verify OpenAPI artifacts are present/clean"
	@echo "  make openapi-check  - ensure OpenAPI artifacts up-to-date (regenerates)"
	@echo "  make api-docs-build - export OpenAPI + build docs/api/site for GitHub Pages (Redoc + openapi.json + handbook/)"
	@echo "  make api-docs-build-static - build docs/api/site from committed web/openapi.json"
	@echo "  make handbook-build - regenerate FE/BE matrix + Docusaurus build into docs/api/site/handbook/"
	@echo "  make diagnostics - run key ops diagnostics (api-ping/api-check/openapi-validate/compose-diagnostics/doctor)"
	@echo "  make db-upgrade - run Alembic migrations"
	@echo "  make db-revision - create Alembic revision (m=msg)"
	@echo "  make verify    - api-check + web lint/typecheck + backend compileall"
	@echo "  make enterprise-checks - verify + backend/web tests (CI-like)"
	@echo "  make parser-status - print parser backend availability"
	@echo "  make dify-console-login - refresh Dify console storage state for trace gates"
	@echo "  make dify-console-ensure - check Dify console storage state, refreshing it when credentials are provided"
	@echo "  make plugin-release-gate - run generic local pipeline-plugin release gate"
	@echo "  make mixed-rag-quality - compare complex mixed RAG runs with deterministic evidence/subquestion scoring"
	@echo "  make check-retrieval-profile-compat - validate retrieval profile + reranker compatibility"
	@echo "  make check-queryset-health-policy - validate query-set health threshold policy JSON"
	@echo "  make check-parsing-proof-governance - validate broader parsing-proof governance JSON"
	@echo "  make check-parsing-proof-rollout - validate broader parsing-proof staged rollout JSON"
	@echo "  make helm-template - helm template smoke (deploy/helm/mimirq)"
	@echo "  make helm-lint  - helm lint (deploy/helm/mimirq)"
	@echo "  make clean     - remove local caches"
	@echo "  make compose-diagnostics - print docker compose status + health as JSON"
	@echo "  make doctor    - quick env sanity checks"
	@for target in $(PLUGIN_HELP_TARGETS); do $(MAKE) --no-print-directory $$target; done

init:
	@# Cross-platform env bootstrap (non-destructive by default).
	@$(PY) scripts/init_env.py

models:
	@$(PY) scripts/bootstrap_mimirq_models.py

up: init
	$(COMPOSE) up -d --build

up-web: init
	$(COMPOSE_WEB) up -d --build

up-lite: init
	$(COMPOSE_LITE) up -d --build

up-retrieval-dev: init
	$(COMPOSE_RETRIEVAL_DEV) up -d --build

up-etl4llm: init
	$(COMPOSE_PARSERS) --profile etl4llm up -d --build

up-marker: init
	$(COMPOSE_PARSERS) --profile marker up -d --build

up-paddlevl: init
	$(COMPOSE_PARSERS) --profile paddlevl up -d --build

up-mineru: init
	$(COMPOSE_PARSERS) --profile mineru up -d --build

up-mineru-vlm: init
	$(COMPOSE_PARSERS) --profile mineru --profile mineru-vlm up -d --build

up-olmocr: init
	$(COMPOSE_PARSERS) --profile olmocr up -d --build

up-qianfanocr: init
	$(COMPOSE_PARSERS) --profile qianfanocr up -d --build

up-dev:
	@$(MAKE) up

up-dev-web:
	@$(MAKE) up-web

.PHONY: prod-preflight
prod-preflight: init
	@ENV=production $(PY) -c "from app.core.config import settings"

up-prod: prod-preflight
	ENV=production $(COMPOSE) up -d --build

up-prod-web: prod-preflight
	ENV=production $(COMPOSE_WEB) up -d --build

infra-up: init
	$(COMPOSE_INFRA) up -d

infra-up-etl4llm: init
	$(COMPOSE_INFRA_PARSERS) --profile etl4llm up -d

infra-up-marker: init
	$(COMPOSE_INFRA_PARSERS) --profile marker up -d --build

infra-up-paddlevl: init
	$(COMPOSE_INFRA_PARSERS) --profile paddlevl up -d --build

infra-up-mineru: init
	$(COMPOSE_INFRA_PARSERS) --profile mineru up -d --build

infra-up-mineru-vlm: init
	$(COMPOSE_INFRA_PARSERS) --profile mineru --profile mineru-vlm up -d --build

infra-up-olmocr: init
	$(COMPOSE_INFRA_PARSERS) --profile olmocr up -d --build

infra-up-qianfanocr: init
	$(COMPOSE_INFRA_PARSERS) --profile qianfanocr up -d --build

infra-ps:
	$(COMPOSE_INFRA) ps

infra-down:
	$(COMPOSE_INFRA) down

down:
	$(COMPOSE) down

down-lite:
	$(COMPOSE_LITE) down

down-retrieval-dev:
	$(COMPOSE_RETRIEVAL_DEV) down

ps:
	$(COMPOSE) ps

ps-lite:
	$(COMPOSE_LITE) ps

ps-retrieval-dev:
	$(COMPOSE_RETRIEVAL_DEV) ps

logs:
	$(COMPOSE) logs -f --tail=200

logs-lite:
	$(COMPOSE_LITE) logs -f --tail=200

restart:
	$(COMPOSE) restart mimirq-api

backend:
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --reload-dir app --reload-dir scripts --reload-exclude web/node_modules --reload-exclude web/.next --reload-exclude web/.next_build --reload-exclude uploads

backend-no-reload:
	$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

web:
	cd web && pnpm dev

test:
	$(PY) -m pytest -q $(PYTEST_ARGS)

test-full: test

test-web:
	cd web && pnpm exec vitest run $(VITEST_ARGS)

test-web-full: test-web

test-web-e2e:
	cd web && PLAYWRIGHT_USE_PROD_SERVER=1 pnpm exec playwright test

test-management-smoke:
	cd web && PLAYWRIGHT_USE_PROD_SERVER=1 pnpm exec playwright test e2e/management-surfaces.smoke.spec.ts

.PHONY: test-core-browser-smoke
test-core-browser-smoke:
	cd web && PLAYWRIGHT_USE_PROD_SERVER=1 pnpm exec playwright test e2e/document-chat.smoke.spec.ts e2e/live-stack.smoke.spec.ts

test-matrix: openapi-export
	@mkdir -p artifacts
	$(PY) scripts/generate_test_coverage_matrix.py --json-out artifacts/test-coverage-matrix.json --markdown-out artifacts/test-coverage-matrix.md

perf-smoke:
	$(PY) scripts/perf/run_perf_suite.py --llm-mock --out runs/perf/perf-smoke.json

parser-status:
	$(PY) scripts/check_parsers.py

dify-console-login:
	$(PY) scripts/dify_console_login.py \
		--console-base-url "$(DIFY_CONSOLE_BASE_URL)" \
		--console-origin "$(DIFY_CONSOLE_ORIGIN)" \
		--email "$(DIFY_CONSOLE_EMAIL)" \
		--password-file "$(DIFY_CONSOLE_PASSWORD_FILE)" \
		--storage-state "$(DIFY_CONSOLE_STORAGE_STATE)" \
		--min-ttl-seconds $(DIFY_CONSOLE_MIN_TTL_SECONDS) \
		--out "$(DIFY_CONSOLE_CHECK_OUT)"

dify-console-check:
	$(PY) scripts/dify_console_login.py \
		--storage-state "$(DIFY_CONSOLE_STORAGE_STATE)" \
		--check \
		--min-ttl-seconds $(DIFY_CONSOLE_MIN_TTL_SECONDS) \
		--out "$(DIFY_CONSOLE_CHECK_OUT)"

dify-console-ensure:
	@set +e; \
	$(MAKE) dify-console-check; rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		exit 0; \
	fi; \
	if [ -n "$(DIFY_CONSOLE_EMAIL)" ] && [ -n "$(DIFY_CONSOLE_PASSWORD_FILE)" ] && [ -f "$(DIFY_CONSOLE_PASSWORD_FILE)" ]; then \
		echo "Dify console storage state is invalid or expiring; refreshing with configured credentials."; \
		$(MAKE) dify-console-login; \
	else \
		echo "Dify console storage state is invalid or expiring, and DIFY_CONSOLE_EMAIL/DIFY_CONSOLE_PASSWORD_FILE are not both available."; \
		exit $$rc; \
	fi

plugin-release-gate:
	@test -n "$(PLUGIN_RELEASE_GATE_PLUGIN_DIR)" || (echo "Set PLUGIN_RELEASE_GATE_PLUGIN_DIR=/path/to/plugin" >&2; exit 2)
	@test -n "$(PLUGIN_RELEASE_GATE_SAMPLE)" || (echo "Set PLUGIN_RELEASE_GATE_SAMPLE=/path/to/sample.json" >&2; exit 2)
	$(PY) scripts/plugin_release_gate.py \
		--plugin-dir "$(PLUGIN_RELEASE_GATE_PLUGIN_DIR)" \
		--sample "$(PLUGIN_RELEASE_GATE_SAMPLE)" \
		--out "$(PLUGIN_RELEASE_GATE_OUT)" \
		$(PLUGIN_RELEASE_GATE_EXTRA_ARGS)

mixed-rag-quality:
	@test -n "$(MIXED_RAG_CASES)" || (echo "MIXED_RAG_CASES is required" >&2; exit 2)
	@test -n "$(MIXED_RAG_RUNS)" || (echo "MIXED_RAG_RUNS is required, e.g. MIXED_RAG_RUNS='mimirq=/tmp/mimirq.json dify=/tmp/dify.json'" >&2; exit 2)
	$(PY) scripts/evaluate_mixed_rag_quality.py \
		--cases "$(MIXED_RAG_CASES)" \
		$(foreach run,$(MIXED_RAG_RUNS),--run "$(run)") \
		--out "$(MIXED_RAG_OUT)" \
		--out-md "$(MIXED_RAG_MD)" \
		$(MIXED_RAG_EXTRA_ARGS)

check-retrieval-profile-compat:
	$(PY) scripts/check_retrieval_profile_compat.py

check-queryset-health-policy:
	$(PY) scripts/validate_queryset_health_policy.py --policy $(QUERYSET_HEALTH_POLICY)

check-parsing-proof-governance:
	$(PY) scripts/validate_parsing_retrieval_proof_governance.py --governance ci/parsing_retrieval_proof_governance.v1.json

check-parsing-proof-rollout:
	$(PY) scripts/validate_parsing_retrieval_proof_rollout.py --rollout ci/parsing_retrieval_proof_rollout.v1.json

compose-diagnostics:
	$(PY) scripts/compose_diagnostics.py

api-check:
	node web/scripts/check-api-contract.mjs
	node web/scripts/check-api-coverage.mjs
	node web/scripts/check-api-types-drift.mjs --strict --baseline web/scripts/api-types-drift-baseline.json

api-ping:
	$(PY) scripts/api_ping.py

web-api-ping:
	cd web && pnpm run api-ping

api-smoke:
	$(PY) scripts/api_smoke.py --base-url http://127.0.0.1:8000 --skip-llm-test --skip-mineru

.PHONY: core-e2e
core-e2e:
	@mkdir -p $(dir $(CORE_E2E_OUT))
	$(PY) scripts/smoke_test.py --base-url "$(CORE_E2E_BASE_URL)" --core-only --out "$(CORE_E2E_OUT)" \
		$(if $(filter 1 true yes on,$(CORE_E2E_BOOTSTRAP_REGISTER)),--bootstrap-register,) \
		$(CORE_E2E_EXTRA_ARGS)

.PHONY: rag-concurrency-gate
rag-concurrency-gate:
	@test -n "$(RAG_CONCURRENCY_BASELINE)" || (echo "Set RAG_CONCURRENCY_BASELINE=<serial-report.json>" >&2; exit 2)
	@test -n "$(RAG_CONCURRENCY_CANDIDATE)" || (echo "Set RAG_CONCURRENCY_CANDIDATE=<concurrent-report.json>" >&2; exit 2)
	$(PY) scripts/rag_e2e_load_test.py \
		--baseline-report "$(RAG_CONCURRENCY_BASELINE)" \
		--candidate-report "$(RAG_CONCURRENCY_CANDIDATE)" \
		--min-retrieve-throughput-ratio "$(RAG_CONCURRENCY_MIN_RETRIEVE_RATIO)" \
		--min-chat-throughput-ratio "$(RAG_CONCURRENCY_MIN_CHAT_RATIO)" \
		--out "$(RAG_CONCURRENCY_OUT)"

typecheck:
	cd web && pnpm run typecheck

ui-check:
	cd web && pnpm run ui-check

lint-py:
	$(PY) -m ruff check app tests scripts main.py

lint-py-docker:
	$(COMPOSE) exec -T -w /app mimirq-api ruff check app scripts main.py

compileall-docker:
	$(COMPOSE) exec -T -w /app mimirq-api python -m compileall -q app

# No patched releases exist for these advisories yet. Keep the exceptions explicit
# and centralized while still resolving and auditing every transitive dependency:
# - Chroma: MimirQ does not expose Chroma's affected HTTP collection endpoint.
# - Ragas: MimirQ does not call the affected multimodal URL evaluator.
# - DiskCache: exploitation requires prior write access to the private cache directory.
# - ecdsa: JWT signing uses the cryptography backend; verification is unaffected.
audit-py:
	$(PY) -m pip_audit -r requirements.txt \
		--ignore-vuln PYSEC-2026-311 \
		--ignore-vuln PYSEC-2026-3046 \
		--ignore-vuln PYSEC-2026-2447 \
		--ignore-vuln PYSEC-2026-1325

audit-web:
	pnpm --dir web audit --prod --audit-level high --registry https://registry.npmjs.org/
	# Remaining unfixed brace-expansion versions are permitted only in bounded build tooling.
	pnpm --dir web audit --audit-level high --json --registry https://registry.npmjs.org/ | $(PY) scripts/check_pnpm_audit.py

audit-docs:
	cd docs-site && npm audit --audit-level=high --registry https://registry.npmjs.org/

audit:
	@$(MAKE) audit-py
	@$(MAKE) audit-web
	@$(MAKE) audit-docs

openapi-export:
	$(PY) scripts/export_openapi.py --out web/openapi.json

openapi-types:
	@$(MAKE) openapi-export
	cd web && pnpm run gen:api-types

openapi-validate:
	$(PY) scripts/openapi_check.py
	node web/scripts/check-openapi-coverage.mjs

openapi-check:
	@$(MAKE) openapi-types
	@$(MAKE) openapi-validate

# Static API docs for GitHub Pages: Redoc + full openapi.json (see docs/api/README.md)
API_DOCS_SITE := docs/api/site
HANDBOOK_MATRIX := docs-site/docs/integration/generated/fe-be-matrix.mdx

.PHONY: handbook-matrix-check handbook-build
# Fail if OpenAPI / web routes changed but generated matrix was not committed.
handbook-matrix-check:
	@$(PY) scripts/docs/generate_fe_be_matrix.py
	@git diff --exit-code -- $(HANDBOOK_MATRIX) || (echo "[handbook] $(HANDBOOK_MATRIX) is out of date. Run: python scripts/docs/generate_fe_be_matrix.py && git add $(HANDBOOK_MATRIX)" && exit 1)

handbook-build: handbook-matrix-check
	cd docs-site && npm ci && npm run build
	@mkdir -p $(API_DOCS_SITE)/handbook
	@rm -rf $(API_DOCS_SITE)/handbook/*
	@cp -a docs-site/build/. $(API_DOCS_SITE)/handbook/
	@echo "[handbook] $(API_DOCS_SITE)/handbook/ (Docusaurus)"

api-docs-build: openapi-export
	@$(PY) scripts/openapi_paths_sanity.py
	@mkdir -p $(API_DOCS_SITE)
	@cp -f web/openapi.json $(API_DOCS_SITE)/openapi.json
	@$(MAKE) handbook-build
	@echo "[api-docs] $(API_DOCS_SITE)/index.html + openapi.json + handbook/ (run: cd $(API_DOCS_SITE) && python3 -m http.server 8765)"

api-docs-build-static:
	@$(PY) scripts/openapi_paths_sanity.py
	@mkdir -p $(API_DOCS_SITE)
	@cp -f web/openapi.json $(API_DOCS_SITE)/openapi.json
	@$(MAKE) handbook-build
	@echo "[api-docs] static $(API_DOCS_SITE)/index.html + openapi.json + handbook/"

diagnostics:
	@$(MAKE) api-ping
	@$(MAKE) api-check
	@$(MAKE) openapi-validate
	@$(MAKE) compose-diagnostics
	@$(MAKE) doctor

.PHONY: parsing-proof-sample
parsing-proof-sample:
	$(PY) scripts/run_sample_parsing_retrieval_proof.py

db-upgrade:
	$(PY) scripts/alembic_cli.py -c alembic.ini upgrade head

db-revision:
	$(PY) scripts/alembic_cli.py -c alembic.ini revision --autogenerate -m "$(m)"

verify:
	@$(MAKE) lint-py
	@$(MAKE) check-queryset-health-policy
	@$(MAKE) check-parsing-proof-governance
	@$(MAKE) check-parsing-proof-rollout
	@$(MAKE) api-check
	node scripts/docs/check_doc_links.mjs
	cd web && pnpm run lint
	cd web && pnpm run typecheck
	$(COMPILEALL_VERIFY)

enterprise-checks:
	@$(MAKE) verify
	@$(MAKE) test
	@$(MAKE) test-web
	@$(MAKE) test-matrix

helm-template:
	helm template mimirq deploy/helm/mimirq -n mimirq >/dev/null

helm-lint:
	helm lint deploy/helm/mimirq

verify-docker:
	@$(MAKE) api-check
	cd web && pnpm run lint
	cd web && pnpm run ui-check
	cd web && pnpm run typecheck
	@$(MAKE) lint-py-docker
	@$(MAKE) compileall-docker

clean:
	$(PY) scripts/clean.py

doctor:
	$(PY) scripts/doctor.py
