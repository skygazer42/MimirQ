.PHONY: help init up up-web up-lite up-retrieval-dev up-etl4llm up-marker up-paddlevl up-mineru up-mineru-vlm up-olmocr up-qianfanocr up-dev up-dev-web up-prod up-prod-web infra-up infra-up-etl4llm infra-up-marker infra-up-paddlevl infra-up-mineru infra-up-mineru-vlm infra-up-olmocr infra-up-qianfanocr infra-ps infra-down down down-lite down-retrieval-dev ps ps-lite ps-retrieval-dev logs logs-lite restart backend backend-no-reload web test test-web test-management-smoke test-matrix perf-smoke api-check api-ping web-api-ping api-smoke typecheck ui-check lint-py lint-py-docker compileall-docker verify-docker audit-py audit-web audit openapi-export openapi-types openapi-validate openapi-check api-docs-build diagnostics db-upgrade db-revision verify enterprise-checks parser-status dify-console-login dify-console-check dify-console-ensure changzhou-gov-plugin-chunk-report changzhou-gov-plugin-chunk-evidence changzhou-gov-plugin-test-report changzhou-gov-plugin-test-evidence changzhou-gov-plugin-corpus-closed-loop-smoke changzhou-gov-plugin-corpus-closed-loop-evidence changzhou-gov-delivery-pack changzhou-gov-delivery-pack-refresh changzhou-dify-knowledge-map-check changzhou-dify-mimirq-direct-gate changzhou-dify-external-probe changzhou-dify-workflow-lint changzhou-dify-workflow-sync-dry-run changzhou-dify-workflow-sync-apply changzhou-dify-full-gate changzhou-dify-readiness-summary changzhou-dify-readiness-status changzhou-dify-readiness-evidence changzhou-dify-readiness-gate changzhou-dify-readiness-gate-quiet check-retrieval-profile-compat check-queryset-health-policy check-parsing-proof-governance check-parsing-proof-rollout compose-diagnostics helm-template helm-lint clean doctor

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
DIFY_CONSOLE_BASE_URL ?= https://ai.kingdonsoft.com:5001/console/api
DIFY_CONSOLE_ORIGIN ?= https://ai.kingdonsoft.com:3000
DIFY_CONSOLE_UI_BASE_URL ?= https://ai.kingdonsoft.com:3000/brainai
DIFY_CONSOLE_EMAIL ?=
DIFY_CONSOLE_PASSWORD_FILE ?=
DIFY_CONSOLE_MIN_TTL_SECONDS ?= 900
DIFY_CONSOLE_CHECK_OUT ?= /tmp/dify_console_check.json
CHANGZHOU_DIFY_APP_ID ?= 3c1c8b66-94c1-44fb-a09c-b1856d970eb7
CHANGZHOU_DIFY_BASE_URL ?= https://ai.kingdonsoft.com:5001/v1
CHANGZHOU_DIFY_API_KEY_FILE ?= /tmp/dify_remote_app_api_key.json
CHANGZHOU_DIFY_STORAGE_STATE ?= /tmp/kingdonsoft_dify_storage_state.json
CHANGZHOU_DIFY_MIMIRQ_BASE_URL ?= http://127.0.0.1:8000
CHANGZHOU_DIFY_OUT_PREFIX ?= /tmp/changzhou_gov_dify_full_gate
CHANGZHOU_DIFY_CASES ?= plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json
CHANGZHOU_DIFY_EXTRA_ARGS ?=
CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS ?= $(CHANGZHOU_DIFY_EXTRA_ARGS)
CHANGZHOU_DIFY_READINESS_EXTRA_ARGS ?= --min-generated-answer-grounding-rate 0.9 --min-generated-answer-key-point-recall 0.9
CHANGZHOU_DIFY_EXTERNAL_API_ID ?=
CHANGZHOU_DIFY_PROBE_OUT ?= /tmp/changzhou_gov_dify_external_probe.json
CHANGZHOU_DIFY_PROBE_TOP_K ?= 5
CHANGZHOU_DIFY_PROBE_TIMEOUT ?= 45
CHANGZHOU_DIFY_MIMIRQ_ENV_FILE ?= .env
CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT ?= /tmp/changzhou_gov_dify_mimirq_direct_gate.json
CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS ?= --min-hit-at-1 1 --min-answer-grounding-rate 1 --min-answer-key-point-recall 1
CHANGZHOU_DIFY_READINESS_OUT ?= /tmp/changzhou_gov_dify_readiness_summary.json
CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT ?= /tmp/changzhou_gov_dify_readiness_evidence.md
CHANGZHOU_DIFY_READINESS_LOG ?= /tmp/changzhou_gov_dify_readiness_gate.log
CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE ?= .env
CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT ?= /tmp/changzhou_gov_dify_knowledge_map_check.json
CHANGZHOU_DIFY_WORKFLOW_LINT_OUT ?= /tmp/changzhou_gov_dify_workflow_lint.json
CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT ?= /tmp/changzhou_gov_dify_workflow_sanitized.json
CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT ?= /tmp/changzhou_gov_dify_workflow_current_draft_backup.json
CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT ?= /tmp/changzhou_gov_dify_workflow_sync_payload.json
CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT ?= /tmp/changzhou_gov_dify_workflow_sync.json
CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS ?=
CHANGZHOU_GOV_PLUGIN_DIR ?= plugins/pipelines/changzhou-gov-service-knowledge
CHANGZHOU_GOV_PLUGIN_SAMPLE ?= plugins/pipelines/changzhou-gov-service-knowledge/sample.json
CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT ?= /tmp/changzhou_gov_plugin_chunk_report.json
CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD ?= /tmp/changzhou_gov_plugin_chunk_report.md
CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_chunk_evidence.json
CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_chunk_evidence.md
CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT ?= /tmp/changzhou_gov_plugin_test_report.json
CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_test_evidence.json
CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_test_evidence.md
CHANGZHOU_GOV_PLUGIN_REF ?= plugin:changzhou-gov-service-knowledge@1.0.0:chunk
CHANGZHOU_GOV_CORPUS_SOURCE_DIR ?=
CHANGZHOU_GOV_CORPUS_DATASET_ID ?=
CHANGZHOU_GOV_CORPUS_REPORT_OUT ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_report.json
CHANGZHOU_GOV_CORPUS_EVIDENCE_OUT ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.json
CHANGZHOU_GOV_CORPUS_EVIDENCE_MD ?= /tmp/changzhou_gov_plugin_corpus_closed_loop_evidence.md
CHANGZHOU_GOV_CORPUS_EXTENSIONS ?= .txt,.docx,.xlsx,.doc
CHANGZHOU_GOV_CORPUS_MAX_FILES ?= 0
CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_ITEMS ?= 200
CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_CHUNKS ?= 5000
CHANGZHOU_GOV_CORPUS_PROCESSING_TIMEOUT ?= 1800
CHANGZHOU_GOV_CORPUS_POLL_INTERVAL ?= 2
CHANGZHOU_GOV_CORPUS_EXTRA_ARGS ?=
CHANGZHOU_GOV_DELIVERY_PACK_OUT ?= /tmp/changzhou_gov_delivery_pack.json
CHANGZHOU_GOV_DELIVERY_PACK_MD ?= /tmp/changzhou_gov_delivery_pack.md
CHANGZHOU_GOV_DELIVERY_PACK_MAX_READINESS_AGE_MINUTES ?= 30

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make init      - create local env files if missing (.env, web/.env.local)"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make up-web    - docker compose up + frontend (extra compose file)"
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
	@echo "  make up-prod   - alias of up (set ENV=production/AUTH_MODE/SECRET_KEY in .env)"
	@echo "  make up-prod-web - alias of up-web"
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
	@echo "  make test      - run backend tests (pytest)"
	@echo "  make test-web  - run frontend unit/integration tests (vitest)"
	@echo "  make test-management-smoke - run Playwright smoke against management surfaces"
	@echo "  make test-matrix - generate full-stack test coverage matrix artifacts"
	@echo "  make perf-smoke - run perf harness in LLM mock mode (writes runs/perf/perf-smoke.json)"
	@echo "  make api-check - verify web routes exist in backend"
	@echo "  make api-ping  - ping backend health endpoints (quick reachability check)"
	@echo "  make web-api-ping - ping backend endpoints using frontend URL logic (NEXT_PUBLIC_API_URL)"
	@echo "  make api-smoke - smoke-test all OpenAPI endpoints (docker backend)"
	@echo "  make typecheck - run web TypeScript typecheck"
	@echo "  make ui-check  - verify web UI design tokens (no hard-coded white/cyan etc)"
	@echo "  make lint-py   - run Python lint (ruff)"
	@echo "  make lint-py-docker - run Python lint in Docker (when local env isn't set up)"
	@echo "  make verify-docker - run verify checks using Docker for Python"
	@echo "  make audit-py  - audit Python deps (pip-audit)"
	@echo "  make audit-web - audit web deps (pnpm audit)"
	@echo "  make audit     - run both audits"
	@echo "  make openapi-export - write web/openapi.json"
	@echo "  make openapi-types  - generate web/types/openapi.ts"
	@echo "  make openapi-validate - verify OpenAPI artifacts are present/clean"
	@echo "  make openapi-check  - ensure OpenAPI artifacts up-to-date (regenerates)"
	@echo "  make api-docs-build - export OpenAPI + build docs/api/site for GitHub Pages (Redoc + openapi.json + handbook/)"
	@echo "  make handbook-build - regenerate FE/BE matrix + Docusaurus build into docs/api/site/handbook/"
	@echo "  make diagnostics - run key ops diagnostics (api-ping/api-check/openapi-validate/compose-diagnostics/doctor)"
	@echo "  make db-upgrade - run Alembic migrations"
	@echo "  make db-revision - create Alembic revision (m=msg)"
	@echo "  make verify    - api-check + web lint/typecheck + backend compileall"
	@echo "  make enterprise-checks - verify + backend/web tests (CI-like)"
	@echo "  make parser-status - print parser backend availability"
	@echo "  make dify-console-login - refresh Dify console storage state for trace gates"
	@echo "  make dify-console-ensure - check Dify console storage state, refreshing it when credentials are provided"
	@echo "  make changzhou-gov-plugin-chunk-report - write Changzhou plugin governance/chunk/KG review report"
	@echo "  make changzhou-gov-plugin-chunk-evidence - write shareable sanitized plugin chunk evidence"
	@echo "  make changzhou-gov-plugin-test-report - write Changzhou plugin local test + Golden draft report"
	@echo "  make changzhou-gov-plugin-test-evidence - write shareable sanitized plugin test evidence"
	@echo "  make changzhou-gov-plugin-corpus-closed-loop-smoke - live ingest a corpus with the plugin and run Golden retrieval"
	@echo "  make changzhou-gov-plugin-corpus-closed-loop-evidence - sanitize the live corpus closed-loop smoke report"
	@echo "  make changzhou-gov-delivery-pack - write combined Changzhou plugin + Dify readiness handoff pack"
	@echo "  make changzhou-gov-delivery-pack-refresh - quietly refresh remote readiness, then write delivery pack"
	@echo "  make changzhou-dify-knowledge-map-check - validate local Changzhou Dify knowledge map routes"
	@echo "  make changzhou-dify-mimirq-direct-gate - run MimirQ-only Changzhou golden retrieval gate"
	@echo "  make changzhou-dify-external-probe - compare Dify external hit-testing with direct MimirQ retrieval"
	@echo "  make changzhou-dify-workflow-lint - lint and write a sanitized Changzhou Dify draft workflow JSON"
	@echo "  make changzhou-dify-workflow-sync-dry-run - stage Changzhou Dify draft sync without writing remote state"
	@echo "  make changzhou-dify-workflow-sync-apply - explicitly write the staged Changzhou Dify draft workflow"
	@echo "  make changzhou-dify-full-gate - run Changzhou Dify/MimirQ remote golden gate"
	@echo "  make changzhou-dify-readiness-gate - run external probe, full Dify/MimirQ gate, and write readiness summary"
	@echo "  make changzhou-dify-readiness-gate-quiet - run readiness gate with raw output redirected to a local log"
	@echo "  make changzhou-dify-readiness-status - print compact readiness status from the latest summary"
	@echo "  make changzhou-dify-readiness-evidence - write PII-safe Markdown readiness evidence"
	@echo "  make check-retrieval-profile-compat - validate retrieval profile + reranker compatibility"
	@echo "  make check-queryset-health-policy - validate query-set health threshold policy JSON"
	@echo "  make check-parsing-proof-governance - validate broader parsing-proof governance JSON"
	@echo "  make check-parsing-proof-rollout - validate broader parsing-proof staged rollout JSON"
	@echo "  make helm-template - helm template smoke (deploy/helm/mimirq)"
	@echo "  make helm-lint  - helm lint (deploy/helm/mimirq)"
	@echo "  make clean     - remove local caches"
	@echo "  make compose-diagnostics - print docker compose status + health as JSON"
	@echo "  make doctor    - quick env sanity checks"

