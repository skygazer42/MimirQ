.PHONY: help up up-web up-prod up-prod-web down ps logs restart backend web test api-check typecheck lint-py verify parser-status clean

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make up-web    - docker compose up + frontend (profile web)"
	@echo "  make up-prod   - docker compose up (no override file)"
	@echo "  make up-prod-web - docker compose up + frontend (no override file)"
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
	@echo "  make verify    - api-check + web lint/typecheck + backend compileall"
	@echo "  make parser-status - print parser backend availability"
	@echo "  make clean     - remove local caches"

up:
	docker compose up -d --build

up-web:
	docker compose --profile web up -d --build

up-prod:
	docker compose -f docker-compose.yml up -d --build

up-prod-web:
	docker compose -f docker-compose.yml --profile web up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

restart:
	docker compose restart backend

backend:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:
	cd web && pnpm dev

test:
	python3 -m pytest -q

parser-status:
	python3 scripts/check_parsers.py

api-check:
	node scripts/check-api-contract.mjs

typecheck:
	cd web && pnpm run typecheck

lint-py:
	python3 -m ruff check app tests scripts main.py

verify:
	@$(MAKE) lint-py
	@$(MAKE) api-check
	cd web && pnpm run lint
	cd web && pnpm run typecheck
	PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache python3 -m compileall -q app

clean:
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -rf web/.next web/.next_build
