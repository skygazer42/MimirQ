.PHONY: help up down ps logs restart backend frontend test api-check verify

help:
	@echo "MimirQ dev commands (run from ./backend):"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make down      - docker compose down"
	@echo "  make ps        - docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make restart   - docker compose restart backend"
	@echo "  make backend   - run backend locally (uvicorn --reload)"
	@echo "  make frontend  - run frontend locally (pnpm dev)"
	@echo "  make test      - run backend tests (pytest)"
	@echo "  make api-check - verify frontend routes exist in backend"
	@echo "  make verify    - api-check + frontend lint + backend compileall"

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

frontend:
	cd ../frontend && pnpm dev

test:
	pytest -q

api-check:
	node ../scripts/check-api-contract.mjs

verify:
	@$(MAKE) api-check
	cd ../frontend && pnpm run lint
	PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache python -m compileall -q app