init:
	@# Cross-platform env bootstrap (non-destructive by default).
	@$(PY) scripts/init_env.py

up:
	$(COMPOSE) up -d --build

up-web:
	$(COMPOSE_WEB) up -d --build

up-lite:
	$(COMPOSE_LITE) up -d --build

up-retrieval-dev:
	$(COMPOSE_RETRIEVAL_DEV) up -d --build

up-etl4llm:
	$(COMPOSE_PARSERS) --profile etl4llm up -d --build

up-marker:
	$(COMPOSE_PARSERS) --profile marker up -d --build

up-paddlevl:
	$(COMPOSE_PARSERS) --profile paddlevl up -d --build

up-mineru:
	$(COMPOSE_PARSERS) --profile mineru up -d --build

up-mineru-vlm:
	$(COMPOSE_PARSERS) --profile mineru --profile mineru-vlm up -d --build

up-olmocr:
	$(COMPOSE_PARSERS) --profile olmocr up -d --build

up-qianfanocr:
	$(COMPOSE_PARSERS) --profile qianfanocr up -d --build

up-dev:
	@$(MAKE) up

up-dev-web:
	@$(MAKE) up-web

up-prod:
	@$(MAKE) up

up-prod-web:
	@$(MAKE) up-web

infra-up:
	$(COMPOSE_INFRA) up -d

