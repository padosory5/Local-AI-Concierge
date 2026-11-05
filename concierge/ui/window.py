"""Elaina on the desktop: a full window when she's wanted, a small circle when she isn't.

    the app opens             the full window, on Help me
    minimize or close it      it stays on the taskbar, and she folds into a small
                              circle in the corner
    click the circle          a small window with her agents' work and her
                              messages; Open there brings the full one back
    tap Ctrl twice, anywhere  the Spot: help with what's highlighted, right there

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
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from .. import events
from ..cloud import load_providers, sent_recently
from ..elaina import data_dir
from ..engine import ElainaEngine
from ..events import Engine, Error
from ..fake_engine import FakeEngine
from ..quick.tidy import TidyWatch
from ..reservations import RUN, SORT, TURN_ON, Reservation, ReservationError, Reservations

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
FULL_MIN_SIZE = (640, 560)  # half of a small screen, for working side by side
SCREEN_SETTLE_SECONDS = 0.25  # for the window to be gone before a screenshot
PICTURES = "Pictures (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp)"
EXPORTS = "ChatGPT or Claude download (*.zip;*.json)"
# After the user opens a company's export page, how long she watches Downloads for it:
# the email can take a day to come.
EXPORT_WAIT_HOURS = 48
EXPORT_CHECK_SECONDS = 5
APP_ID = "LocalAIConcierge.Elaina"  # so Windows shows her own icon, not Python's
# Held while she runs, so starting her again finds her: two copies would both answer
# Ctrl tapped twice, and their Spots would fight over the keyboard and the clipboard.
ONE_COPY = r"Local\LocalAIConcierge.Elaina"  # Local\: this user's sign-in only
SPOT_WIDTH, SPOT_START_HEIGHT, SPOT_MIN_HEIGHT = 540, 160, 90
SPOT_GAP = 10  # between the highlighted text and the Spot
SPOT_SETTLE_SECONDS = 0.15  # for the program to have the keyboard again
PASTE_SETTLE_SECONDS = 0.5  # programs read the clipboard a moment after the keys
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
            if origin is not None and origin not in self._pages:
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

    def announce(self, name: str, *args, user: str | None = None) -> None:
        """Work no page started, such as a reservation coming due. Every page
        shows it as if another page had asked."""
        self.run(None, name, *args, user=user)

    def details(self, name: str) -> dict:
        """What an agent's page shows. It only reads, so it doesn't wait for a reply."""
        return self.ask("details", name, default={})

    def ask(self, name: str, *args, default=None):
        """The engine's calls outside the conversation, which don't wait for a reply."""
        call = getattr(self._engine, name, None)
        return call(*args) if call else default

    def menu(self, name: str, *args, default=None):
        """The model menu and the Models page."""
        call = getattr(getattr(self._engine, "menu", None), name, None)
        return call(*args) if call else default

    def book(self, name: str, *args, default=None):
        """Pins and searching, from the engine's saved conversations."""
        call = getattr(getattr(self._engine, "book", None), name, None)
        return call(*args) if call else default

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

    def undo_sorting(self, id: str = "") -> None:
        if self._overlay.watch:
            self._overlay.watch.undo(id or None)

    def set_noticing(self, on: bool) -> None:
        if self._overlay.watch:
            self._overlay.watch.set_noticing(bool(on))

    def activity(self) -> dict:
        return self._hub.ask("activity", default={})

    def privacy(self) -> dict:
        """What the What I see page shows: the switch, how her questions were
        answered, and when words left the computer (never what they were)."""
        watch = self._overlay.watch
        return {"noticing": watch.noticing if watch else None, "answers": watch.answers() if watch else {},
                "sent": sent_recently()}


