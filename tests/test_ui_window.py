import json

from concierge.events import ElainaText
from concierge.fake_engine import FakeEngine
from concierge.ui.window import (
    BUBBLE_SIZE,
    EDGE_GAP,
    UNEXPECTED_ERROR,
    BubbleBridge,
    ChatBridge,
    ChatHub,
    PanelBridge,
    panel_size,
    place_menu,
    place_panel,
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
    assert public(PanelBridge(hub, None)) == chat_calls | {"open_app", "hide_panel"}
    assert public(BubbleBridge(None)) == {"toggle_panel", "menu", "moved", "open_app", "quit"}


def test_panel_is_a_tall_quarter_of_the_screen():
    width, height = panel_size(SCREEN)
    assert width == 1920 // 4
    assert height > width


def test_panel_stays_on_small_screens():
    width, height = panel_size((0, 0, 1280, 680))
    assert width >= 340 and height <= 680


def test_panel_opens_beside_the_bubble_toward_the_middle():
    size = panel_size(SCREEN)
    right_bubble = (1920 - BUBBLE_SIZE - EDGE_GAP, 900)
    x, y = place_panel(right_bubble, size, SCREEN)
    assert x + size[0] <= right_bubble[0]  # to its left
    assert y + size[1] == right_bubble[1] + BUBBLE_SIZE  # bottoms lined up

    left_bubble = (EDGE_GAP, 900)
    x, _ = place_panel(left_bubble, size, SCREEN)
    assert x >= left_bubble[0] + BUBBLE_SIZE  # to its right


def test_panel_never_leaves_the_screen():
    size = panel_size(SCREEN)
    x, y = place_panel((1800, 10), size, SCREEN)  # bubble near the top
    assert y >= EDGE_GAP and x >= EDGE_GAP


def test_menu_grows_toward_the_middle():
    assert place_menu((1840, 600), SCREEN) == "left down"
    assert place_menu((20, 1000), SCREEN) == "right up"