infra-up-etl4llm:
	$(COMPOSE_INFRA_PARSERS) --profile etl4llm up -d

infra-up-marker:
	$(COMPOSE_INFRA_PARSERS) --profile marker up -d --build

infra-up-paddlevl:
	$(COMPOSE_INFRA_PARSERS) --profile paddlevl up -d --build

infra-up-mineru:
	$(COMPOSE_INFRA_PARSERS) --profile mineru up -d --build

infra-up-mineru-vlm:
	$(COMPOSE_INFRA_PARSERS) --profile mineru --profile mineru-vlm up -d --build

infra-up-olmocr:
	$(COMPOSE_INFRA_PARSERS) --profile olmocr up -d --build

infra-up-qianfanocr:
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
	$(PY) -m pytest -q

test-web:
	cd web && pnpm run test

test-management-smoke:
	cd web && PLAYWRIGHT_USE_PROD_SERVER=1 pnpm exec playwright test e2e/management-surfaces.smoke.spec.ts

test-matrix:
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
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--min-ttl-seconds $(DIFY_CONSOLE_MIN_TTL_SECONDS) \
		--out "$(DIFY_CONSOLE_CHECK_OUT)"

dify-console-check:
	$(PY) scripts/dify_console_login.py \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
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

changzhou-dify-external-probe:
	$(PY) scripts/changzhou_gov_dify_external_knowledge_probe.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--external-api-id "$(CHANGZHOU_DIFY_EXTERNAL_API_ID)" \
		--console-base-url "$(DIFY_CONSOLE_BASE_URL)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--out "$(CHANGZHOU_DIFY_PROBE_OUT)"

