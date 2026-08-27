.PHONY: up down logs test build

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

build:
	docker compose build

test:
	python3 -m unittest discover -s api/tests -v
	python3 -m py_compile api/app/*.py sandbox/server.py browser/server.py
	cd frontend && npm ci --no-audit --no-fund && npm run build
