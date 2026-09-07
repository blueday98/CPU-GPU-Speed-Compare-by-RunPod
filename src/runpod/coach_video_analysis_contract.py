"""Shared contract for OCI and RunPod streamlined video analysis."""

from __future__ import annotations

import hashlib
from pathlib import Path


CONTRACT_VERSION = "coach-video-analysis-20260904-v1"
SOURCE_FILES = (
    "scripts/hpe/hpe.py",
    "scripts/hpe/hpe_model.py",
    "scripts/hpe/pose_track.py",
)
MODEL_FILES = {
    "detector": "detectors/rtmdet-nano-person-320x320/end2end.onnx",
    "pose": "pose/rtmpose-m-halpe26-384x288/end2end.onnx",
}
RESULT_FILES = (
    "pose_predictions.json",
    "details.json",
    "output.mp4",
    "evidence.json",
)


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_hashes(code_root: Path) -> dict[str, str]:
    root = Path(code_root)
    return {name: sha256_file(root / name) for name in SOURCE_FILES}


def model_hashes(model_root: Path) -> dict[str, str]:
    root = Path(model_root)
    return {name: sha256_file(root / path) for name, path in MODEL_FILES.items()}
