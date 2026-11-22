"""Replay display loss through the supervisor, App.tick and real Wizard logic."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from csillagszem.storage import save_json
from replay import Replay
from test_tracking import B


class CalibrationReplay(unittest.TestCase):
    def test_display_removal_cancels_waiting_and_active_sessions_before_saving(self):
        for check_only in (False,True):
            for waiting in (False,True):
                for removed in ('a','b'):
                    with self.subTest(check_only=check_only,waiting=waiting,removed=removed), \
                         tempfile.TemporaryDirectory() as home, Replay() as replay, \
                         patch('csillagszem.wizard.tk.Toplevel') as window, \
                         patch('csillagszem.wizard.tk.Canvas'), \
                         patch('csillagszem.wizard.place'):
                        app=replay.app
                        app.profile_path=Path(home)/'person.json'
                        replay.cameras.running=True
                        replay.step(100.)
                        replay.step(100.,[('front',replay.packet('front'))])
                        saved_profile=deepcopy(app.profile)
                        save_json(app.profile_path,app.profile)
                        saved_bytes=app.profile_path.read_bytes()
                        app.finish_session=Mock()
                        phase='Accuracy check' if check_only else 'Natural seating position'
                        # A single final validation target makes cancellation order
                        # observable: ticking it after the removal would finish/save.
                        with patch('csillagszem.wizard.target_list',return_value=[(phase,B,(.5,.5))]):
                            app.begin(check_only)
                        wizard=app.wizard
                        self.assertIsNotNone(wizard)
                        if not waiting:
                            wizard.resume()
                        self.assertEqual(wizard.waiting,waiting)
                        wizard.train['unsaved-camera'].append(dict(screen='b',uv=(.5,.5),features=[0.]*12))
                        # The target remains unfinished at the last tick before the
                        # next display poll and would finish on that next tick.
                        wizard.started=99.285
                        removed_at=100.001
                        replay.layout.pop(removed)
                        replay.step(101.)
                        self.assertIs(app.wizard,wizard)
                        replay.step(101.028)
                        self.assertLessEqual(replay.now-removed_at,1.028)
                        self.assertIsNone(app.wizard)
                        window.return_value.destroy.assert_called_once_with()
                        self.assertIn('Display layout changed',app.notice.get())
                        self.assertNotIn(removed,app.displays)
                        self.assertEqual(wizard.score.rows,[])
                        self.assertEqual(app.profile,saved_profile)
                        self.assertEqual(app.profile_path.read_bytes(),saved_bytes)
                        app.finish_session.assert_not_called()
                        self.assertIsNone(replay.dot)


if __name__=='__main__':
    unittest.main()
