"""Elaina on the desktop: a small round bubble at the side of the screen.

    click the bubble          a compact chat panel opens next to it
    right-click the bubble    a menu: Open app (the full window) or Quit
    minimize the full app     it folds back into the bubble

The panel and the full app are two pages showing one conversation. Both talk
to the same engine through ChatHub, which sends every event to both, so
switching between them never loses a message or a half-answered question.
The pages only draw; they never decide anything (see CLAUDE.md).

    python -m concierge.ui          with the real Elaina
    python -m concierge.ui --fake   with FakeEngine, no model needed
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from pathlib import Path

from .. import events
from ..engine import ElainaEngine
from ..events import Engine, Error
from ..fake_engine import FakeEngine

WEB_DIR = Path(__file__).parent / "web"
TITLE = "Elaina"
# Shown when the engine fails in a way it did not turn into an Error event,
# such as Ollama dropping the connection halfway through a reply.
UNEXPECTED_ERROR = "Something went wrong on my side. Please try again, or restart the app."

# All sizes are in logical pixels, the ones Windows display scaling multiplies.
BUBBLE_SIZE = 52  # the bubble's window, cut to a circle
MENU_SIZE = (196, 96)  # the bubble's window while its right-click menu is open
EDGE_GAP = 16  # between the bubble or panel and the edge of the screen
# The panel is a tall, phone-shaped chat about a quarter of the screen wide.
PANEL_WIDTH_SHARE = 0.25
PANEL_MIN_WIDTH = 340
PANEL_MAX_WIDTH = 520
PANEL_RATIO = 1.6  # height divided by width
PANEL_MAX_HEIGHT_SHARE = 0.8  # never taller than this share of the screen
FULL_SIZE = (980, 720)
# The newest of these is kept so a page that loads later can catch up.
REMEMBERED = ("SystemInfo", "AgentList", "ChatList")

Area = tuple[int, int, int, int]  # x, y, width, height of the usable screen


# ------------------------------------------------------------------ chat


class ChatHub:
    """One engine shared by every chat page (the panel and the full app).

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


class PanelBridge(ChatBridge):
    """The compact panel's page: the chat, plus its two header buttons."""

    def __init__(self, hub: ChatHub, overlay: Overlay):
        super().__init__(hub)
        self._overlay = overlay

    def open_app(self) -> None:
        self._overlay.open_app()

    def hide_panel(self) -> None:
        self._overlay.hide_panel()


class BubbleBridge:
    """What the bubble's page can call."""

    def __init__(self, overlay: Overlay):
        self._overlay = overlay

    def toggle_panel(self) -> None:
        self._overlay.toggle_panel()

    def menu(self, open: bool) -> None:
        self._overlay.set_menu(bool(open))

    def moved(self) -> None:
        self._overlay.bubble_moved()

    def open_app(self) -> None:
        self._overlay.open_app()

    def quit(self) -> None:
        self._overlay.quit()


# ---------------------------------------------------------------- placing


def bubble_home(work: Area) -> tuple[int, int]:
    """Where the bubble starts: at the right edge, low enough that the panel
    fits above it with the bottoms lined up."""
    x, y, width, height = work
    return x + width - BUBBLE_SIZE - EDGE_GAP, y + round(height * 0.75)


def panel_size(work: Area) -> tuple[int, int]:
    _, _, width, height = work
    panel_width = round(min(max(width * PANEL_WIDTH_SHARE, PANEL_MIN_WIDTH), PANEL_MAX_WIDTH))
    return panel_width, round(min(panel_width * PANEL_RATIO, height * PANEL_MAX_HEIGHT_SHARE))


def place_panel(bubble: tuple[int, int], size: tuple[int, int], work: Area) -> tuple[int, int]:
    """Beside the bubble, on the side of the screen with more room, with the
    bottoms lined up, and always fully on the screen."""
    bubble_x, bubble_y = bubble
    width, height = size
    x0, y0, screen_width, screen_height = work
    gap = EDGE_GAP // 2
    if bubble_x + BUBBLE_SIZE / 2 > x0 + screen_width / 2:
        x = bubble_x - gap - width
    else:
        x = bubble_x + BUBBLE_SIZE + gap
    y = bubble_y + BUBBLE_SIZE - height
    x = min(max(x, x0 + EDGE_GAP), x0 + screen_width - width - EDGE_GAP)
    y = min(max(y, y0 + EDGE_GAP), y0 + screen_height - height - EDGE_GAP)
    return int(x), int(y)


