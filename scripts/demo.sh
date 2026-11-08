#!/usr/bin/env bash
# End-to-end demo on SYNTHETIC data: generate -> upload -> process -> (auto) train/score/alerts.
# Requires the stack running (docker compose --profile app up -d) and BITGUARD_BOOTSTRAP_ADMIN_* in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
BASE="${BASE:-http://localhost:8080/api/v1}"; SEED="${SEED:-42}"
PY="${PY:-backend/.venv/bin/python}"
$PY scripts/generate_synthetic.py --seed "$SEED" --formats jsonl --out ml/datasets/synthetic
TOK=$(curl -sf -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$BITGUARD_BOOTSTRAP_ADMIN_EMAIL\",\"password\":\"$BITGUARD_BOOTSTRAP_ADMIN_PASSWORD\"}" | $PY -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOK"
F="ml/datasets/synthetic/bitguard_synthetic_seed${SEED}.jsonl"
DS=$(curl -sf -H "$H" -F "name=demo synthetic seed $SEED" -F provenance=synthetic -F "files=@$F" "$BASE/ingestion/datasets" | $PY -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "dataset $DS uploaded; processing (ingest -> features -> graph -> ML -> risk -> alerts)..."
curl -sf -X POST -H "$H" "$BASE/ingestion/datasets/$DS/process" >/dev/null
for i in $(seq 1 120); do
  S=$(curl -sf -H "$H" "$BASE/ingestion/datasets/$DS" | $PY -c 'import sys,json;print(json.load(sys.stdin)["status"])'); echo "status: $S"
  [ "$S" = processed ] && break; sleep 5
done
curl -sf -H "$H" -F "file=@ml/datasets/synthetic/bitguard_synthetic_seed${SEED}.labels.json" "$BASE/ai/labels/import"; echo
curl -sf -X POST -H "$H" -H 'Content-Type: application/json' -d '{"entity_type":"transaction"}' "$BASE/ai/models/train" >/dev/null
curl -sf -X POST -H "$H" "$BASE/admin/pipeline/rerun?stages=ml&stages=risk&stages=alerts" >/dev/null
curl -sf -H "$H" "$BASE/analytics/overview" | $PY -m json.tool | head -30
echo "Open http://localhost:8080 and sign in as $BITGUARD_BOOTSTRAP_ADMIN_EMAIL"
