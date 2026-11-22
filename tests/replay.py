"""Virtual-clock camera transport for the real supervisor and App.tick.

Only OS boundaries are replaced: discovery, processes, the clock and UI surfaces.
Packets retain the capture-worker wire format. No camera frames leave memory.
"""
from contextlib import ExitStack
import queue
import threading
from unittest.mock import Mock, patch

from csillagszem.app import App
from csillagszem.cameras import Cameras, Device
from csillagszem.model import Smoother
from test_tracking import B, LAYOUT, features, make_bank


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class Output(queue.Queue):
    def close(self):
        self.closed = True


class Process:
    def __init__(self, target, args, daemon):
        self.target, self.args = target, args
        self.alive = self.terminated = self.closed = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False

    def join(self, timeout):
        pass

    def close(self):
        self.closed = True


class Context:
    Queue = staticmethod(Output)
    Event = staticmethod(threading.Event)

    def __init__(self):
        self.processes = []

    def Process(self, **kwargs):
        proc = Process(**kwargs)
        self.processes.append(proc)
        return proc


class Replay:
    def __init__(self):
        self.now = 100.
        self.layout = dict(LAYOUT)
        self.devices = {key:Device(key, key.title(), 700, index)
                        for index, key in enumerate(('front', 'side'))}
        self.context = Context()
        self.cameras = Cameras('unused-model-directory')
        self.cameras.ctx = self.context
        self.app = app = App.__new__(App)
        app.root = Mock()
        app.cameras = self.cameras
        app.displays = dict(self.layout)
        bank = make_bank()
        app.profile = {'version':1, 'banks':{self.mode(k):[bank] for k in self.devices}}
        app.profile_path = None
        app.wizard = None
        app.last_display = app.last_paint = -100.
        app.autodrift = Value(False)
        app.marker = Value(True)
        app.readout, app.notice = Value(), Value()
        app.smoother = Smoother()
        app.draw = Mock()
        app.show_dot = Mock(side_effect=lambda p:setattr(self, 'dot', p))
        app.hide_dot = Mock(side_effect=lambda:setattr(self, 'dot', None))
        self.dot = None

    @staticmethod
    def mode(key):
        return key+'/1920x1080'

    def packet(self, key, stamp=None, xy=None, visible=True, thumbnail=None):
        return ('Eyes visible' if visible else 'No eyes', self.now if stamp is None else stamp,
                self.mode(key), features(B.point((.4,.4)) if xy is None else xy, .04).tolist()
                if visible else None, .9 if visible else 0., thumbnail)

    def __enter__(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch('csillagszem.cameras.time.monotonic', lambda:self.now))
        self.stack.enter_context(patch('csillagszem.cameras.enumerate_devices', lambda:dict(self.devices)))
        self.stack.enter_context(patch('csillagszem.cameras.threading.Thread', InlineThread))
        self.stack.enter_context(patch('csillagszem.app.desktop.screens', lambda:list(self.layout.values())))
        return self

    def step(self, now, packets=(), devices=None):
        if now < self.now:
            raise ValueError('Replay time must be monotonic')
        self.now = now
        if devices is not None:
            self.devices = dict(devices)
            self.cameras.discover()
        for key, packet in packets:
            self.cameras.workers[key][1].put_nowait(packet)
        self.app.tick()
        return self.app.smoother.last

    def __exit__(self, *exc):
        self.cameras.close()
        self.stack.close()
