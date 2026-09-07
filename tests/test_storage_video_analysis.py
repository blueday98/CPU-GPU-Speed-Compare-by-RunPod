import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/runpod"))
from storage_contract import REQUEST
from storage_video_analysis import (
    load_release_evidence,
    publish_video_analysis,
    validate_release_request,
)


class Store:
    def __init__(self, input_bytes):
        self.input_bytes = input_bytes
        self.uploads = []

    def download_input(self, name, destination, expected_bytes, etag):
        Path(destination).write_bytes(self.input_bytes)

    def upload_result(self, name, source, content_type):
        self.uploads.append((name, Path(source).read_bytes(), content_type))


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.input = b"input video"
        self.request = {
            "schema_version": REQUEST,
            "job_id": "job-1",
            "attempt_id": "try-1",
            "model_id": "sehyeon-dcc2d7d",
            "model_release": "sha-example",
            "source_sha256": {"hpe.py": "a" * 64},
            "model_sha256": {"pose": "b" * 64},
            "input": {
                "object_name": "uploads/input.mp4",
                "etag": "object-etag",
                "bytes": len(self.input),
            },
            "result_prefix": "jobs/job-1/video-analysis/try-1",
        }
        self.store = Store(self.input)

    @staticmethod
    def execute(workspace, run_id, input_path):
        output = workspace / "run" / run_id / "outputs"
        (output / "details.json").write_text(json.dumps({
            "video": {"width": 1280, "height": 720, "fps": 60, "frame_count": 255}
        }))
        (output / "pose_predictions.json").write_text('{"frames":[{"people":[]}]}')
        (output / "output.mp4").write_bytes(b"intermediate")

    @staticmethod
    def encode(source, target):
        target.write_bytes(b"h264 result")

    def test_artifacts_are_uploaded_before_manifest(self):
        result = publish_video_analysis(
            self.request, self.store, self.execute, self.encode,
            lambda path, meta: None, gpu_name="test GPU",
        )
        names = [row[0] for row in self.store.uploads]
        self.assertEqual(names[-1], self.request["result_prefix"] + "/pose_manifest.json")
        self.assertEqual(names[:-1], [
            self.request["result_prefix"] + "/pose_predictions.json",
            self.request["result_prefix"] + "/details.json",
            self.request["result_prefix"] + "/rendered.mp4",
        ])
        self.assertEqual(result["manifest"]["execution"]["provider"], "CUDAExecutionProvider")

    def test_bad_input_stops_before_analysis_and_upload(self):
        self.store.input_bytes = b"changed"
        with self.assertRaises(ValueError):
            publish_video_analysis(
                self.request, self.store,
                lambda *args: self.fail("analysis must not run"),
                self.encode, lambda *args: None, gpu_name="test GPU",
            )
        self.assertFalse(self.store.uploads)

    def test_analysis_failure_does_not_publish_manifest(self):
        def fail(*args):
            raise RuntimeError("GPU failed")
        with self.assertRaises(RuntimeError):
            publish_video_analysis(
                self.request, self.store, fail, self.encode,
                lambda *args: None, gpu_name="test GPU",
            )
        self.assertFalse(self.store.uploads)

    def test_cpu_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            publish_video_analysis(
                self.request, self.store, self.execute, self.encode,
                lambda *args: None, gpu_name="test GPU",
                provider="CPUExecutionProvider",
            )


class ReleaseEvidenceTests(unittest.TestCase):
    def test_hashes_loaded_code_and_models_and_rejects_different_request(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = root / "code"
            models = root / "models"
            for relative in (
                "scripts/hpe/hpe.py",
                "scripts/hpe/hpe_model.py",
                "scripts/hpe/pose_track.py",
            ):
                path = code / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")
            weight = models / "pose/model.onnx"
            weight.parent.mkdir(parents=True)
            weight.write_bytes(b"weights")
            digest = hashlib.sha256(b"weights").hexdigest()
            (code / "model_manifest.json").write_text(json.dumps({
                "model_id": "model-1",
                "weights": [{"path": "pose/model.onnx", "sha256": digest}],
            }), encoding="utf-8")

            release = load_release_evidence(code, models)
            request = {
                "model_id": "model-1",
                "model_release": "sha-image",
                "source_sha256": release["source_sha256"],
                "model_sha256": release["model_sha256"],
            }
            validate_release_request(request, release, "sha-image")
            request["source_sha256"] = {"hpe.py": "0" * 64}
            with self.assertRaisesRegex(ValueError, "source_sha256"):
                validate_release_request(request, release, "sha-image")
