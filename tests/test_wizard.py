"""Exercise normal desktop entry points with a deterministic two-camera replay."""
from collections import deque
from pathlib import Path
import os
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from csillagszem.app import App
from csillagszem.desktop import Screen
from csillagszem.model import Frame
from csillagszem.storage import load_profile, save_json
from test_tracking import features


@unittest.skipUnless(os.name=='nt','Windows desktop integration')
class DesktopFlow(unittest.TestCase):
    def test_display_removal_closes_calibration_window_and_preserves_profile(self):
        for waiting in (True,False):
            with self.subTest(waiting=waiting), tempfile.TemporaryDirectory() as home:
                root=tk.Tk()
                root.withdraw()
                app=App(root,Path(home),home)
                try:
                    a=Screen('a','Left',-1280,-160,1280,720)
                    b=Screen('b','Right',0,0,1920,1080)
                    app.displays={s.id:s for s in (a,b)}
                    app.cameras.running=True
                    app.cameras.frames={'front':Frame('front',100.,[0]*12,.9)}
                    save_json(app.profile_path,app.profile)
                    saved=app.profile_path.read_bytes()
                    targets=[('Natural seating position',b,(.5,.5))]
                    with patch('csillagszem.wizard.place',lambda window,*args:window.withdraw()), \
                         patch('csillagszem.wizard.target_list',return_value=targets), \
                         patch('time.monotonic',return_value=100.):
                        app.begin(False)
                        wizard=app.wizard
                        if not waiting:
                            wizard.resume()
                        self.assertEqual(wizard.waiting,waiting)
                    app.last_display=100.
                    with patch('time.monotonic',return_value=101.01), \
                         patch('csillagszem.app.desktop.screens',return_value=[a]), \
                         patch.object(app.cameras,'maintenance'), \
                         patch.object(app,'finish_session') as finish:
                        app.tick()
                    self.assertIsNone(app.wizard)
                    self.assertFalse(wizard.win.winfo_exists())
                    self.assertIn('Display layout changed',app.notice.get())
                    self.assertEqual(app.displays,{'a':a})
                    self.assertEqual(app.profile_path.read_bytes(),saved)
                    finish.assert_not_called()
                finally:
                    app.close()

    def test_full_calibration_validation_reload_and_abort(self):
        with tempfile.TemporaryDirectory() as home:
            root=tk.Tk()
            root.withdraw()
            app=App(root,Path(home),home)
            try:
                # Place tests in a tiny hidden window. All geometry math and labels
                # still use the complete simulated physical desktop.
                a=Screen('a','Left',-1280,-160,1280,720)
                b=Screen('b','Right',0,0,1920,1080)
                app.displays={s.id:s for s in (a,b)}
                app.cameras.running=True
                app.cameras.frames={'front':Frame('front',time.monotonic(),[0]*12,.9)}
                with patch('csillagszem.wizard.place',lambda window,*args:window.withdraw()):
                    app.begin(False)
                    wizard=app.wizard
                    iterations=0
                    while app.wizard:
                        iterations+=1
                        self.assertLess(iterations,70)
                        wizard.resume()
                        start=wizard.started
                        xy=wizard.screen.point(wizard.uv)
                        pos=.12 if 'slightly' in wizard.phase else (.04 if wizard.phase=='Accuracy check' else 0)
                        x=features(xy,pos).tolist()
                        for cam in ('front','side'):
                            ff=[Frame(cam,start+.75+j*.045,x,.9) for j in range(20)]
                            app.cameras.history[cam]=deque(ff)
                            app.cameras.frames[cam]=ff[-1]
                        if wizard.phase=='Accuracy check':
                            # Supply fresh frames throughout the measurement window.
                            for elapsed in (.85,1.05,1.25,1.45,1.75):
                                for cam in ('front','side'):
                                    app.cameras.frames[cam]=Frame(cam,start+elapsed-.03,x,.9)
                                wizard.tick(start+elapsed)
                        else:
                            wizard.tick(start+1.63)
                    self.assertEqual(iterations,62)
                    self.assertEqual(set(app.report['saved']),{'front','side'})
                    self.assertEqual(len(app.report['summary']),6)
                    saved=load_profile(app.profile_path)
                    self.assertEqual(saved['banks'],app.profile['banks'])
                    app.begin(True)
                    self.assertTrue(app.wizard.check_only)
                    app.wizard.cancel()
                    self.assertEqual(load_profile(app.profile_path),saved)
            finally:
                app.close()
