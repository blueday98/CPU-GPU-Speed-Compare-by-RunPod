from __future__ import annotations

import hashlib
import json
import statistics
import argparse
from pathlib import Path


SOURCES = ("720p_60fps_crf18", "treadmill_30fps_720p")
TRIALS = ("trial1", "trial2")


parser = argparse.ArgumentParser(description="CPU 격리 시험 결과를 증거 JSON으로 변환")
parser.add_argument(
    "--benchmark-root",
    type=Path,
    required=True,
    help="inputs, candidate, results 폴더가 있는 격리 시험 루트",
)
parser.add_argument(
    "--output",
    type=Path,
    default=Path(__file__).resolve().parents[1] / "evidence" / "cpu_stream_final_evidence.json",
)
args = parser.parse_args()
ROOT = args.benchmark_root.resolve()
RESULTS = ROOT / "results"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result(mode: str, source: str, trial: str) -> dict:
    name = f"{mode}_{source}_{trial}"
    root = RESULTS / name
    outputs = root / "run" / name / "outputs"
    video = json.loads((root / "ffprobe.json").read_text())["streams"][0]
    return {
        "elapsed_seconds": float((root / "elapsed_seconds.txt").read_text()),
        "prediction_sha256": sha256(outputs / "pose_predictions.json"),
        "rendered_sha256": sha256(outputs / "rendered.mp4"),
        "rendered_bytes": (outputs / "rendered.mp4").stat().st_size,
        "video": video,
    }


evidence = {
    "scope": "isolated OCI CPU benchmark; production container unchanged",
    "worker_image": "ghcr.io/temu-f4/runners-feed-coach-worker:sha-d3753fc9c2c28c22492542e35d3f3cdb7c34534c",
    "change": "replace intermediate OpenCV mp4v plus final libx264 pass with direct raw-frame libx264 veryfast CRF23 streaming",
    "inputs": {
        "720p_60fps_crf18": {
            "filename": "720p_60fps_crf18.mp4",
            "sha256": sha256(ROOT / "inputs" / "720p_60fps_crf18.mp4"),
        },
        "treadmill_30fps_720p": {
            "filename": "treadmill_30fps_720p.mp4",
            "sha256": sha256(ROOT / "inputs" / "treadmill_30fps_720p.mp4"),
        },
    },
    "candidate_sha256": sha256(ROOT / "candidate" / "cpu_stream_candidate.py"),
    "results": {},
}

for source in SOURCES:
    baseline = [result("baseline", source, trial) for trial in TRIALS]
    candidate = [result("streamvf", source, trial) for trial in TRIALS]
    prediction_hashes = {
        row["prediction_sha256"] for row in baseline + candidate
    }
    if len(prediction_hashes) != 1:
        raise RuntimeError(f"prediction mismatch: {source}: {prediction_hashes}")

    expected = (
        {"codec_name": "h264", "width": 1280, "height": 720,
         "pix_fmt": "yuv420p", "r_frame_rate": "60/1", "nb_frames": "255"}
        if source == "720p_60fps_crf18"
        else {"codec_name": "h264", "width": 1280, "height": 720,
              "pix_fmt": "yuv420p", "r_frame_rate": "30000/1001", "nb_frames": "631"}
    )
    for row in candidate:
        for key, value in expected.items():
            if row["video"].get(key) != value:
                raise RuntimeError(
                    f"video metadata mismatch: {source} {key}={row['video'].get(key)}"
                )

    baseline_times = [row["elapsed_seconds"] for row in baseline]
    candidate_times = [row["elapsed_seconds"] for row in candidate]
    baseline_median = statistics.median(baseline_times)
    candidate_median = statistics.median(candidate_times)
    evidence["results"][source] = {
        "baseline_trials_seconds": baseline_times,
        "candidate_trials_seconds": candidate_times,
        "baseline_median_seconds": baseline_median,
        "candidate_median_seconds": candidate_median,
        "saved_seconds": baseline_median - candidate_median,
        "reduction_percent": (baseline_median - candidate_median) / baseline_median * 100,
        "predictions_exact": True,
        "prediction_sha256": prediction_hashes.pop(),
        "candidate_video": candidate[0]["video"],
        "baseline_rendered_bytes": [row["rendered_bytes"] for row in baseline],
        "candidate_rendered_bytes": [row["rendered_bytes"] for row in candidate],
    }

output = args.output.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(output)
print(json.dumps(evidence["results"], ensure_ascii=False, indent=2))
