"""Independent device discovery, capture watchdogs, and timestamped latest-frame delivery."""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import hashlib
import math
import multiprocessing as mp
import queue
import threading
import time

from .model import Frame


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    backend: int
    index: int


def enumerate_devices():
    import cv2
    from cv2_enumerate_cameras import enumerate_cameras
    entries = []
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
        try:
            entries.extend(enumerate_cameras(backend))
        except (RuntimeError,OSError):
            continue
    names = Counter((i.backend,i.name.casefold()) for i in entries)
    devices = {}
    for i in entries:
        path = (i.path or '').casefold()
        if path:
            path = path.removeprefix('@device:pnp:').removesuffix('\\global')
        elif names[i.backend,i.name.casefold()] == 1:
            path = 'name:' + i.name.casefold()
        else:
            continue  # indistinguishable devices must not swap personal calibrations
        key = hashlib.sha256(path.encode()).hexdigest()[:24]
        devices.setdefault(key,Device(key,i.name,i.backend,i.index))
    return devices


def capture_worker(device, directory, output, stop, preview, size):
    import cv2
    from .vision import Vision
    def send(status, t=None, mode='', features=None, quality=0., thumbnail=None):
        try:
            output.put_nowait((status,time.monotonic() if t is None else t,mode,features,quality,thumbnail))
        except queue.Full:
            pass

    cap = detector = None
    condition = threading.Condition()
    latest = [None]
    ended = threading.Event()
    try:
        send("Loading vision models")
        detector = Vision(directory)
        # Look up the current capture index from the persistent identifier at open time.
        actual = enumerate_devices().get(device.id)
        if actual is None:
            raise RuntimeError("Camera disconnected")
        cap = cv2.VideoCapture(actual.index, actual.backend)
        if not cap.isOpened():
            raise RuntimeError("Cannot open camera. Check Windows camera access and other apps.")
        cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT,size[1])
        cap.set(cv2.CAP_PROP_FPS,30)
        if enumerate_devices().get(device.id) != actual:
            raise RuntimeError("Camera list changed during open. Retrying.")
        def read_latest():
            failures = 0
            try:
                while not stop.is_set():
                    ok, image = cap.read()
                    captured = time.monotonic()
                    if not ok:
                        failures += 1
                        if failures >= 5:
                            break
                        time.sleep(.045)
                        continue
                    failures = 0
                    with condition:
                        latest[0] = captured,image
                        condition.notify()
            finally:
                ended.set()
                with condition:
                    condition.notify()
        reader = threading.Thread(target=read_latest,daemon=True)
        reader.start()
        last_preview = -100.
        while not stop.is_set() and not ended.is_set():
            with condition:
                condition.wait_for(lambda:latest[0] is not None or ended.is_set() or stop.is_set(),.4)
                packet,latest[0] = latest[0],None
            if packet is None:
                continue
            stamp,image = packet
            result,status = detector.read(image,stamp)
            h,w = image.shape[:2]
            mode = f'{device.id}/{w}x{h}'
            features,quality = result if result else (None,0.)
            thumbnail = None
            if preview.is_set() and stamp-last_preview>=.3:
                last_preview=stamp
                thumb=cv2.resize(image,(224,max(1,round(224*h/w))),interpolation=cv2.INTER_AREA)
                ok,png=cv2.imencode('.png',cv2.flip(thumb,1))
                if ok:
                    thumbnail=png.tobytes()
            send(status,stamp,mode,features,quality,thumbnail)
        if ended.is_set() and not stop.is_set():
            raise RuntimeError("Camera stopped delivering frames")
    except Exception as e:
        send(str(e)[:280])
    finally:
        # On shutdown a hardware driver may block inside read(). Only its owning
        # child is ever terminated. Do not release OpenCV concurrently with read().
        if cap is not None and ('reader' not in locals() or not reader.is_alive()):
            cap.release()
        if detector is not None:
            detector.close()


