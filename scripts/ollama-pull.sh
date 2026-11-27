#!/usr/bin/env bash
# Pull Ollama models through the HTTP API (the CI service container has no shell step).
# Usage: scripts/ollama-pull.sh MODEL [MODEL...]   (OLLAMA at $KB_OLLAMA_BASE_URL)
set -euo pipefail
base=${KB_OLLAMA_BASE_URL:-http://localhost:11434}
for model in "$@"; do
  echo "Pulling $model…"
  curl -fsS --max-time 900 "$base/api/pull" -d "{\"model\": \"$model\", \"stream\": false}" \
    | grep -q '"status":"success"' || { echo "Pull of $model failed" >&2; exit 1; }
done
curl -fsS "$base/api/tags" | python3 -c "import sys,json; print('Models:', ', '.join(m['name'] for m in json.load(sys.stdin)['models']))"
