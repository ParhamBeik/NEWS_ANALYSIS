# One entry point for every routine task. If a command belongs in a contributor's muscle
# memory, it belongs here - and nowhere else, so there is one thing to keep true.
#
# The gates below are the same ones .github/workflows/ci.yml runs. `make ci` is the whole
# set, and running it before a push is the difference between finding a problem here and
# finding it after main has already deployed to production.

SHELL := /bin/bash
PY := backend/.venv/bin/python
COMPOSE_DEV := deploy/docker-compose.dev.yml

.DEFAULT_GOAL := help
.PHONY: help setup services dev test lint check migrations build ci fmt clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sort | awk -F':.*##' '{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create backend/.venv on Python 3.13 and install both dependency sets
	@command -v uv >/dev/null || { echo "uv not found: https://docs.astral.sh/uv/"; exit 1; }
	@# Recreates backend/.venv. It is a virtualenv, not data - but note that it replaces
	@# whatever is there, which is deliberate: a venv on the wrong Python is worse than none.
	uv venv --python 3.13 backend/.venv
	uv pip install --python backend/.venv -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm ci
	@test -f backend/.env || { cp backend/.env.example backend/.env; echo "→ created backend/.env; set GAPGPT_API_KEY"; }

services: ## Start Postgres and Redis for local development
	docker compose -f $(COMPOSE_DEV) up -d

dev: services ## Run the API and the dashboard together (Ctrl-C stops both)
	@trap 'kill 0' EXIT INT TERM; \
	  ( cd backend && ../$(PY) manage.py runserver ) & \
	  ( cd frontend && npm run dev ) & \
	  wait

test: ## Run both test suites
	cd backend && ../$(PY) -m pytest -q
	cd frontend && npm test

lint: ## Lint the backend
	cd backend && ../$(PY) -m ruff check .

check: ## Django system checks, including the strict deploy checks CI runs
	cd backend && ../$(PY) manage.py check
	cd backend && DJANGO_SETTINGS_MODULE=config.settings.prod \
	  DJANGO_SECRET_KEY=local-only-not-a-real-secret-0000000000000000000000000000 \
	  DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=local.invalid POSTGRES_PASSWORD=x \
	  GAPGPT_API_KEY=local-not-real \
	  ../$(PY) manage.py check --deploy --fail-level WARNING

migrations: ## Fail if a model change has no migration
	cd backend && ../$(PY) manage.py makemigrations --check --dry-run

build: ## Production build of the dashboard
	cd frontend && npm run build

ci: lint check migrations test build ## Everything CI checks, in CI's order

fmt: ## Format the backend (NOT enforced by CI - see ARCHITECTURE.md before using)
	cd backend && ../$(PY) -m ruff format .

clean: ## Remove tool caches and build output
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/htmlcov frontend/.next
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
