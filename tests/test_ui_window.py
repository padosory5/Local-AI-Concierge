import json
import re

from concierge.events import ElainaText
from concierge.fake_engine import FakeEngine
from concierge.ui.window import (
    EDGE_GAP,
    FULL_MIN_SIZE,
    GLASS_ABOVE,
    GLASS_CHAT_HEIGHT,
    GLASS_MIN_HEIGHT,
    GLASS_SIZE,
    UNEXPECTED_ERROR,
    WEB_DIR,
    ChatBridge,
    ChatHub,
    GlassBridge,
    TodayBridge,
    centered,
    full_size,
    glass_height,
    place_glass,
)

SCREEN = (0, 0, 1920, 1032)  # a 1080p screen without the taskbar


class FakeWindow:
    """Records what the hub asks the page to draw instead of drawing it."""

    def __init__(self):
        self.calls = []  # (function, data) for each app.<function>(data)

    def run_js(self, script):
        name, _, rest = script.partition("(")
        assert name.startswith("app.") and rest.endswith(")")
        self.calls.append((name[len("app."):], json.loads(rest[:-1])))

    @property
    def events(self):
        return [data for function, data in self.calls if function == "onEvent"]

    def mirrored(self):
        return [data for function, data in self.calls if function == "mirror"]


def page_for(hub):
    bridge = ChatBridge(hub)
    window = FakeWindow()
    bridge._attach(window)
    return bridge, window


def types(window):
    return [e["type"] for e in window.events]


def test_startup_pushes_system_info_then_agents():
    page, window = page_for(ChatHub(FakeEngine(delay=0)))
    page.startup()
    assert types(window) == ["SystemInfo", "AgentList", "ChatList"]


def test_reply_streams_to_the_page_then_finishes():
    page, window = page_for(ChatHub(FakeEngine(delay=0)))
    page.send("hello")
    assert types(window)[0] == "ChatList"  # the new conversation appears in the list first
    assert set(types(window)[1:-1]) == {"ElainaText"}
    assert types(window)[-1] == "ElainaDone"


def test_button_clicks_reach_the_engine():
    page, window = page_for(ChatHub(FakeEngine(delay=0)))
    page.send("make an agent")
    page.send("Desktop/Work")
    window.calls.clear()
    page.choose("file_types", "PDF only")
    assert types(window) == ["AgentCard"]
    assert "Desktop/Work" in window.events[0]["reads"][0]


def test_panel_and_full_app_show_the_same_conversation():
    starts = []

    class CountingEngine(FakeEngine):
        def startup(self):
            starts.append(True)
            yield from super().startup()

    hub = ChatHub(CountingEngine(delay=0))
    panel, panel_window = page_for(hub)
    full, full_window = page_for(hub)
    panel.startup()
    full.startup()
    assert starts == [True]  # the engine starts once, the second page catches up
    assert types(full_window) == types(panel_window)

    panel_window.calls.clear()
    full_window.calls.clear()
    panel.send("hello")
    # The full app shows the user's message, waits, gets the same reply, and is told it is done.
    assert full_window.mirrored() == [{"state": "start", "user": "hello", "dots": True}, {"state": "end"}]
    assert full_window.events == panel_window.events
    assert panel_window.mirrored() == []  # the page that asked draws its own message


def test_a_page_that_loads_later_gets_the_newest_lists():
    hub = ChatHub(FakeEngine(delay=0))
    panel, _ = page_for(hub)
    panel.startup()
    panel.send("hello")  # starts a conversation, so the chat list changes
    late, late_window = page_for(hub)
    late.startup()
    chat_list = next(e for e in late_window.events if e["type"] == "ChatList")
    assert chat_list["current"] is not None


def test_engine_crash_becomes_a_friendly_error():
    class BrokenEngine(FakeEngine):
        def send(self, text, think=False):
            yield ElainaText("Hel")
            raise ConnectionError("Ollama went away")

    page, window = page_for(ChatHub(BrokenEngine(delay=0)))
    page.send("hello")
    assert types(window) == ["ElainaText", "Error"]
    assert window.events[-1]["text"] == UNEXPECTED_ERROR


def test_closing_frees_elaina_and_stops_drawing():
    closed = []

    class ClosingEngine(FakeEngine):
        def close(self):
            closed.append(True)

    hub = ChatHub(ClosingEngine(delay=0))
    page, window = page_for(hub)
    hub.close()
    page.send("hello")
    assert closed == [True]
    assert window.calls == []


def public(obj):
    # pywebview hands every public attribute of a bridge to its page.
    return {name for name in dir(obj) if not name.startswith("_")}