class TodayBridge(WatchBridge):
    """The full window's page."""

    def agent_details(self, name: str) -> dict:
        return self._hub.details(name)

    # Home: the first two minutes and the Help me switches

    def welcome(self) -> dict:
        """What the first run and Help me need to know about this computer and the user's choices."""
        from ..quick.spot import home_language

        return {"welcomed": self._overlay.settings.get("welcomed", False), "home": home_language(),
                "spot": self._overlay.settings.get("spot", True), "role": self._overlay.settings.get("role", "")}

    def set_welcomed(self, role: str = "") -> None:
        self._overlay.remember(welcomed=True, role=role)

    def measure(self) -> dict:
        return self._hub.ask("measure", default={"error": "I can't measure this computer right now."})

    # Getting to know the user from their ChatGPT and Claude downloads (history.py).

    def bring_in_history(self) -> dict:
        """Windows' own picker for the download, then reading it. Nothing is read
        until the user picks a file themselves."""
        chosen = self._overlay.pick(exports=True)
        if not chosen:
            return {"cancelled": True}
        results = [self._hub.ask("bring_in_history", path, default={"error": "I can't read downloads here."})
                   for path in chosen]
        if problem := next((result for result in results if "error" in result), None):
            return problem
        return {"read": sum(result["read"] for result in results), "new": sum(result["new"] for result in results),
                "sources": sorted({source for result in results for source in result["sources"]}),
                "total": results[-1]["total"]}

    def understand_history(self) -> dict:
        return self._hub.ask("understand_history", default={"error": "I can't read chats here."})

    def what_i_know(self) -> dict:
        return self._hub.ask("what_i_know", default={})

    def keep_fact(self, fact_id: str, kept: bool) -> dict:
        return self._hub.ask("keep_fact", fact_id, bool(kept), default={})

    def forget_history(self) -> None:
        self._hub.ask("forget_history")

    def open_export_page(self, source: str) -> None:
        """Only a page from our own list, never an address a page hands us. From now
        on she watches Downloads for that download (Overlay.expect_exports)."""
        from ..history import EXPORT_PAGES

        if source in EXPORT_PAGES:
            webbrowser.open(EXPORT_PAGES[source])
            if self._overlay:
                self._overlay.expect_exports()

    def look_around(self) -> dict:
        return self._hub.ask("look_around", default={"error": "I can't look around this computer here."})

    def find_downloads(self) -> dict:
        found = self._hub.ask("bring_in_downloads", 0, default={})
        return found or {"error": "I didn't find a ChatGPT or Claude download in your Downloads yet. "
                                  "Click the links in their email first."}

    def set_spot(self, on: bool) -> None:
        self._overlay.set_spot(bool(on))

    def switch_agent(self, name: str, on: bool) -> None:
        self._hub.run(self, "switch_agent", name, bool(on), dots=False)

    def quit_app(self) -> None:
        self._overlay.quit()

    # The + button

    def send_files(self, text: str, paths: list[str], think: bool = False) -> None:
        names = ", ".join(Path(path).name for path in paths)
        said = "\n".join(filter(None, [text, f"Attached: {names}"]))
        self._hub.run(self, "send_files", text, list(paths), bool(think), user=said)

    def pick_files(self) -> list[str]:
        return self._overlay.pick()

    def pick_images(self) -> list[str]:
        return self._overlay.pick(images=True)

    def pick_folder(self) -> list[str]:
        return self._overlay.pick(folder=True)

    def screenshot(self) -> list[str]:
        return self._overlay.screenshot()

    # The model menu

    def models(self) -> dict:
        return self._hub.menu("info", default={})

    def pick_model(self, provider: str = "", model: str = "") -> dict:
        return self._hub.menu("pick", provider, model, default={})

    def save_key(self, provider: str, key: str) -> dict:
        return self._hub.menu("save_key", provider, key, default={})

    def forget_key(self, provider: str) -> dict:
        return self._hub.menu("forget_key", provider, default={})

    def more_models(self, provider: str) -> list[dict]:
        return self._hub.menu("more", provider, default=[])

    def open_key_page(self, provider: str) -> None:
        """Only a page from our own list, never an address a page hands us."""
        webbrowser.open(load_providers()[provider].keys)

    def hide_model(self, provider: str, model: str, hidden: bool) -> dict:
        return self._hub.menu("hide", provider, model, bool(hidden), default={})

    def add_custom_model(self, name: str, url: str, model: str, key: str = "") -> dict:
        return self._hub.menu("add_custom", name, url, model, key, default={})

    def remove_custom_model(self, id: str) -> dict:
        return self._hub.menu("remove_custom", id, default={})

    def delete_model(self, tag: str) -> dict:
        return self._hub.menu("delete_local", tag, default={})

    # Finding models

    def browse_models(self, words: str = "", sort: str = "downloads", kind: str = "") -> dict:
        return self._hub.menu("browse", words, sort, kind, default={})

    def get_model(self, text: str) -> dict:
        return self._hub.menu("download", text, default={})

    def cancel_download(self, tag: str) -> None:
        self._hub.menu("cancel", tag)

    def downloads(self) -> list[dict]:
        return self._hub.menu("downloads", default=[])

    # Finding and sharing agents

    def recipes(self) -> dict:
        return self._hub.ask("recipes", default={})

    def add_recipe(self, id: str) -> None:
        self._hub.run(self, "add_recipe", id, dots=False)

    def post_agent(self, name: str, about: str, category: str, by: str = "") -> dict:
        """Opens the page in the user's browser, where they press Submit themselves."""
        reply = self._hub.ask("post_agent", name, about, category, by, default={})
        address = reply.pop("address", None)
        if address:
            webbrowser.open(address)
        return reply

    # Sessions

    def pinned_chats(self) -> list[str]:
        return self._hub.book("pinned", default=[])

    def pin_chat(self, id: str, on: bool) -> list[str]:
        return self._hub.book("pin", id, bool(on), default=[])

    def search_chats(self, words: str) -> list[str]:
        return self._hub.book("search", words, default=[])

    # Reservations

    def reservations(self) -> list[dict]:
        return self._overlay.bookings.listing()

    def add_reservation(self, agent: str, action: str, text: str, when: str, repeat: str) -> dict:
        try:
            self._overlay.bookings.add(agent, action, text, when, repeat)
        except ReservationError as exc:
            return {"error": str(exc)}
        return {}

    def remove_reservation(self, id: str) -> None:
        self._overlay.bookings.remove(id)

    def switch_reservation(self, id: str, on: bool) -> None:
        self._overlay.bookings.set_active(id, bool(on))


