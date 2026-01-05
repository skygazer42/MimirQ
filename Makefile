.PHONY: help up down ps logs restart backend web test api-check verify parser-status

help:
	@echo "MimirQ dev commands (run from repo root):"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make down      - docker compose down"
	@echo "  make ps        - docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make restart   - docker compose restart backend"
	@echo "  make backend   - run backend locally (uvicorn --reload)"
	@echo "  make web       - run web locally (pnpm dev)"
	@echo "  make test      - run backend tests (pytest)"
	@echo "  make api-check - verify web routes exist in backend"
	@echo "  make verify    - api-check + web lint + backend compileall"
	@echo "  make parser-status - print parser backend availability"

up:
	docker compose up -d --build

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

verify:
	@$(MAKE) api-check
	cd web && pnpm run lint
	PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache python3 -m compileall -q app
