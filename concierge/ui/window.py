"""Elaina on the desktop: a full window when she's wanted, a small circle when she isn't.

    the app opens             the full window, on Help me
    minimize or close it      it folds into a small circle in the corner
    click the circle          a small see-through window with her agents' work
                              and her messages; Open there brings the full one back

The full window and the see-through one are two pages showing one conversation.
Both talk to the same engine through ChatHub, which sends every event to both.
The pages only draw; they never decide anything (see CLAUDE.md).

    python -m concierge.ui          with the real Elaina
    python -m concierge.ui --fake   with FakeEngine and practice suggestions, no
                                    model needed and no files moved
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from pathlib import Path

from .. import events
from ..engine import ElainaEngine
from ..events import Engine, Error
from ..fake_engine import FakeEngine
from ..quick.tidy import TidyWatch

WEB_DIR = Path(__file__).parent / "web"
TITLE = "Elaina"
# Shown when the engine fails in a way it did not turn into an Error event,
# such as Ollama dropping the connection halfway through a reply.
UNEXPECTED_ERROR = "Something went wrong on my side. Please try again, or restart the app."

# All sizes are in logical pixels, the ones Windows display scaling multiplies.
EDGE_GAP = 16  # between the see-through window and the edge of the screen
GLASS_SIZE = (380, 130)  # quiet, its height follows what it has to say
GLASS_MIN_HEIGHT = 110
GLASS_CHAT_HEIGHT = 560  # the tallest it gets while talking
GLASS_GROW_STEPS, GLASS_GROW_SECONDS = 12, 0.012
GLASS_ABOVE = 84  # its bottom stays above minimized Elaina
GLASS_ALPHA = 253  # 0 to 255: nearly solid, because text behind it made it hard to read
GLASS_FADE_STEPS, GLASS_FADE_SECONDS = 10, 0.012
GLASS_LOAD_SECONDS = 20  # at most, while the app starts
FULL_SHARE = 0.9  # of the screen when the app opens, so it has the user's attention
FULL_MIN_SIZE = (860, 560)
# The newest of these is kept so a page that loads later can catch up.
REMEMBERED = ("SystemInfo", "AgentList", "ChatList")

Area = tuple[int, int, int, int]  # x, y, width, height of the usable screen


# ------------------------------------------------------------------ chat


class ChatHub:
    """One engine shared by every page (the full window and the see-through one).

    Every event goes to every page, and the other pages are told when one of
    them starts or finishes a call, so they all show the same conversation.
    """

    def __init__(self, engine: Engine):
        self._engine = engine
        self._pages: list[ChatBridge] = []  # pages that loaded and can draw
        # pywebview runs each call from a page in its own thread. One engine
        # call at a time keeps two replies from streaming into each other.
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._started = False
        self._startup: list[dict] = []  # what startup() sent, for pages that load later
        self._latest: dict[str, dict] = {}

    def join(self, page: ChatBridge) -> None:
        """A page has loaded. The first one starts the engine (startup() may
        only run once); later ones are caught up with what it said."""
        with self._lock:
            self._pages.append(page)
            if self._started:
                for data in self._startup:
                    page._call("onEvent", self._latest.get(data["type"], data))
                return
            self._started = True
            self._stream("startup", record=True)

    def run(self, origin: ChatBridge, name: str, *args, user: str | None = None, dots: bool = True) -> None:
        """Run one engine call for a page. Returns when every event is drawn,
        which is when the page enables its input again."""
        with self._lock:
            if origin not in self._pages:
                self._pages.append(origin)
            others = [page for page in self._pages if page is not origin]
            # The other pages show the user's message and wait, as the page
            # that made the call does.
            for page in others:
                page._call("mirror", {"state": "start", "user": user, "dots": dots})
            try:
                self._stream(name, *args)
            finally:
                for page in others:
                    page._call("mirror", {"state": "end"})

    def details(self, name: str) -> dict:
        """What an agent's page shows. It only reads, so it doesn't wait for a reply."""
        ask = getattr(self._engine, "details", None)
        return ask(name) if ask else {}

    def reset(self) -> None:
        with self._lock:
            self._engine.reset()

    def close(self) -> None:
        """The app is closing: stop drawing and let the engine free Elaina's memory.

        Does not wait for the lock, so closing never waits for a reply to finish.
        """
        self._closed.set()
        self._engine.close()

    def _stream(self, name: str, *args, record: bool = False) -> None:
        try:
            for event in getattr(self._engine, name)(*args):
                if self._closed.is_set():
                    break  # Leaving the loop also stops the reply.
                data = events.to_dict(event)
                if record:
                    self._startup.append(data)
                if data["type"] in REMEMBERED:
                    self._latest[data["type"]] = data
                self._send(data)
        except Exception:
            traceback.print_exc()
            self._send(events.to_dict(Error(UNEXPECTED_ERROR)))

    def _send(self, data: dict) -> None:
        for page in self._pages:
            page._call("onEvent", data)


class ChatBridge:
    """What a chat page can call, as window.pywebview.api.<method>.

    pywebview hands every public attribute to the page, so everything except
    the calls is kept private with a leading underscore.
    """

    def __init__(self, hub: ChatHub):
        self._hub = hub
        self._window = None

    def startup(self) -> None:
        self._hub.join(self)

    def send(self, text: str, think: bool = False) -> None:
        self._hub.run(self, "send", text, bool(think), user=text)

    def choose(self, id: str, choice: str) -> None:
        self._hub.run(self, "choose", id, choice, user=choice)

    def new_chat(self) -> None:
        self._hub.run(self, "new_chat", dots=False)

    def open_chat(self, id: str) -> None:
        self._hub.run(self, "open_chat", id, dots=False)

    def delete_chat(self, id: str) -> None:
        self._hub.run(self, "delete_chat", id, dots=False)

    def delete_agent(self, name: str) -> None:
        self._hub.run(self, "delete_agent", name)

    def toggle_agent(self, name: str) -> None:
        self._hub.run(self, "toggle_agent", name, dots=False)

    def reset(self) -> None:
        self._hub.reset()

    def _attach(self, window) -> None:
        self._window = window

    def _call(self, function: str, data: dict) -> None:
        """Run app.<function>(data) in the page."""
        if self._window is not None and not self._hub._closed.is_set():
            self._window.run_js(f"app.{function}({json.dumps(data)})")


class WatchBridge(ChatBridge):
    """A page that also shows what Elaina noticed and what her jobs are doing."""

    def __init__(self, hub: ChatHub, overlay: Overlay):
        super().__init__(hub)
        self._overlay = overlay

    def today(self) -> dict:
        watch = self._overlay.watch
        return watch.today() if watch else {}

    def answer(self, which: str, yes: bool) -> None:
        if self._overlay.watch:
            self._overlay.watch.answer(which, bool(yes))

    def undo_sorting(self) -> None:
        if self._overlay.watch:
            self._overlay.watch.undo()


class TodayBridge(WatchBridge):
    """The full window's page."""

    def agent_details(self, name: str) -> dict:
        return self._hub.details(name)

    def quit_app(self) -> None:
        self._overlay.quit()


