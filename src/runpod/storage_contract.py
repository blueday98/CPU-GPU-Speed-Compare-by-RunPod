"""Validate v2 metadata only; callers must verify actual objects and contents."""
import math
import re
from urllib.parse import urlparse

REQUEST = "video-analysis-request-2.0"
MANIFEST = "video-analysis-manifest-2.0"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
HASH = re.compile(r"[0-9a-f]{64}")
FILES = {
    "predictions": ("pose_predictions.json", "application/json"),
    "details": ("details.json", "application/json"),
    "video": ("rendered.mp4", "video/mp4"),
}
UPLOAD_ROLES = (*FILES.keys(), "manifest")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def object_meta(value):
    require(isinstance(value, dict), "object metadata must be an object")
    name = value.get("object_name")
    require(text(name) and not name.startswith("/") and "\\" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/")), "invalid object_name")
    require(isinstance(value.get("sha256"), str) and HASH.fullmatch(value["sha256"]), "invalid sha256")
    require(type(value.get("bytes")) is int and value["bytes"] > 0, "invalid bytes")


def input_meta(value):
    require(isinstance(value, dict), "input metadata must be an object")
    name = value.get("object_name")
    require(text(name) and not name.startswith("/") and "\\" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/")), "invalid object_name")
    require(text(value.get("etag")), "invalid input etag")
    require(type(value.get("bytes")) is int and value["bytes"] > 0, "invalid bytes")


def validate_request(request):
    require(isinstance(request, dict), "request must be an object")
    require(request.get("schema_version") == REQUEST, "request schema mismatch")
    for key in ("job_id", "attempt_id", "model_id"):
        require(isinstance(request.get(key), str) and ID.fullmatch(request[key]), f"invalid {key}")
    require(text(request.get("model_release")), "missing model_release")
    for key in ("source_sha256", "model_sha256"):
        hashes = request.get(key)
        require(isinstance(hashes, dict) and bool(hashes), f"invalid {key}")
        require(all(text(k) and isinstance(v, str) and HASH.fullmatch(v)
                    for k, v in hashes.items()), f"invalid {key}")
    input_meta(request.get("input"))
    prefix = f"jobs/{request['job_id']}/video-analysis/{request['attempt_id']}"
    require(request.get("result_prefix") == prefix, "result prefix mismatch")
    transfer = request.get("transfer")
    if transfer is not None:
        validate_transfer(transfer)
    return prefix


def validate_transfer(transfer):
    require(isinstance(transfer, dict), "transfer must be an object")
    input_url = transfer.get("input_url")
    uploads = transfer.get("upload_urls")
    require(_https_url(input_url), "invalid signed input URL")
    require(isinstance(uploads, dict) and set(uploads) == set(UPLOAD_ROLES),
            "invalid signed upload URL set")
    require(all(_https_url(value) for value in uploads.values()),
            "invalid signed upload URL")


def _https_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and hostname.endswith(".oraclecloud.com")
        and not parsed.username
    )


def validate_manifest(manifest, request):
    prefix = validate_request(request)
    require(isinstance(manifest, dict), "manifest must be an object")
    require(manifest.get("schema_version") == MANIFEST, "manifest schema mismatch")
    require(manifest.get("status") == "complete", "manifest incomplete")
    for key in ("job_id", "attempt_id", "model_id", "model_release",
                "source_sha256", "model_sha256", "input"):
        require(manifest.get(key) == request[key], f"request mismatch: {key}")
    require(isinstance(manifest.get("input_sha256"), str)
            and HASH.fullmatch(manifest["input_sha256"]), "invalid input_sha256")
    objects = manifest.get("objects")
    require(isinstance(objects, dict) and set(objects) == set(FILES), "artifact set mismatch")
    for role, (filename, mime) in FILES.items():
        obj = objects[role]
        object_meta(obj)
        require(obj["object_name"] == f"{prefix}/{filename}", "artifact path mismatch")
        require(obj.get("content_type") == mime, "artifact content type mismatch")
    execution = manifest.get("execution")
    require(isinstance(execution, dict), "missing execution evidence")
    require(execution.get("device") == "cuda"
            and execution.get("provider") == "CUDAExecutionProvider"
            and text(execution.get("gpu_name")), "invalid GPU evidence")
    timings = manifest.get("timings_seconds")
    require(isinstance(timings, dict), "missing timings")
    for key in ("download", "analysis", "encode", "upload", "worker_total"):
        value = timings.get(key)
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                f"invalid timing: {key}")
    return f"{prefix}/pose_manifest.json"
