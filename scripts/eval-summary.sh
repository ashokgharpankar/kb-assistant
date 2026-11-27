#!/usr/bin/env bash
# Put the newest evaluation report on the GitHub Actions run page.
set -euo pipefail
latest=$(ls -t eval/results/*.md 2>/dev/null | head -1 || true)
if [[ -z "$latest" ]]; then
  echo "No evaluation report was written." | tee -a "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
  exit 0
fi
cat "$latest" >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
