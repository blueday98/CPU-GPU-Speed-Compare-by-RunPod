from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(os.environ.get("BENCHMARK_ROOT", "/path/to/benchmark"))
RESULTS = ROOT / "gpu_results"
RESULTS.mkdir(parents=True, exist_ok=True)
ENDPOINT = os.environ["RUNPOD_VIDEO_ANALYSIS_ENDPOINT"]
TOKEN = os.environ["RUNPOD_BENCHMARK_TOKEN"]

SOURCES = {
    "scripts/hpe/hpe.py": "12e86ead285dacbf7502b8276566b77f7b10857b682cb6928d72c92039d07e22",
    "scripts/hpe/hpe_model.py": "2dc56a671444c0a1115ef1d7827cceba843d4040ee5ab0d064f8673a960c161b",
    "scripts/hpe/pose_track.py": "18ae1a947471f7bd9c9a1bee5cc2f8bcb17f496bdbb2692f016d835817619fa6",
}
MODELS = {
    "detector": "dae7d98b247441ec4e408381c72087be5bbf325df939704bb978e21725a948ea",
    "pose": "f43e623a47dd21e465d1f4e7b3083e99c589cd4048958b152d650b27732e6946",
}
CASES = (
    ("oci_gpu60_t1", ROOT / "inputs" / "720p_60fps_crf18.mp4"),
    ("oci_gpu60_t2", ROOT / "inputs" / "720p_60fps_crf18.mp4"),
    ("oci_gpu30_t1", ROOT / "inputs" / "treadmill_30fps_720p.mp4"),
    ("oci_gpu30_t2", ROOT / "inputs" / "treadmill_30fps_720p.mp4"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


summary = {}
for run_id, video in CASES:
    contract = json.dumps(
        {
            "contract_version": "coach-video-analysis-20260904-v1",
            "run_id": run_id,
            "source_sha256": SOURCES,
            "model_sha256": MODELS,
            "input_sha256": sha256(video),
        },
        separators=(",", ":"),
    )
    archive = RESULTS / f"{run_id}.zip"
    extracted = RESULTS / run_id
    if archive.exists() or extracted.exists():
        raise RuntimeError(f"result already exists: {run_id}")
    command = [
        "curl", "-fsS", "--connect-timeout", "15", "--max-time", "600",
        "-H", f"Authorization: Bearer {TOKEN}",
        "-F", f"video=@{video};type=video/mp4",
        "-F", f"run_id={run_id}",
        "-F", f"contract={contract}",
        "-o", str(archive),
        "-w", '{"http_code":%{http_code},"roundtrip_seconds":%{time_total},"starttransfer_seconds":%{time_starttransfer},"upload_bytes":%{size_upload},"download_bytes":%{size_download}}',
        ENDPOINT,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    metrics = json.loads(completed.stdout)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(extracted)
    evidence = json.loads((extracted / "evidence.json").read_text())
    summary[run_id] = {
        "input": str(video),
        "input_sha256": sha256(video),
        "http": metrics,
        "gpu": evidence["gpu"],
        "providers": evidence["providers"],
        "execution_mode": evidence["execution_mode"],
        "analysis_seconds": evidence["analysis_seconds"],
        "final_encoder": evidence["final_encoder"],
        "final_encode_seconds": evidence["final_encode_seconds"],
        "intermediate_video_bytes": evidence["intermediate_video_bytes"],
        "final_video_bytes": evidence["final_video_bytes"],
        "result_sha256": evidence["result_sha256"],
    }
    print(
        f"{run_id} roundtrip={metrics['roundtrip_seconds']} "
        f"analysis={evidence['analysis_seconds']:.6f} "
        f"encode={evidence['final_encode_seconds']:.6f}",
        flush=True,
    )

(RESULTS / "oci_gpu_http_raw_results.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
