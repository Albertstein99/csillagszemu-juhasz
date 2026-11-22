"""Startup and process-exit failure cases through the live replay entry point."""
import unittest

from replay import Replay


class SupervisorReplay(unittest.TestCase):
    def test_status_only_traffic_cannot_extend_startup_timeout(self):
        with Replay() as r:
            r.cameras.running = True
            r.step(100.)
            old = r.cameras.workers['front']
            for now in (100.1, 120., 144.99, 145.):
                loading = ('Loading vision models', now, '', None, 0., None)
                point = r.step(now, [('front',loading), ('side',r.packet('side',now))])
                self.assertIs(r.cameras.workers['front'], old)
                self.assertEqual(point.cameras, (r.mode('side'),))
            loading = ('Loading vision models', 145.01, '', None, 0., None)
            point = r.step(145.01, [('front',loading), ('side',r.packet('side',145.01))])
            self.assertNotIn('front', r.cameras.workers)
            self.assertTrue(old[2].is_set())
            self.assertEqual(point.cameras, (r.mode('side'),))
            self.assertIsNotNone(r.dot)

    def test_dead_worker_is_detached_without_waiting_for_watchdog(self):
        with Replay() as r:
            r.cameras.running = True
            r.step(100.)
            point = r.step(100., [(k,r.packet(k)) for k in ('front','side')])
            self.assertEqual(len(point.cameras), 2)
            old = r.cameras.workers['front']
            old[0].alive = False
            point = r.step(100.10, [('side',r.packet('side',100.10))])
            self.assertEqual(point.cameras, (r.mode('side'),))
            self.assertNotIn('front', r.cameras.workers)
            self.assertNotIn(r.mode('front'), r.cameras.frames)
            self.assertNotIn(r.mode('front'), r.cameras.history)
            self.assertTrue(old[2].is_set())
            r.step(100.11, [('side',r.packet('side',100.11))])
            self.assertTrue(old[0].closed)
            self.assertTrue(old[1].closed)
            self.assertFalse(old[0].terminated)
            r.step(104.11, [('side',r.packet('side',104.11))])
            self.assertIsNot(r.cameras.workers['front'][0], old[0])
            point = r.step(104.12, [(k,r.packet(k,104.12)) for k in ('front','side')])
            self.assertEqual(set(point.cameras), {r.mode('front'),r.mode('side')})
