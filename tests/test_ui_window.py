import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from concierge import folderwatch as fw
from concierge.agents import parts, store
from concierge.events import NoirText
from concierge.folderwatch import FolderWatch
from concierge.ui import window
from concierge.fake_engine import FakeEngine
from concierge.ui.window import (
    DRAWER_GAP,
    DRAWER_MIN_HEIGHT,
    DRAWER_WIDTH,
    EDGE_GAP,
    FULL_MIN_SIZE,
    UNEXPECTED_ERROR,
    WEB_DIR,
    ChatBridge,
    ChatHub,
    GlassBridge,
    TodayBridge,
    WatchBridge,
    centered,
    drawer_bounds,
    drawer_x,
    full_size,
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
    assert set(types(window)[1:-1]) == {"NoirText"}
    assert types(window)[-1] == "NoirDone"


def test_button_clicks_reach_the_engine():
    page, window = page_for(ChatHub(FakeEngine(delay=0)))
    page.send("make an agent")
    page.send("keep the manuals together")
    window.calls.clear()
    page.choose("looks_at", "Only the file's name")
    assert types(window)[-2:] == ["Result", "AgentCard"]  # the try-out, then the card
    card = window.events[-1]
    assert card["can_do"][0] == "Rule: keep the manuals together" and "never what's inside it" in card["reads"][0]


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
            yield NoirText("Hel")
            raise ConnectionError("Ollama went away")

    page, window = page_for(ChatHub(BrokenEngine(delay=0)))
    page.send("hello")
    assert types(window) == ["NoirText", "Error"]
    assert window.events[-1]["text"] == UNEXPECTED_ERROR


def test_closing_frees_noir_and_stops_drawing():
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
    chat_calls = {"startup", "send", "choose", "reset", "ask_again",
                  "new_chat", "open_chat", "delete_chat", "delete_agent", "toggle_agent"}
    hub = ChatHub(FakeEngine())
    assert public(ChatBridge(hub)) == chat_calls
    jobs = {"today", "chores", "answer", "undo_sorting", "set_noticing", "privacy", "activity", "set_web", "open_link", "set_search_key"}
    full_window = {"quit_app", "agent_details", "send_files", "pick_files", "pick_images", "pick_folder", "screenshot", "paste_text",
                   "follow_up", "after_answer", "pictures",
                   "models", "pick_model", "save_key", "forget_key", "more_models", "open_key_page",
                   "hide_model", "add_custom_model", "remove_custom_model", "delete_model",
                   "browse_models", "get_model", "cancel_download", "downloads",
                   "recipes", "add_recipe", "post_agent",
                   "welcome", "set_welcomed", "measure", "set_spot", "switch_agent", "setup_state", "setup_begin", "setup_finish",
                   "bring_in_history", "understand_history", "what_i_know", "keep_fact", "forget_history",
                   "open_export_page", "look_around", "find_downloads", "sign_in_account", "install_account", "check_accounts", "use_account", "usage",
                   "pinned_chats", "pin_chat", "search_chats",
                   "reservations", "add_reservation", "remove_reservation", "switch_reservation"}
    assert public(TodayBridge(hub, None)) == chat_calls | jobs | full_window
    assert public(GlassBridge(hub, None)) == chat_calls | jobs | {"open_app", "hide_drawer"}


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


def test_the_drawer_sits_flush_with_the_right_edge_with_a_gap_above_and_below():
    x, y, width, height = drawer_bounds(SCREEN)
    assert (x + width, y, width, height) == (1920, DRAWER_GAP, DRAWER_WIDTH, round(1032 * 0.62))
    assert drawer_bounds((0, 0, 2560, 1400))[3] == 680  # never a tower on a tall screen
    x, y, width, height = drawer_bounds(SCREEN, scale=1.5)
    assert (x + width, y, width) == (1920, 24, 570)


def test_an_agents_page_gets_what_the_agent_really_does():
    hub = ChatHub(FakeEngine(delay=0))
    translator = hub.details("Korean translator")
    assert translator["does"] == "Translate the text into Korean."
    assert dict(translator["facts"])["How long it stays"] == "Until you unhighlight the text"
    documents = hub.details("Contracts helper")
    assert dict(documents["facts"]) ["Knows"] == "3 files"
    # One that works on a folder's new files has a page of its own kind, never a translator's.
    files = dict(hub.details("Home papers")["facts"])
    assert files["When it works"] == "When a new file lands in Downloads" and files["Folders"] == "Manuals, Trips"
    assert hub.details("Nobody") == {}


def test_work_no_page_started_is_shown_on_every_page():
    hub = ChatHub(FakeEngine(delay=0))
    page, window = page_for(hub)
    page.startup()
    window.calls.clear()
    hub.announce("send", "Grammar Fixer: me and him goes", False, user="Grammar Fixer: me and him goes")
    assert window.mirrored()[0] == {"state": "start", "user": "Grammar Fixer: me and him goes", "dots": True}
    assert window.mirrored()[-1] == {"state": "end"}
    assert "NoirText" in types(window)


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


def test_the_drawer_follows_the_hand_out_of_the_edge_and_stops_when_it_is_out():
    bounds = drawer_bounds(SCREEN)
    assert drawer_x(0, bounds) == 1920  # still off the edge
    assert drawer_x(100, bounds) == 1820
    assert drawer_x(5000, bounds) == 1920 - DRAWER_WIDTH  # all the way out
    assert drawer_x(100, bounds, closing=True) == 1920 - DRAWER_WIDTH + 100  # pushed back in
    assert drawer_x(-30, bounds) == 1920  # a pull the wrong way does nothing


def test_the_drawer_keeps_a_least_height_but_never_outgrows_the_screen():
    assert drawer_bounds((0, 0, 1280, 300))[3] == DRAWER_MIN_HEIGHT  # 62% would be too little to read
    assert drawer_bounds((0, 0, 1280, 100))[3] == 100


def test_the_drawer_has_every_part_it_draws_into():
    assert {"card", "status", "list", "back", "thread", "ask", "text", "send", "summary", "open", "hide", "mark"} <= page_ids("glass.html")


def test_the_drawer_stays_on_a_screen_to_the_side():
    left_screen = (-1920, 0, 1920, 1032)
    x, _, width, _ = drawer_bounds(left_screen)
    assert x + width == 0


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows' own named lock")


@windows_only
def test_a_second_copy_finds_the_first_even_in_another_process():
    name = rf"Local\NoirTest.{uuid.uuid4().hex}"
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

    title = f"Noir test {uuid.uuid4().hex[:8]}"
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


# ------------------------------------ helpers that work while switched on, and the windows
# The windows know nothing about what a helper is for: the rule, folders and files below
# are made up, and the model is a pretend one that fills whichever form it is handed.


class Filer:
    """The built-in model as the folder watcher asks it: every file it can read is a
    manual that goes in Boat, or gets one line written about it."""

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        if "note" in schema["properties"]:
            return {"what": "a manual", "note": "How to start the engine."}
        return {"what": "a manual", "choice": "Boat"}

    def capabilities(self, tag):
        return ["completion"]

    def list_models(self):
        return ["noir:latest"]

    def refresh(self, model, keep_alive):
        pass

    def unload(self, model):
        pass


class Watching:
    """An engine as far as the windows' hooks go: what runs the helpers that work on a
    folder's new files, and the undo of their jobs."""

    def __init__(self, home):
        # An hour ahead, so every file written counts as having stood still; it never
        # looks by itself: the tests look by hand.
        self.folderwatch = FolderWatch(Filer(), "noir", home / "folderwatch.json", home / "folderwatch_done.json",
                                       clock=lambda: time.time() + 3600, look_seconds=3600)

    def undo_move(self, id):
        return self.folderwatch.undo(id)

    def close(self):
        self.folderwatch.stop()


def file_card(folder, then, name="Paper sorter"):
    slots = {"when": parts.NEW_FILE, "then": then, "instruction": "Manuals go in Boat.", "folder": str(folder),
             "looks_at": parts.INSIDE_FILE, "name": name}
    slots.update({"choices": "Boat", "open": parts.OPEN_NO, "into": ""} if then == parts.MOVE else {"notes": ""})
    return store.Agent(name, parts.CUSTOM, slots)


@pytest.fixture
def watching(tmp_path, monkeypatch):
    """A made-up home with a Downloads folder, and an engine that watches it for real."""
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    engine = Watching(tmp_path)
    yield engine, tmp_path / "Downloads"
    engine.close()


class Pages:
    """The full window and the drawer, as far as being told to redraw goes."""

    def __init__(self):
        self.told = []

    def run_js(self, script):
        self.told.append(script)


def overlay_for(engine, monkeypatch):
    """The windows around an engine, with nothing opened, and the note by the circle
    replaced by a list of what it would have shown, each time answered with Undo."""
    from concierge.quick import glow, note
    from concierge.quick.tidy import TidyWatch
    from concierge.ui.window import Overlay

    shown = []
    monkeypatch.setattr(glow, "full_screen_in_use", lambda: False)
    monkeypatch.setattr(note, "tell", lambda lines, yes, no, cancel, seconds: shown.append((lines, yes, no)) or "Undo")
    overlay = Overlay(engine, TidyWatch(practice=True))
    overlay._full = overlay._glass = Pages()
    return overlay, shown


def test_the_windows_hear_from_what_runs_the_helpers_that_work_on_files(watching):
    engine, downloads = watching
    hub = ChatHub(engine)
    changed, moved, working, stayed = [], [], [], []
    hub.on_chores(lambda: changed.append(True))
    hub.on_move(moved.append)
    hub.on_working(working.append)
    hub.on_stayed(stayed.append)
    engine.folderwatch.switch(file_card(downloads, parts.MOVE), True)
    (downloads / "engine.txt").write_text("How to start the engine", encoding="utf-8")
    (downloads / "setup.exe").write_bytes(b"MZ" * 64)
    engine.folderwatch.look()
    assert [move["name"] for move in moved] == ["engine.txt"] and [report["name"] for report in stayed] == ["setup.exe"]
    assert changed and working[0] is True and working[-1] is False  # the circle runs its line, then rests
    # An engine that runs no such helpers (the practice one) has nothing to hook, and nothing breaks.
    for quiet in (ChatHub(FakeEngine(delay=0)), ChatHub(object())):
        for hook in (quiet.on_chores, quiet.on_move, quiet.on_working, quiet.on_stayed):
            hook(print)


def test_the_note_by_the_circle_says_what_the_record_says(watching, monkeypatch):
    engine, downloads = watching
    overlay, shown = overlay_for(engine, monkeypatch)
    moved, stayed = [], []
    overlay.hub.on_move(moved.append)
    overlay.hub.on_stayed(stayed.append)
    mover = file_card(downloads, parts.MOVE)
    engine.folderwatch.switch(mover, True)
    (downloads / "engine.txt").write_text("How to start the engine", encoding="utf-8")
    engine.folderwatch.look()
    overlay._show_move(moved[0])
    lines, yes, no = shown[-1]
    record = engine.folderwatch.done_lately()[0]
    assert lines[0] == record["text"] == "Put engine.txt in Boat" and (yes, no) == ("Undo", "OK")
    assert lines[1:] == moved[0]["steps"][1:] and "Read it as: a manual" in lines  # what was read and decided, small
    # Undo on the note puts the file back through the engine, and the lists are told to redraw.
    assert (downloads / "engine.txt").is_file() and not (downloads / "Boat" / "engine.txt").exists()
    assert overlay._full.told == ["window.today && today.refresh()", "window.app && app.refresh()"]

    # A helper that writes about a file moves nothing: the note says what was written, in
    # the record's own words, and there is nothing to undo. (It once said "Put engine.txt in
    # Reading log.md" with an Undo that undid nothing.)
    engine.folderwatch.switch(mover, False)
    engine.folderwatch.switch(file_card(downloads, parts.NOTE, "Reading log"), True)
    (downloads / "pump.txt").write_text("How to prime the pump", encoding="utf-8")
    engine.folderwatch.look()
    overlay._show_move(moved[-1])
    lines, yes, no = shown[-1]
    assert lines[0] == engine.folderwatch.done_lately()[-1]["text"] == "Wrote about pump.txt in Reading log.md"
    assert (yes, no) == (None, "OK") and not any(line.startswith("Put ") for line in lines)

    # A file a helper looked at and left: where it stayed, and why, from the helper's own steps.
    engine.folderwatch.switch(mover, True)
    (downloads / "setup.exe").write_bytes(b"MZ" * 64)
    engine.folderwatch.look()
    overlay._show_stayed(next(report for report in stayed if report["name"] == "setup.exe"))
    lines, yes, no = shown[-1]
    assert lines[0] == "setup.exe stayed in Downloads" and lines[-1].endswith(fw.NO_TEXT) and yes is None


def test_the_pages_show_a_helper_at_work_where_they_show_the_watchs_work():
    class Engine:
        doing = "Paper sorter: reading engine.txt now"

        def chore_doing(self):
            return self.doing

    class Watch:
        working = None

        def today(self):
            return {"working": self.working, "noticed": {"id": "sort", "text": "Sort them?"}}

    class Overlay:
        watch = Watch()

    engine = Engine()
    bridge = WatchBridge(ChatHub(engine), Overlay())
    assert bridge.today()["working"] == "Paper sorter: reading engine.txt now"
    assert bridge.today()["noticed"]["id"] == "sort"  # what the watch noticed is passed on as it is
    Overlay.watch.working = "Sorting your Downloads folder"
    assert bridge.today()["working"] == "Sorting your Downloads folder"  # the watch's own job comes first
    Overlay.watch.working, engine.doing = None, ""
    assert not bridge.today()["working"]
    Overlay.watch = None
    assert bridge.today() == {}


def test_yes_and_no_outside_the_chat_only_ever_answer_the_watch():
    class Watch:
        answered = []

        def answer(self, which, yes):
            self.answered.append((which, yes))

    class Overlay:
        watch = Watch()

    class Engine:
        def __getattr__(self, name):  # nothing of the engine's is asked: no helper asks outside the chat
            raise AssertionError(name)

    WatchBridge(ChatHub(Engine()), Overlay()).answer("sort", 1)
    assert Overlay.watch.answered == [("sort", True)]


def test_the_chores_list_is_put_together_from_what_the_engine_gives():
    class Bookings:
        def listing(self):
            return []

    class Overlay:
        watch = None
        bookings = Bookings()

    engine = FakeEngine(delay=0)
    listing = WatchBridge(ChatHub(engine), Overlay()).chores()
    rows = {chore["name"]: chore for chore in listing["chores"]}
    assert set(rows) == {"Keep Downloads tidy", "Korean translator", "Home papers"}
    assert rows["Home papers"]["on"] is True and rows["Korean translator"]["on"] is False
    assert rows["Home papers"]["how"] == engine.chore_agents()[1]["how"]  # the engine's own sentence, as it is
    assert rows["Home papers"]["last"] == "Put ferry-booking.pdf in Trips · 30 min ago"
    assert rows["Korean translator"]["last"] == ""  # it keeps no record of its work
    jobs = [job["text"] for day in listing["days"] for job in day["jobs"]]
    assert jobs == ["Put ferry-booking.pdf in Trips", "Put dishwasher-manual.pdf in Manuals"]


def test_undo_goes_to_the_engine_first_and_to_the_watch_for_what_is_not_the_engines():
    class Watch:
        undone = []

        def undo(self, id):
            self.undone.append(id)

    class Overlay:
        watch = Watch()

    engine = FakeEngine(delay=0)
    bridge = WatchBridge(ChatHub(engine), Overlay())
    bridge.undo_sorting("practice-1")
    assert Overlay.watch.undone == [] and engine.chore_done()[-1]["text"] == "Put 1 file back"
    bridge.undo_sorting("a-sort-of-the-watchs")
    bridge.undo_sorting()
    assert Overlay.watch.undone == ["a-sort-of-the-watchs", None]


def test_every_call_the_windows_make_is_one_both_engines_have():
    """The windows ask the engine by name and take a usual answer when it has no such call,
    so a call that was renamed in the engine fails without a word: the lists and the circle
    once went on asking for names the engine no longer had, and showed nothing."""
    from concierge.engine import NoirEngine

    source = Path(window.__file__).read_text(encoding="utf-8")
    asked = set(re.findall(r'\.(?:ask|run|announce)\((?:self, )?"(\w+)"', source))
    assert {"send", "choose", "details", "chore_agents", "chore_done", "chore_doing", "undo_move", "set_agent"} <= asked
    for name in sorted(asked):
        assert callable(getattr(NoirEngine, name, None)), name
        assert callable(getattr(FakeEngine, name, None)), name
    # What runs the helpers that work on files is hooked by these names.
    hooks = set(re.findall(r'self\._hook\("(\w+)"', source))
    assert hooks == {"changed", "moved", "working", "stayed"}
    real = NoirEngine(Filer())
    for hook in hooks:
        assert callable(getattr(real.folderwatch, hook)), hook
    ChatHub(real).on_move(print)
    assert real.folderwatch.moved is print


def test_the_windows_side_loads_none_of_the_modules_the_helpers_no_longer_need():
    import ast

    from concierge import chores, fake_engine

    for module in (window, fake_engine, chores):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update([*(node.module or "").split("."), *(alias.name for alias in node.names)])
            elif isinstance(node, ast.Import):
                names.update(part for alias in node.names for part in alias.name.split("."))
        assert not names & {"organizer", "conductor", "talk"}, module.__name__