class GlassBridge(WatchBridge):
    """The see-through window's page."""

    def open_app(self) -> None:
        self._overlay.open_app()

    def hide_glass(self) -> None:
        self._overlay.hide_glass()

    def fit_glass(self, height: int, talking: bool = False) -> None:
        self._overlay.fit_glass(height, talking)


class SpotBridge:
    """What the Spot's page can call. Not a chat page: it never gets the conversation."""

    def __init__(self, overlay: Overlay):
        self._overlay = overlay

    def run(self, action: str, text: str, ask: str = "") -> dict:
        return self._overlay.hub.ask("spot_run", action, text, ask, default={"error": "I can't do that here."})

    def put_back(self, how: str, text: str) -> None:
        self._overlay.put_back(how, text)

    def fit(self, height: int) -> None:
        self._overlay.fit_spot(height)

    def close(self) -> None:
        self._overlay.hide_spot()


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


def place_spot(height: int, anchor: tuple[int, int, int], work: Area) -> tuple[int, int]:
    """Just below the highlighted text, or above it when there's no room below,
    and always on the screen. anchor is (left, top, bottom) of the highlight."""
    x, top, bottom = anchor
    left, area_top, width, area_height = work
    y = bottom + SPOT_GAP
    if y + height > area_top + area_height:
        y = max(area_top, top - SPOT_GAP - height)
    return min(max(x, left), left + width - SPOT_WIDTH), y


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

    def __init__(self, engine: Engine, watch: TidyWatch | None = None, debug: bool = False,
                 bookings: Reservations | None = None):
        self.hub = ChatHub(engine)
        self.watch = watch
        self.debug = debug
        self.bookings = bookings or Reservations()
        # The user's choices about the windows themselves. Kept in memory in the practice run.
        self._settings_path = None if watch is None or watch.practice else data_dir() / "window.json"
        self.settings = self._read_settings()
        self._tray = self._mini = self._tap = None
        self._full = self._glass = self._spot = None
        self._spot_target: tuple[int, str] = (0, "")
        self._spot_anchor = (0, 0, 0)
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
        self._spot = webview.create_window(
            f"{TITLE} spot",
            str(WEB_DIR / "spot.html"),
            js_api=SpotBridge(self),
            width=SPOT_WIDTH,
            height=SPOT_START_HEIGHT,
            min_size=(SPOT_WIDTH, SPOT_MIN_HEIGHT),
            hidden=True,
            resizable=False,
            frameless=True,
            easy_drag=False,
            on_top=True,
            background_color="#0F0D12",
        )
        full_bridge._attach(self._full)
        glass_bridge._attach(self._glass)

        self._full.events.before_show += _blend_title(self._full)
        self._full.events.minimized += self.fold_up
        self._full.events.restored += self.unfold
        self._full.events.maximized += self.unfold  # it comes back maximized if it left that way
        self._full.events.closing += self._closing(self._full.minimize)
        self._glass.events.closing += self._closing(self.hide_glass)
        self._spot.events.closing += self._closing(self.hide_spot)

        try:
            webview.start(self._ready, debug=self.debug)
        finally:
            self.hub.close()
            self.bookings.stop()
            if self._tap:
                self._tap.stop()
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
        if self._spot.events.loaded.wait(GLASS_LOAD_SECONDS):
            from ..quick.spot import DoubleTap

            _prepare_spot(self._spot)
            self._tap = DoubleTap(self.open_spot)
            if self.settings.get("spot", True):
                self._tap.start()
        self._mini = Mini(self.toggle_glass)
        self._tray = Tray(self.open_app, self.quit, self.watch)
        self._tray.start()
        if self.watch:
            self.watch.changed = self._watch_changed
            # While the full window is open she has the user's attention anyway.
            self.watch.held = lambda: self._full_open
            self.watch.start()
        self.bookings.start(self._run_booking, self._bookings_changed)
        if self._settings_path:  # the practice run looks at no real downloads
            threading.Thread(target=self._watch_exports, name="exports", daemon=True).start()

    def expect_exports(self) -> None:
        """The user went to ask ChatGPT or Claude for their chats. For the next
        EXPORT_WAIT_HOURS, a download of them landing in Downloads is read at once,
        so all they do is click the links in the email."""
        now = time.time()
        if self.settings.get("expecting_until", 0) < now:
            self.remember(expecting_since=now)
        self.remember(expecting_until=now + EXPORT_WAIT_HOURS * 3600)

    def _watch_exports(self) -> None:
        while not self._quitting:
            time.sleep(EXPORT_CHECK_SECONDS)
            if self._quitting or time.time() > self.settings.get("expecting_until", 0):
                continue
            found = self.hub.ask("bring_in_downloads", self.settings.get("expecting_since", 0), default={})
            if not found:
                continue
            made = self.hub.ask("understand_history", default={})
            arrived = {**found, "error": made.get("error", "")}
            if self._full and not self._quitting:
                self._full.run_js(f"window.today && today.chatsArrived({json.dumps(arrived)})")

    def _run_booking(self, item: Reservation) -> None:
        if item.action == SORT:
            if self.watch:
                self.watch.sort_now()
        elif item.action == RUN:
            text = f"{item.agent}: {item.text}"
            self.hub.announce("send", text, False, user=text)
        else:
            self.hub.announce("set_agent", item.agent, item.action == TURN_ON)

    def _bookings_changed(self) -> None:
        if not self._quitting:
            self._full.run_js("window.today && today.refresh()")

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
        _bring_back(self._full)
        self.unfold()

    def unfold(self) -> None:
        """The full window is back, by the taskbar or from her: the circle steps aside."""
        with self._lock:
            if self._quitting:
                return
            self.hide_glass()
            if self._mini:
                self._mini.hide()
            self._full_open = True
            self._full.run_js("window.app && app.shown()")

    def fold_up(self) -> None:
        """The full window was minimized: it stays on the taskbar, and she folds into the circle."""
        with self._lock:
            if self._quitting:
                return
            self._full_open = False
            if self._mini:
                self._mini.show()

    def _read_settings(self) -> dict:
        try:
            return json.loads(self._settings_path.read_text(encoding="utf-8")) if self._settings_path else {}
        except (OSError, ValueError):
            return {}

    def remember(self, **choices) -> None:
        self.settings.update(choices)
        if self._settings_path:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(json.dumps(self.settings), encoding="utf-8")

    def set_spot(self, on: bool) -> None:
        """The Help me switch for the Spot: off means Ctrl tapped twice does nothing at all."""
        self.remember(spot=on)
        if self._tap:
            if on:
                self._tap.start()
            else:
                self._tap.stop()

    # ------------------------------------------------------------ the Spot

    def open_spot(self) -> None:
        """Ctrl tapped twice: read what's highlighted where the user is working,
        and open the Spot right there."""
        if sys.platform != "win32" or self._quitting or self._spot.native is None:
            return
        import ctypes
        from ctypes import wintypes

        from ..quick.selection import foreground_app, read_selection
        from ..quick.spot import MAX_SPOT_CHARS, caret_box, selection_editable

        user32 = ctypes.windll.user32
        target = user32.GetForegroundWindow()
        ours = {window.native.Handle.ToInt32() for window in (self._full, self._glass, self._spot) if window.native}
        if target in ours:
            return  # inside her own windows the chat is right there
        _, app = foreground_app()
        try:
            words, rect = read_selection(app)
        except Exception:
            words, rect = "", None  # a program that can't be read gets the Spot with nothing picked
        words = (words or "").strip()[:MAX_SPOT_CHARS]
        editable = selection_editable()
        caret = caret_box()
        if rect:
            anchor = (rect[0], rect[1], rect[3])
        elif caret:
            anchor = caret  # right where the user is typing
        else:
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            anchor = (point.x, point.y, point.y)
        scale = user32.GetDpiForSystem() / 96  # the pointer is in real pixels, the windows in logical ones
        self._spot_anchor = tuple(round(value / scale) for value in anchor)
        self._spot_target = (target, app)
        actions = self.hub.ask("spot_actions", words, editable, default=[])
        name = app.removesuffix(".exe").capitalize() if app else ""
        self._spot.run_js(f"spot.open({json.dumps({'text': words, 'editable': editable, 'actions': actions, 'app': name})})")
        self.fit_spot(SPOT_START_HEIGHT)
        self._spot.show()
        _take_focus(self._spot.native.Handle.ToInt32())
        self._full.run_js("window.today && today.spotTried()")  # the first two minutes wait for this

    def fit_spot(self, height: int) -> None:
        height = max(int(height), SPOT_MIN_HEIGHT)
        x, y = place_spot(height, self._spot_anchor, self._work)
        _set_bounds(self._spot, (x, y, SPOT_WIDTH, height))

    def hide_spot(self) -> None:
        if self._spot is not None and self._spot.native is not None:
            self._spot.hide()

    def put_back(self, how: str, text: str) -> None:
        """The answer goes into the program the user was in: in place of what was
        highlighted, on a new line under it, at the cursor, or only onto the clipboard.
        Their own clipboard is put back afterwards."""
        from pynput.keyboard import Controller, Key

        from ..quick.selection import restore_clipboard, save_clipboard, set_clipboard_text

        target, _ = self._spot_target
        self.hide_spot()
        if how == "copy":
            set_clipboard_text(text)
            return
        _take_focus(target)
        time.sleep(SPOT_SETTLE_SECONDS)
        saved = save_clipboard()
        set_clipboard_text(text)
        keys = Controller()
        if how == "below":
            keys.tap(Key.right)  # to the end of the highlighted text
            with keys.pressed(Key.shift):
                keys.tap(Key.enter)  # a new line that doesn't send a chat message
        with keys.pressed(Key.ctrl):
            keys.tap("v")
        time.sleep(PASTE_SETTLE_SECONDS)
        restore_clipboard(saved)

    def pick(self, folder: bool = False, images: bool = False, exports: bool = False) -> list[str]:
        """Windows' own file picker, for the + button and for chat downloads."""
        import webview

        kind = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
        types = (PICTURES,) if images else (EXPORTS,) if exports else ()
        chosen = self._full.create_file_dialog(kind, allow_multiple=not folder, file_types=types)
        return list(chosen or ())

    def screenshot(self) -> list[str]:
        """What's on the screen behind this window, which steps aside for a moment."""
        from PIL import ImageGrab

        with self._lock:
            self._full.hide()
            time.sleep(SCREEN_SETTLE_SECONDS)
            try:
                picture = ImageGrab.grab()
            finally:
                self._full.show()
        path = Path(tempfile.gettempdir()) / f"elaina-screen-{time.strftime('%H%M%S')}.png"
        picture.save(path)
        return [str(path)]

    def quit(self) -> None:
        with self._lock:
            if self._quitting:
                return
            self._quitting = True
        if self._tap:
            self._tap.stop()
        for window in (self._full, self._glass, self._spot):
            if window is not None:  # quitting while the app is still starting
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


