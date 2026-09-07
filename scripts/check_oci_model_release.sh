#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${1:-runners-feed-coach-worker-1}"

echo '=== Container ==='
docker inspect --format 'name={{.Name}}
image_ref={{.Config.Image}}
image_id={{.Image}}
created={{.Created}}
started={{.State.StartedAt}}' "$CONTAINER"

echo '=== Non-secret release environment ==='
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" \
  | grep -E '^(COACH_MODEL_ID|MODEL_RELEASE|COACH_HPE_ENTRYPOINT|COACH_FEATURE_ENTRYPOINT|COACH_AGENT_ENTRYPOINT|COACH_MODEL_PLUGIN_ROOT)=' || true

echo '=== Active entrypoint ==='
docker exec "$CONTAINER" grep -nE 'MODEL_PLUGIN_ROOT|HPE_ENTRYPOINT' /app/coach/scripts/hpe/hpe.sh

echo '=== Active model files ==='
model_id=$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${COACH_MODEL_ID:-sehyeon-dcc2d7d}"')
echo "resolved_model_id=$model_id"
docker exec "$CONTAINER" sha256sum \
  "/app/coach/model_plugins/$model_id/scripts/hpe/hpe.py" \
  "/app/coach/model_plugins/$model_id/model_manifest.json" \
  /workspace/models/detectors/rtmdet-nano-person-320x320/end2end.onnx \
  /workspace/models/pose/rtmpose-m-halpe26-384x288/end2end.onnx

echo '=== Manifest identity ==='
docker exec "$CONTAINER" python -c \
  'import json,sys; d=json.load(open(sys.argv[1])); print("model_id="+d["model_id"]); print("algorithm_version="+d["algorithm_version"]); print("golden_status="+d["quality"]["golden_status"])' \
  "/app/coach/model_plugins/$model_id/model_manifest.json"
