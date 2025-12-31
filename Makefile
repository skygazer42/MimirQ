.PHONY: help up down ps logs backend frontend test

help:
	@echo "MimirQ dev commands:"
	@echo "  make up        - docker compose up (build + detach)"
	@echo "  make down      - docker compose down"
	@echo "  make ps        - docker compose ps"
	@echo "  make logs      - docker compose logs -f"
	@echo "  make backend   - run backend locally (uvicorn --reload)"
	@echo "  make frontend  - run frontend locally (next dev)"
	@echo "  make test      - run backend tests (pytest)"

up:
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest -q

