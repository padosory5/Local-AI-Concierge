"""The light around the screen: how the user sees that work started and ended.

When a job the user said yes to starts, a soft light runs once around the edge
of the screen they are working on, then fades. A thin line stays at the right
edge while the job runs. When it is done, the same light runs round in green.
Noir shows no message for any of this; the light is the message.

The light is four windows, one along each edge. Windows blends their soft
edges itself and is told only how much of each to show, so a frame costs almost
nothing, and clicks and typing pass straight through to the program below.

The windows only exist while there is light to show. Everything Windows needs
is on one thread of its own, which ends again when the light goes out.
"""

from __future__ import annotations

import ctypes
import math
import queue
import sys
import threading
import time
from ctypes import wintypes

LILAC, GREEN = (166, 139, 189), (79, 196, 140)  # started, done
THICKNESS_SHARE = 0.09  # how far the light reaches in, as a share of the screen's height
RIM_SHARE = 0.03  # the bright rim at the very edge, as a share of that reach
BRIGHTEST = 0.8  # how solid the light is at the rim, 0 to 1
RUN_SECONDS, HOLD_SECONDS, FADE_SECONDS = 0.8, 0.25, 1.0
FRAME_SECONDS = 1 / 60
LINE_SHARE = 0.4  # how long the thin line is, as a share of the screen's height
LINE_BREATH_SECONDS = 3.0  # one slow brighter and dimmer of the line

if sys.platform == "win32":
    _user32, _gdi32, _shell32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32"), ctypes.WinDLL("shell32")
else:  # the light is Windows only for now: elsewhere the module imports and shows nothing
    _user32 = _gdi32 = _shell32 = None
_pointer = wintypes.HANDLE
WS_POPUP = 0x80000000
# Layered: soft edges. Transparent: clicks go through. The others keep it on
# top, out of Alt+Tab, and away from the keyboard.
LIGHT_STYLE = 0x00080000 | 0x00000020 | 0x00000008 | 0x00000080 | 0x08000000
_SW_HIDE, _SW_SHOW_QUIETLY = 0, 4
_ULW_ALPHA = 2
_MONITOR_PRIMARY = 1


class _Blend(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]


class _BitmapHeader(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                ("image_size", wintypes.DWORD), ("x_ppm", wintypes.LONG), ("y_ppm", wintypes.LONG),
                ("used", wintypes.DWORD), ("important", wintypes.DWORD)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]


if sys.platform == "win32":  # the shapes of the calls, told once
    _user32.CreateWindowExW.restype = _pointer
    _user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, _pointer, _pointer, _pointer, _pointer]
    _user32.UpdateLayeredWindow.argtypes = [_pointer, _pointer, ctypes.POINTER(wintypes.POINT),
                                            ctypes.POINTER(wintypes.SIZE), _pointer, ctypes.POINTER(wintypes.POINT),
                                            wintypes.DWORD, ctypes.POINTER(_Blend), wintypes.DWORD]
    _user32.ShowWindow.argtypes = [_pointer, ctypes.c_int]
    _user32.DestroyWindow.argtypes = [_pointer]
    _user32.GetForegroundWindow.restype = _pointer
    _user32.MonitorFromWindow.restype = _pointer
    _user32.MonitorFromWindow.argtypes = [_pointer, wintypes.DWORD]
    _user32.GetMonitorInfoW.argtypes = [_pointer, ctypes.POINTER(_MonitorInfo)]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), _pointer, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _gdi32.CreateCompatibleDC.restype = _pointer
    _gdi32.CreateCompatibleDC.argtypes = [_pointer]
    _gdi32.CreateDIBSection.restype = _pointer
    _gdi32.CreateDIBSection.argtypes = [_pointer, ctypes.POINTER(_BitmapHeader), wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_void_p), _pointer, wintypes.DWORD]
    _gdi32.SelectObject.restype = _pointer
    _gdi32.SelectObject.argtypes = [_pointer, _pointer]
    _gdi32.DeleteObject.argtypes = [_pointer]
    _gdi32.DeleteDC.argtypes = [_pointer]