changzhou-gov-plugin-chunk-report:
	$(PY) scripts/changzhou_gov_plugin_chunk_report.py \
		--plugin-dir "$(CHANGZHOU_GOV_PLUGIN_DIR)" \
		--input "$(CHANGZHOU_GOV_PLUGIN_SAMPLE)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_MD)"

changzhou-gov-plugin-chunk-evidence: changzhou-gov-plugin-chunk-report
	$(PY) scripts/changzhou_gov_plugin_chunk_evidence.py \
		--input "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD)"

changzhou-gov-plugin-test-report:
	@mkdir -p "$$(dirname "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)")"
	$(PY) scripts/pipeline_plugin_runner.py test "$(CHANGZHOU_GOV_PLUGIN_DIR)" \
		--input "$(CHANGZHOU_GOV_PLUGIN_SAMPLE)" \
		--stage governance \
		--stage chunk \
		--stage kg \
		--no-write-report >"$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)"

changzhou-gov-plugin-test-evidence: changzhou-gov-plugin-test-report
	$(PY) scripts/changzhou_gov_plugin_test_evidence.py \
		--input "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_MD)"

changzhou-gov-plugin-corpus-closed-loop-smoke:
	@test -n "$(CHANGZHOU_GOV_CORPUS_SOURCE_DIR)" || (echo "Set CHANGZHOU_GOV_CORPUS_SOURCE_DIR=/path/to/corpus" >&2; exit 2)
	$(PY) scripts/plugin_corpus_closed_loop_smoke.py \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--source-dir "$(CHANGZHOU_GOV_CORPUS_SOURCE_DIR)" \
		--dataset-id "$(CHANGZHOU_GOV_CORPUS_DATASET_ID)" \
		--plugin-ref "$(CHANGZHOU_GOV_PLUGIN_REF)" \
		--extensions "$(CHANGZHOU_GOV_CORPUS_EXTENSIONS)" \
		--max-files $(CHANGZHOU_GOV_CORPUS_MAX_FILES) \
		--golden-max-items $(CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_ITEMS) \
		--golden-max-chunks $(CHANGZHOU_GOV_CORPUS_GOLDEN_MAX_CHUNKS) \
		--processing-timeout $(CHANGZHOU_GOV_CORPUS_PROCESSING_TIMEOUT) \
		--poll-interval $(CHANGZHOU_GOV_CORPUS_POLL_INTERVAL) \
		$(CHANGZHOU_GOV_CORPUS_EXTRA_ARGS) >"$(CHANGZHOU_GOV_CORPUS_REPORT_OUT)"

