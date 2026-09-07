"""Publish one GPU video-analysis attempt to OCI Object Storage.

This module owns the RunPod side of the v2 storage contract. Runtime adapters
provide the actual HPE execution and video encoding so the orchestration can be
tested without a GPU.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from storage_contract import MANIFEST, validate_manifest, validate_request, validate_transfer


MAX_INPUT_BYTES = 512 * 1024 * 1024
SOURCE_FILES = (
    "scripts/hpe/hpe.py",
    "scripts/hpe/hpe_model.py",
    "scripts/hpe/pose_track.py",
)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_release_evidence(code_root: Path, model_root: Path) -> dict:
    """Hash the exact code and weights loaded by this worker once at startup."""
    manifest = _load_json(code_root / "model_manifest.json")
    source_sha256 = {
        relative: _sha256(code_root / relative)
        for relative in SOURCE_FILES
    }
    model_sha256 = {}
    for item in manifest.get("weights", []):
        relative = item.get("path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("invalid model weight manifest entry")
        actual = _sha256(model_root / relative)
        if actual != expected:
            raise ValueError(f"model weight checksum mismatch: {relative}")
        model_sha256[relative] = actual
    if not model_sha256:
        raise ValueError("model manifest contains no weights")
    return {
        "model_id": manifest.get("model_id"),
        "source_sha256": source_sha256,
        "model_sha256": model_sha256,
    }


def validate_release_request(request: dict, release: dict, model_release: str) -> None:
    if request.get("model_id") != release["model_id"]:
        raise ValueError("worker model_id mismatch")
    if request.get("model_release") != model_release:
        raise ValueError("worker model_release mismatch")
    for key in ("source_sha256", "model_sha256"):
        if request.get(key) != release[key]:
            raise ValueError(f"worker {key} mismatch")


def _load_json(path: Path) -> dict:
    def reject_constant(value: str):
        raise ValueError(f"non-finite JSON value: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path.name}")
    return value


def _artifact(path: Path, object_name: str, content_type: str) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"missing or empty artifact: {path.name}")
    return {
        "object_name": object_name,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "content_type": content_type,
    }


def _validate_pose_outputs(output_dir: Path) -> dict:
    details = _load_json(output_dir / "details.json")
    predictions = _load_json(output_dir / "pose_predictions.json")
    video = details.get("video")
    if not isinstance(video, dict):
        raise ValueError("details.json.video must be an object")
    for key in ("width", "height", "fps", "frame_count"):
        value = video.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid details.json.video.{key}")
    frames = predictions.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("pose_predictions.json.frames must not be empty")
    return video


def publish_video_analysis(
    request: dict,
    store,
    execute_analysis,
    encode_video,
    inspect_video,
    *,
    gpu_name: str,
    provider: str = "CUDAExecutionProvider",
) -> dict:
    """Run, validate and publish artifacts; publish the manifest last."""
    prefix = validate_request(request)
    if provider != "CUDAExecutionProvider" or not gpu_name.strip():
        raise ValueError("CUDA execution evidence is required")
    input_meta = request["input"]
    if input_meta["bytes"] > MAX_INPUT_BYTES:
        raise ValueError("input exceeds configured size limit")

    total_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="coach-gpu-analysis-") as temporary:
        workspace = Path(temporary)
        run_dir = workspace / "run" / request["job_id"]
        output_dir = run_dir / "outputs"
        output_dir.mkdir(parents=True)
        input_path = run_dir / "input.mp4"

        started = time.perf_counter()
        store.download_input(input_meta["object_name"], input_path, input_meta["bytes"], input_meta["etag"])
        download_seconds = time.perf_counter() - started
        if input_path.stat().st_size != input_meta["bytes"]:
            raise ValueError("input size mismatch")
        input_sha256 = _sha256(input_path)

        started = time.perf_counter()
        execute_analysis(workspace, request["job_id"], input_path)
        analysis_seconds = time.perf_counter() - started
        video_meta = _validate_pose_outputs(output_dir)

        intermediate = output_dir / "output.mp4"
        rendered = output_dir / "rendered.mp4"
        started = time.perf_counter()
        encode_video(intermediate, rendered)
        encode_seconds = time.perf_counter() - started
        inspect_video(rendered, video_meta)

        files = {
            "predictions": (output_dir / "pose_predictions.json", "pose_predictions.json", "application/json"),
            "details": (output_dir / "details.json", "details.json", "application/json"),
            "video": (rendered, "rendered.mp4", "video/mp4"),
        }
        objects = {
            role: _artifact(path, f"{prefix}/{filename}", content_type)
            for role, (path, filename, content_type) in files.items()
        }

        upload_started = time.perf_counter()
        for role, (path, _, _) in files.items():
            store.upload_result(objects[role]["object_name"], path, objects[role]["content_type"])
        upload_seconds = time.perf_counter() - upload_started

        manifest = {
            "schema_version": MANIFEST,
            "status": "complete",
            **{key: request[key] for key in (
                "job_id", "attempt_id", "model_id", "model_release",
                "source_sha256", "model_sha256", "input",
            )},
            "input_sha256": input_sha256,
            "objects": objects,
            "execution": {
                "device": "cuda",
                "provider": provider,
                "gpu_name": gpu_name,
            },
            "timings_seconds": {
                "download": download_seconds,
                "analysis": analysis_seconds,
                "encode": encode_seconds,
                "upload": upload_seconds,
                "worker_total": time.perf_counter() - total_started,
            },
        }
        manifest_name = validate_manifest(manifest, request)
        manifest_path = workspace / "pose_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        store.upload_result(manifest_name, manifest_path, "application/json")
        return {"manifest_object": manifest_name, "manifest": manifest}


class OCIStore:
    """Minimal adapter for fixed OCI raw and result buckets."""

    def __init__(self, client, namespace: str, raw_bucket: str, results_bucket: str):
        self.client = client
        self.namespace = namespace
        self.raw_bucket = raw_bucket
        self.results_bucket = results_bucket

    def download_input(self, object_name: str, destination: Path, expected_bytes: int, etag: str):
        response = self.client.get_object(
            namespace_name=self.namespace,
            bucket_name=self.raw_bucket,
            object_name=object_name,
            if_match=etag,
        )
        total = 0
        try:
            with destination.open("xb") as output:
                for chunk in response.data.raw.stream(1024 * 1024, decode_content=False):
                    total += len(chunk)
                    if total > expected_bytes:
                        raise ValueError("input exceeds declared size")
                    output.write(chunk)
        finally:
            response.data.close()

    def upload_result(self, object_name: str, source: Path, content_type: str):
        with source.open("rb") as body:
            self.client.put_object(
                namespace_name=self.namespace,
                bucket_name=self.results_bucket,
                object_name=object_name,
                put_object_body=body,
                content_type=content_type,
            )


class SignedURLStore:
    """Transfer only through short-lived, object-scoped HTTPS URLs."""

    def __init__(self, transfer: dict, opener=urlopen):
        validate_transfer(transfer)
        self.input_url = transfer["input_url"]
        self.upload_urls = transfer["upload_urls"]
        self.opener = opener

    def download_input(self, object_name: str, destination: Path, expected_bytes: int, etag: str):
        del object_name
        request = Request(self.input_url, headers={"If-Match": etag}, method="GET")
        total = 0
        try:
            with self.opener(request, timeout=300) as response:
                with destination.open("xb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > expected_bytes:
                            raise ValueError("input exceeds declared size")
                        output.write(chunk)
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"signed input download failed: {error}") from error

    def upload_result(self, object_name: str, source: Path, content_type: str):
        role = self._role_for(object_name)
        request = Request(
            self.upload_urls[role],
            data=source.read_bytes(),
            headers={"Content-Type": content_type},
            method="PUT",
        )
        try:
            with self.opener(request, timeout=300) as response:
                if getattr(response, "status", 200) not in (200, 201):
                    raise RuntimeError(f"signed upload failed: HTTP {response.status}")
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"signed upload failed: {error}") from error

    @staticmethod
    def _role_for(object_name: str) -> str:
        filename = Path(object_name).name
        roles = {
            "pose_predictions.json": "predictions",
            "details.json": "details",
            "rendered.mp4": "video",
            "pose_manifest.json": "manifest",
        }
        try:
            return roles[filename]
        except KeyError as error:
            raise ValueError(f"unexpected upload object: {object_name}") from error
