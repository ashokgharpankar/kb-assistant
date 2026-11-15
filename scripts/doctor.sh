#!/usr/bin/env bash
# Checks that every tool Phase 0 needs is installed, and new enough.
set -u

ok=0; bad=0
check() { # name, command, minimum version (informational)
  local name="$1" cmd="$2" min="$3" out
  if out=$(eval "$cmd" 2>&1 | head -n1); then
    printf '  ok    %-12s %s  (need %s)\n' "$name" "$out" "$min"; ok=$((ok+1))
  else
    printf '  MISSING %-10s need %s\n' "$name" "$min"; bad=$((bad+1))
  fi
}

echo "Tool check"
check uv         "uv --version"                   ">= 0.5"
check python     "uv run python --version"        "3.12.x"
check node       "node --version"                 ">= 22"
check docker     "docker --version"               "any recent"
check compose    "docker compose version"         "v2"
check aws        "aws --version"                  ">= 2.32 (for aws login)"
check terraform  "terraform version"              ">= 1.15 (for aws login + S3 backend)"
check tflint     "tflint --version"               "any recent"
check gh         "gh --version"                   "any recent"
check pre-commit "pre-commit --version"           ">= 4"
check gitleaks   "gitleaks version"               ">= 8"
check ollama     "ollama --version"               "any recent"

echo
if docker info >/dev/null 2>&1; then echo "  ok    docker daemon is running"
else echo "  WARN  docker daemon is not running (start OrbStack or Docker Desktop)"; fi

if [ -n "${AWS_PROFILE:-}" ] && aws sts get-caller-identity >/dev/null 2>&1; then
  echo "  ok    AWS login valid for profile ${AWS_PROFILE}: $(aws sts get-caller-identity --query Arn --output text)"
else
  echo "  WARN  no valid AWS login (run: aws login --profile kb-dev, and check AWS_PROFILE)"
fi

echo
echo "$ok found, $bad missing"
[ "$bad" -eq 0 ]
