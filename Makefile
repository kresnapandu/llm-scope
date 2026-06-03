.PHONY: up down dev test install build migrate logs shell-backend shell-db lint

up:
	docker compose up -d

down:
	docker compose down

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

test:
	cd sdk && python -m pytest tests/ -v --tb=short
	cd backend && python -m pytest tests/ -v --tb=short

install:
	cd sdk && pip install -e ".[all]"
	cd dashboard && npm install

build:
	docker compose build

migrate:
	cd backend && alembic upgrade head

logs:
	docker compose logs -f backend

shell-backend:
	docker compose exec backend bash

shell-db:
	docker compose exec postgres psql -U llmscope

lint:
	ruff check sdk/llmscope backend/app
	mypy sdk/llmscope --ignore-missing-imports

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