changzhou-gov-plugin-corpus-closed-loop-evidence:
	$(PY) scripts/plugin_corpus_closed_loop_evidence.py \
		--input "$(CHANGZHOU_GOV_CORPUS_REPORT_OUT)" \
		--json-out "$(CHANGZHOU_GOV_CORPUS_EVIDENCE_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_CORPUS_EVIDENCE_MD)"

changzhou-gov-delivery-pack: changzhou-gov-plugin-chunk-evidence changzhou-gov-plugin-test-evidence changzhou-dify-readiness-evidence
	$(PY) scripts/changzhou_gov_delivery_pack.py \
		--plugin-report "$(CHANGZHOU_GOV_PLUGIN_CHUNK_REPORT_OUT)" \
		--plugin-chunk-evidence "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_OUT)" \
		--plugin-chunk-evidence-markdown "$(CHANGZHOU_GOV_PLUGIN_CHUNK_EVIDENCE_MD)" \
		--plugin-test-report "$(CHANGZHOU_GOV_PLUGIN_TEST_REPORT_OUT)" \
		--plugin-test-evidence "$(CHANGZHOU_GOV_PLUGIN_TEST_EVIDENCE_OUT)" \
		--readiness-summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--readiness-evidence "$(CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT)" \
		--max-readiness-age-minutes $(CHANGZHOU_GOV_DELIVERY_PACK_MAX_READINESS_AGE_MINUTES) \
		--json-out "$(CHANGZHOU_GOV_DELIVERY_PACK_OUT)" \
		--markdown-out "$(CHANGZHOU_GOV_DELIVERY_PACK_MD)"