class GlassBridge(WatchBridge):
    """The see-through window's page."""

    def open_app(self) -> None:
        self._overlay.open_app()

    def hide_glass(self) -> None:
        self._overlay.hide_glass()

    def fit_glass(self, height: int, talking: bool = False) -> None:
        self._overlay.fit_glass(height, talking)


# ---------------------------------------------------------------- placing


def full_size(work: Area) -> tuple[int, int]:
    """Most of the screen, however big it is, and never smaller than the window can be."""
    _, _, width, height = work
    return (min(width, max(round(width * FULL_SHARE), FULL_MIN_SIZE[0])),
            min(height, max(round(height * FULL_SHARE), FULL_MIN_SIZE[1])))


def centered(size: tuple[int, int], work: Area) -> tuple[int, int]:
    x, y, width, height = work
    return x + (width - size[0]) // 2, y + (height - size[1]) // 2


def glass_height(height: int, talking: bool, work: Area) -> int:
    """Always fits on the screen, under the circle's reach."""
    room = work[3] - GLASS_ABOVE - EDGE_GAP
    return min(max(int(height), GLASS_MIN_HEIGHT), GLASS_CHAT_HEIGHT, room)


def place_glass(size: tuple[int, int], work: Area) -> tuple[int, int]:
    """In the bottom right corner, just above minimized Elaina."""
    x, y, screen_width, screen_height = work
    width, height = size
    return x + screen_width - width - EDGE_GAP, y + screen_height - height - GLASS_ABOVE


def work_area() -> Area:
    """The main screen without the taskbar. Called before the windows open."""
    import webview

    screens = webview.screens
    # Windows puts the main screen's top-left corner at 0, 0.
    screen = next((s for s in screens if s.x == 0 and s.y == 0), screens[0])
    frame = getattr(screen, "frame", None)
    try:
        return int(frame.X), int(frame.Y), int(frame.Width), int(frame.Height)
    except AttributeError:  # not Windows: the whole screen
        return screen.x, screen.y, screen.width, screen.height


# --------------------------------------------------------------- windows


