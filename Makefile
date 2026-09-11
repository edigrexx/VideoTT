.PHONY: up down logs migrate test smoke-test seed first-video list preflight
preflight:
	docker compose exec worker python scripts/check_providers.py
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100 worker runner

migrate:
	docker compose run --rm migrate

test:
	docker compose -f docker-compose.test.yml run --build --rm tests

smoke-test:
	docker compose exec worker python scripts/smoke_test.py

seed:
	docker compose exec worker python scripts/client.py seed

first-video:
	docker compose exec worker python scripts/client.py create --wait

list:
	docker compose exec worker python scripts/client.py list
