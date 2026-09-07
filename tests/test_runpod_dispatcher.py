import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/oci"))
from runpod_dispatcher import RunPodPodClient, build_request


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_request(
            job_id="job-1", attempt_id="try-1", model_id="sehyeon-dcc2d7d",
            model_release="sha-example", source_sha256={"hpe.py": "a" * 64},
            model_sha256={"pose": "b" * 64}, input_object_name="uploads/input.mp4",
            input_etag="object-etag", input_bytes=123,
        )

    def test_builds_attempt_scoped_prefix(self):
        self.assertEqual(
            self.payload["result_prefix"], "jobs/job-1/video-analysis/try-1"
        )

    def test_can_attach_ephemeral_transfer_envelope(self):
        transfer = {"input_url": "signed", "upload_urls": {}}
        payload = build_request(
            job_id="job-1", attempt_id="try-1", model_id="model",
            model_release="release", source_sha256={"a": "a" * 64},
            model_sha256={"b": "b" * 64}, input_object_name="input.mp4",
            input_etag="etag", input_bytes=1, transfer=transfer,
        )
        self.assertIs(payload["transfer"], transfer)

    def test_accepts_only_matching_completion(self):
        def opener(request, **kwargs):
            body = json.loads(request.data)
            self.assertNotIn("token", body)
            return Response(json.dumps({
                "status": "complete",
                "job_id": body["job_id"],
                "attempt_id": body["attempt_id"],
                "manifest_object": body["result_prefix"] + "/pose_manifest.json",
            }).encode())
        client = RunPodPodClient("https://example.test", "x" * 24, opener=opener)
        result = client.submit(self.payload)
        self.assertEqual(result["attempt_id"], "try-1")

    def test_stale_or_foreign_completion_is_rejected(self):
        for key, value in (("job_id", "other"), ("attempt_id", "old"),
                           ("manifest_object", "jobs/other/pose_manifest.json")):
            with self.subTest(key=key):
                response = {
                    "status": "complete", "job_id": "job-1", "attempt_id": "try-1",
                    "manifest_object": self.payload["result_prefix"] + "/pose_manifest.json",
                }
                response[key] = value
                client = RunPodPodClient(
                    "https://example.test", "x" * 24,
                    opener=lambda *args, _body=json.dumps(response).encode(), **kwargs: Response(_body),
                )
                with self.assertRaises(RuntimeError):
                    client.submit(self.payload)

    def test_plain_http_is_rejected(self):
        with self.assertRaises(ValueError):
            RunPodPodClient("http://example.test", "x" * 24)
