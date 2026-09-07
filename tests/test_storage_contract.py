import copy
import unittest
from storage_contract import FILES, MANIFEST, REQUEST, validate_manifest, validate_transfer


class StorageContractTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(schema_version=REQUEST, job_id="job-1", attempt_id="try-2",
            model_id="sehyeon-dcc2d7d", model_release="sha-example",
            source_sha256={"hpe.py": "a" * 64}, model_sha256={"pose": "b" * 64},
            input=dict(object_name="uploads/input.mp4", etag="object-etag", bytes=100),
            result_prefix="jobs/job-1/video-analysis/try-2")
        self.manifest = {k: copy.deepcopy(v) for k, v in self.request.items()
                         if k not in {"schema_version", "result_prefix"}}
        self.manifest.update(schema_version=MANIFEST, status="complete", input_sha256="c" * 64,
            objects={role: dict(object_name=self.request["result_prefix"] + "/" + filename,
                sha256="d" * 64, bytes=50, content_type=mime)
                for role, (filename, mime) in FILES.items()},
            execution=dict(device="cuda", provider="CUDAExecutionProvider", gpu_name="test GPU"),
            timings_seconds=dict(download=1, analysis=2, encode=1, upload=1, worker_total=5))

    def test_valid_metadata(self):
        self.assertEqual(validate_manifest(self.manifest, self.request),
                         self.request["result_prefix"] + "/pose_manifest.json")

    def test_stale_attempt_model_and_input_rejected(self):
        for key in ("attempt_id", "job_id", "model_release", "source_sha256", "input"):
            with self.subTest(key=key):
                value = copy.deepcopy(self.manifest)
                value[key] = "different"
                with self.assertRaises(ValueError):
                    validate_manifest(value, self.request)

    def test_missing_or_foreign_artifact_rejected(self):
        for change in ("missing", "foreign", "bad_hash"):
            with self.subTest(change=change):
                value = copy.deepcopy(self.manifest)
                if change == "missing":
                    del value["objects"]["video"]
                elif change == "foreign":
                    value["objects"]["video"]["object_name"] = "jobs/other/rendered.mp4"
                else:
                    value["objects"]["video"]["sha256"] = "bad"
                with self.assertRaises(ValueError):
                    validate_manifest(value, self.request)

    def test_invalid_timings_rejected(self):
        for timing in (True, float("nan"), float("inf"), -1):
            with self.subTest(timing=timing):
                self.manifest["timings_seconds"]["analysis"] = timing
                with self.assertRaises(ValueError):
                    validate_manifest(self.manifest, self.request)

    def test_cpu_evidence_rejected(self):
        self.manifest["execution"]["provider"] = "CPUExecutionProvider"
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, self.request)

    def test_transfer_requires_oci_https_urls_and_exact_roles(self):
        base = "https://objectstorage.ap-seoul-1.oraclecloud.com/p/token"
        transfer = {
            "input_url": base + "/input",
            "upload_urls": {
                role: base + "/" + role
                for role in ("predictions", "details", "video", "manifest")
            },
        }
        validate_transfer(transfer)
        transfer["input_url"] = "http://127.0.0.1/private"
        with self.assertRaises(ValueError):
            validate_transfer(transfer)