class Overlay:
    """The full window, minimized Elaina and the see-through window, and moving between them."""

    def __init__(self, engine: Engine, watch: TidyWatch | None = None, debug: bool = False):
        self.hub = ChatHub(engine)
        self.watch = watch
        self.debug = debug
        self._tray = self._mini = None
        self._full = self._glass = None
        self._work: Area = (0, 0, 0, 0)
        self._full_open = True
        self._glass_open = False
        self._glass_size = GLASS_SIZE
        self._quitting = False
        # Clicks arrive on several threads; one window change at a time.
        self._lock = threading.RLock()

    def open(self) -> None:
        """Open the full window and block until the user quits."""
        import webview

        self._work = work_area()
        width, height = full_size(self._work)
        x, y = centered((width, height), self._work)
        full_bridge = TodayBridge(self.hub, self)
        self._full = webview.create_window(
            TITLE,
            str(WEB_DIR / "today.html"),
            js_api=full_bridge,
            width=width,
            height=height,
            x=x,
            y=y,
            min_size=FULL_MIN_SIZE,
            background_color="#000000",  # the page's black, before it loads
            text_select=True,
        )
        glass_bridge = GlassBridge(self.hub, self)
        self._glass = webview.create_window(
            f"{TITLE} messages",
            str(WEB_DIR / "glass.html"),
            js_api=glass_bridge,
            width=GLASS_SIZE[0],
            height=GLASS_SIZE[1],
            min_size=(GLASS_SIZE[0], GLASS_MIN_HEIGHT),  # or Windows keeps it taller than its words
            hidden=True,
            resizable=False,
            frameless=True,
            easy_drag=False,
            on_top=True,
            background_color="#0A090C",
        )
        full_bridge._attach(self._full)
        glass_bridge._attach(self._glass)

        self._full.events.before_show += _dark_title(self._full)
        self._full.events.minimized += self.fold_up
        self._full.events.closing += self._closing(self.fold_up)
        self._glass.events.closing += self._closing(self.hide_glass)

        try:
            webview.start(self._ready, debug=self.debug)
        finally:
            self.hub.close()
            if self._tray:
                self._tray.stop()
            if self._mini:
                self._mini.close()
            if self.watch:
                self.watch.stop()

    def _ready(self) -> None:
        """The windows exist: she can start noticing things."""
        from .mini import Mini
        from .tray import Tray

        # A hidden window only has its handle, and stops changing, once its page is in.
        self._glass.events.loaded.wait(GLASS_LOAD_SECONDS)
        _prepare_glass(self._glass, self._glass_size)
        self._mini = Mini(self.toggle_glass)
        self._tray = Tray(self.open_app, self.quit, self.watch)
        self._tray.start()
        if self.watch:
            self.watch.changed = self._watch_changed
            # While the full window is open she has the user's attention anyway.
            self.watch.held = lambda: self._full_open
            self.watch.start()

    def _watch_changed(self) -> None:
        from .mini import ASKING, IDLE, WORKING

        if self._quitting:
            return
        self._tray.refresh()
        working = self.watch.today()["working"]
        self._mini.set_state(WORKING if working else ASKING if self.watch.asking else IDLE)
        self._full.run_js("window.today && today.refresh()")
        self._glass.run_js("window.app && app.refresh()")

    # These run on the page's, the circle's or the icon's thread when the user clicks something.

    def toggle_glass(self) -> None:
        with self._lock:
            if self._glass_open:
                self.hide_glass()
                return
            _set_bounds(self._glass, (*place_glass(self._glass_size, self._work), *self._glass_size))
            self._glass.show()
            self._glass_open = True
            self._glass.run_js("window.app && app.shown()")
            _fade(self._glass, 0, GLASS_ALPHA)

    def fit_glass(self, height: int, talking: bool = False) -> None:
        """It's exactly as tall as the page asks, rising smoothly out of the
        corner when the user is talking."""
        with self._lock:
            start = self._glass_size[1]
            end = glass_height(height, talking, self._work)
            self._glass_size = (GLASS_SIZE[0], end)
            if self._quitting or self._glass.native is None or start == end:
                return
            steps = GLASS_GROW_STEPS if self._glass_open and talking else 1
            for step in range(1, steps + 1):
                now = round(start + (end - start) * step / steps)
                _set_bounds(self._glass, (*place_glass((GLASS_SIZE[0], now), self._work), GLASS_SIZE[0], now))
                if steps > 1:
                    time.sleep(GLASS_GROW_SECONDS)

    def hide_glass(self) -> None:
        with self._lock:
            if self._glass_open:
                _fade(self._glass, GLASS_ALPHA, 0)
                self._glass.hide()
                self._glass_open = False

    def open_app(self) -> None:
        with self._lock:
            self.hide_glass()
            if self._mini:
                self._mini.hide()
            self._full_open = True
            self._full.show()
            self._full.restore()  # in case it was minimized when it folded up
            self._full.run_js("window.app && app.shown()")

    def fold_up(self) -> None:
        """The full window was minimized or closed: she folds into the circle."""
        with self._lock:
            if self._quitting:
                return
            self._full.hide()
            self._full_open = False
            if self._mini:
                self._mini.show()

    def quit(self) -> None:
        with self._lock:
            if self._quitting:
                return
            self._quitting = True
        for window in (self._full, self._glass):
            window.destroy()

    def _closing(self, instead):
        """Closing a window hides it instead. The
        handler runs on the window's own thread, which must not wait on the
        work it asks for, so that work runs on a thread of its own."""

        def handler():
            if self._quitting:
                return True
            threading.Thread(target=instead, daemon=True).start()
            return False  # pywebview: False cancels the close

        return handler


