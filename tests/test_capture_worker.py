"""Exercise camera opening without native libraries, devices, or real threads."""
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from csillagszem.cameras import Device, capture_worker


class InlineReader:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()

    def is_alive(self):
        return False


class CaptureOpen(unittest.TestCase):
    def run_worker(self, discoveries):
        original = Device('front', 'Front', 700, 0)
        cap = Mock()
        cap.isOpened.return_value = True
        cv = SimpleNamespace(VideoCapture=Mock(return_value=cap),
                             VideoWriter_fourcc=Mock(return_value=1),
                             CAP_PROP_FOURCC=6, CAP_PROP_FRAME_WIDTH=3,
                             CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5)
        output, stop, preview = queue.Queue(), threading.Event(), threading.Event()
        # Opening and identity checks happen before the reader loop. An already
        # requested stop lets us exercise that path without frames or timing.
        stop.set()
        detector = Mock()
        with patch.dict('sys.modules', {'cv2':cv}), \
             patch('csillagszem.vision.Vision', return_value=detector), \
             patch('csillagszem.cameras.enumerate_devices', side_effect=discoveries), \
             patch('csillagszem.cameras.time.monotonic', return_value=100.), \
             patch('csillagszem.cameras.threading.Thread', side_effect=InlineReader) as reader:
            capture_worker(original, 'unused-model-directory', output, stop, preview, (1280,720))
        packets = []
        while not output.empty():
            packets.append(output.get_nowait())
        detector.close.assert_called_once_with()
        return cv, cap, reader, packets

    def test_persistent_identity_is_resolved_again_at_open_time(self):
        # The supervisor's spawn arguments can predate another enumeration.
        moved = Device('front', 'Front', 1400, 7)
        cv, cap, reader, packets = self.run_worker([{'front':moved}, {'front':moved}])
        cv.VideoCapture.assert_called_once_with(7, 1400)
        cap.read.assert_not_called()
        cap.release.assert_called_once_with()
        reader.assert_called_once()
        self.assertEqual([p[0] for p in packets], ['Loading vision models'])

    def test_disconnect_before_open_does_not_open_old_index(self):
        cv, cap, reader, packets = self.run_worker([{}])
        cv.VideoCapture.assert_not_called()
        reader.assert_not_called()
        self.assertEqual(packets[-1][0], 'Camera disconnected')
        self.assertTrue(all(not p[2] for p in packets))

    def test_reindex_during_open_releases_handle_and_requests_retry(self):
        moved = Device('front', 'Front', 700, 7)
        changed = Device('front', 'Front', 700, 9)
        cv, cap, reader, packets = self.run_worker([{'front':moved}, {'front':changed}])
        cv.VideoCapture.assert_called_once_with(7, 700)
        cap.release.assert_called_once_with()
        reader.assert_not_called()
        self.assertEqual(packets[-1][0], 'Camera list changed during open. Retrying.')
        self.assertTrue(all(not p[2] for p in packets))