def test_pages_see_only_their_calls():
    chat_calls = {"startup", "send", "choose", "reset",
                  "new_chat", "open_chat", "delete_chat", "delete_agent", "toggle_agent"}
    hub = ChatHub(FakeEngine())
    assert public(ChatBridge(hub)) == chat_calls
    jobs = {"today", "answer", "undo_sorting"}
    assert public(TodayBridge(hub, None)) == chat_calls | jobs | {"quit_app", "agent_details"}
    assert public(GlassBridge(hub, None)) == chat_calls | jobs | {"open_app", "hide_glass", "fit_glass"}


def page_ids(name):
    return set(re.findall(r'\bid="([\w-]+)"', (WEB_DIR / name).read_text(encoding="utf-8")))


def test_the_full_window_has_every_part_of_the_chat():
    # app.js draws into these; a missing one breaks the chat.
    assert {"messages", "empty", "input", "send", "new-chat", "composer", "think", "progress", "progress-text",
            "model-line", "chats"} <= page_ids("today.html")


def test_the_full_window_loads_only_local_files_that_exist_and_app_js_last():
    page = (WEB_DIR / "today.html").read_text(encoding="utf-8")
    files = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert files and all((WEB_DIR / file).is_file() for file in files)
    # today.js must be listening before app.js can draw the first event.
    assert [f for f in files if f.endswith(".js")][-1] == "app.js"


def test_the_see_through_window_loads_only_local_files_that_exist():
    page = (WEB_DIR / "glass.html").read_text(encoding="utf-8")
    files = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert files and all((WEB_DIR / file).is_file() for file in files)


def test_fonts_ship_with_the_app():
    # It must work with no internet, so nothing may come from a website.
    for page in ("today.css", "glass.css"):
        css = (WEB_DIR / page).read_text(encoding="utf-8")
        fonts = re.findall(r'url\("([^"]+)"\)', css)
        assert fonts and all((WEB_DIR / font).is_file() for font in fonts)
        assert "http" not in css


def test_see_through_window_sits_in_the_corner_above_the_circle():
    x, y = place_glass(GLASS_SIZE, SCREEN)
    assert x + GLASS_SIZE[0] == 1920 - EDGE_GAP
    assert y + GLASS_SIZE[1] == 1032 - GLASS_ABOVE


def test_an_agents_page_gets_what_the_agent_really_does():
    hub = ChatHub(FakeEngine(delay=0))
    translator = hub.details("Korean translator")
    assert translator["does"] == "Translate the text into Korean."
    assert dict(translator["facts"])["How long it stays"] == "Until you unhighlight the text"
    documents = hub.details("Contracts helper")
    assert dict(documents["facts"]) ["Knows"] == "3 files"


def test_an_engine_without_details_just_gives_nothing():
    class Plain(FakeEngine):
        details = None

    assert ChatHub(Plain(delay=0)).details("Anything") == {}


def test_the_app_opens_big_on_any_screen():
    assert full_size(SCREEN) == (1728, 929)
    big = full_size((0, 0, 3840, 2100))
    assert big[0] > 3000
    # A small laptop still gets a window it can show, and it stays on screen.
    small = (0, 0, 900, 600)
    width, height = full_size(small)
    assert (width, height) == (FULL_MIN_SIZE[0], FULL_MIN_SIZE[1])
    assert width <= 900 and height <= 600


def test_the_app_opens_in_the_middle_of_the_screen():
    size = full_size(SCREEN)
    x, y = centered(size, SCREEN)
    assert x == (1920 - size[0]) // 2 and y == (1032 - size[1]) // 2


def test_the_card_is_as_tall_as_the_page_asks_within_limits():
    assert glass_height(240, False, SCREEN) == 240
    assert glass_height(430, True, SCREEN) == 430
    assert glass_height(10, False, SCREEN) == GLASS_MIN_HEIGHT
    assert glass_height(9999, True, SCREEN) == GLASS_CHAT_HEIGHT


def test_the_card_always_fits_on_a_short_screen():
    short = (0, 0, 1280, 500)
    assert glass_height(9999, True, short) == 500 - GLASS_ABOVE - EDGE_GAP


def test_the_card_has_every_part_it_draws_into():
    assert {"card", "status", "thread", "ask", "text", "send", "summary", "open", "hide", "mark"} <= page_ids("glass.html")


def test_see_through_window_stays_on_a_screen_to_the_side():
    left_screen = (-1920, 0, 1920, 1032)
    x, _ = place_glass(GLASS_SIZE, left_screen)
    assert x + GLASS_SIZE[0] == -EDGE_GAP
