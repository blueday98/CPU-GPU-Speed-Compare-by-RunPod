"""Run the pinned HPE script while streaming rendered frames directly to H.264.

This wrapper does not change detection, pose, tracking, or drawing logic.  It only
replaces OpenCV's intermediate mp4v writer with an ffmpeg raw-video pipe using
the same libx264 defaults as the current final transcode (medium / CRF 23).
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import cv2


class FFmpegH264Writer:
    def __init__(self, filename, _fourcc, fps, frame_size):
        width, height = frame_size
        preset = os.getenv("CPU_STREAM_PRESET", "medium")
        threads = os.getenv("CPU_STREAM_THREADS", "1")
        self.preset = preset
        self.threads = int(threads)
        self.filename = str(filename)
        self.frames = 0
        self.write_seconds = 0.0
        self.started_at = time.perf_counter()
        self.released = False
        self.command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{width}x{height}", "-framerate", str(fps),
            "-i", "pipe:0", "-an", "-c:v", "libx264",
            "-preset", preset, "-crf", "23", "-threads", threads,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", self.filename,
        ]
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE)

    def isOpened(self):
        return self.process.poll() is None and self.process.stdin is not None

    def write(self, frame):
        if self.process.stdin is None:
            raise RuntimeError("ffmpeg stdin is unavailable")
        started = time.perf_counter()
        self.process.stdin.write(frame.tobytes())
        self.write_seconds += time.perf_counter() - started
        self.frames += 1

    def release(self):
        if self.released:
            return
        self.released = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        return_code = self.process.wait()
        if return_code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {return_code}")
        evidence = {
            "mode": "single_pass_ffmpeg_pipe",
            "encoder": "libx264",
            "preset": self.preset,
            "threads": self.threads,
            "crf": 23,
            "frames": self.frames,
            "write_block_seconds": self.write_seconds,
            "writer_elapsed_seconds": time.perf_counter() - self.started_at,
            "ffmpeg_command": self.command,
        }
        Path(self.filename).with_suffix(".stream-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: cpu_stream_candidate.py HPE_SCRIPT [HPE_SCRIPT_ARGS...]"
        )
    hpe_script = Path(sys.argv[1]).resolve()
    sys.argv = [str(hpe_script), *sys.argv[2:]]
    original_writer = cv2.VideoWriter
    cv2.VideoWriter = FFmpegH264Writer
    try:
        runpy.run_path(str(hpe_script), run_name="__main__")
    finally:
        cv2.VideoWriter = original_writer


if __name__ == "__main__":
    main()
