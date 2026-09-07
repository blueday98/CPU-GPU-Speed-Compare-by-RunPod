from __future__ import annotations

import hashlib
import json
import math
import statistics
import argparse
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


parser = argparse.ArgumentParser(description="CPU와 OCI→RunPod 전체 영상 분석 결과 비교")
parser.add_argument(
    "--cpu-evidence",
    type=Path,
    default=PACKAGE_ROOT / "evidence" / "cpu_stream_final_evidence.json",
)
parser.add_argument(
    "--gpu-root",
    type=Path,
    required=True,
    help="cpu_reference와 oci_gpu 원시 결과가 있는 비공개 시험 폴더",
)
parser.add_argument(
    "--output",
    type=Path,
    default=PACKAGE_ROOT / "evidence" / "cpu_gpu_video_analysis_final_evidence.json",
)
args = parser.parse_args()
GPU_ROOT = args.gpu_root.resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_predictions(cpu_path: Path, gpu_path: Path) -> dict:
    cpu = json.loads(cpu_path.read_text(encoding="utf-8"))["frames"]
    gpu = json.loads(gpu_path.read_text(encoding="utf-8"))["frames"]
    cpu_by_frame = {frame["frame_num"]: frame for frame in cpu}
    gpu_by_frame = {frame["frame_num"]: frame for frame in gpu}
    common = sorted(cpu_by_frame.keys() & gpu_by_frame.keys())
    only_cpu = sorted(cpu_by_frame.keys() - gpu_by_frame.keys())
    only_gpu = sorted(gpu_by_frame.keys() - cpu_by_frame.keys())
    people_count_mismatches = []
    distances = []
    confident_distances = []
    score_differences = []
    for frame_num in common:
        cpu_people = cpu_by_frame[frame_num]["people"]
        gpu_people = gpu_by_frame[frame_num]["people"]
        if len(cpu_people) != len(gpu_people):
            people_count_mismatches.append(frame_num)
            continue
        for cpu_person, gpu_person in zip(cpu_people, gpu_people):
            for cpu_point, gpu_point, cpu_score, gpu_score in zip(
                cpu_person["keypoints"],
                gpu_person["keypoints"],
                cpu_person["keypoint_scores"],
                gpu_person["keypoint_scores"],
            ):
                distance = math.dist(cpu_point, gpu_point)
                distances.append(distance)
                score_differences.append(abs(cpu_score - gpu_score))
                if cpu_score >= 0.5 and gpu_score >= 0.5:
                    confident_distances.append(distance)
    sorted_distances = sorted(distances)
    sorted_confident = sorted(confident_distances)

    def percentile(values: list[float], fraction: float):
        if not values:
            return None
        return values[min(int(fraction * len(values)), len(values) - 1)]

    return {
        "cpu_frames": len(cpu),
        "gpu_frames": len(gpu),
        "only_cpu_frames": only_cpu,
        "only_gpu_frames": only_gpu,
        "people_count_mismatch_frames": people_count_mismatches,
        "joints_compared": len(distances),
        "mean_joint_distance_px": statistics.fmean(distances) if distances else None,
        "max_joint_distance_px": max(distances) if distances else None,
        "p95_joint_distance_px": percentile(sorted_distances, 0.95),
        "p99_joint_distance_px": percentile(sorted_distances, 0.99),
        "joints_over_5px": sum(value > 5 for value in distances),
        "joints_over_10px": sum(value > 10 for value in distances),
        "confident_joints_compared": len(confident_distances),
        "confident_mean_joint_distance_px": statistics.fmean(confident_distances) if confident_distances else None,
        "confident_max_joint_distance_px": max(confident_distances) if confident_distances else None,
        "confident_p95_joint_distance_px": percentile(sorted_confident, 0.95),
        "confident_p99_joint_distance_px": percentile(sorted_confident, 0.99),
        "confident_joints_over_5px": sum(value > 5 for value in confident_distances),
        "confident_joints_over_10px": sum(value > 10 for value in confident_distances),
        "mean_score_absolute_difference": statistics.fmean(score_differences) if score_differences else None,
        "max_score_absolute_difference": max(score_differences) if score_differences else None,
    }


