.PHONY: up dev seed demo mock test fmt clean help

help:   ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-8s\033[0m %s\n",$$1,$$2}'

up:     ## docker compose up --build  (the one command)
	docker compose up --build

dev:    ## native dev (no docker) — run each line in its own shell
	@echo "backend : cd backend && uvicorn app.main:app --reload --port 8000"
	@echo "frontend: cd frontend && npm install && npm run dev"

seed:   ## (LLD 11) seed tools + agents + templates into the DB
	cd backend && python -m app.seed

demo:   ## seed DEMO RUNS into the UI (server must be running) — routing + send_message examples
	cd backend && python scripts/seed_demo.py

mock:   ## run the standalone mock IKEA/payments API on :8001 (the IKEA HTTP tools call it)
	cd backend && uvicorn app.mock_api:app --port 8001

test:   ## backend pytest + frontend vitest
	cd backend && pytest -q
	cd frontend && npm run test --silent || true

fmt:    ## ruff lint-fix + format
	cd backend && ruff check --fix . && ruff format .

clean:  ## drop caches + build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/dist
