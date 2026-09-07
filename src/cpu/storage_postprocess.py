"""Postprocess a trusted dispatch request using OCI objects, without running HPE.

The caller owns Job authorization, current-attempt checks and DB transitions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runpod"))
from storage_contract import validate_manifest, validate_request


def load_json(path):
    def invalid(value):
        raise ValueError(f"non-finite JSON: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)


class OCIStore:
    """SDK client is injected; this class never embeds credentials."""
    def __init__(self, client, namespace, bucket):
        self.client, self.namespace, self.bucket = client, namespace, bucket

    def download(self, name, destination, max_bytes):
        response = self.client.get_object(self.namespace, self.bucket, name)
        total = 0
        try:
            with Path(destination).open("xb") as target:
                for chunk in response.data.raw.stream(1024 * 1024, decode_content=False):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("object exceeds size limit")
                    target.write(chunk)
        finally:
            response.data.close()

    def upload(self, name, source, content_type):
        with Path(source).open("rb") as body:
            self.client.put_object(self.namespace, self.bucket, name, body,
                                   content_type=content_type)


def verify_file(path, metadata):
    with Path(path).open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if Path(path).stat().st_size != metadata["bytes"] or digest != metadata["sha256"]:
        raise ValueError("artifact checksum/size mismatch")


def validate_pose(output):
    details = load_json(output / "details.json")
    predictions = load_json(output / "pose_predictions.json")
    video = details["video"]
    for key in ("width", "height", "fps", "frame_count"):
        value = video[key]
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid video {key}")
    frames = predictions["frames"]
    if not isinstance(frames, list) or not frames:
        raise ValueError("empty/invalid pose frames")
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("people"), list):
            raise ValueError("invalid pose frame")
    return video


def verify_video(path, video):
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
        "-of", "json", str(path)], check=True, capture_output=True, text=True, timeout=120)
    stream = json.loads(result.stdout)["streams"][0]
    if (stream["codec_name"], stream["pix_fmt"]) != ("h264", "yuv420p"):
        raise ValueError("unsupported output encoding")
    for key in ("width", "height"):
        if stream[key] != video[key]:
            raise ValueError(f"video {key} mismatch")
    if int(stream["nb_read_frames"]) != video["frame_count"]:
        raise ValueError("video frame count mismatch")
    numerator, denominator = map(int, stream["r_frame_rate"].split("/"))
    if not math.isclose(numerator / denominator, video["fps"], rel_tol=1e-4):
        raise ValueError("video fps mismatch")


def execute_postprocess(workspace, run_id, coach_root, adapter_root, feature_entry,
                        agent_entry=None, timeout=600):
    """Explicit entrypoints: never invoke main.sh or hpe.sh."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(feature_entry.parent), str(coach_root),
                                       env.get("PYTHONPATH", "")))
    commands = [[sys.executable, str(feature_entry), str(workspace), run_id],
        [sys.executable, str(coach_root / "scripts/model_contract/validate_artifacts.py"),
         str(workspace / "run" / run_id)]]
    if agent_entry:
        # Must be a workspace-compatible service adapter, not the raw Coach/run plugin.
        commands.append([sys.executable, str(agent_entry), str(workspace), run_id])
    commands.extend([[sys.executable, str(adapter_root / filename),
                      str(workspace / "run" / run_id)]
                     for filename in ("report_adapter.py", "skeleton_adapter.py")])
    for command in commands:
        subprocess.run(command, check=True, env=env, cwd=coach_root, timeout=timeout)


def postprocess(request, store, height_m, execute, video_check=verify_video):
    prefix = validate_request(request)
    if type(height_m) not in (int, float) or not 0.5 <= height_m <= 2.5:
        raise ValueError("invalid height snapshot")
    with tempfile.TemporaryDirectory(prefix="coach-postprocess-") as tmp:
        workspace = Path(tmp)
        run_id = request["job_id"]
        run = workspace / "run" / run_id
        output = run / "outputs"
        output.mkdir(parents=True)
        manifest_path = workspace / "manifest.json"
        store.download(prefix + "/pose_manifest.json", manifest_path, 1024 * 1024)
        manifest = load_json(manifest_path)
        validate_manifest(manifest, request)
        for role in ("predictions", "details", "video"):
            meta = manifest["objects"][role]
            # Bound even correctly signed metadata to avoid unbounded disk consumption.
            if meta["bytes"] > 512 * 1024 * 1024:
                raise ValueError("artifact exceeds configured contract limit")
            path = output / Path(meta["object_name"]).name
            store.download(meta["object_name"], path, meta["bytes"])
            verify_file(path, meta)
        video_check(output / "rendered.mp4", validate_pose(output))
        (output / "rendered.mp4").unlink()
        (run / "user_info.json").write_text(json.dumps({"user": {"height": height_m}}))
        execute(workspace, run_id)
        for filename in ("feature_results.json", "report.json"):
            if not isinstance(load_json(output / filename), dict):
                raise ValueError("invalid postprocess JSON")
        report = load_json(output / "report.json")
        if not isinstance(report.get("features"), dict) or not isinstance(report.get("metrics"), list):
            raise ValueError("invalid report contract")
        import gzip
        skeleton = json.loads(gzip.decompress((output / "skeleton.json.gz").read_bytes()))
        if skeleton.get("schema_version") != "skeleton-1.0" or not isinstance(skeleton.get("frames"), list):
            raise ValueError("invalid skeleton contract")
        # Each postprocess retry writes a distinct prefix; no partial overwrite of prior results.
        result_prefix = prefix + "/postprocess/" + uuid.uuid4().hex
        result = {"details": manifest["objects"]["details"]["object_name"],
                  "predictions": manifest["objects"]["predictions"]["object_name"],
                  "rendered_video": manifest["objects"]["video"]["object_name"]}
        for role, filename, mime in (("features", "feature_results.json", "application/json"),
                ("report", "report.json", "application/json"),
                ("skeleton", "skeleton.json.gz", "application/gzip")):
            result[role] = result_prefix + "/" + filename
            store.upload(result[role], output / filename, mime)
        return {"job_id": run_id, "attempt_id": request["attempt_id"],
                "manifest_object": prefix + "/pose_manifest.json", "result_objects": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True, help="Trusted dispatcher snapshot")
    parser.add_argument("--height-m", type=float, required=True)
    parser.add_argument("--coach-root", type=Path, required=True)
    parser.add_argument("--adapter-root", type=Path, required=True)
    parser.add_argument("--feature-entry", type=Path, required=True)
    parser.add_argument("--agent-entry", type=Path, help="Workspace-compatible agent adapter")
    args = parser.parse_args()
    import oci
    config = oci.config.from_file(os.environ["OCI_CONFIG_FILE"],
                                  os.getenv("OCI_CONFIG_PROFILE", "DEFAULT"))
    store = OCIStore(oci.object_storage.ObjectStorageClient(config),
                     os.environ["OCI_NAMESPACE"], os.environ["OCI_RESULTS_BUCKET"])
    def execute(workspace, run_id):
        execute_postprocess(workspace, run_id, args.coach_root.resolve(),
            args.adapter_root.resolve(), args.feature_entry.resolve(),
            args.agent_entry.resolve() if args.agent_entry else None)
    print(json.dumps(postprocess(load_json(args.request), store, args.height_m, execute)))


if __name__ == "__main__":
    main()
