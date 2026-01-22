.PHONY: help up up-web up-etl4llm up-marker up-paddlevl up-mineru up-olmocr up-dev up-dev-web up-prod up-prod-web infra-up infra-up-etl4llm infra-up-marker infra-up-paddlevl infra-up-mineru infra-up-olmocr infra-ps infra-down down ps logs restart backend web test api-check api-smoke typecheck ui-check lint-py audit-py audit-web audit openapi-export openapi-types openapi-check db-upgrade db-revision verify parser-status clean doctor

PY := python3
ifeq ($(OS),Windows_NT)
PY := python
endif

COMPOSE := docker compose -f docker/docker-compose.yml
COMPOSE_INFRA := docker compose -f docker/docker-compose.infra.yml
COMPOSE_PARSERS := docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml
COMPOSE_INFRA_PARSERS := docker compose -f docker/docker-compose.infra.yml -f docker/docker-compose.parsers.yml
COMPOSE_WEB := docker compose -f docker/docker-compose.yml -f docker/docker-compose.web.yml

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make up-web    - docker compose up + frontend (extra compose file)"
	@echo "  make up-etl4llm - docker compose up + ETL4LLM parser (profile etl4llm)"
	@echo "  make up-marker - docker compose up + Marker parser (profile marker)"
	@echo "  make up-paddlevl - docker compose up + PaddleOCR-VL parser (profile paddlevl)"
	@echo "  make up-mineru - docker compose up + MinerU local API (profile mineru)"
	@echo "  make up-olmocr - docker compose up + olmOCR parser (profile olmocr)"
	@echo "  make up-dev    - alias of up (set UVICORN_RELOAD in docker/.env)"
	@echo "  make up-dev-web - alias of up-web"
	@echo "  make up-prod   - alias of up (set ENV=production/AUTH_MODE/SECRET_KEY in docker/.env)"
	@echo "  make up-prod-web - alias of up-web"
	@echo "  make infra-up  - start infra only (ports exposed)"
	@echo "  make infra-up-etl4llm - infra-up + ETL4LLM parser (profile etl4llm)"
	@echo "  make infra-up-marker - infra-up + Marker parser (profile marker)"
	@echo "  make infra-up-paddlevl - infra-up + PaddleOCR-VL parser (profile paddlevl)"
	@echo "  make infra-up-mineru - infra-up + MinerU local API (profile mineru)"
	@echo "  make infra-up-olmocr - infra-up + olmOCR parser (profile olmocr)"
	@echo "  make infra-ps  - infra docker compose ps"
	@echo "  make infra-down - stop infra only"
	@echo "  make down      - docker compose down"
	@echo "  make ps        - docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make restart   - docker compose restart mimirq-api"
	@echo "  make backend   - run backend locally (uvicorn --reload)"
	@echo "  make web       - run web locally (pnpm dev)"
	@echo "  make test      - run backend tests (pytest)"
	@echo "  make api-check - verify web routes exist in backend"
	@echo "  make api-smoke - smoke-test all OpenAPI endpoints (docker backend)"
	@echo "  make typecheck - run web TypeScript typecheck"
	@echo "  make ui-check  - verify web UI design tokens (no hard-coded white/cyan etc)"
	@echo "  make lint-py   - run Python lint (ruff)"
	@echo "  make audit-py  - audit Python deps (pip-audit)"
	@echo "  make audit-web - audit web deps (pnpm audit)"
	@echo "  make audit     - run both audits"
	@echo "  make openapi-export - write web/openapi.json"
	@echo "  make openapi-types  - generate web/types/openapi.ts"
	@echo "  make openapi-check  - ensure openapi types up-to-date"
	@echo "  make db-upgrade - run Alembic migrations"
	@echo "  make db-revision - create Alembic revision (m=msg)"
	@echo "  make verify    - api-check + web lint/typecheck + backend compileall"
	@echo "  make parser-status - print parser backend availability"
	@echo "  make clean     - remove local caches"
	@echo "  make doctor    - quick env sanity checks"

up:
	$(COMPOSE) up -d --build

up-web:
	$(COMPOSE_WEB) up -d --build

up-etl4llm:
	$(COMPOSE_PARSERS) --profile etl4llm up -d --build

up-marker:
	$(COMPOSE_PARSERS) --profile marker up -d --build

up-paddlevl:
	$(COMPOSE_PARSERS) --profile paddlevl up -d --build

up-mineru:
	$(COMPOSE_PARSERS) --profile mineru up -d --build

up-olmocr:
	$(COMPOSE_PARSERS) --profile olmocr up -d --build

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

infra-up-olmocr:
	$(COMPOSE_INFRA_PARSERS) --profile olmocr up -d --build

infra-ps:
	$(COMPOSE_INFRA) ps

infra-down:
	$(COMPOSE_INFRA) down

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

restart:
	$(COMPOSE) restart mimirq-api

backend:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --reload-dir app --reload-dir scripts --reload-exclude web/node_modules --reload-exclude web/.next --reload-exclude web/.next_build --reload-exclude uploads

web:
	cd web && pnpm dev

test:
	$(PY) -m pytest -q

parser-status:
	$(PY) scripts/check_parsers.py

api-check:
	node web/scripts/check-api-contract.mjs
	node web/scripts/check-api-coverage.mjs

api-smoke:
	$(COMPOSE) exec -T mimirq-api python scripts/api_smoke.py --base-url http://localhost:8000 --skip-llm-test --skip-mineru

typecheck:
	cd web && pnpm run typecheck

ui-check:
	cd web && pnpm run ui-check

lint-py:
	$(PY) -m ruff check app tests scripts main.py

audit-py:
	pip-audit -r requirements.txt --no-deps --disable-pip

audit-web:
	cd web && pnpm audit --prod --audit-level high --ignore-registry-errors

audit:
	@$(MAKE) audit-py
	@$(MAKE) audit-web

openapi-export:
	$(PY) scripts/export_openapi.py --out web/openapi.json

openapi-types:
	@$(MAKE) openapi-export
	cd web && pnpm run gen:api-types

openapi-check:
	@$(MAKE) openapi-types
	$(PY) scripts/openapi_check.py

db-upgrade:
	alembic upgrade head

db-revision:
	alembic revision --autogenerate -m "$(m)"

verify:
	@$(MAKE) lint-py
	@$(MAKE) api-check
	cd web && pnpm run lint
	cd web && pnpm run ui-check
	cd web && pnpm run typecheck
	PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache $(PY) -m compileall -q app

clean:
	$(PY) scripts/clean.py

doctor:
	$(PY) scripts/doctor.py
