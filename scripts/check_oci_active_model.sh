#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${1:-runners-feed-coach-worker-1}"
MODEL_ID=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${COACH_MODEL_ID:-sehyeon-dcc2d7d}"')

echo "COACH_MODEL_ID=$MODEL_ID"
docker exec "$CONTAINER" sha256sum \
  "/app/coach/model_plugins/$MODEL_ID/scripts/hpe/hpe.py" \
  /app/coach/scripts/hpe/hpe.py
docker exec "$CONTAINER" grep -n 'HPE_ENTRYPOINT' /app/coach/scripts/hpe/hpe.sh
