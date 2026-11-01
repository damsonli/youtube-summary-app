.PHONY: up down logs build test lint-web

up:            ## build and start
	docker compose up --build -d
down:
	docker compose down
logs:
	docker compose logs -f app
build:
	docker compose build
test:          ## backend lint + tests (runs inside a build stage)
	docker build --target test .
lint-web:      ## frontend lint + build check
	docker run --rm -v "$(CURDIR)/frontend:/web" -w /web node:26.13.0-alpine3.24 \
	  sh -c 'npm ci --no-audit --no-fund && npm run lint && npm run build; rm -rf node_modules dist'