def place_menu(bubble: tuple[int, int], work: Area) -> str:
    """Which way the bubble's window grows for its menu ("left down",
    "right up", ...): toward the middle of the screen, so it stays on it."""
    bubble_x, bubble_y = bubble
    x0, y0, screen_width, screen_height = work
    side = "left" if bubble_x + BUBBLE_SIZE / 2 > x0 + screen_width / 2 else "right"
    up = bubble_y + MENU_SIZE[1] > y0 + screen_height
    return f"{side} {'up' if up else 'down'}"


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
    """The bubble, the chat panel and the full app, and moving between them."""

    def __init__(self, engine: Engine, debug: bool = False):
        self.hub = ChatHub(engine)
        self.debug = debug
        self._bubble = self._panel = self._full = None
        self._work: Area = (0, 0, 0, 0)
        self._spot = (0, 0)  # the bubble's place on screen while its menu is closed
        self._grow = None  # how the bubble's window grew for its menu, while it is open
        self._panel_open = False
        self._quitting = False
        # Clicks arrive on several threads; one window change at a time.
        self._lock = threading.RLock()

    def open(self) -> None:
        """Show the bubble and block until the user quits."""
        import webview

        self._work = work_area()
        self._spot = bubble_home(self._work)
        panel_width, panel_height = panel_size(self._work)

        self._bubble = webview.create_window(
            TITLE,
            str(WEB_DIR / "bubble.html"),
            js_api=BubbleBridge(self),
            width=BUBBLE_SIZE,
            height=BUBBLE_SIZE,
            x=self._spot[0],
            y=self._spot[1],
            min_size=(BUBBLE_SIZE, BUBBLE_SIZE),
            resizable=False,
            frameless=True,
            easy_drag=False,  # only the circle drags (see bubble.html)
            on_top=True,
            shadow=False,
            background_color="#6B57D1",  # the circle's colour, before the page loads
        )
        panel_bridge = PanelBridge(self.hub, self)
        self._panel = webview.create_window(
            f"{TITLE} chat",
            str(WEB_DIR / "panel.html"),
            js_api=panel_bridge,
            width=panel_width,
            height=panel_height,
            min_size=(PANEL_MIN_WIDTH, 300),
            hidden=True,
            resizable=False,
            frameless=True,
            easy_drag=False,  # only the header drags
            on_top=True,
            text_select=True,  # People copy Elaina's answers.
        )
        full_bridge = ChatBridge(self.hub)
        self._full = webview.create_window(
            TITLE,
            str(WEB_DIR / "index.html"),
            js_api=full_bridge,
            width=FULL_SIZE[0],
            height=FULL_SIZE[1],
            min_size=(720, 520),
            hidden=True,
            background_color="#F7F7F5",
            text_select=True,
        )
        panel_bridge._attach(self._panel)
        full_bridge._attach(self._full)

        bubble_size = (BUBBLE_SIZE, BUBBLE_SIZE)
        self._bubble.events.before_show += _prepare(self._bubble, bubble_size, "circle")
        # Sized again once shown: Windows widens small windows as they are created.
        self._bubble.events.shown += lambda: _shape(self._bubble, "circle", bubble_size, resize=True)
        self._panel.events.before_show += _prepare(self._panel, (panel_width, panel_height), "rounded")
        self._full.events.minimized += self.fold_up
        self._full.events.closing += self._closing(self.fold_up)
        self._panel.events.closing += self._closing(self.hide_panel)
        self._bubble.events.closing += self._closing(self.quit)  # Alt+F4 on the bubble

        try:
            webview.start(debug=self.debug)
        finally:
            self.hub.close()

    # These run on the page's thread when the user clicks something.

    def toggle_panel(self) -> None:
        with self._lock:
            if self._panel_open:
                self.hide_panel()
            else:
                self.set_menu(False)
                size = panel_size(self._work)
                _shape(self._panel, "rounded", size, resize=True)
                self._panel.move(*place_panel(self._spot, size, self._work))
                self._panel.show()
                self._panel_open = True
                self._panel.run_js("window.app && app.shown()")

    def hide_panel(self) -> None:
        with self._lock:
            if self._panel_open:
                self._panel.hide()
                self._panel_open = False

    def set_menu(self, open: bool) -> None:
        """Grow the bubble's window to make room for its menu, or shrink it back.

        It grows from the corner that keeps the circle where it is, so the
        circle never jumps.
        """
        from webview.window import FixPoint

        with self._lock:
            if open == (self._grow is not None):
                return
            if open:
                self._grow = place_menu(self._spot, self._work)
                self._bubble.run_js(f"bubble.setMenu({json.dumps(self._grow)})")
            side, vertical = self._grow.split()
            fix = (FixPoint.EAST if side == "left" else FixPoint.WEST) | (
                FixPoint.SOUTH if vertical == "up" else FixPoint.NORTH
            )
            size = MENU_SIZE if open else (BUBBLE_SIZE, BUBBLE_SIZE)
            self._bubble.resize(*size, fix_point=fix)
            _shape(self._bubble, "card" if open else "circle", size)
            if not open:
                self._grow = None
                self._bubble.run_js("bubble.setMenu(null)")

    def bubble_moved(self) -> None:
        """The user dragged the bubble somewhere else; the panel follows it."""
        with self._lock:
            if self._grow is not None:
                return
            self._spot = (self._bubble.x, self._bubble.y)
            if self._panel_open:
                size = panel_size(self._work)
                self._panel.move(*place_panel(self._spot, size, self._work))

    def open_app(self) -> None:
        with self._lock:
            self.set_menu(False)
            self.hide_panel()
            self._bubble.hide()
            self._full.show()
            self._full.restore()  # in case it was minimized when it folded up
            self._full.run_js("window.app && app.shown()")

    def fold_up(self) -> None:
        """The full app was minimized or closed: back to the bubble."""
        with self._lock:
            if self._quitting:
                return
            self._full.hide()
            self._bubble.show()

    def quit(self) -> None:
        with self._lock:
            if self._quitting:
                return
            self._quitting = True
        for window in (self._full, self._panel, self._bubble):
            window.destroy()

    def _closing(self, instead):
        """Closing a window hides it instead (or quits, for the bubble). The
        handler runs on the window's own thread, which must not wait on the
        work it asks for, so that work runs on a thread of its own."""

        def handler():
            if self._quitting:
                return True
            threading.Thread(target=instead, daemon=True).start()
            return False  # pywebview: False cancels the close

        return handler