def light_at(distance: int, reach: int) -> float:
    """How solid the light is this many pixels in from the screen's edge."""
    rim = max(2, round(reach * RIM_SHARE))
    if distance < rim:
        return BRIGHTEST
    left = 1 - (distance - rim) / max(1, reach - rim)
    return max(0.0, BRIGHTEST * 0.62 * left ** 2.4)


def pixel(color: tuple[int, int, int], strength: float) -> bytes:
    """One pixel the way Windows wants it: blue first, colour already dimmed by its strength."""
    red, green, blue = color
    return bytes((round(blue * strength), round(green * strength), round(red * strength), round(255 * strength)))


def reached(progress: float, width: int, height: int) -> dict[str, int]:
    """How far along each edge the light has run, 0 to 1 of its way round.

    It starts in the bottom right corner, where the question was, and goes
    both ways round until the two ends meet in the top left corner.
    """
    run = progress * (width + height)
    return {"right": round(min(run, height)), "bottom": round(min(run, width)),
            "top": round(min(max(run - height, 0), width)), "left": round(min(max(run - width, 0), height))}


def eased(t: float) -> float:
    """Starts and ends gently, for anything that moves."""
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def full_screen_in_use() -> bool:
    """A game, a video, a slideshow or the lock screen: not the moment for light."""
    state = ctypes.c_int(0)
    # Windows' answers: 1 locked, 2 full screen, 3 a game, 4 a presentation.
    return _shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (1, 2, 3, 4)


def work_screen(whole: bool = True, main: bool = False) -> tuple[int, int, int, int]:
    """x, y, width, height of the screen the user is working on (or the main
    screen), whole or just the part above the taskbar. Call real_pixels() on
    the thread first."""
    monitor = _user32.MonitorFromWindow(None if main else _user32.GetForegroundWindow(), _MONITOR_PRIMARY)
    info = _MonitorInfo()
    info.size = ctypes.sizeof(_MonitorInfo)
    _user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    rect = info.monitor if whole else info.work
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def real_pixels() -> None:
    """The same pixels as the mouse and the screen, on any display scaling."""
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