def _prepare_glass(window, size: tuple[int, int]) -> None:
    """Ready the see-through window while it is still hidden, so it never
    flashes up solid: keep it out of the taskbar and Alt+Tab, like other
    overlays, and let Windows blend it with whatever is behind it."""
    if sys.platform != "win32":
        return
    import ctypes

    gwl_exstyle, ws_ex_toolwindow, ws_ex_appwindow, ws_ex_layered = -20, 0x80, 0x40000, 0x80000
    user32 = ctypes.windll.user32
    hwnd = window.native.Handle.ToInt32()
    style = user32.GetWindowLongW(hwnd, gwl_exstyle)
    user32.SetWindowLongW(hwnd, gwl_exstyle, (style | ws_ex_toolwindow | ws_ex_layered) & ~ws_ex_appwindow)
    _see_through(hwnd, 0)
    _rounded(window, size)


def _dark_title(window):
    """A title bar that matches the page's dark side list. Windows 11 only;
    older versions ignore this and keep their own colour."""

    def handler():
        if sys.platform != "win32":
            return
        import ctypes

        dwmwa_caption_color, caption = 35, ctypes.c_int(0x0C090A)  # #0a090c, written blue first
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            window.native.Handle.ToInt32(), dwmwa_caption_color, ctypes.byref(caption), ctypes.sizeof(caption)
        )

    return handler


def _see_through(hwnd: int, alpha: int) -> None:
    import ctypes

    lwa_alpha = 2
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, lwa_alpha)


def _fade(window, start: int, end: int) -> None:
    """Fade a see-through window in or out, instead of it popping up."""
    if sys.platform != "win32":
        return
    hwnd = window.native.Handle.ToInt32()
    for step in range(1, GLASS_FADE_STEPS + 1):
        _see_through(hwnd, round(start + (end - start) * step / GLASS_FADE_STEPS))
        time.sleep(GLASS_FADE_SECONDS)


def _set_bounds(window, bounds: tuple[int, int, int, int]) -> None:
    """Move and size a window (logical pixels) in one step, so its edges never
    jump, as they would with a resize and then a move."""
    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = window.native.Handle.ToInt32()
    scale = user32.GetDpiForWindow(hwnd) / 96  # the same scale pywebview uses
    x, y, width, height = (round(value * scale) for value in bounds)
    swp_nozorder, swp_noactivate = 0x4, 0x10
    user32.SetWindowPos(hwnd, None, x, y, width, height, swp_nozorder | swp_noactivate)


def _rounded(window, size: tuple[int, int]) -> None:
    """Set the window's exact size (logical pixels), without showing or moving
    it, and let Windows 11 round its corners, smoothly and with a shadow."""
    if sys.platform != "win32":
        return
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = window.native.Handle.ToInt32()
    scale = user32.GetDpiForWindow(hwnd) / 96  # the same scale pywebview uses
    swp_nomove, swp_nozorder, swp_noactivate = 0x2, 0x4, 0x10
    user32.SetWindowPos(hwnd, None, 0, 0, round(size[0] * scale), round(size[1] * scale),
                        swp_nomove | swp_nozorder | swp_noactivate)
    dwmwa_window_corner_preference, dwmwcp_round = 33, ctypes.c_int(2)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, dwmwa_window_corner_preference, ctypes.byref(dwmwcp_round), ctypes.sizeof(dwmwcp_round)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concierge.ui", description="Elaina's chat window")
    parser.add_argument("--fake", action="store_true", help="use FakeEngine, no model needed")
    parser.add_argument("--debug", action="store_true", help="open the pages' developer tools")
    args = parser.parse_args(argv)

    engine = FakeEngine() if args.fake else ElainaEngine()
    Overlay(engine, TidyWatch(practice=args.fake), debug=args.debug).open()
    return 0