def _prepare_spot(window) -> None:
    """Like the card from the circle: out of the taskbar and Alt+Tab, with round corners."""
    if sys.platform != "win32":
        return
    import ctypes

    gwl_exstyle, ws_ex_toolwindow, ws_ex_appwindow = -20, 0x80, 0x40000
    hwnd = window.native.Handle.ToInt32()
    style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
    ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle, (style | ws_ex_toolwindow) & ~ws_ex_appwindow)
    _rounded(window, (SPOT_WIDTH, SPOT_START_HEIGHT))


def _take_focus(hwnd: int) -> None:
    """Bring a window to the front with the keyboard. Windows only lets the program
    in front do that, so this borrows its input for a moment."""
    if sys.platform != "win32":
        return
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    front = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    here = kernel32.GetCurrentThreadId()
    joined = front != here and user32.AttachThreadInput(here, front, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if joined:
            user32.AttachThreadInput(here, front, False)


def _blend_title(window):
    """The title bar takes the page's black, its border goes the same way, and
    the name in it disappears, so the minimize, size and close buttons sit on the
    app itself. The frame stays Windows' own, or the window would lose snapping
    to half the screen. Windows 11 only; older versions ignore this."""

    def handler():
        if sys.platform != "win32":
            return
        import ctypes

        dark_mode, border, caption, words = 20, 34, 35, 36
        hwnd = window.native.Handle.ToInt32()
        for attribute, value in ((dark_mode, 1), (border, 0), (caption, 0), (words, 0)):
            setting = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
        _set_icons(hwnd)

    return handler


def _set_icons(hwnd: int) -> None:
    """Her own icon on the taskbar, and none in the title bar."""
    import ctypes
    from ctypes import wintypes

    from PIL import Image

    from .tray import tray_picture

    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    big, small = folder / "elaina.ico", folder / "blank.ico"
    tray_picture().save(big, sizes=[(64, 64), (48, 48), (32, 32)])
    Image.new("RGBA", (32, 32)).save(small)
    # Its own copy of user32, because these settings would change it for all the other code.
    user32 = ctypes.WinDLL("user32")
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT)
    user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    wm_seticon, image_icon, load_from_file = 0x80, 1, 0x10
    for which, picture in ((1, big), (0, small)):
        icon = user32.LoadImageW(None, str(picture), image_icon, 0, 0, load_from_file)
        user32.SendMessageW(hwnd, wm_seticon, which, icon)


