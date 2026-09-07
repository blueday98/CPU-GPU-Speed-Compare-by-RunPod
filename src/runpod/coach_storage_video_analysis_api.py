"""RunPod Pod API that publishes GPU video-analysis artifacts to OCI storage."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from storage_video_analysis import (
    OCIStore,
    load_release_evidence,
    publish_video_analysis,
    validate_release_request,
)
from warm_engine import WarmEngine


GPU_LOCK = threading.Lock()


def inspect_h264(path: Path, expected: dict) -> None:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    streams = json.loads(completed.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError("expected exactly one output video stream")
    stream = streams[0]
    if stream.get("codec_name") != "h264" or stream.get("pix_fmt") != "yuv420p":
        raise ValueError("output must be H.264/yuv420p")
    if stream.get("width") != expected["width"] or stream.get("height") != expected["height"]:
        raise ValueError("output dimensions differ from details.json")
    if int(stream.get("nb_read_frames", 0)) != int(expected["frame_count"]):
        raise ValueError("output frame count differs from details.json")
    numerator, denominator = map(int, stream["r_frame_rate"].split("/"))
    if denominator == 0 or not math.isclose(
        numerator / denominator, float(expected["fps"]), rel_tol=1e-4
    ):
        raise ValueError("output FPS differs from details.json")


def encode_nvenc(source: Path, destination: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=float(os.getenv("VIDEO_ANALYSIS_TIMEOUT", "3600")),
    )
    if completed.returncode or not destination.is_file():
        raise RuntimeError(f"NVENC failed: {completed.stderr[-1000:]}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import oci
    import onnxruntime as ort
    import torch

    token = os.environ["RUNPOD_SHARED_TOKEN"]
    if len(token) < 24:
        raise RuntimeError("RUNPOD_SHARED_TOKEN must contain at least 24 characters")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    providers = ort.get_available_providers()
    if "CUDAExecutionProvider" not in providers:
        raise RuntimeError(f"CUDAExecutionProvider unavailable: {providers}")

    code_root = Path(os.environ["COACH_CODE_ROOT"]).resolve()
    model_root = Path(os.environ["COACH_MODEL_ROOT"]).resolve()
    config = oci.config.from_file(
        os.environ["OCI_CONFIG_FILE"], os.getenv("OCI_CONFIG_PROFILE", "DEFAULT")
    )
    client = oci.object_storage.ObjectStorageClient(config)
    namespace = os.getenv("OCI_NAMESPACE") or client.get_namespace().data
    runtime = SimpleNamespace(
        token=token,
        code_root=code_root,
        model_root=model_root,
        engine=WarmEngine(code_root, model_root),
        store=OCIStore(
            client,
            namespace,
            os.environ["OCI_RAW_BUCKET"],
            os.environ["OCI_RESULTS_BUCKET"],
        ),
        gpu_name=torch.cuda.get_device_name(0),
        providers=providers,
        timeout=float(os.getenv("VIDEO_ANALYSIS_TIMEOUT", "3600")),
        model_release=os.environ["MODEL_RELEASE"],
        release=load_release_evidence(code_root, model_root),
    )
    runtime.engine.start()
    app.state.runtime = runtime
    try:
        yield
    finally:
        runtime.engine.close()


app = FastAPI(title="Coach storage GPU video analysis", version="2.0", lifespan=lifespan)


@app.middleware("http")
async def authorize(request: Request, call_next):
    if request.url.path != "/health":
        expected = f"Bearer {app.state.runtime.token}"
        if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    runtime = app.state.runtime
    return {
        "status": "ok",
        "gpu": runtime.gpu_name,
        "providers": runtime.providers,
        "contract": "video-analysis-request-2.0",
    }


@app.post("/v4/storage-video-analysis")
def video_analysis(request: dict):
    runtime = app.state.runtime
    if not GPU_LOCK.acquire(blocking=False):
        raise HTTPException(429, "GPU busy")

    def execute(workspace: Path, run_id: str, input_path: Path) -> None:
        model_link = workspace / "models"
        model_link.symlink_to(runtime.model_root, target_is_directory=True)
        command = [
            sys.executable,
            str(runtime.code_root / "scripts/hpe/hpe.py"),
            str(workspace),
            run_id,
            str(input_path),
            "--device",
            "cuda",
        ]
        completed = runtime.engine.run(command, timeout=runtime.timeout)
        if completed.returncode:
            raise RuntimeError(f"GPU analysis failed: {completed.stderr[-1000:]}")

    try:
        validate_release_request(request, runtime.release, runtime.model_release)
        result = publish_video_analysis(
            request,
            runtime.store,
            execute,
            encode_nvenc,
            inspect_h264,
            gpu_name=runtime.gpu_name,
        )
        return {
            "status": "complete",
            "job_id": request.get("job_id"),
            "attempt_id": request.get("attempt_id"),
            "manifest_object": result["manifest_object"],
        }
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    finally:
        GPU_LOCK.release()