class Layer:
    """One see-through window holding a picture; any part of it can be shown."""

    def __init__(self, width: int, height: int, pixels: bytes, style: int = LIGHT_STYLE, window_style: int = WS_POPUP):
        self.width, self.height = width, height
        self.hwnd = _user32.CreateWindowExW(style, "Static", None, window_style, 0, 0, 0, 0, None, None, None, None)
        self.dc = _gdi32.CreateCompatibleDC(None)
        # A negative height: rows start at the top, as `pixels` does.
        header = _BitmapHeader(ctypes.sizeof(_BitmapHeader), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        self.bitmap = _gdi32.CreateDIBSection(self.dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        self.bits = bits
        self.draw(pixels)
        self.previous = _gdi32.SelectObject(self.dc, self.bitmap)
        self.shown = False

    def draw(self, pixels: bytes) -> None:
        """Put a new picture of the same size in the window."""
        ctypes.memmove(self.bits, pixels, len(pixels))

    def show(self, x: int, y: int, width: int, height: int, from_x: int, from_y: int, alpha: int) -> None:
        """Show part of the picture, starting at from_x, from_y, at x, y on screen."""
        if width <= 0 or height <= 0 or alpha <= 0:
            self.hide()
            return
        _user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(wintypes.POINT(x, y)),
                                    ctypes.byref(wintypes.SIZE(width, height)), self.dc,
                                    ctypes.byref(wintypes.POINT(from_x, from_y)), 0,
                                    ctypes.byref(_Blend(0, 0, alpha, 1)), _ULW_ALPHA)
        if not self.shown:
            _user32.ShowWindow(self.hwnd, _SW_SHOW_QUIETLY)
            self.shown = True

    def hide(self) -> None:
        if self.shown:
            _user32.ShowWindow(self.hwnd, _SW_HIDE)
            self.shown = False

    def close(self) -> None:
        _user32.DestroyWindow(self.hwnd)
        _gdi32.SelectObject(self.dc, self.previous)
        _gdi32.DeleteObject(self.bitmap)
        _gdi32.DeleteDC(self.dc)


def _edges(color: tuple[int, int, int], width: int, height: int) -> dict[str, Layer]:
    reach = round(height * THICKNESS_SHARE)
    across = [pixel(color, light_at(distance, reach)) for distance in range(reach)]  # edge first
    return {
        "top": Layer(width, reach, b"".join(p * width for p in across)),
        "bottom": Layer(width, reach, b"".join(p * width for p in reversed(across))),
        "left": Layer(reach, height, b"".join(across) * height),
        "right": Layer(reach, height, b"".join(reversed(across)) * height),
    }


def pump(on_message=None) -> None:
    """Answer whatever Windows asks these windows, so nothing waits on them.
    on_message sees each message first, for windows that can be clicked."""
    message = wintypes.MSG()
    while _user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
        if on_message:
            on_message(message)
        _user32.TranslateMessage(ctypes.byref(message))
        _user32.DispatchMessageW(ctypes.byref(message))


class Glow:
    """Safe to call from any thread. Lights take turns: a green light asked for
    while the lilac one is still running waits for it to finish."""

    def __init__(self, in_full_screen=None):
        """in_full_screen is replaced in tests."""
        self._in_full_screen = in_full_screen or full_screen_in_use
        self._requests: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()

    def started(self) -> None:
        self._ask("started")

    def finished(self) -> None:
        self._ask("finished")

    def failed(self) -> None:
        """The job stopped without finishing: the line goes out, with no green."""
        self._ask("failed")

    def close(self) -> None:
        self._closing.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _ask(self, request: str) -> None:
        with self._lock:
            self._requests.put(request)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="glow", daemon=True)
                self._thread.start()

    # Everything below runs on the light's own thread.

    def _run(self) -> None:
        real_pixels()
        line = None
        while not self._closing.is_set():
            try:
                request = self._requests.get(timeout=FRAME_SECONDS * 4)
            except queue.Empty:
                with self._lock:
                    if line is None and self._requests.empty():
                        self._thread = None
                        return
                pump()
                if line:
                    self._breathe(line)
                continue
            if request == "started":
                if not self._in_full_screen():
                    self._run_light(LILAC)
                    line = line or self._line()
            else:
                if line:
                    line.close()
                    line = None
                if request == "finished":
                    # Saved for when the game or video is over, so "done" is still seen.
                    while self._in_full_screen() and not self._closing.is_set():
                        self._closing.wait(2)
                    self._run_light(GREEN)
        if line:
            line.close()
        with self._lock:
            self._thread = None

    def _run_light(self, color: tuple[int, int, int]) -> None:
        x, y, width, height = work_screen()
        edges = _edges(color, width, height)
        reach = edges["top"].height
        began = time.monotonic()
        try:
            while not self._closing.is_set():
                spent = time.monotonic() - began
                after_hold = spent - RUN_SECONDS - HOLD_SECONDS
                alpha = 255 if after_hold <= 0 else round(255 * (1 - eased(after_hold / FADE_SECONDS)))
                if alpha <= 0:
                    break
                far = reached(eased(spent / RUN_SECONDS), width, height)
                # Each edge grows out of the corner the light reached it from.
                edges["right"].show(x + width - reach, y + height - far["right"], reach, far["right"],
                                    0, height - far["right"], alpha)
                edges["bottom"].show(x + width - far["bottom"], y + height - reach, far["bottom"], reach,
                                     width - far["bottom"], 0, alpha)
                edges["top"].show(x + width - far["top"], y, far["top"], reach, width - far["top"], 0, alpha)
                edges["left"].show(x, y + height - far["left"], reach, far["left"], 0, height - far["left"], alpha)
                pump()
                time.sleep(FRAME_SECONDS)
        finally:
            for edge in edges.values():
                edge.close()

    def _line(self) -> Layer:
        x, y, width, height = work_screen()
        long = round(height * LINE_SHARE)
        wide = max(3, round(height / 400))
        rows = [pixel(LILAC, 0.95 * math.sin(math.pi * row / long)) * wide for row in range(long)]
        layer = Layer(wide, long, b"".join(rows))
        self._line_place = (x + width - wide, y + (height - long) // 2)
        self._breathe(layer)
        return layer

    def _breathe(self, line: Layer) -> None:
        phase = time.monotonic() / LINE_BREATH_SECONDS * math.tau
        line.show(*self._line_place, line.width, line.height, 0, 0, round(190 + 65 * math.sin(phase)))
