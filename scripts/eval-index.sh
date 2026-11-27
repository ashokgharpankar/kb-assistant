#!/usr/bin/env bash
# The indexed knowledge base the evaluation runs against in CI (Phase 7c).
#
#   publish  dump the local chunks and embeddings, record their sha256 in
#            eval/index.sha256, upload the dump to the private S3 bucket
#   restore  download that dump, check it matches eval/index.sha256, load it into
#            the database at $DATABASE_URL (CI)
#
# Private S3, not a public GitHub release: the dump contains the documents' text, and
# the repository is public. The checksum is committed, so a new index is a reviewed
# change in a pull request, and CI refuses a dump that doesn't match it.
#
# Bucket: $EVAL_INDEX_BUCKET, or the Terraform output eval_index_bucket.
set -euo pipefail

FILE=kb-index.sql.gz
SUM_FILE=eval/index.sha256
TABLES=(kb_documents kb_ingest_state kb_chunks_ollama_nomic_embed_text_768)
COMPOSE=(docker compose -f infra/local/docker-compose.yml)

bucket() {
  if [[ -n "${EVAL_INDEX_BUCKET:-}" ]]; then
    echo "$EVAL_INDEX_BUCKET"
  else
    terraform -chdir=infra/terraform/envs/dev output -raw eval_index_bucket
  fi
}

publish() {
  "${COMPOSE[@]}" ps --status running --services | grep -qx postgres \
    || { echo "Local Postgres isn't running: run 'make up' first." >&2; exit 1; }
  local out; out=$(mktemp -d)/$FILE
  # Plain SQL (not the custom format), so any psql client can load it.
  "${COMPOSE[@]}" exec -T postgres pg_dump -U kb -d kb --no-owner --no-privileges --clean --if-exists \
    $(printf -- '-t %s ' "${TABLES[@]}") | gzip -9 > "$out"
  local sum; sum=$(sha256sum "$out" | cut -d' ' -f1)
  local chunks; chunks=$("${COMPOSE[@]}" exec -T postgres psql -U kb -d kb -tAc \
    "SELECT count(*) FROM ${TABLES[2]}")
  echo "$sum  $FILE" > "$SUM_FILE"
  local dest; dest="s3://$(bucket)/$FILE"
  aws s3 cp "$out" "$dest" --only-show-errors
  echo "Published $dest ($(du -h "$out" | cut -f1), $chunks chunks), sha256 $sum"
  echo "Commit $SUM_FILE so CI uses this index."
}

restore() {
  : "${DATABASE_URL:?set DATABASE_URL}"
  local dir; dir=$(mktemp -d)
  aws s3 cp "s3://$(bucket)/$FILE" "$dir/$FILE" --only-show-errors
  (cd "$dir" && sha256sum -c "$OLDPWD/$SUM_FILE") \
    || { echo "The published index doesn't match $SUM_FILE: refusing to use it." >&2; exit 1; }
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -c "CREATE EXTENSION IF NOT EXISTS vector"
  gunzip -c "$dir/$FILE" | psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q > /dev/null
  psql "$DATABASE_URL" -tAc "SELECT count(*) || ' chunks loaded' FROM ${TABLES[2]}"
}

case "${1:-}" in
  publish) publish ;;
  restore) restore ;;
  *) echo "usage: $0 publish|restore" >&2; exit 2 ;;
esac
