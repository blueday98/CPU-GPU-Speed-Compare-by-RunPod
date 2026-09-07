"""Persistent, serialized model subprocess; preserve the pinned HPE source logic."""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import traceback
from types import SimpleNamespace


def compile_pipeline(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    # Only dependency construction moves out of the per-video execution.
    expected = {"args": "parser.parse_args", "detector": "RTMDet", "pose_model": "RTMPose"}
    found = set()
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in expected:
                if not isinstance(node.value, ast.Call) or ast.unparse(node.value.func) != expected[name]:
                    raise RuntimeError("HPE construction changed: " + name)
                found.add(name)
                continue
        body.append(node)
    if found != set(expected):
        raise RuntimeError("Unsupported HPE source")
    tree.body = body
    return compile(ast.fix_missing_locations(tree), str(path), "exec")


def execute_video(code, args, detector, pose_model):
    detector.score_thr = 0.6
    namespace = {"__name__": "__main__", "args": args,
                 "detector": detector, "pose_model": pose_model}
    output, errors = io.StringIO(), io.StringIO()
    returncode = 0
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            exec(code, namespace)
    except BaseException:
        returncode = 1
        traceback.print_exc(file=errors)
    finally:
        # Fresh per-request globals and restored detector threshold prevent cross-job state.
        detector.score_thr = 0.6
        for name in ("capture", "writer"):
            resource = namespace.get(name)
            if resource is not None:
                resource.release()
    return {"returncode": returncode, "stdout": output.getvalue(), "stderr": errors.getvalue()}


def worker(code_root, model_root):
    protocol = sys.stdout
    sys.path.insert(0, str(code_root))
    with contextlib.redirect_stdout(sys.stderr):
        from rtmlib import RTMDet, RTMPose
        from scripts.hpe.hpe_model import estimate_pose
        detector = RTMDet(onnx_model=model_root / "detectors/rtmdet-nano-person-320x320/end2end.onnx",
                         model_input_size=(320, 320), det_mode="human", score_thr=0.6,
                         nms_thr=0.45, backend="onnxruntime", device="cuda")
        pose_model = RTMPose(onnx_model=model_root / "pose/rtmpose-m-halpe26-384x288/end2end.onnx",
                            model_input_size=(288, 384), backend="onnxruntime", device="cuda",
                            to_openpose=False)
        code = compile_pipeline(code_root / "scripts/hpe/hpe.py")
    protocol.write(json.dumps({"ready": True}) + "\n")
    protocol.flush()
    for line in sys.stdin:
        request = json.loads(line)
        args = SimpleNamespace(coach_folder=Path(request["workspace"]),
                               run_folder=request["run_id"], video=Path(request["video"]), device="cuda")
        result = execute_video(code, args, detector, pose_model)
        protocol.write(json.dumps(result) + "\n")
        protocol.flush()


class WarmEngine:
    def __init__(self, code_root, model_root):
        self.code_root, self.model_root = code_root, model_root
        self.process = None
        self.pending = b""

    def _receive(self, timeout):
        import time
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    self.close()
                    raise subprocess.TimeoutExpired("warm GPU process", timeout)
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    self.close()
                    raise RuntimeError("Warm GPU process exited; see server stderr")
                self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        return json.loads(line)

    def start(self):
        self.close()
        self.pending = b""
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve()), str(self.code_root), str(self.model_root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, bufsize=0)
        try:
            if self._receive(120) != {"ready": True}:
                raise RuntimeError("Unexpected warm process startup reply")
        except BaseException:
            self.close()
            raise

    def run(self, command, *, timeout, **kwargs):
        if self.process is None or self.process.poll() is not None:
            self.start()
        request = {"workspace": command[2], "run_id": command[3], "video": command[4]}
        try:
            self.process.stdin.write((json.dumps(request) + "\n").encode())
            self.process.stdin.flush()
            result = self._receive(timeout)
        except BaseException:
            self.close()
            raise
        return subprocess.CompletedProcess(command, result["returncode"], result["stdout"], result["stderr"])

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()


if __name__ == "__main__":
    worker(Path(sys.argv[1]), Path(sys.argv[2]))
