import gzip
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/cpu"))
from storage_postprocess import postprocess, execute_postprocess
import test_storage_contract


class Store:
    def __init__(self, objects):
        self.objects, self.uploaded = objects, {}

    def download(self, name, destination, max_bytes):
        body = self.objects[name]
        if len(body) > max_bytes:
            raise ValueError("too large")
        Path(destination).write_bytes(body)

    def upload(self, name, source, content_type):
        self.uploaded[name] = Path(source).read_bytes()


class PostprocessTests(unittest.TestCase):
    def setUp(self):
        fixture = test_storage_contract.StorageContractTests()
        fixture.setUp()
        self.request, self.manifest = fixture.request, fixture.manifest
        payloads = {"details": json.dumps({"video": dict(width=1280, height=720,
                     fps=60, frame_count=255)}).encode(),
                    "predictions": b'{"frames":[{"people":[]}]}', "video": b"fake video"}
        self.objects = {}
        for role, payload in payloads.items():
            meta = self.manifest["objects"][role]
            meta.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            self.objects[meta["object_name"]] = payload
        self.manifest_name = self.request["result_prefix"] + "/pose_manifest.json"
        self.objects[self.manifest_name] = json.dumps(self.manifest).encode()
        self.store = Store(self.objects)

    def execute(self, workspace, run_id):
        output = workspace / "run" / run_id / "outputs"
        self.assertFalse((output / "rendered.mp4").exists())
        self.assertTrue((output / "pose_predictions.json").exists())
        (output / "feature_results.json").write_text('{}')
        (output / "report.json").write_text('{"features":{},"metrics":[]}')
        (output / "skeleton.json.gz").write_bytes(gzip.compress(
            b'{"schema_version":"skeleton-1.0","frames":[]}'))

    def test_video_reused_and_retry_has_separate_outputs(self):
        results = [postprocess(self.request, self.store, 1.75, self.execute,
                              video_check=lambda *args: None) for _ in range(2)]
        self.assertEqual(results[0]["result_objects"]["rendered_video"],
                         self.manifest["objects"]["video"]["object_name"])
        self.assertNotEqual(results[0]["result_objects"]["report"],
                            results[1]["result_objects"]["report"])
        self.assertEqual(len(self.store.uploaded), 6)

    def test_corrupt_input_never_executes(self):
        self.objects[self.manifest["objects"]["predictions"]["object_name"]] = b"broken"
        with self.assertRaises(ValueError):
            postprocess(self.request, self.store, 1.75,
                        lambda *args: self.fail("must not execute"))
        self.assertFalse(self.store.uploaded)

    def test_failure_can_resume_from_original_manifest(self):
        def fail(*args):
            raise RuntimeError("feature failed")
        with self.assertRaises(RuntimeError):
            postprocess(self.request, self.store, 1.75, fail, lambda *args: None)
        self.assertFalse(self.store.uploaded)
        postprocess(self.request, self.store, 1.75, self.execute, lambda *args: None)

    def test_entrypoint_has_no_hpe_command(self):
        with patch("storage_postprocess.subprocess.run") as run:
            execute_postprocess(Path('/tmp/w'), 'job', Path('/coach'),
                                Path('/adapters'), Path('/feature.py'))
        paths = [call.args[0][1] for call in run.call_args_list]
        self.assertEqual(paths, ['/feature.py', '/coach/scripts/model_contract/validate_artifacts.py',
                                 '/adapters/report_adapter.py', '/adapters/skeleton_adapter.py'])
