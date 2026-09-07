#!/usr/bin/env bash
set -euo pipefail

root="${BENCHMARK_ROOT:?BENCHMARK_ROOT is required}"
image="${WORKER_IMAGE:?WORKER_IMAGE is required}"
models="${MODEL_ROOT:?MODEL_ROOT is required}"

run_one() {
  mode="$1"
  source_name="$2"
  trial_id="${TRIAL_ID:-trial1}"
  run_id="${mode}_${source_name%.mp4}_${trial_id}"
  result_dir="$root/results/$run_id"
  mkdir -p "$result_dir/run/$run_id/outputs"

  encoder_preset=medium
  encoder_threads=1
  if [[ "$mode" == streamvf ]]; then
    encoder_preset=veryfast
    encoder_threads=0
  fi

  if [[ "$mode" == baseline ]]; then
    pipeline='python /app/coach/scripts/hpe/hpe.py /workspace "'$run_id'" "/benchmark/inputs/'$source_name'" --device cpu && ffmpeg -y -hide_banner -loglevel error -i "/workspace/run/'$run_id'/outputs/output.mp4" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "/workspace/run/'$run_id'/outputs/rendered.mp4"'
  else
    pipeline='python /candidate/cpu_stream_candidate.py /app/coach/scripts/hpe/hpe.py /workspace "'$run_id'" "/benchmark/inputs/'$source_name'" --device cpu && mv "/workspace/run/'$run_id'/outputs/output.mp4" "/workspace/run/'$run_id'/outputs/rendered.mp4"'
  fi

  if [[ ! -s "$result_dir/elapsed_seconds.txt" || ! -s "$result_dir/run/$run_id/outputs/rendered.mp4" ]]; then
    started=$(date +%s.%N)
    docker run --rm \
      --name "coach-cpu-bench-${mode}-${source_name%%.*}" \
      --network none \
      --user 1001:1001 \
      --env CPU_STREAM_PRESET="$encoder_preset" \
      --env CPU_STREAM_THREADS="$encoder_threads" \
      --cap-drop ALL \
      --security-opt no-new-privileges \
      --mount type=bind,src="$models",dst=/workspace/models,readonly \
      --mount type=bind,src="$result_dir/run",dst=/workspace/run \
      --mount type=bind,src="$root/inputs",dst=/benchmark/inputs,readonly \
      --mount type=bind,src="$root/candidate",dst=/candidate,readonly \
      --entrypoint /bin/bash \
      "$image" -lc "nice -n 10 bash -lc '$pipeline'" \
      >"$result_dir/process.log" 2>&1
    ended=$(date +%s.%N)

    elapsed=$(awk -v start="$started" -v end="$ended" 'BEGIN { printf "%.6f", end-start }')
    printf '%s\n' "$elapsed" >"$result_dir/elapsed_seconds.txt"
  else
    elapsed=$(cat "$result_dir/elapsed_seconds.txt")
    echo "재사용: $mode $source_name"
  fi
  sha256sum \
    "$result_dir/run/$run_id/outputs/pose_predictions.json" \
    "$result_dir/run/$run_id/outputs/rendered.mp4" \
    >"$result_dir/sha256.txt"
  docker run --rm --network none --user 1001:1001 --cap-drop ALL \
    --security-opt no-new-privileges \
    --mount type=bind,src="$result_dir/run/$run_id/outputs",dst=/outputs,readonly \
    --entrypoint ffprobe "$image" -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames,duration,pix_fmt \
    -of json /outputs/rendered.mp4 \
    >"$result_dir/ffprobe.json"
  echo "$mode $source_name elapsed=${elapsed}s"
}

if [[ "${ONLY_FINAL:-0}" == 1 ]]; then
  run_one baseline 720p_60fps_crf18.mp4
  run_one streamvf 720p_60fps_crf18.mp4
  run_one baseline treadmill_30fps_720p.mp4
  run_one streamvf treadmill_30fps_720p.mp4
  exit 0
fi

run_one baseline 720p_60fps_crf18.mp4
run_one stream 720p_60fps_crf18.mp4
run_one baseline treadmill_30fps_720p.mp4
run_one stream treadmill_30fps_720p.mp4
run_one stream1 720p_60fps_crf18.mp4
run_one stream1 treadmill_30fps_720p.mp4
run_one streamvf 720p_60fps_crf18.mp4
run_one streamvf treadmill_30fps_720p.mp4

python3 - "$root/results" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
summary = {}
for elapsed in sorted(root.glob("*_trial1/elapsed_seconds.txt")):
    result = elapsed.parent
    name = result.name
    summary[name] = {
        "elapsed_seconds": float(elapsed.read_text()),
        "sha256": (result / "sha256.txt").read_text().splitlines(),
        "video": json.loads((result / "ffprobe.json").read_text()),
    }
for source in ("720p_60fps_crf18", "treadmill_30fps_720p"):
    before = summary[f"baseline_{source}_trial1"]["elapsed_seconds"]
    after = summary[f"stream_{source}_trial1"]["elapsed_seconds"]
    summary[f"comparison_{source}"] = {
        "baseline_seconds": before,
        "stream_seconds": after,
        "saved_seconds": before - after,
        "reduction_percent": (before - after) / before * 100,
    }
    one_thread = summary[f"stream1_{source}_trial1"]["elapsed_seconds"]
    summary[f"comparison_stream1_{source}"] = {
        "baseline_seconds": before,
        "stream_seconds": one_thread,
        "saved_seconds": before - one_thread,
        "reduction_percent": (before - one_thread) / before * 100,
    }
    veryfast = summary[f"streamvf_{source}_trial1"]["elapsed_seconds"]
    summary[f"comparison_streamvf_{source}"] = {
        "baseline_seconds": before,
        "stream_seconds": veryfast,
        "saved_seconds": before - veryfast,
        "reduction_percent": (before - veryfast) / before * 100,
    }
(root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({k:v for k,v in summary.items() if k.startswith("comparison_")}, indent=2))
PY
