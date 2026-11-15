#!/usr/bin/env bash
# Runs Langfuse (LLM observability) locally from the OFFICIAL compose file.
#
# Why not copy their compose file into this repo? Langfuse v3 is six containers
# (web, worker, Postgres, ClickHouse, Redis, MinIO) and the file changes between
# releases. Fetching it keeps us on a known-good definition that they maintain.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/local/langfuse"
REF="${LANGFUSE_REF:-main}"   # pin to a release tag once you have it working
URL="https://raw.githubusercontent.com/langfuse/langfuse/${REF}/docker-compose.yml"

case "${1:-}" in
  up)
    mkdir -p "$DIR"
    [ -f "$DIR/docker-compose.yml" ] || curl -fsSL "$URL" -o "$DIR/docker-compose.yml"
    docker compose -p langfuse -f "$DIR/docker-compose.yml" up -d
    echo "Langfuse is starting. Open http://localhost:3000 in a minute or two."
    echo "First visit: sign up (local account), create a project, copy the API keys into .env"
    ;;
  down)   docker compose -p langfuse -f "$DIR/docker-compose.yml" down ;;
  logs)   docker compose -p langfuse -f "$DIR/docker-compose.yml" logs -f --tail=50 ;;
  update) rm -f "$DIR/docker-compose.yml"; "$0" up ;;
  *) echo "usage: $0 {up|down|logs|update}"; exit 2 ;;
esac
