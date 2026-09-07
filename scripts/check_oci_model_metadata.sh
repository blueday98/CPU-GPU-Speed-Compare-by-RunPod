#!/usr/bin/env bash
set -euo pipefail

MODEL_ROOT="${1:-/home/ubuntu/runners-feed-runtime/models}"
CONTAINER="${2:-runners-feed-coach-worker-1}"

print_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "MISSING $path"
    return
  fi
  stat --printf='path=%n\nsize=%s\nmtime=%y\nctime=%z\nbirth=%w\ninode=%i\n' "$path"
  sha256sum "$path"
}

echo '=== OCI host model files ==='
print_file "$MODEL_ROOT/detectors/rtmdet-nano-person-320x320/end2end.onnx"
print_file "$MODEL_ROOT/pose/rtmpose-m-halpe26-384x288/end2end.onnx"

echo '=== Model directory metadata ==='
stat --printf='path=%n\nmtime=%y\nctime=%z\nbirth=%w\n' "$MODEL_ROOT"

echo '=== Worker bind mount ==='
docker inspect --format '{{range .Mounts}}{{if eq .Destination "/workspace/models"}}{{println .Source "->" .Destination "read_write=" .RW}}{{end}}{{end}}' "$CONTAINER"

echo '=== Hashes seen inside Worker ==='
docker exec "$CONTAINER" sha256sum \
  /workspace/models/detectors/rtmdet-nano-person-320x320/end2end.onnx \
  /workspace/models/pose/rtmpose-m-halpe26-384x288/end2end.onnx