changzhou-gov-delivery-pack-refresh: changzhou-dify-readiness-gate-quiet changzhou-gov-delivery-pack

changzhou-dify-workflow-lint:
	$(PY) scripts/changzhou_gov_dify_workflow_lint.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--preflight-gate \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_LINT_OUT)" \
		--patched-workflow-out "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)"

changzhou-dify-workflow-sync-dry-run:
	$(PY) scripts/changzhou_gov_dify_workflow_sync.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--workflow-json "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--backup-out "$(CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT)" \
		--payload-out "$(CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT)" \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT)" \
		$(CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS)

changzhou-dify-workflow-sync-apply:
	$(PY) scripts/changzhou_gov_dify_workflow_sync.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--workflow-json "$(CHANGZHOU_DIFY_WORKFLOW_SANITIZED_OUT)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--backup-out "$(CHANGZHOU_DIFY_WORKFLOW_BACKUP_OUT)" \
		--payload-out "$(CHANGZHOU_DIFY_WORKFLOW_PAYLOAD_OUT)" \
		--out "$(CHANGZHOU_DIFY_WORKFLOW_SYNC_OUT)" \
		--apply \
		$(CHANGZHOU_DIFY_WORKFLOW_SYNC_EXTRA_ARGS)

changzhou-dify-knowledge-map-check:
	$(PY) scripts/changzhou_gov_dify_knowledge_map_check.py \
		--env-file "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_ENV_FILE)" \
		--out "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)"

changzhou-dify-mimirq-direct-gate:
	$(PY) scripts/changzhou_gov_golden_eval.py \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--env-file "$(CHANGZHOU_DIFY_MIMIRQ_ENV_FILE)" \
		--top-k $(CHANGZHOU_DIFY_PROBE_TOP_K) \
		--timeout $(CHANGZHOU_DIFY_PROBE_TIMEOUT) \
		--out "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" \
		$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_EXTRA_ARGS)

