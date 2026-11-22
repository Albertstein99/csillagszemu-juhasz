"""Timestamped failure replays through Cameras.maintenance and App.tick."""
import unittest

from csillagszem.cameras import Device
from test_tracking import A, B
from replay import Replay


class CameraReplay(unittest.TestCase):
    def start(self, r, keys=('front', 'side')):
        r.cameras.running = True
        r.step(100.)
        point = r.step(100., [(k,r.packet(k)) for k in keys])
        self.assertIsNotNone(point)
        self.assertEqual(set(point.cameras), {r.mode(k) for k in keys})
        return point

    def test_camera_start_is_explicit(self):
        with Replay() as r:
            self.assertIsNone(r.step(100.))
            self.assertFalse(r.context.processes)
            self.start(r)

    def test_stalled_worker_becomes_unavailable_then_recovers(self):
        with Replay() as r:
            self.start(r, ('front',))
            old = r.cameras.workers['front']
            self.assertIsNotNone(r.step(100.30))
            self.assertIsNone(r.step(100.33))
            self.assertIsNone(r.dot)
            r.step(100.42)  # text readout paints at most once per 75 ms
            self.assertEqual(r.app.readout.get(), 'Gaze unavailable')
            # Loss at 330 ms; the blocked process is retired after 4 s,
            # terminated after its 1.2 s grace, then reopened after 4 s backoff.
            r.step(104.01)
            self.assertNotIn('front', r.cameras.workers)
            self.assertTrue(old[2].is_set())
            r.step(105.22)
            self.assertTrue(old[0].terminated)
            self.assertTrue(old[0].closed)
            r.step(108.02)
            self.assertIsNot(r.cameras.workers['front'][0], old[0])
            point = r.step(108.05, [('front',r.packet('front',108.05))])
            self.assertEqual(point.cameras, (r.mode('front'),))
            self.assertIsNotNone(r.dot)

    def test_surviving_view_and_reconnection_at_new_index(self):
        with Replay() as r:
            self.start(r)
            old = r.cameras.workers['front']
            old[1].put_nowait(r.packet('front',100.05))
            point = r.step(100.10, [('side',r.packet('side',100.10))],
                           devices={'side':r.devices['side']})
            self.assertEqual(point.cameras, (r.mode('side'),))
            self.assertNotIn(r.mode('front'), r.cameras.frames)
            self.assertNotIn(r.mode('front'), r.cameras.history)
            returning = {**r.devices, 'front':Device('front','Front',700,7)}
            r.step(100.20, [('side',r.packet('side',100.20))], devices=returning)
            self.assertNotIn('front', r.cameras.workers)  # old child still owns device
            for now in (100.40,100.60,100.80,101.,101.20,101.31):
                point = r.step(now, [('side',r.packet('side',now))])
                self.assertEqual(point.cameras, (r.mode('side'),))
                self.assertIsNotNone(r.dot)
            self.assertTrue(old[0].terminated)
            new = r.cameras.workers['front'][0]
            self.assertEqual(new.args[0].index, 7)
            self.assertEqual(new.args[0].id, 'front')
            point = r.step(101.40, [(k,r.packet(k,101.40)) for k in ('front','side')])
            self.assertEqual(set(point.cameras), {r.mode('front'),r.mode('side')})
            self.assertIn(r.mode('front'), r.app.profile['banks'])

    def test_temporary_disagreement_and_surviving_view_recovery(self):
        with Replay() as r:
            self.start(r)
            self.assertIsNone(r.step(100.10, [
                ('front',r.packet('front',100.10,A.point((.4,.4)))),
                ('side',r.packet('side',100.10,B.point((.4,.4))))]))
            self.assertIsNone(r.dot)
            # A fresh surviving view resumes as soon as the disagreeing view is
            # more than 90 ms behind; smoothing cannot retain the old point.
            point = r.step(100.20, [('side',r.packet('side',100.20))])
            self.assertEqual(point.cameras, (r.mode('side'),))
            self.assertEqual(point.screen, B.id)
            self.assertIsNotNone(r.dot)
            point = r.step(100.30, [(k,r.packet(k,100.30)) for k in ('front','side')])
            self.assertEqual(len(point.cameras), 2)

    def test_loss_and_survivor_latency_at_28ms_live_tick_interval(self):
        with Replay() as r:
            self.start(r, ('front',))
            for tick in range(1,13):
                point = r.step(100.+tick*.028)
                if tick < 12:
                    self.assertIsNotNone(point)
            self.assertIsNone(point)
            self.assertIsNone(r.dot)
            self.assertAlmostEqual(r.now-100., .336)
        with Replay() as r:
            self.start(r)
            conflict_at = 100.028
            self.assertIsNone(r.step(conflict_at, [
                ('front',r.packet('front',conflict_at,A.point((.4,.4)))),
                ('side',r.packet('side',conflict_at,B.point((.4,.4))))]))
            for tick in range(2,6):
                now = 100.+tick*.028
                point = r.step(now, [('side',r.packet('side',now))])
                if tick < 5:
                    self.assertIsNone(point)
            self.assertEqual(point.cameras, (r.mode('side'),))
            self.assertIsNotNone(r.dot)
            self.assertAlmostEqual(r.now-conflict_at, .112)

    def test_old_and_duplicate_packets_cannot_replace_fresh_observation(self):
        with Replay() as r:
            self.start(r, ('front',))
            mode = r.mode('front')
            fresh = r.cameras.frames[mode]
            for stamp, visible in ((99.9,True),(99.,True),(99.9,False),(100.,True)):
                point = r.step(100.10, [('front',r.packet('front',stamp,A.point((.4,.4)),visible))])
                self.assertEqual(point.screen, B.id)
                self.assertIs(r.cameras.frames[mode], fresh)
                self.assertEqual(len(r.cameras.history[mode]), 1)

    def test_future_and_nonfinite_packets_cannot_poison_stream(self):
        with Replay() as r:
            self.start(r, ('front',))
            mode = r.mode('front')
            fresh = r.cameras.frames[mode]
            r.cameras.preview_key = 'front'
            for stamp in (101.,float('nan'),float('inf')):
                point = r.step(100.10, [('front',r.packet('front',stamp,thumbnail=b'invalid'))])
                self.assertIs(r.cameras.frames[mode], fresh)
                self.assertIsNotNone(point)
                self.assertIsNone(r.cameras.thumbnail)
            point = r.step(100.20, [('front',r.packet('front',100.20))])
            self.assertIsNotNone(point)
            self.assertEqual(r.cameras.frames[mode].t,100.20)

    def test_stale_packet_traffic_does_not_feed_watchdog(self):
        with Replay() as r:
            self.start(r, ('front',))
            for now in (101.,102.,103.,104.,104.01):
                point = r.step(now, [('front',r.packet('front',100.))])
                self.assertIsNone(point)
            self.assertNotIn('front', r.cameras.workers)
            self.assertNotIn(r.mode('front'), r.cameras.history)

    def test_no_eyes_is_live_capture_but_clears_observations(self):
        with Replay() as r:
            self.start(r)
            for now in (101.,102.,103.,104.,105.,106.):
                point = r.step(now, [('front',r.packet('front',now,visible=False)),
                                     ('side',r.packet('side',now))])
                self.assertEqual(point.cameras, (r.mode('side'),))
                self.assertIn('front', r.cameras.workers)
                self.assertNotIn(r.mode('front'), r.cameras.frames)
                self.assertFalse(r.cameras.history[r.mode('front')])

    def test_expired_frame_is_removed_before_starting_calibration(self):
        with Replay() as r:
            self.start(r, ('front',))
            r.app.profile_path = 'unused'
            self.assertIsNone(r.step(100.33))
            self.assertFalse(r.cameras.frames)
            r.app.begin(False)
            self.assertIsNone(r.app.wizard)
            self.assertIn('Waiting for visible eyes', r.app.notice.get())
