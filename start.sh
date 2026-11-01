#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit it (AI provider, email), then run ./start.sh again."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker and try again."
  exit 1
fi

docker compose up --build -d
port=$(grep -E '^APP_PORT=' .env | cut -d= -f2 || true)
echo "YouTube Digest is running at http://localhost:${port:-8090}"
echo "Logs: docker compose logs -f    Stop: docker compose down"