changzhou-dify-readiness-gate: CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS = $(CHANGZHOU_DIFY_EXTRA_ARGS) $(CHANGZHOU_DIFY_READINESS_EXTRA_ARGS)
changzhou-dify-readiness-gate:
	@set +e; \
	rm -f "$(CHANGZHOU_DIFY_PROBE_OUT)" "$(CHANGZHOU_DIFY_OUT_PREFIX).json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		"$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		"$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)" "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" "$(DIFY_CONSOLE_CHECK_OUT)"; \
	$(MAKE) changzhou-dify-knowledge-map-check; map_rc=$$?; \
	if [ $$map_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-mimirq-direct-gate; direct_rc=$$?; \
	else \
		direct_rc=1; \
	fi; \
	if [ $$map_rc -eq 0 ] && [ $$direct_rc -eq 0 ]; then \
		$(MAKE) dify-console-ensure; auth_rc=$$?; \
	else \
		auth_rc=1; \
	fi; \
	if [ $$map_rc -eq 0 ] && [ $$direct_rc -eq 0 ] && [ $$auth_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-external-probe; probe_rc=$$?; \
	else \
		probe_rc=1; \
	fi; \
	if [ $$auth_rc -eq 0 ] && [ $$probe_rc -eq 0 ]; then \
		$(MAKE) changzhou-dify-full-gate CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS="$(CHANGZHOU_DIFY_EXTRA_ARGS) $(CHANGZHOU_DIFY_READINESS_EXTRA_ARGS)"; full_rc=$$?; \
	else \
		full_rc=1; \
	fi; \
	$(MAKE) changzhou-dify-readiness-summary; summary_rc=$$?; \
	if [ $$map_rc -ne 0 ] || [ $$direct_rc -ne 0 ] || [ $$auth_rc -ne 0 ] || [ $$probe_rc -ne 0 ] || [ $$full_rc -ne 0 ] || [ $$summary_rc -ne 0 ]; then \
		exit 1; \
	fi

changzhou-dify-readiness-gate-quiet:
	@set +e; \
	$(MAKE) --no-print-directory changzhou-dify-readiness-gate >"$(CHANGZHOU_DIFY_READINESS_LOG)" 2>&1; rc=$$?; \
	$(MAKE) --no-print-directory changzhou-dify-readiness-status; \
	echo "Readiness raw log: $(CHANGZHOU_DIFY_READINESS_LOG)"; \
	exit $$rc

changzhou-dify-readiness-summary:
	$(PY) scripts/changzhou_gov_dify_readiness_summary.py \
		--knowledge-map "$(CHANGZHOU_DIFY_KNOWLEDGE_MAP_OUT)" \
		--mimirq-direct "$(CHANGZHOU_DIFY_MIMIRQ_DIRECT_OUT)" \
		--console-auth "$(DIFY_CONSOLE_CHECK_OUT)" \
		--external-probe "$(CHANGZHOU_DIFY_PROBE_OUT)" \
		--full-summary "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" \
		--answers "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		--eval "$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" \
		--trace "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" \
		--out "$(CHANGZHOU_DIFY_READINESS_OUT)"

changzhou-dify-readiness-status:
	$(PY) scripts/changzhou_gov_dify_readiness_status.py \
		--summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--console-ui-base-url "$(DIFY_CONSOLE_UI_BASE_URL)" \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" || true

changzhou-dify-readiness-evidence:
	$(PY) scripts/changzhou_gov_dify_readiness_status.py \
		--summary "$(CHANGZHOU_DIFY_READINESS_OUT)" \
		--console-ui-base-url "$(DIFY_CONSOLE_UI_BASE_URL)" \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--markdown-out "$(CHANGZHOU_DIFY_READINESS_EVIDENCE_OUT)"

changzhou-dify-full-gate:
	$(PY) scripts/changzhou_gov_dify_full_gate.py \
		--app-id "$(CHANGZHOU_DIFY_APP_ID)" \
		--cases "$(CHANGZHOU_DIFY_CASES)" \
		--dify-base-url "$(CHANGZHOU_DIFY_BASE_URL)" \
		--dify-api-key-file "$(CHANGZHOU_DIFY_API_KEY_FILE)" \
		--storage-state "$(CHANGZHOU_DIFY_STORAGE_STATE)" \
		--mimirq-base-url "$(CHANGZHOU_DIFY_MIMIRQ_BASE_URL)" \
		--out "$(CHANGZHOU_DIFY_OUT_PREFIX).json" \
		--answers-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_answers.json" \
		--eval-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_eval.json" \
		--trace-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_trace.json" \
		--summary-out "$(CHANGZHOU_DIFY_OUT_PREFIX)_summary.json" \
		$(CHANGZHOU_DIFY_EFFECTIVE_EXTRA_ARGS)

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
	node web/scripts/check-api-types-drift.mjs

api-ping:
	$(PY) scripts/api_ping.py

web-api-ping:
	cd web && pnpm run api-ping

api-smoke:
	$(COMPOSE) exec -T -w /app mimirq-api python scripts/api_smoke.py --base-url http://localhost:8000 --skip-llm-test --skip-mineru

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

audit-py:
	pip-audit -r requirements.txt --no-deps --disable-pip --extra-index-url https://download.pytorch.org/whl/cpu

audit-web:
	cd web && pnpm audit --prod --audit-level high --registry https://registry.npmjs.org/ --ignore-registry-errors

audit:
	@$(MAKE) audit-py
	@$(MAKE) audit-web

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
	cd web && pnpm run lint
	cd web && pnpm run ui-check
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
