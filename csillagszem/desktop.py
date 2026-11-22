"""Physical desktop pixels throughout. An interface path survives DISPLAY1 renumbering."""
import ctypes as C
import hashlib
from ctypes import wintypes as W
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Screen:
    id: str
    name: str
    x: int
    y: int
    w: int
    h: int

    def point(self, uv):
        return self.x + uv[0] * (self.w - 1), self.y + uv[1] * (self.h - 1)

    def uv(self, xy):
        return (xy[0] - self.x) / (self.w - 1), (xy[1] - self.y) / (self.h - 1)

    def contains(self, xy):
        return self.x <= xy[0] < self.x + self.w and self.y <= xy[1] < self.y + self.h

    def record(self):
        return asdict(self)


def aware():
    try:
        C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except AttributeError:
        C.windll.shcore.SetProcessDpiAwareness(2)


class MonitorInfo(C.Structure):
    _fields_ = [('size', W.DWORD), ('monitor', W.RECT), ('work', W.RECT),
                ('flags', W.DWORD), ('device', W.WCHAR * 32)]


class DisplayDevice(C.Structure):
    _fields_ = [('size', W.DWORD), ('name', W.WCHAR * 32), ('label', W.WCHAR * 128),
                ('flags', W.DWORD), ('path', W.WCHAR * 128), ('key', W.WCHAR * 128)]


def screens():
    user = C.windll.user32
    found = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HANDLE, W.HDC, C.POINTER(W.RECT), W.LPARAM)

    @callback_type
    def visit(handle, dc, rect, data):
        info = MonitorInfo()
        info.size = C.sizeof(info)
        if not user.GetMonitorInfoW(W.HANDLE(handle), C.byref(info)):
            return True
        dev = DisplayDevice()
        dev.size = C.sizeof(dev)
        identity = ''
        label = info.device
        index = 0
        while user.EnumDisplayDevicesW(info.device, index, C.byref(dev), 1):
            if dev.flags & 1 and dev.path:
                identity, label = dev.path, dev.label
                break
            index += 1
        # Virtual/RDP screens sometimes only expose the adapter name.
        identity = identity or ('logical:' + info.device)
        sid = hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
        area = info.monitor
        found.append(Screen(sid, label, area.left, area.top, area.right-area.left, area.bottom-area.top))
        return True
    if not user.EnumDisplayMonitors(None, None, visit, 0):
        raise OSError("Windows display enumeration failed")
    return sorted(found, key=lambda s: (s.x, s.y, s.id))


def place(window, x, y, w, h, no_activate=False):
    """SetWindowPos avoids Tk's relative-to-right-edge negative geometry convention."""
    window.update_idletasks()
    user = C.windll.user32
    user.GetAncestor.restype = W.HWND
    hwnd = user.GetAncestor(W.HWND(window.winfo_id()), 2)
    if no_activate:
        style = user.GetWindowLongW(W.HWND(hwnd), -20)
        user.SetWindowLongW(W.HWND(hwnd), -20, style | 0x20 | 0x80000 | 0x08000000 | 0x80)
    user.SetWindowPos(W.HWND(hwnd), W.HWND(-1), int(x), int(y), int(w), int(h), 0x10 if no_activate else 0)


def mouse():
    user = C.windll.user32
    p = W.POINT()
    user.GetCursorPos(C.byref(p))
    return bool(user.GetAsyncKeyState(1) & 0x8000), (p.x, p.y)
