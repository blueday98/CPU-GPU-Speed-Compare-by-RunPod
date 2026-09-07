#!/usr/bin/env bash
set -euo pipefail

: "${SSH_TARGET:?예: ubuntu@OCI주소}"
: "${SSH_KEY:?개인키 경로}"
: "${LOCAL_DETECTOR:?GitHub에서 받은 detector end2end.onnx 경로}"
: "${LOCAL_POSE:?GitHub에서 받은 pose end2end.onnx 경로}"

REMOTE_DETECTOR="${REMOTE_DETECTOR:-/home/ubuntu/runners-feed-runtime/models/detectors/rtmdet-nano-person-320x320/end2end.onnx}"
REMOTE_POSE="${REMOTE_POSE:-/home/ubuntu/runners-feed-runtime/models/pose/rtmpose-m-halpe26-384x288/end2end.onnx}"
CONTAINER="${CONTAINER:-runners-feed-coach-worker-1}"

require_real_model() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "파일 없음: $path" >&2
    exit 1
  fi
  if head -n 1 "$path" | grep -qx 'version https://git-lfs.github.com/spec/v1'; then
    echo "Git LFS 포인터만 있습니다: $path" >&2
    echo "먼저 git lfs pull을 실행하세요." >&2
    exit 1
  fi
}

require_real_model "$LOCAL_DETECTOR"
require_real_model "$LOCAL_POSE"

local_detector_hash=$(sha256sum "$LOCAL_DETECTOR" | awk '{print $1}')
local_pose_hash=$(sha256sum "$LOCAL_POSE" | awk '{print $1}')

remote_output=$(ssh -o BatchMode=yes -i "$SSH_KEY" "$SSH_TARGET" bash -s -- \
  "$REMOTE_DETECTOR" "$REMOTE_POSE" "$CONTAINER" <<'REMOTE'
set -euo pipefail
detector="$1"
pose="$2"
container="$3"

printf 'host_detector\t%s\n' "$(sha256sum "$detector" | awk '{print $1}')"
printf 'host_pose\t%s\n' "$(sha256sum "$pose" | awk '{print $1}')"
printf 'worker_detector\t%s\n' "$(docker exec "$container" sha256sum /workspace/models/detectors/rtmdet-nano-person-320x320/end2end.onnx | awk '{print $1}')"
printf 'worker_pose\t%s\n' "$(docker exec "$container" sha256sum /workspace/models/pose/rtmpose-m-halpe26-384x288/end2end.onnx | awk '{print $1}')"
stat --printf='detector_mtime_utc\t%y\ndetector_ctime_utc\t%z\ndetector_birth_utc\t%w\n' "$detector"
stat --printf='pose_mtime_utc\t%y\npose_ctime_utc\t%z\npose_birth_utc\t%w\n' "$pose"
REMOTE
)

value() {
  awk -F '\t' -v key="$1" '$1 == key {print $2}' <<<"$remote_output"
}

host_detector_hash=$(value host_detector)
host_pose_hash=$(value host_pose)
worker_detector_hash=$(value worker_detector)
worker_pose_hash=$(value worker_pose)

echo "GitHub detector : $local_detector_hash"
echo "OCI host detector: $host_detector_hash"
echo "Worker detector  : $worker_detector_hash"
echo "GitHub pose       : $local_pose_hash"
echo "OCI host pose     : $host_pose_hash"
echo "Worker pose       : $worker_pose_hash"
echo

status=0
if [[ "$local_detector_hash" == "$host_detector_hash" && "$host_detector_hash" == "$worker_detector_hash" ]]; then
  echo 'PASS: detector 모델이 GitHub·OCI·Worker에서 동일합니다.'
else
  echo 'FAIL: detector 모델이 서로 다릅니다.'
  status=1
fi

if [[ "$local_pose_hash" == "$host_pose_hash" && "$host_pose_hash" == "$worker_pose_hash" ]]; then
  echo 'PASS: pose 모델이 GitHub·OCI·Worker에서 동일합니다.'
else
  echo 'FAIL: pose 모델이 서로 다릅니다.'
  status=1
fi

echo
echo "$remote_output" | grep -E '_(mtime|ctime|birth)_utc'
exit "$status"
