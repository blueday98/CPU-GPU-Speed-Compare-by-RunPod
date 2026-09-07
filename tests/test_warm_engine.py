import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from warm_engine import compile_pipeline, execute_video

class WarmTests(unittest.TestCase):
    def test_per_request_state_reset_and_no_model_reconstruction(self):
        source = '''args = parser.parse_args()
detector = RTMDet()
pose_model = RTMPose()
assert detector.score_thr == 0.6
assert "frames" not in globals()
frames = [args.run_folder]
detector.score_thr = 0.1
print(frames[0])
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hpe.py'
            path.write_text(source)
            code = compile_pipeline(path)
        detector = SimpleNamespace(score_thr=0.4)
        for name in ('first', 'second'):
            result = execute_video(code, SimpleNamespace(run_folder=name), detector, object())
            self.assertEqual(result['returncode'], 0, result['stderr'])
            self.assertEqual(result['stdout'].strip(), name)
            self.assertEqual(detector.score_thr, 0.6)

    def test_source_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hpe.py'
            path.write_text('args = 1\ndetector = RTMDet()\npose_model = RTMPose()')
            with self.assertRaises(RuntimeError):
                compile_pipeline(path)

    def test_exception_is_failure_and_restores_detector(self):
        detector = SimpleNamespace(score_thr=0.6)
        code = compile('detector.score_thr=0.1\nraise ValueError("bad input")', '<test>', 'exec')
        result = execute_video(code, None, detector, None)
        self.assertEqual(result['returncode'], 1)
        self.assertIn('bad input', result['stderr'])
        self.assertEqual(detector.score_thr, 0.6)

if __name__ == '__main__':
    unittest.main()