class Cameras:
    def __init__(self, directory):
        self.directory = str(directory)
        self.ctx = mp.get_context('spawn')
        self.devices = {}
        self.disabled = set()
        self.workers = {}
        self.retry = {}
        self.status = {}
        self.frames = {}
        self.history = defaultdict(lambda:deque(maxlen=150))
        self.results = queue.Queue(1)
        self.scanning = False
        self.scan_time = -100.
        self.running = False
        self.discovery_error = ''
        self.retiring = []
        self.size = (1920,1080)
        self.preview_key = None
        self.thumbnail = None

    def discover(self):
        if self.scanning:
            return
        self.scan_time = time.monotonic()
        self.scanning = True
        def scan():
            try:
                self.results.put((enumerate_devices(), ''))
            except Exception as e:
                self.results.put((None,str(e)))
        threading.Thread(target=scan,daemon=True).start()

    def detach(self, key):
        if self.thumbnail and self.thumbnail[0]==key:
            self.thumbnail=None
        worker = self.workers.pop(key,None)
        if worker:
            proc,output,stop,*_ = worker
            stop.set()
            self.retiring.append((time.monotonic(),proc,output,key))
        for mode in list(self.frames):
            if mode.startswith(key+'/'):
                self.frames.pop(mode,None)
        for mode in list(self.history):
            if mode.startswith(key+'/'):
                self.history.pop(mode,None)

    def maintenance(self, now):
        # Expiry must happen even when a worker is silent. In particular, stale
        # observations must not make App.begin think calibration can start.
        for mode,frame in list(self.frames.items()):
            if not 0 <= now-frame.t <= .32:
                self.frames.pop(mode,None)
                self.history[mode].clear()
        for entry in self.retiring[:]:
            since,proc,out,key = entry
            if proc.is_alive() and now-since>1.2:
                proc.terminate()
            if not proc.is_alive():
                proc.join(0)
                proc.close()
                out.close()
                self.retiring.remove(entry)
        if now-self.scan_time>=3 and not self.scanning:
            self.discover()
        try:
            devices,self.discovery_error = self.results.get_nowait()
            self.scanning = False
            if devices is not None:
                self.devices = devices
        except queue.Empty:
            pass
        for key in list(self.workers):
            if key not in self.devices or key in self.disabled or not self.running:
                self.detach(key)
        if not self.running:
            return
        for key,device in self.devices.items():
            if key in self.disabled:
                continue
            if key not in self.workers:
                if now < self.retry.get(key,0) or any(w[3]==key for w in self.retiring):
                    continue
                output,stop = self.ctx.Queue(8),self.ctx.Event()
                preview=self.ctx.Event()
                proc = self.ctx.Process(target=capture_worker,args=(device,self.directory,output,stop,preview,self.size),daemon=True)
                proc.start()
                self.workers[key] = [proc,output,stop,now,False,preview,-math.inf]
                self.status[key] = 'Starting camera'
            worker = self.workers[key]
            proc,output,stop,heartbeat,started,preview,last_capture = worker
            if key==self.preview_key:
                preview.set()
            else:
                preview.clear()
            while True:
                try:
                    status,t,mode,x,q,thumbnail = output.get_nowait()
                except (queue.Empty,EOFError,OSError):
                    break
                if not mode:
                    self.status[key] = status
                    continue
                # Receipt is not capture progress: delayed, duplicate or invalid
                # packets must neither replace a newer observation nor keep a
                # stalled capture/inference pipeline alive. No-eyes captures do
                # count as progress, and clear the previous fixation normally.
                if not math.isfinite(t) or not 0 <= now-t <= .32 or t <= worker[6]:
                    continue
                worker[3],worker[4],worker[6] = t,True,t
                if thumbnail and key==self.preview_key:
                    self.thumbnail=(key,t,thumbnail)
                self.status[key] = status
                if x is None:
                    self.frames.pop(mode,None)
                    self.history[mode].clear()
                else:
                    f = Frame(mode,t,x,q)
                    self.frames[mode] = f
                    self.history[mode].append(f)
            if not proc.is_alive() or now-worker[3] > (4. if worker[4] else 45.):
                if proc.is_alive():
                    self.status[key] = 'Camera stalled; reconnecting'
                self.detach(key)
                self.retry[key] = now+4.

    def close(self):
        self.running = False
        for key in list(self.workers):
            self.detach(key)
        for _,proc,out,_ in self.retiring:
            if proc.is_alive():
                proc.terminate()
            proc.join(.5)
            out.close()
