import json

from concierge.events import ElainaText
from concierge.fake_engine import FakeEngine
from concierge.ui.window import UNEXPECTED_ERROR, ChatBridge


class FakeWindow:
    """Records the events the bridge pushes to the page instead of drawing them."""

    def __init__(self):
        self.events = []

    def run_js(self, script):
        assert script.startswith("app.onEvent(") and script.endswith(")")
        self.events.append(json.loads(script[len("app.onEvent("):-1]))


def bridge_for(engine):
    bridge = ChatBridge(engine)
    window = FakeWindow()
    bridge._attach(window)
    return bridge, window


def types(window):
    return [e["type"] for e in window.events]


def test_startup_pushes_system_info_then_agents():
    bridge, window = bridge_for(FakeEngine(delay=0))
    bridge.startup()
    assert types(window) == ["SystemInfo", "AgentList", "ChatList"]


def test_reply_streams_to_the_page_then_finishes():
    bridge, window = bridge_for(FakeEngine(delay=0))
    bridge.send("hello")
    assert types(window)[0] == "ChatList"  # the new conversation appears in the list first
    assert set(types(window)[1:-1]) == {"ElainaText"}
    assert types(window)[-1] == "ElainaDone"


def test_button_clicks_reach_the_engine():
    bridge, window = bridge_for(FakeEngine(delay=0))
    bridge.send("make an agent")
    bridge.send("Desktop/Work")
    window.events.clear()
    bridge.choose("file_types", "PDF only")
    assert types(window) == ["AgentCard"]
    assert "Desktop/Work" in window.events[0]["reads"][0]


def test_engine_crash_becomes_a_friendly_error():
    class BrokenEngine(FakeEngine):
        def send(self, text, think=False):
            yield ElainaText("Hel")
            raise ConnectionError("Ollama went away")

    bridge, window = bridge_for(BrokenEngine(delay=0))
    bridge.send("hello")
    assert types(window) == ["ElainaText", "Error"]
    assert window.events[-1]["text"] == UNEXPECTED_ERROR


def test_closing_frees_elaina_and_stops_drawing():
    closed = []

    class ClosingEngine(FakeEngine):
        def close(self):
            closed.append(True)

    bridge, window = bridge_for(ClosingEngine(delay=0))
    bridge._close()
    bridge.send("hello")
    assert closed == [True]
    assert window.events == []


def test_page_sees_only_the_engine_calls():
    # pywebview hands every public attribute of the bridge to the page.
    public = {name for name in dir(ChatBridge(FakeEngine())) if not name.startswith("_")}
    assert public == {"startup", "send", "choose", "reset",
                      "new_chat", "open_chat", "delete_chat", "delete_agent", "toggle_agent"}
