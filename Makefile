.PHONY: help up up-web up-dev up-dev-web up-prod up-prod-web down ps logs restart backend web test api-check typecheck lint-py audit-py audit-web audit openapi-export openapi-types openapi-check db-upgrade db-revision verify parser-status clean

PY := python3
ifeq ($(OS),Windows_NT)
PY := python
endif

COMPOSE := docker compose -f docker-compose.yml
COMPOSE_DEV := docker compose -f docker-compose.yml -f docker-compose.override.yml
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make up-web    - docker compose up + frontend (profile web)"
	@echo "  make up-dev    - docker compose up (dev override + reload)"
	@echo "  make up-dev-web - docker compose up (dev override + web profile)"
	@echo "  make up-prod   - docker compose up (production stack)"
	@echo "  make up-prod-web - docker compose up (production + web profile)"
	@echo "  make down      - docker compose down"
	@echo "  make ps        - docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make restart   - docker compose restart backend"
	@echo "  make backend   - run backend locally (uvicorn --reload)"
	@echo "  make web       - run web locally (pnpm dev)"
	@echo "  make test      - run backend tests (pytest)"
	@echo "  make api-check - verify web routes exist in backend"
	@echo "  make typecheck - run web TypeScript typecheck"
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

up:
	$(COMPOSE) up -d --build

up-web:
	$(COMPOSE) --profile web up -d --build

up-dev:
	$(COMPOSE_DEV) up -d --build

up-dev-web:
	$(COMPOSE_DEV) --profile web up -d --build

up-prod:
	$(COMPOSE_PROD) up -d --build

up-prod-web:
	$(COMPOSE_PROD) --profile web up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

restart:
	$(COMPOSE) restart backend

backend:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:
	cd web && pnpm dev

test:
	$(PY) -m pytest -q

parser-status:
	$(PY) scripts/check_parsers.py

api-check:
	node scripts/check-api-contract.mjs

typecheck:
	cd web && pnpm run typecheck

lint-py:
	$(PY) -m ruff check app tests scripts main.py

audit-py:
	pip-audit -r requirements-minimal.txt --no-deps --disable-pip

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
	test -s web/types/openapi.ts

db-upgrade:
	alembic upgrade head

db-revision:
	alembic revision --autogenerate -m "$(m)"

verify:
	@$(MAKE) lint-py
	@$(MAKE) api-check
	cd web && pnpm run lint
	cd web && pnpm run typecheck
	PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache $(PY) -m compileall -q app

clean:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -rf web/.next web/.next_build