def _bring_back(window) -> None:
    """As it was, maximized or not; pywebview's restore() always makes it a normal window."""
    if sys.platform != "win32":
        window.restore()
        return
    _to_front(window.native.Handle.ToInt32())


def _to_front(hwnd: int) -> None:
    import ctypes

    wm_syscommand, sc_restore = 0x0112, 0xF120
    if ctypes.windll.user32.IsIconic(hwnd):
        # Asked of the window itself, the way a taskbar click does it. ShowWindow from
        # the circle's or the tray's thread brought it back with its page left black.
        ctypes.windll.user32.PostMessageW(hwnd, wm_syscommand, sc_restore, 0)
    ctypes.windll.user32.SetForegroundWindow(hwnd)


_held_copy = None  # kept open until the app ends; Windows lets go of it even after a crash


def first_copy(name: str = ONE_COPY) -> bool:
    """False when Elaina is already running on this computer for this user."""
    global _held_copy
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    already_exists = 183
    if handle and ctypes.get_last_error() == already_exists:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _held_copy = handle
    return True


def bring_forward(title: str = TITLE, kind: str = "WindowsForms10.") -> bool:
    """Bring the running copy's full window to the front, as it was. Only a window of
    her own kind counts, so a folder that happens to be called Elaina is left alone."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    hwnd = None
    while hwnd := user32.FindWindowExW(None, hwnd, None, title):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), name, 256)
        if name.value.startswith(kind):
            _to_front(hwnd)
            return True
    return False


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

    if not first_copy():
        # Started again while she's running, from the Start menu, say: the one already
        # running comes forward instead. The practice run counts too: its Spot answers Ctrl.
        print("Elaina is already running, so her window was brought forward.")
        bring_forward()
        return 0
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    engine = FakeEngine() if args.fake else ElainaEngine()
    bookings = Reservations(None if args.fake else data_dir() / "reservations.json")
    Overlay(engine, TidyWatch(practice=args.fake), debug=args.debug, bookings=bookings).open()
    return 0
