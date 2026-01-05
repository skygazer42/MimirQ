.PHONY: help api-check verify \
	backend-up backend-down backend-ps backend-logs backend-restart backend-test backend-verify \
	frontend-install frontend-dev frontend-build frontend-start frontend-lint

help:
	@echo "MimirQ commands (run from repo root):"
	@echo "  make api-check        - verify frontend routes exist in backend"
	@echo "  make verify           - api-check + backend verify"
	@echo "  make backend-up       - docker compose up (backend stack)"
	@echo "  make backend-down     - docker compose down (backend stack)"
	@echo "  make backend-ps       - docker compose ps (backend stack)"
	@echo "  make backend-logs     - docker compose logs -f (backend stack)"
	@echo "  make backend-restart  - docker compose restart backend"
	@echo "  make backend-test     - run backend tests"
	@echo "  make backend-verify   - run backend verify (includes lint/compile)"
	@echo "  make frontend-install - pnpm install"
	@echo "  make frontend-dev     - pnpm dev"
	@echo "  make frontend-build   - pnpm build"
	@echo "  make frontend-start   - pnpm start"
	@echo "  make frontend-lint    - pnpm lint"

api-check:
	node scripts/check-api-contract.mjs

verify: api-check backend-verify

backend-up:
	$(MAKE) -C backend up

backend-down:
	$(MAKE) -C backend down

backend-ps:
	$(MAKE) -C backend ps

backend-logs:
	$(MAKE) -C backend logs

backend-restart:
	$(MAKE) -C backend restart

backend-test:
	$(MAKE) -C backend test

backend-verify:
	$(MAKE) -C backend verify

frontend-install:
	cd frontend && pnpm install

frontend-dev:
	cd frontend && pnpm dev

frontend-build:
	cd frontend && pnpm build

frontend-start:
	cd frontend && pnpm start

frontend-lint:
	cd frontend && pnpm run lint

