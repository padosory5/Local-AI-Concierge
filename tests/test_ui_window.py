import json
import re
import subprocess
import sys
import uuid

import pytest

from concierge.events import ElainaText
from concierge.ui import window
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
    jobs = {"today", "answer", "undo_sorting", "set_noticing", "privacy", "activity"}
    full_window = {"quit_app", "agent_details", "send_files", "pick_files", "pick_images", "pick_folder", "screenshot", "paste_text",
                   "follow_up", "after_answer", "pictures",
                   "models", "pick_model", "save_key", "forget_key", "more_models", "open_key_page",
                   "hide_model", "add_custom_model", "remove_custom_model", "delete_model",
                   "browse_models", "get_model", "cancel_download", "downloads",
                   "recipes", "add_recipe", "post_agent",
                   "welcome", "set_welcomed", "measure", "set_spot", "switch_agent",
                   "bring_in_history", "understand_history", "what_i_know", "keep_fact", "forget_history",
                   "open_export_page", "look_around", "find_downloads", "sign_in_account", "install_account", "check_accounts", "use_account",
                   "pinned_chats", "pin_chat", "search_chats",
                   "reservations", "add_reservation", "remove_reservation", "switch_reservation"}
    assert public(TodayBridge(hub, None)) == chat_calls | jobs | full_window
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


def test_work_no_page_started_is_shown_on_every_page():
    hub = ChatHub(FakeEngine(delay=0))
    page, window = page_for(hub)
    page.startup()
    window.calls.clear()
    hub.announce("send", "Grammar Fixer: me and him goes", False, user="Grammar Fixer: me and him goes")
    assert window.mirrored()[0] == {"state": "start", "user": "Grammar Fixer: me and him goes", "dots": True}
    assert window.mirrored()[-1] == {"state": "end"}
    assert "ElainaText" in types(window)


def test_pins_and_search_come_from_the_saved_chats():
    hub = ChatHub(FakeEngine(delay=0))
    list(hub._engine.send("marmalade on toast"))
    chat = hub._engine.book.current.id
    assert hub.book("search", "MARMALADE toast") == [chat]
    assert hub.book("search", "bicycle") == []
    assert hub.book("pin", chat, True) == [chat]
    assert hub.book("pinned") == [chat]


def test_a_deleted_chat_loses_its_pin():
    book = FakeEngine(delay=0).book
    list(book.record("hello", iter(())))
    chat = book.current.id
    book.pin(chat, True)
    book.delete(chat)
    assert book.pinned() == []


def test_pins_are_kept_with_the_saved_chats(tmp_path):
    from concierge.conversations import ChatBook

    ChatBook(tmp_path / "conversations").pin("abc", True)
    assert ChatBook(tmp_path / "conversations").pinned() == ["abc"]


def test_an_engine_without_details_just_gives_nothing():
    class Plain(FakeEngine):
        details = None

    assert ChatHub(Plain(delay=0)).details("Anything") == {}


def test_the_app_opens_big_on_any_screen():
    assert full_size(SCREEN) == (1728, 929)
    big = full_size((0, 0, 3840, 2100))
    assert big[0] > 3000
    # A small laptop still gets a window it can show, and it stays on screen.
    small = (0, 0, 700, 600)
    width, height = full_size(small)
    assert (width, height) == (FULL_MIN_SIZE[0], FULL_MIN_SIZE[1])
    assert width <= 700 and height <= 600


def test_the_window_can_shrink_to_half_of_a_small_screen():
    assert FULL_MIN_SIZE[0] <= 1280 / 2


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


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows' own named lock")


@windows_only
def test_a_second_copy_finds_the_first_even_in_another_process():
    name = rf"Local\ElainaTest.{uuid.uuid4().hex}"
    holder = subprocess.Popen(
        [sys.executable, "-c", f"from concierge.ui import window; print(window.first_copy({name!r}), flush=True); input()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "True"
        assert window.first_copy(name) is False
    finally:
        holder.communicate("\n", timeout=10)
    assert window.first_copy(name) is True  # the first one ended, so this one is first now


def test_starting_again_brings_the_running_one_forward_and_opens_nothing(monkeypatch):
    brought = []
    monkeypatch.setattr(window, "first_copy", lambda: False)
    monkeypatch.setattr(window, "bring_forward", lambda: brought.append(True))
    monkeypatch.setattr(window, "Overlay", lambda *args, **kwargs: pytest.fail("a second copy opened"))
    assert window.main(["--fake"]) == 0 and brought == [True]


@windows_only
def test_only_a_window_of_her_own_kind_is_brought_forward(monkeypatch):
    import tkinter

    title = f"Elaina test {uuid.uuid4().hex[:8]}"
    root = tkinter.Tk()
    root.withdraw()  # never on screen, and focus is never taken from the person running the tests
    root.title(title)
    root.update()
    fronted = []
    monkeypatch.setattr(window, "_to_front", fronted.append)
    try:
        assert window.bring_forward(title) is False  # a window by that name, but not hers
        assert window.bring_forward(title, kind="TkTopLevel") is True and len(fronted) == 1
    finally:
        root.destroy()


def test_the_export_page_opens_only_from_our_own_list(monkeypatch):
    opened = []
    monkeypatch.setattr(window.webbrowser, "open", opened.append)
    bridge = TodayBridge(ChatHub(FakeEngine(delay=0)), None)
    bridge.open_export_page("Claude")
    bridge.open_export_page("https://example.com/not-ours")
    assert opened == ["https://claude.ai/settings/data-privacy-controls"]


def test_two_downloads_picked_together_are_counted_together():
    class Picker:
        def pick(self, folder=False, images=False, exports=False):
            return ["chatgpt.zip", "claude.zip"] if exports else []

    class Reader(FakeEngine):
        def bring_in_history(self, path):
            source = "ChatGPT" if "chatgpt" in path else "Claude"
            return {"read": 30 if source == "ChatGPT" else 12, "new": 1, "sources": [source], "total": 42}

    bridge = TodayBridge(ChatHub(Reader(delay=0)), Picker())
    assert bridge.bring_in_history() == {"read": 42, "new": 2, "sources": ["ChatGPT", "Claude"], "total": 42}


def test_opening_an_export_page_starts_watching_downloads_for_it(monkeypatch):
    from concierge.quick.tidy import TidyWatch
    from concierge.ui.window import EXPORT_WAIT_HOURS, Overlay

    monkeypatch.setattr(window.webbrowser, "open", lambda url: None)
    overlay = Overlay(FakeEngine(delay=0), TidyWatch(practice=True))
    TodayBridge(overlay.hub, overlay).open_export_page("ChatGPT")
    until, since = overlay.settings["expecting_until"], overlay.settings["expecting_since"]
    assert until - since == pytest.approx(EXPORT_WAIT_HOURS * 3600, abs=5)
    overlay.expect_exports()  # asking again keeps the earliest start, so nothing in between is missed
    assert overlay.settings["expecting_since"] == since


def test_nothing_in_downloads_is_said_plainly():
    class Empty(FakeEngine):
        def bring_in_downloads(self, since=0):
            return {}

    assert "didn't find" in TodayBridge(ChatHub(Empty(delay=0)), None).find_downloads()["error"]


def test_a_long_paste_becomes_a_file_named_plainly():
    from concierge.ui.window import pasted_file

    words = "line\n" * 40
    first, second = pasted_file(words), pasted_file("other")
    assert first.name == second.name == "Pasted text.txt" and first != second
    assert first.read_text(encoding="utf-8") == words