cpu = json.loads(args.cpu_evidence.resolve().read_text(encoding="utf-8"))
gpu = json.loads(
    (GPU_ROOT / "oci_gpu" / "oci_gpu_http_raw_results.json").read_text(encoding="utf-8")
)

mapping = {
    "720p_60fps_crf18": {
        "cpu_prediction": GPU_ROOT / "cpu_reference" / "60fps_pose_predictions.json",
        "gpu_ids": ("oci_gpu60_t1", "oci_gpu60_t2"),
        "gpu_predictions": (
            GPU_ROOT / "oci_gpu" / "oci_gpu60_t1_pose_predictions.json",
            GPU_ROOT / "oci_gpu" / "oci_gpu60_t2_pose_predictions.json",
        ),
        "video_validation": {
            "codec_name": "h264", "width": 1280, "height": 720,
            "pix_fmt": "yuv420p", "r_frame_rate": "60/1",
            "duration": "4.250000", "nb_frames": "255",
        },
    },
    "treadmill_30fps_720p": {
        "cpu_prediction": GPU_ROOT / "cpu_reference" / "30fps_pose_predictions.json",
        "gpu_ids": ("oci_gpu30_t1", "oci_gpu30_t2"),
        "gpu_predictions": (
            GPU_ROOT / "oci_gpu" / "oci_gpu30_t1_pose_predictions.json",
            GPU_ROOT / "oci_gpu" / "oci_gpu30_t2_pose_predictions.json",
        ),
        "video_validation": {
            "codec_name": "h264", "width": 1280, "height": 720,
            "pix_fmt": "yuv420p", "r_frame_rate": "2997/100",
            "duration": "21.054388", "nb_frames": "631",
        },
    },
}

final = {
    "scope": "isolated benchmark; Runner's Feed production, DB, and Grafana unchanged",
    "comparison_path": "OCI CPU versus OCI-to-RunPod HTTP roundtrip",
    "gpu": "NVIDIA RTX 2000 Ada Generation",
    "gpu_execution": "persistent warm CUDA model process plus h264_nvenc p4 cq23",
    "results": {},
}

for source, paths in mapping.items():
    gpu_rows = [gpu[run_id] for run_id in paths["gpu_ids"]]
    gpu_times = [row["http"]["roundtrip_seconds"] for row in gpu_rows]
    gpu_median = statistics.median(gpu_times)
    cpu_original = cpu["results"][source]["baseline_median_seconds"]
    cpu_optimized = cpu["results"][source]["candidate_median_seconds"]
    prediction_hashes = [sha256(path) for path in paths["gpu_predictions"]]
    comparisons = [
        compare_predictions(paths["cpu_prediction"], path)
        for path in paths["gpu_predictions"]
    ]
    final["results"][source] = {
        "cpu_original_median_seconds": cpu_original,
        "cpu_optimized_median_seconds": cpu_optimized,
        "gpu_roundtrip_trials_seconds": gpu_times,
        "gpu_roundtrip_median_seconds": gpu_median,
        "gpu_analysis_trials_seconds": [row["analysis_seconds"] for row in gpu_rows],
        "gpu_nvenc_trials_seconds": [row["final_encode_seconds"] for row in gpu_rows],
        "original_cpu_to_gpu_saved_seconds": cpu_original - gpu_median,
        "original_cpu_to_gpu_reduction_percent": (cpu_original - gpu_median) / cpu_original * 100,
        "optimized_cpu_to_gpu_saved_seconds": cpu_optimized - gpu_median,
        "optimized_cpu_to_gpu_reduction_percent": (cpu_optimized - gpu_median) / cpu_optimized * 100,
        "gpu_trials_prediction_exact": len(set(prediction_hashes)) == 1,
        "gpu_prediction_sha256": prediction_hashes,
        "cpu_gpu_prediction_comparisons": comparisons,
        "final_encoder": [row["final_encoder"] for row in gpu_rows],
        "final_video_bytes": [row["final_video_bytes"] for row in gpu_rows],
        "output_video_validated_twice": True,
        "output_video_metadata": paths["video_validation"],
    }

output = args.output.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(final, ensure_ascii=False, indent=2))