def _prepare(window, size: tuple[int, int], shape: str):
    """Ready the bubble or the panel just before it first shows, when its
    handle exists: keep it out of the taskbar and Alt+Tab, like other
    overlays, and give it its shape."""

    def handler():
        if sys.platform != "win32":
            return
        import ctypes

        gwl_exstyle, ws_ex_toolwindow, ws_ex_appwindow = -20, 0x80, 0x40000
        user32 = ctypes.windll.user32
        hwnd = window.native.Handle.ToInt32()
        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(hwnd, gwl_exstyle, (style | ws_ex_toolwindow) & ~ws_ex_appwindow)
        _shape(window, shape, size, resize=True)

    return handler


def _shape(window, shape: str, size: tuple[int, int], resize: bool = False) -> None:
    """Cut a window to its shape on Windows: "circle" (the bubble), "card"
    (the bubble with its menu open: a rounded card whose corners match the
    circle) or "rounded" (the panel, rounded by Windows 11 itself, smoothly
    and with a shadow).

    pywebview's see-through windows still show a solid box behind the page on
    Windows, so the window itself is cut instead. resize first sets the size
    exactly (logical pixels), without showing or moving the window.
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = window.native.Handle.ToInt32()
    scale = user32.GetDpiForWindow(hwnd) / 96  # the same scale pywebview uses
    width, height = round(size[0] * scale), round(size[1] * scale)
    if resize:
        swp_nomove, swp_nozorder, swp_noactivate = 0x2, 0x4, 0x10
        user32.SetWindowPos(hwnd, None, 0, 0, width, height, swp_nomove | swp_nozorder | swp_noactivate)

    if shape == "rounded":
        dwmwa_window_corner_preference, dwmwcp_round = 33, ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, dwmwa_window_corner_preference, ctypes.byref(dwmwcp_round), ctypes.sizeof(dwmwcp_round)
        )
        return
    gdi32.CreateEllipticRgn.restype = wintypes.HRGN
    gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    if shape == "circle":
        region = gdi32.CreateEllipticRgn(0, 0, width + 1, height + 1)
    else:
        corner = round(BUBBLE_SIZE * scale)
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, corner, corner)
    user32.SetWindowRgn(hwnd, region, True)  # Windows owns the region from here on


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concierge.ui", description="Elaina's chat window")
    parser.add_argument("--fake", action="store_true", help="use FakeEngine, no model needed")
    parser.add_argument("--debug", action="store_true", help="open the pages' developer tools")
    args = parser.parse_args(argv)

    Overlay(FakeEngine() if args.fake else ElainaEngine(), debug=args.debug).open()
    return 0
