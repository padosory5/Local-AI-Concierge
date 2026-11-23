"""The folder runtime (concierge/folderwatch.py): the one machine that runs every card
that works on new files. What counts as new, noticing and settling, one file in hand at a
time, what the lists say, moving with undo, notes, reading files and pictures, what is
kept across a restart, and the dry run a card is tried with before it exists.

Most of this was learned the hard way by the file organizer it was made from (the live
runs of 8 to 13 Nov 2026), and is kept here for every card. The rule and the file names
below are made up: nothing in the runtime knows what a card is for."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

from concierge import chores, noir
from concierge import folderwatch as fw
from concierge.agents import parts, store
from concierge.agents.parts import INSIDE_FILE, MOVE, NAME_ONLY, NEW_FILE, NOTE, OPEN_NO, OPEN_YES
from concierge.agents.worker import FILE_IT, LEAVE, NOTHING, UNSURE, WRITE_IT
from concierge.folderwatch import FolderWatch
from concierge.ollama import Ollama, OllamaError

NAME = "Paper sorter"
RULE = "Anything about the boat goes in Boat, plant lists go in Garden. Leave bills where they are."
HELPER = "qwen3-vl:8b"  # a model that can see, installed beside Noir's own
MADE: list[FolderWatch] = []


class Model:
    """A pretend model: fills whichever form it is handed, by the form's own fields, and
    keeps what it was asked, with what, and what was loaded and unloaded. It follows the
    made-up rule above by the words in what it is given."""

    def __init__(self, sees=False, helper=True):
        self.sees, self.helper = sees, helper
        self.asked: list[tuple[str, str]] = []  # (the model, the file as it was given) for every form
        self.told: list[str] = []  # the note that came with each form
        self.schemas: list[dict] = []
        self.seen: list = []  # the pictures shown to a model that can see
        self.unloaded, self.warmed, self.options, self.kept_alive = [], [], [], []
        self.while_asked = lambda: None  # run in the middle of a form, to see what is shown meanwhile
        self.down = False  # Ollama can't be reached

    def list_models(self):
        return ["noir:latest", *([HELPER] if self.helper else [])]

    def capabilities(self, tag):
        return ["completion", "vision"] if "vl" in tag or self.sees else ["completion"]

    def refresh(self, model, keep_alive):
        self.warmed.append(model)

    def unload(self, model):
        self.unloaded.append(model)

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        given = messages[-1]["content"]
        self.asked.append((model, given))
        self.told.append(messages[0]["content"])
        self.schemas.append(schema)
        self.options.append(options)
        self.kept_alive.append(keep_alive)
        self.while_asked()
        if self.down:
            raise OllamaError("Ollama can't be reached.")
        fields = schema["properties"]
        if "words" in fields:  # the form for a picture
            self.seen.append(messages[-1].get("images"))
            return {"words": "Engine service log: 40 hours", "what": "a photo of a logbook"}
        low = given.lower()
        if "bill" in low:
            what, folder = "a bill", LEAVE
        elif "boat" in low or "engine" in low:
            what, folder = "a paper about the boat", "Boat"
        elif "plant" in low or "seed" in low:
            what, folder = "a plant list", "Garden"
        elif "trip" in low:
            what, folder = "a travel plan", "Trips"  # a folder no card below has to begin with
        else:
            what, folder = "can't tell", UNSURE
        if "write" in fields:  # writing about a file, the first form: does the rule ask for anything about it?
            return {"what": what, "write": NOTHING if folder == LEAVE else WRITE_IT}
        if "note" in fields:  # and the second: the note
            return {"what": what, "note": "" if folder == LEAVE else self.note_for(what)}
        if "folder" in fields:  # it may make folders: only a name is asked for
            named = folder not in (LEAVE, UNSURE)
            return {"what": what, "choice": FILE_IT if named else folder, "folder": folder if named else ""}
        return {"what": what, "choice": folder if folder in fields["choice"]["enum"] else UNSURE}

    def note_for(self, what: str) -> str:
        return f"This is {what}."


def card(folder: Path, then: str = MOVE, name: str = NAME, **more) -> store.Agent:
    """A made-up card that watches `folder`: one that moves files, or one that writes notes."""
    slots = {"when": NEW_FILE, "then": then, "instruction": RULE, "folder": str(folder), "looks_at": INSIDE_FILE,
             "name": name}
    slots.update({"choices": "Boat, Garden", "open": OPEN_NO, "into": ""} if then == MOVE else {"notes": ""})
    return store.Agent(name=name, blueprint=parts.CUSTOM, slots={**slots, **more})


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home with a Downloads folder; agents are saved inside it, never on this computer."""
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    yield tmp_path
    for one in MADE:
        one.stop()
    MADE.clear()


def watch(home: Path, model=None, now=None, **more) -> FolderWatch:
    """A folder watch with nothing switched on. It never looks by itself: the tests look by hand."""
    clock = (lambda: now[0]) if now else time.time
    one = FolderWatch(model or Model(), "noir", home / "folderwatch.json", home / "folderwatch_done.json", clock=clock,
                      look_seconds=3600, **more)
    MADE.append(one)
    return one


def make(home: Path, model=None, now=None, agent=None, **more) -> FolderWatch:
    """A folder watch with one card switched on, on the real clock unless `now` (a one-item
    list) is given to move it by hand. An hour ahead, every file written counts as settled."""
    one = watch(home, model, now, **more)
    one.switch(agent or card(home / "Downloads"), True)
    return one


def later() -> list[float]:
    return [time.time() + 3600]


def until(condition, seconds=5.0) -> bool:
    """Wait for something another thread does, however slow the machine: never a fixed sleep."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return bool(condition())


def land(home: Path, name="engine.txt", text="Service record for the boat engine") -> Path:
    path = home / "Downloads" / name
    path.write_text(text, encoding="utf-8")
    return path


def state_of(home: Path) -> dict:
    return json.loads((home / fw.STATE_NAME).read_text(encoding="utf-8"))


def everything_in(home: Path) -> dict:
    """Every file and folder under the made-up home, each file with what is in it and when it changed."""
    found = {}
    for path in sorted(home.rglob("*")):
        found[str(path.relative_to(home))] = (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
    return found


# ------------------------------------------------------------ what counts as new


def test_what_was_there_when_it_was_switched_on_is_left_alone(home):
    downloads = home / "Downloads"
    land(home, "old.txt", "boat papers from last year")
    one = make(home, now=later())
    land(home, "new.txt", "the boat's winter cover")
    one.look()
    assert (downloads / "old.txt").is_file()  # old: never judged
    assert (downloads / "Boat" / "new.txt").is_file()
    assert len(one.ollama.asked) == 1


def test_a_file_it_cannot_tell_stays_and_is_not_asked_about_again(home):
    one = make(home, now=later())
    path = land(home, "something.txt", "eggs, milk")
    one.look()
    one.look()
    assert path.is_file() and len(one.ollama.asked) == 1
    assert one.last_skipped()[0]["why"] == "not sure where it goes: can't tell"


def test_a_download_still_arriving_a_hidden_file_and_a_fresh_file_wait(home):
    one = make(home)  # the real clock
    land(home, "engine.txt.crdownload", "boat")  # a browser's name for a download that isn't whole
    land(home, ".engine.txt", "boat")
    fresh = land(home, "engine.txt", "boat engine")  # written just now
    one.look()
    assert fresh.is_file() and one.ollama.asked == []
    assert [path.name for path in one.files(one.active[NAME], settled=False)] == ["engine.txt"]
    assert one.count_files(one.active[NAME]) == 1 and one.files(one.active[NAME]) == []  # not settled yet


def test_a_card_with_no_folder_watches_nothing(home):
    one = watch(home)
    nowhere = card("")
    assert one.files(nowhere, settled=False) == []  # never the folder the app happens to run in
    assert one.rehearse(nowhere) == [] and one.count_files(nowhere) == 0
    path = land(home)
    assert one.place(nowhere, path, "Tools") is None and path.is_file() and not Path("Tools").exists()


def test_changing_the_watched_folder_starts_fresh_there(home):
    before, after = home / "Sorted", home / "Downloads"
    before.mkdir()
    land(home, "old-engine.txt", "boat engine, last term")
    one = make(home, now=later(), agent=card(before))  # watching the wrong folder, by mistake
    changed = card(after)
    one.refresh([changed])  # the saved agent changed under the same name
    one.switch(changed, True)
    one.look()
    assert (after / "old-engine.txt").is_file()  # old at the moment the folder changed: left alone
    land(home, "new-engine.txt", "boat engine, serviced")
    one.look()
    assert (after / "Boat" / "new-engine.txt").is_file()


def test_a_card_switched_on_again_with_another_folder_starts_fresh_there_too(home):
    (home / "Documents").mkdir()
    one = make(home, now=later(), agent=card(home / "Documents"))
    since = one.since[NAME]
    old = land(home, "old-engine.txt", "boat engine")
    one._clock = lambda: since + 50
    one.switch(card(home / "Downloads"), True)  # changed, and switched on without a refresh in between
    one.look()
    assert old.is_file() and one.ollama.asked == [] and one.since[NAME] == since + 50
    one.switch(card(home / "Downloads"), True)  # the same folder again: nothing starts over
    land(home, "new-engine.txt", "boat engine")
    one._clock = lambda: since + 5000
    one.look()
    assert (home / "Downloads" / "Boat" / "new-engine.txt").is_file() and one.since[NAME] == since + 50


def test_what_was_on_comes_back_when_the_app_starts_again_and_a_file_that_landed_since_is_still_new(home):
    make(home, now=later())  # switched on in a folder with nothing in it
    land(home)  # lands after that, and before the app starts again
    two = watch(home, now=later())
    two.refresh([card(home / "Downloads")])
    assert two.is_on(NAME)
    two.look()
    # A record with nothing in it is a record too. Taken for no record, this file became old
    # at the restart and was never handled, while the same file in a folder that had held
    # one old file was new.
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()
    two.refresh([])  # deleted since
    assert not two.is_on(NAME)


def test_a_card_with_no_record_of_what_it_had_seen_counts_what_is_there_as_old(home):
    arrived = land(home, "arrived-before.txt", "boat")
    (home / fw.STATE_NAME).write_text(json.dumps({"on": [NAME]}), encoding="utf-8")  # as an older version wrote it
    one = watch(home, now=later())
    one.refresh([card(home / "Downloads")])
    one.look()
    assert one.is_on(NAME) and arrived.is_file() and one.ollama.asked == []  # old at this start: left alone


def test_a_folder_with_more_files_than_are_remembered_keeps_them_all_old_after_a_restart(home, monkeypatch):
    """What a card had seen was cut by alphabet when it was written down, so the first files
    by name of a full folder were new again after a restart, and were moved."""
    monkeypatch.setattr(fw, "SEEN_KEPT", 5)
    for number in range(8):
        land(home, f"old{number:02}.txt", "boat papers from before")
    one = make(home, now=later())
    for number in range(4):
        land(home, f"z-new{number}.txt", "boat engine")  # judged and moved away: seen, and gone
    one.look()
    kept = state_of(home)["seen"][NAME]
    assert sorted(Path(path).name for path in kept) == [f"old{number:02}.txt" for number in range(8)]
    again = watch(home, now=later())
    again.refresh([card(home / "Downloads")])
    again.look()
    assert again.ollama.asked == [] and len(list((home / "Downloads").glob("old*.txt"))) == 8
    # With room left, the ones that are gone fill it; the ones still there always stay.
    here = {str(path) for path in one.files(one.active[NAME], settled=False)[:2]}
    assert len(one._seen_to_keep(NAME, here | {f"gone{number}" for number in range(9)})) == 5
    assert here <= set(one._seen_to_keep(NAME, here | {f"gone{number}" for number in range(9)}))


def test_what_was_seen_and_why_files_stayed_survive_a_restart(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    land(home, "phone-bill.txt", "Amount due")
    one.look()
    assert one.last_skipped()[0]["name"] == "phone-bill.txt"
    land(home, "engine9.txt", "boat engine")  # lands a moment before the restart
    again = watch(home, now=later())  # the app starts again
    again.refresh([card(downloads)])
    assert again.last_skipped()[0]["why"] == "the rule leaves it: a bill"  # the reason is still known
    again.look()
    assert (downloads / "Boat" / "engine9.txt").is_file()  # new, not old: what was seen before stayed seen
    assert (downloads / "phone-bill.txt").is_file() and len(again.last_skipped()) == 1  # not judged again


def test_a_refresh_while_files_are_in_hand_loses_no_reason(home):
    """Every refresh used to read the state file again, putting what was on disk in place of
    the reasons recorded since the last write: the file stayed seen, with nothing to say why."""
    one = make(home, now=later())
    land(home, "a-phone-bill.txt", "Amount due")
    land(home, "b-engine.txt", "boat engine")

    def an_agent_is_switched_somewhere_else():
        if "b-engine" in one.ollama.asked[-1][1]:
            one.refresh([one.active[NAME]])

    one.ollama.while_asked = an_agent_is_switched_somewhere_else
    one.look()
    assert [(item["name"], item["why"]) for item in one.last_skipped()] == [("a-phone-bill.txt", "the rule leaves it: a bill")]
    assert [item["name"] for item in state_of(home)["skipped"][NAME]] == ["a-phone-bill.txt"]
    assert (home / "Downloads" / "Boat" / "b-engine.txt").is_file() and one.made[NAME] == ["Boat"]


def test_only_cards_that_watch_a_folder_are_brought_back(home):
    make(home, now=later())
    text_card = store.Agent(name=NAME, blueprint=parts.CUSTOM, slots={"when": parts.IN_CHAT, "instruction": RULE})
    two = watch(home, now=later())
    two.refresh([text_card])  # the same name, but no longer a card that watches
    assert not two.is_on(NAME)


# ------------------------------------------------------------ seen at once


def test_a_file_is_noticed_at_once_and_read_when_it_has_stood_still(home):
    now = [time.time()]
    one = make(home, now=now)
    working, changed = [], []
    one.working, one.changed = working.append, lambda: changed.append(one.status(NAME))
    path = land(home)
    one.look()
    # Just landed: nothing is read yet, but it shows, the circle's line runs and the model warms up.
    assert path.is_file() and one.ollama.asked == []
    assert one.status(NAME) == "engine.txt just landed: reading it in a moment"
    assert one.doing() == f"{NAME}: engine.txt just landed: reading it in a moment"
    assert working == [True] and changed
    now[0] += fw.SETTLE_SECONDS + 0.5
    one.look()
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()
    assert working == [True, False] and one.status(NAME) == "" and one.doing() == ""
    assert until(lambda: one.ollama.warmed == ["noir"])  # loaded while the file settled, not after


def test_a_batch_of_files_asks_for_the_model_once(home):
    one = make(home, now=later())
    for number in range(8):
        land(home, f"engine{number}.txt", "Notes on the boat engine")
    one.look()
    assert until(lambda: bool(one.ollama.warmed))
    time.sleep(0.05)
    assert one.ollama.warmed == ["noir"]  # eight files landing together, one call to have it ready


def test_a_program_is_left_with_no_model_asked_or_loaded(home):
    one = make(home, now=later())
    stayed = []
    one.stayed = stayed.append
    (home / "Downloads" / "boat-setup.exe").write_bytes(bytes(range(256)) * 8)
    one.look()
    time.sleep(0.05)
    assert (home / "Downloads" / "boat-setup.exe").is_file() and one.last_skipped()[0]["why"] == fw.NO_TEXT
    assert stayed[0]["steps"][1] == "A program or a recording: nothing inside to read"
    # Judged by a name alone, a program was once taken for something it wasn't: no model is
    # asked, and none is loaded while it settles.
    assert one.ollama.asked == [] and one.ollama.warmed == []
    (home / "Downloads" / "boat.dat").write_bytes(bytes(range(256)) * 8)  # no kind it knows, and nothing readable inside
    one.look()
    assert (home / "Downloads" / "boat.dat").is_file() and one.ollama.asked == []
    assert {item["why"] for item in one.last_skipped()} == {fw.NO_TEXT}
    assert until(lambda: one.ollama.warmed == ["noir"])  # it might have been text: the model was made ready


def test_a_card_that_goes_by_names_has_the_model_ready_for_a_program_too(home):
    one = make(home, now=later(), agent=card(home / "Downloads", looks_at=NAME_ONLY))
    (home / "Downloads" / "boat-setup.exe").write_bytes(b"MZ" * 64)
    one.look()
    assert until(lambda: one.ollama.warmed == ["noir"]) and len(one.ollama.asked) == 1


def test_a_file_still_growing_waits_and_one_held_open_waits(home, monkeypatch):
    now = [time.time()]
    one = make(home, now=now)
    path = land(home, text="Service record")
    one.look()
    now[0] += 2
    with path.open("a", encoding="utf-8") as more:  # the download is still arriving
        more.write(" for the boat engine, part two")
    os.utime(path, (now[0], now[0]))  # written at the test's own time
    one.look()
    now[0] += 2  # four seconds since it was first seen, but only two since it last grew
    one.look()
    assert path.is_file() and one.ollama.asked == []
    now[0] += 2
    with monkeypatch.context() as held:
        held.setattr(fw, "_can_open", lambda path: False)  # a program is still writing it
        one.look()
        assert path.is_file()
    one.look()
    assert not path.is_file()


def test_a_big_download_is_said_to_be_still_arriving_and_the_circle_rests_meanwhile(home):
    now = [time.time()]
    one = make(home, now=now)
    working = []
    one.working = working.append
    path = land(home, "engine_manual.txt", "The boat engine")
    one.look()
    assert working == [True]
    for _ in range(12):  # it keeps growing, look after look, for longer than ARRIVING_SECONDS
        now[0] += 3
        with path.open("a", encoding="utf-8") as more:
            more.write(" and more of the manual")
        os.utime(path, (now[0], now[0]))
        one.look()
    assert path.is_file() and one.ollama.asked == []
    assert one.status(NAME) == "engine_manual.txt is still arriving: I'll read it once it's whole"
    assert one.doing() == "" and working == [True, False]  # waiting on a download is not work in hand
    now[0] += fw.SETTLE_SECONDS + 1  # whole at last
    one.look()
    assert (home / "Downloads" / "Boat" / "engine_manual.txt").is_file()
    assert working == [True, False, True, False] and one.status(NAME) == ""


def test_a_file_another_program_has_open_is_said_to_be_and_is_left_in_the_end(home, monkeypatch):
    now = [time.time()]
    one = make(home, now=now)
    working = []
    one.working = working.append
    path = land(home, "engine-log.txt", "The boat engine's log")
    with monkeypatch.context() as held:
        held.setattr(fw, "_can_open", lambda path: False)  # open in an editor that shares nothing
        one.look()
        now[0] += fw.ARRIVING_SECONDS + 1
        one.look()
        assert one.status(NAME) == "engine-log.txt is open in another program: I'll read it once it's free"
        assert one.doing() == "" and working == [True, False]
        now[0] += fw.GIVE_UP_SECONDS
        one.look()
        # Ten minutes on it is left, with why, and no longer sits in the lists as about to be read.
        assert path.is_file() and one.status(NAME) == ""
        assert one.last_skipped(1)[0] == {"name": "engine-log.txt", "where": str(home / "Downloads"),
                                          "why": fw.HELD_OPEN, "when": now[0]}
    one.look()
    assert path.is_file()  # left means left: only naming it in the chat looks at it again
    list(one.run_once(one.active[NAME], only=[path]))
    assert (home / "Downloads" / "Boat" / "engine-log.txt").is_file()


def test_a_file_that_never_stops_changing_is_left_in_the_end(home):
    now = [time.time()]
    one = make(home, now=now)
    path = land(home, "app.log", "started")
    one.look()
    for _ in range(fw.GIVE_UP_SECONDS // 2 + 2):  # a program writing a line every two seconds, for ever
        now[0] += 2
        with path.open("a", encoding="utf-8") as more:
            more.write("line")
        os.utime(path, (now[0], now[0]))
        one.look()
    assert path.is_file() and one.ollama.asked == [] and one.status(NAME) == ""
    assert one.last_skipped(1)[0]["why"] == fw.STILL_CHANGING


def test_a_file_moved_in_with_an_old_date_is_read_at_the_first_look(home):
    one = make(home, now=later())  # an hour on: every file's own time is old
    land(home)
    one.look()
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()


def test_the_lists_say_what_is_being_read_while_it_is(home):
    one = make(home, now=later())
    shown = []
    one.ollama.while_asked = lambda: shown.append((one.status(NAME), one.doing()))
    land(home)
    one.look()
    assert shown == [("Reading engine.txt now", f"{NAME}: reading engine.txt now")]
    assert one.status("Nobody") == ""


def test_a_card_that_goes_by_names_never_says_it_is_reading(home, monkeypatch):
    """Someone who chose names only because their files must not be read was told "Reading
    ... now" while it worked."""
    now = [time.time()]
    one = make(home, now=now, agent=card(home / "Downloads", looks_at=NAME_ONLY))
    shown = []
    one.ollama.while_asked = lambda: shown.append((one.status(NAME), one.doing()))

    def lands(name: str) -> None:
        os.utime(land(home, name, "private"), (now[0], now[0]))  # written at the test's own time

    lands("boat-cover.txt")
    one.look()
    assert one.status(NAME) == "boat-cover.txt just landed: looking at its name in a moment"
    now[0] += fw.SETTLE_SECONDS + 0.5
    one.look()
    assert shown == [("Looking at the name of boat-cover.txt now", f"{NAME}: looking at the name of boat-cover.txt now")]
    lands("boat-hook.txt")
    lands("boat-keys.txt")
    one.look()
    assert one.status(NAME) == "boat-hook.txt and 1 more just landed: looking at their names in a moment"
    steps = list(one.run_once(one.active[NAME]))
    assert steps[0] == "Looking at the name of boat-hook.txt (1 of 2)..."
    assert shown[-1][0] == "Looking at the name of boat-keys.txt now (2 of 2)"
    lands("boat-log.txt")
    monkeypatch.setattr(fw, "_can_open", lambda path: False)  # open in a program that shares nothing
    one.look()
    now[0] += fw.ARRIVING_SECONDS + 1
    one.look()
    assert one.status(NAME) == "boat-log.txt is open in another program: I'll get to it once it's free"
    assert not any("read" in line.lower() for line, _ in shown)


# ------------------------------------------------- one actor at a time


def test_an_agent_switched_off_in_the_middle_of_a_look_takes_no_more_files(home):
    one = make(home, now=later())
    land(home, "a.txt", "Notes on the boat")
    land(home, "b.txt", "Notes on the boat engine")
    made = one.active[NAME]
    one.ollama.while_asked = lambda: one.switch(made, False)  # the user switches it off while a.txt is read
    one.look()
    assert not (home / "Downloads" / "a.txt").is_file()  # the one in hand is finished
    assert (home / "Downloads" / "b.txt").is_file() and len(one.ollama.asked) == 1  # and not one more


def test_a_file_named_in_the_chat_is_not_also_taken_by_the_look_on_its_own(home):
    path = land(home)  # there before it was switched on, so already counted as old
    one = make(home, now=later())
    path.write_text("Notes on the boat engine", encoding="utf-8")
    passing = one.run_once(one.active[NAME], only=[path])
    assert next(passing) == "Reading engine.txt (1 of 1)..."
    one.look()  # the look on its own comes round in the middle of the pass
    assert path.is_file() and one.ollama.asked == []  # it used to take the file here, and the pass then failed
    outcome = list(passing)[-1]
    assert outcome["moved"] == 1 and outcome["left"] == 0 and len(one.ollama.asked) == 1


def test_a_file_the_look_dealt_with_first_is_not_called_a_failure(home):
    one = make(home, now=later())
    land(home)
    passing = one.run_once(one.active[NAME])
    next(passing)
    one.look()  # gets to it first
    outcome = list(passing)[-1]
    assert outcome == {"moved": 0, "where": [], "left": 0, "why": [], "id": "", "looked": 1, "already": 1}
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()


def test_a_pass_waits_for_the_file_the_look_has_in_hand(home):
    """The look on its own was reading a file when the user asked for a pass, and the pass,
    seeing nothing it hadn't seen, answered "nothing new has landed" about the very file being
    read that second. It waits for the file in hand, then lists."""
    reading, let_go = threading.Event(), threading.Event()
    one = make(home, now=later())
    one.ollama.while_asked = lambda: (reading.set(), let_go.wait(5))
    land(home)
    looking = threading.Thread(target=one.look, daemon=True)
    looking.start()
    assert reading.wait(5)
    passing = one.run_once(one.active[NAME])
    waited = []
    threading.Thread(target=lambda: (waited.append(next(passing, None)), None), daemon=True).start()
    time.sleep(0.3)
    assert waited == []  # the pass is waiting on the file in hand, not answering about it
    let_go.set()
    looking.join(5)
    assert until(lambda: bool(waited))
    # With the file finished, the pass has nothing to read: its first word is the outcome itself.
    assert waited and waited[0] == {"moved": 0, "where": [], "left": 0, "why": [], "id": "", "looked": 0,
                                    "already": 0}
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()
    assert one.last_moves(1)[0]["name"] == "engine.txt"  # the pass can say where it went


def test_a_pass_shows_which_file_of_how_many(home):
    land(home, "a.txt", "Notes on the boat")
    land(home, "b.txt", "Notes on the boat engine")
    one = make(home, now=later())
    shown, working = [], []
    one.working = working.append
    one.ollama.while_asked = lambda: shown.append(one.status(NAME))
    list(one.run_once(one.active[NAME], everything=True))
    assert shown == ["Reading a.txt now (1 of 2)", "Reading b.txt now (2 of 2)"]
    assert working == [True, False]


# ------------------------------------------------------------ moving, and undoing


def test_a_new_file_goes_where_the_rule_says_and_the_move_can_be_undone(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    land(home, "engine.txt", "Service record for the outboard engine.")
    land(home, "seeds.txt", "Plant list for the spring.")
    land(home, "phone-bill.txt", "Amount due: 40")
    one.look()
    assert (downloads / "Boat" / "engine.txt").is_file() and (downloads / "Garden" / "seeds.txt").is_file()
    assert (downloads / "phone-bill.txt").is_file()
    done = one.done_lately()
    assert [job["text"] for job in done] == ["Put engine.txt in Boat", "Put seeds.txt in Garden"]
    assert all(job["undo"] for job in done) and all(job["agent"] == NAME for job in done)
    last = one.last_moves()[0]
    assert (last["name"], last["to"]) == ("seeds.txt", str(downloads / "Garden"))
    assert one.undo(done[0]["sort"]) == 1
    assert (downloads / "engine.txt").is_file()
    assert one.done_lately()[0]["undo"] is False and one.done_lately()[-1]["text"] == "Put 1 file back"
    asked = len(one.ollama.asked)
    one.look()
    assert (downloads / "engine.txt").is_file() and len(one.ollama.asked) == asked  # put back means left alone
    assert one.undo("") == 0 and one.undo("no-such-job") == 0


@pytest.mark.parametrize("how", ["off and on", "renamed"])
def test_a_file_put_back_is_left_alone_after_its_card_was_switched_on_again(home, how):
    """Undo stuck only while the file was still on the card's list of files seen. A card
    switched on again (from off, or under its new name after a change in the chat) makes
    that list again from what is there, and the file put back was moved again at the next
    look, a couple of seconds after the user had put it back."""
    downloads = home / "Downloads"
    one = make(home, now=later())
    land(home, "engine.txt", "Service record for the outboard engine.")
    one.look()
    job = one.done_lately()[-1]
    name = NAME if how == "off and on" else "Boat papers"
    if how == "off and on":
        one.switch(one.active[NAME], False)
    else:
        one.forget(NAME)  # what the engine does when a change renamed the helper, before switching it on
    one.switch(card(downloads, name=name), True)
    assert one.undo(job["sort"]) == 1 and (downloads / "engine.txt").is_file()
    asked = len(one.ollama.asked)
    one.look()
    assert (downloads / "engine.txt").is_file() and len(one.ollama.asked) == asked
    assert [job["text"] for job in one.done_lately()] == ["Put engine.txt in Boat", "Put 1 file back"]
    assert str(downloads / "engine.txt") in state_of(home)["seen"][name]  # and after a restart


def test_a_file_of_the_same_name_that_landed_since_is_not_taken_for_one_put_back(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    land(home, "engine.txt", "Service record for the outboard engine.")
    one.look()
    job = one.done_lately()[-1]
    one.switch(one.active[NAME], False)
    one.switch(card(downloads), True)
    land(home, "engine.txt", "A newer record for the boat engine")  # where the first one was, since it was switched on
    assert one.undo(job["sort"]) == 0  # the first one keeps its place, so nothing went back
    one.look()
    assert (downloads / "Boat" / "engine (2).txt").read_text(encoding="utf-8") == "A newer record for the boat engine"


def test_an_undo_and_a_move_at_the_same_moment_both_stay_on_record(home, monkeypatch):
    """Undo is clicked on the window's thread while the look may be moving a file, and both
    write the one move log: a move written down in the middle of an Undo was written over,
    and could never be undone."""
    downloads = home / "Downloads"
    one = make(home, now=later())
    land(home, "engine.txt", "Service record for the outboard engine.")
    one.look()
    first = one.done_lately()[-1]["sort"]
    land(home, "seeds.txt", "Plant list for the spring.")
    rename, looks = Path.rename, []

    def putting_back(self, target):
        done = rename(self, target)
        if not looks and Path(target).name == "engine.txt":  # Undo has put engine.txt back, and writes the log next
            looks.append(threading.Thread(target=one.look))  # the look, on its own thread as in the app
            looks[0].start()
            looks[0].join(0.5)
        return done

    monkeypatch.setattr(Path, "rename", putting_back)
    assert one.undo(first) == 1
    looks[0].join(5)
    assert (downloads / "engine.txt").is_file() and (downloads / "Garden" / "seeds.txt").is_file()
    seeds = next(job for job in one.done_lately() if job["text"] == "Put seeds.txt in Garden")
    assert seeds["undo"] and one.undo(seeds["sort"]) == 1 and (downloads / "seeds.txt").is_file()


def _mark(path: Path, marks: int, on: bool = True) -> None:
    """Give a file marks Windows keeps on it, or take them off: OneDrive marks a file kept
    only in the cloud this way, and Windows a file it hides."""
    import ctypes

    kernel = ctypes.windll.kernel32
    now = kernel.GetFileAttributesW(str(path))
    assert kernel.SetFileAttributesW(str(path), (now | marks) if on else (now & ~marks))


OFFLINE, HIDDEN = 0x1000, 0x2  # one of the marks tidy.CLOUD_ONLY is made of, and FILE_ATTRIBUTE_HIDDEN


@pytest.mark.skipif(sys.platform != "win32", reason="the marks Windows keeps on a file")
def test_a_file_kept_only_in_the_cloud_is_left_alone_until_it_is_on_this_computer(home):
    """Desktop and Documents are often OneDrive's, and a file of theirs kept only in the
    cloud is a placeholder: reading it makes OneDrive download it, and moving it out of the
    OneDrive folder takes it out of the cloud copy, so the user's other devices lose it.
    The folder runtime listed, read and moved such files, which tidy has always left alone."""
    downloads = home / "Downloads"
    old = land(home, "boat-old.txt", "boat papers from last year")
    _mark(old, OFFLINE)
    one = make(home, now=later())  # it was there, in the cloud, when the card was switched on
    agent = one.active[NAME]
    new = land(home, "engine.txt", "Service record for the outboard engine.")
    _mark(new, OFFLINE)  # landed from another computer, and not brought down yet
    one.look()
    assert new.is_file() and one.ollama.asked == [] and one.files(agent, settled=False) == []
    assert one.rehearse(agent) == [] and list(one.run_once(agent, everything=True))[-1]["looked"] == 0
    assert one.ollama.asked == []
    _mark(new, OFFLINE, on=False)
    _mark(old, OFFLINE, on=False)  # both brought down to this computer, say by opening them
    one.look()
    assert (downloads / "Boat" / "engine.txt").is_file()  # landed after it was switched on: handled now
    assert old.is_file() and len(one.ollama.asked) == 1  # there before: old, as everything there then is


def test_files_windows_keeps_for_itself_are_never_listed_tried_or_moved(home):
    """A folder's desktop.ini gives it the name and icon it is shown with on a Windows in
    another language. It was listed like any file, put to the model in the try-out and the
    first pass, and a broad enough rule could move it out."""
    downloads = home / "Downloads"
    one = make(home, now=later(), agent=card(downloads, open=OPEN_YES))
    agent = one.active[NAME]
    (downloads / "desktop.ini").write_text("[.ShellClassInfo]\nLocalizedResourceName=Boat engine", encoding="utf-8")
    (downloads / "Thumbs.db").write_bytes(b"boat engine")
    hidden = []
    if sys.platform == "win32":
        hidden.append(land(home, "~$engine.docx", "boat engine"))  # an open document's lock file is hidden
        _mark(hidden[0], HIDDEN)
    assert one.files(agent, settled=False) == [] and one.rehearse(agent) == []
    one.look()
    list(one.run_once(agent, everything=True))
    assert one.ollama.asked == [] and (downloads / "desktop.ini").is_file() and (downloads / "Thumbs.db").is_file()
    assert all(path.is_file() for path in hidden)


def test_a_file_the_rule_puts_in_the_folder_it_is_in_stays_with_its_name(home):
    """A card that watches Desktop\\Inbox and keeps its folders on the Desktop may have
    Inbox among them. Put there, the file was only given a new name where it was, which
    made it a new file to the next look: after four looks it was letter (2) (2) (2) (2).txt,
    with the model asked and a job written down each time."""
    desktop = home / "Desktop"
    inbox = desktop / "Inbox"
    inbox.mkdir(parents=True)

    class Inbox(Model):
        def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
            super().chat_json(model, messages, schema, think, keep_alive, options)
            return {"what": "a letter", "choice": "Inbox"}

    one = make(home, Inbox(), now=later(), agent=card(inbox, choices="Inbox, Done", into=str(desktop)))
    letter = inbox / "letter.txt"
    letter.write_text("a letter", encoding="utf-8")
    for _ in range(3):
        one.look()
    assert [path.name for path in inbox.iterdir()] == ["letter.txt"] and len(one.ollama.asked) == 1
    assert one.done_lately() == [] and one.last_skipped()[0]["why"] == fw.ALREADY_THERE == "it is in that folder already"
    assert one.place(one.active[NAME], letter, "inbox") is None and letter.is_file()  # nor when the user says so
    assert list(inbox.iterdir()) == [letter] and one.done_lately() == []


def test_the_folders_named_are_the_only_places_a_file_can_go(home):
    one = make(home, now=later())
    path = land(home, "trip-to-oslo.txt", "The trip, day by day")  # the rule's folders are Boat and Garden
    land(home, "engine.txt", "boat engine")
    one.look()
    assert one.ollama.schemas[0]["properties"]["choice"]["enum"] == ["Boat", "Garden", LEAVE, UNSURE]
    assert RULE in one.ollama.told[0] and "- Boat\n- Garden\n" in one.ollama.told[0]
    assert path.is_file() and (home / "Downloads" / "Boat" / "engine.txt").is_file()
    assert one.last_skipped()[0]["why"] == "not sure where it goes: a travel plan"


def test_a_name_that_is_taken_gets_a_number_and_nothing_is_overwritten(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    (downloads / "Boat").mkdir()
    (downloads / "Boat" / "engine.txt").write_text("the one already there", encoding="utf-8")
    land(home, "engine.txt", "a newer boat engine record")
    one.look()
    assert (downloads / "Boat" / "engine.txt").read_text(encoding="utf-8") == "the one already there"
    assert (downloads / "Boat" / "engine (2).txt").read_text(encoding="utf-8") == "a newer boat engine record"


def test_the_folders_can_be_kept_somewhere_else(home):
    downloads, sorted_into = home / "Downloads", home / "Desktop" / "Sorted"
    one = make(home, now=later(), agent=card(downloads, into=str(sorted_into)))
    land(home)
    one.look()
    assert (sorted_into / "Boat" / "engine.txt").is_file()
    job = one.done_lately()[-1]
    assert job["text"] == f"Put engine.txt in {Path('Sorted') / 'Boat'}" and job["where"] == str(sorted_into / "Boat")
    assert one.last_moves()[0]["to"] == str(sorted_into / "Boat")
    assert one.made[NAME] == ["Boat"]


def test_a_card_that_goes_by_names_never_opens_the_file(home):
    opened = []
    one = make(home, now=later(), agent=card(home / "Downloads", looks_at=NAME_ONLY),
               read=lambda path: opened.append(path) or [(None, "words")])
    land(home, "boat-cover.txt", "nothing telling inside")
    (home / "Downloads" / "boat-video.mp4").write_bytes(bytes(range(256)))
    one.look()
    assert [given for _, given in one.ollama.asked] == ["File name: boat-cover.txt", "File name: boat-video.mp4"]
    assert opened == [] and one.ollama.seen == []
    assert (home / "Downloads" / "Boat" / "boat-cover.txt").is_file()
    assert (home / "Downloads" / "Boat" / "boat-video.mp4").is_file()  # a recording has a name like any file
    item = one.item(one.active[NAME], home / "Downloads" / "x.txt")
    assert (item.text, item.how, item.name_only) == ("", "its name only", True)


def test_it_may_make_a_folder_when_the_card_says_so_and_then_it_is_one_of_its_folders(home):
    downloads = home / "Downloads"
    agent = card(downloads, choices="Boat", open=OPEN_YES)
    store.save(agent)
    one = make(home, now=later(), agent=agent)
    told = []
    one.moved = told.append
    land(home, "trip-to-oslo.txt", "The trip, day by day")
    one.look()
    assert (downloads / "Trips" / "trip-to-oslo.txt").is_file()
    assert one.ollama.schemas[0]["properties"]["choice"]["enum"] == [FILE_IT, LEAVE, UNSURE]  # a name is asked for, no list
    assert "The rule puts it in Trips, a new folder" in told[0]["steps"]
    assert agent.slots["choices"] == "Boat, Trips"
    assert store.find_agent(NAME).slots["choices"] == "Boat, Trips"  # saved, so it is there after a restart
    land(home, "trip-home.txt", "The trip back")
    one.look()
    assert "spelled the same way:\n- Boat\n- Trips\n" in one.ollama.told[-1]
    assert (downloads / "Trips" / "trip-home.txt").is_file() and agent.slots["choices"] == "Boat, Trips"
    assert "The rule puts it in Trips" in told[1]["steps"]


def test_a_card_changed_while_its_file_is_in_hand_keeps_the_change(home):
    """A look works with the card it took before the file was read. A new folder used to be
    saved from that copy, which wrote the change the user had just made over with the old
    card, on disk and here."""
    downloads = home / "Downloads"
    agent = card(downloads, choices="Boat", open=OPEN_YES)
    store.save(agent)
    one = make(home, now=later(), agent=agent)

    def changed_in_the_chat():
        one.ollama.while_asked = lambda: None
        store.save(card(downloads, choices="Boat", open=OPEN_NO, instruction="Only papers about the boat go in Boat."))
        one.refresh(store.list_agents())

    one.ollama.while_asked = changed_in_the_chat
    land(home, "trip-to-oslo.txt", "The trip, day by day")
    one.look()
    assert (downloads / "Trips" / "trip-to-oslo.txt").is_file()  # decided by the card as it was when the file was read
    assert one.active[NAME] is not agent
    for now in (store.find_agent(NAME), one.active[NAME]):
        assert now.slots["instruction"] == "Only papers about the boat go in Boat." and now.slots["open"] == OPEN_NO
        assert now.slots["choices"] == "Boat, Trips"  # the folder that was made is one of its folders all the same


def test_a_card_deleted_while_its_file_is_in_hand_is_not_saved_again(home):
    downloads = home / "Downloads"
    agent = card(downloads, choices="Boat", open=OPEN_YES)
    store.save(agent)
    one = make(home, now=later(), agent=agent)
    one.ollama.while_asked = lambda: store.delete(agent)
    land(home, "trip-to-oslo.txt", "The trip, day by day")
    one.look()
    assert (downloads / "Trips" / "trip-to-oslo.txt").is_file() and store.list_agents() == []


def test_the_words_the_note_has_for_no_folders_never_become_a_folder(home):
    class Echo(Model):
        """Gives back, as the folder's name, what the note says where no folder is listed."""

        def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
            super().chat_json(model, messages, schema, think, keep_alive, options)
            return {"what": "a travel plan", "choice": FILE_IT, "folder": "(None yet)"}

    downloads = home / "Downloads"
    agent = card(downloads, choices="", open=OPEN_YES)
    one = make(home, Echo(), now=later(), agent=agent)
    path = land(home, "trip-to-oslo.txt", "The trip, day by day")
    one.look()
    assert "spelled the same way:\n(none yet)\n" in one.ollama.told[0]
    assert path.is_file() and [found.name for found in downloads.iterdir()] == ["trip-to-oslo.txt"]  # no folder was made
    assert one.last_skipped()[0]["why"] == "not sure where it goes: a travel plan" and agent.slots["choices"] == ""


def test_a_file_that_cannot_be_moved_is_left_with_that_on_record(home):
    downloads = home / "Downloads"
    (downloads / "Boat").write_text("a file where the folder would be", encoding="utf-8")
    one = make(home, now=later())
    stayed = []
    one.stayed = stayed.append
    path = land(home)
    one.look()
    assert path.is_file() and one.last_skipped()[0]["why"] == fw.NOT_MOVED
    assert stayed[0]["why"] == fw.NOT_MOVED and one.done_lately() == []
    assert list(one.run_once(one.active[NAME], only=[path]))[-1]["why"] == [{"why": fw.NOT_MOVED, "count": 1}]


def test_a_model_that_cannot_be_reached_moves_nothing_and_says_so(home):
    one = make(home, now=later())
    one.ollama.down = True
    path = land(home)
    one.look()
    assert path.is_file() and one.last_skipped()[0]["why"] == fw.NO_MODEL == "the built-in model couldn't be reached"


class Closed(Model):
    """Ollama as it is while it is closed: not even the list of its models answers. `closed`
    is that list; `down`, as before, is the forms."""

    closed = False

    def list_models(self):
        if self.closed:
            raise OllamaError("Ollama can't be reached.")
        return super().list_models()


def test_a_file_that_landed_while_the_model_could_not_be_reached_is_tried_again_once_it_can(home):
    """Written down as handled, a file that landed while Ollama was closed (from the tray,
    or still starting) stayed where it was for good: the look never took it again, and "go
    through them" said nothing new had landed. It is tried again once Ollama answers, at
    most once a minute, with nothing blinking or said again meanwhile."""
    downloads = home / "Downloads"
    now = later()
    one = make(home, Closed(), now=now)
    stayed = []
    one.stayed = stayed.append
    one.ollama.closed = one.ollama.down = True
    path = land(home)
    one.look()
    assert path.is_file() and one.last_skipped()[0]["why"] == fw.NO_MODEL and len(stayed) == 1
    assert str(path) not in state_of(home)["seen"][NAME]  # so after a restart it is new as well
    asked = len(one.ollama.asked)
    one.look()
    now[0] += fw.RETRY_SECONDS
    one.look()  # a minute on, and Ollama still closed: not tried
    assert len(one.ollama.asked) == asked and one.status(NAME) == ""
    one.ollama.closed = False  # Ollama answers, but the model can't be had yet
    now[0] += fw.RETRY_SECONDS
    one.look()
    assert len(one.ollama.asked) == asked + 1 and len(stayed) == 1  # tried, and not said a second time
    one.ollama.down = False
    one.look()  # not a minute since the last try
    assert path.is_file()
    now[0] += fw.RETRY_SECONDS
    one.look()
    assert (downloads / "Boat" / "engine.txt").is_file()
    assert one.last_skipped() == []  # the reason it had is no longer why it is anywhere


def test_a_pass_takes_again_at_once_a_file_the_model_could_not_be_reached_for(home):
    one = make(home, now=later())
    one.ollama.down = True
    land(home)
    one.look()
    one.ollama.down = False  # "go through them", once Ollama is back
    outcome = list(one.run_once(one.active[NAME]))[-1]
    assert (outcome["looked"], outcome["moved"]) == (1, 1) and (home / "Downloads" / "Boat" / "engine.txt").is_file()


def test_a_reply_that_is_no_form_is_not_said_to_be_the_model_out_of_reach(home, monkeypatch):
    """Ollama.chat_json raises an OllamaError for a reply that isn't valid JSON as well, and
    such a file was said to have stayed because the model couldn't be reached. It is not
    tried again either: the same file gives the same reply."""
    real = Ollama()
    monkeypatch.setattr(real, "_post", lambda path, body: {"message": {"content": '{"what": "a paper ab'}})

    class Garbled(Model):
        def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
            super().chat_json(model, messages, schema, think, keep_alive, options)
            return real.chat_json(model, messages, schema, think, keep_alive, options)

    now = later()
    one = make(home, Garbled(), now=now)
    path = land(home)
    one.look()
    assert path.is_file() and one.last_skipped()[0]["why"] == fw.NO_ANSWER == "the built-in model gave no answer it could use"
    now[0] += fw.RETRY_SECONDS
    one.look()
    assert len(one.ollama.asked) == 1 and list(one.run_once(one.active[NAME]))[-1]["looked"] == 0


def test_a_card_with_no_rule_moves_nothing(home):
    one = make(home, now=later(), agent=card(home / "Downloads", instruction="  "))
    path = land(home)
    one.look()
    assert path.is_file() and one.ollama.asked == [] and one.last_skipped()[0]["why"] == fw.NO_RULE


def test_a_file_that_stayed_keeps_the_reason(home):
    one = make(home, now=later())
    land(home, "phone-bill.txt", "Amount due: 40. For the boat's mooring.")
    land(home, "engine.txt", "boat engine")
    one.look()
    skipped = one.last_skipped()
    assert [item["name"] for item in skipped] == ["phone-bill.txt"]
    assert skipped[0]["why"] == "the rule leaves it: a bill" and skipped[0]["where"] == str(home / "Downloads")
    assert one.skipped[NAME] == skipped  # by card, for the chores list
    assert one.last_moves()[0]["name"] == "engine.txt"


def test_each_job_tells_its_steps_and_the_circle_is_told_when_it_works(home):
    one = make(home, now=later())
    told, stayed, working = [], [], []
    one.moved, one.stayed, one.working = told.append, stayed.append, working.append
    land(home, "engine.txt", "Service record for the boat engine")
    land(home, "phone-bill.txt", "Amount due")
    one.look()
    # It blinks for each file it notices, and its line runs until the last one is dealt with.
    assert working == [True, True, False]
    assert told[0]["steps"] == ["Noticed engine.txt in Downloads", "Read its first lines",
                                "Read it as: a paper about the boat", "The rule puts it in Boat", "Put it in Boat"]
    assert told[0]["text"] == "Put engine.txt in Boat"  # what the record says, for the small note
    assert stayed[0]["name"] == "phone-bill.txt" and stayed[0]["why"] == "the rule leaves it: a bill"
    assert stayed[0]["where"] == str(home / "Downloads")
    assert stayed[0]["steps"][1:] == ["Read its first lines", "Read it as: a bill",
                                      "Stayed in Downloads: the rule leaves it: a bill"]
    assert one.done_lately()[-1]["details"] == "from Downloads · The rule puts it in Boat"


def test_each_move_while_watching_is_told_with_undo(home):
    downloads = home / "Downloads"
    one = make(home, now=later(), agent=card(downloads, into=str(home / "Sorted")))
    told = []
    one.moved = told.append
    land(home, "engine.txt", "boat engine")
    land(home, "phone-bill.txt", "Amount due")
    one.look()
    assert len(told) == 1 and told[0]["name"] == "engine.txt" and told[0]["folder"] == str(Path("Sorted") / "Boat")
    assert told[0]["to"] == str(home / "Sorted" / "Boat") and one.undo(told[0]["sort"]) == 1
    assert (downloads / "engine.txt").is_file()
    # A pass asked for in the chat tells the chat instead, not the screen.
    land(home, "engine2.txt", "boat engine again")
    list(one.run_once(one.active[NAME]))
    assert len(told) == 1


def test_a_window_whose_callback_breaks_does_not_stop_the_watching(home):
    one = make(home, now=later())

    def broken(*args):
        raise RuntimeError("the window is gone")

    one.changed = one.moved = one.stayed = one.working = broken
    land(home)
    land(home, "phone-bill.txt", "Amount due")
    one.look()
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file() and len(one.last_skipped()) == 1


# ------------------------------------------------------------ a pass asked for in the chat


def test_a_pass_goes_through_what_is_new_or_everything(home):
    downloads = home / "Downloads"
    land(home, "old.txt", "boat papers from before")
    one = make(home, now=later())
    agent = one.active[NAME]
    for index in range(2):
        land(home, f"p{index}.txt", "boat")
    land(home, "list.txt", "eggs")
    steps = list(one.run_once(agent))
    assert steps[0] == "Reading list.txt (1 of 3)..."
    outcome = steps[-1]
    assert sorted(outcome) == ["already", "id", "left", "looked", "moved", "where", "why"]
    assert outcome["moved"] == 2 and outcome["left"] == 1 and outcome["looked"] == 3 and outcome["already"] == 0
    assert outcome["where"] == [{"folder": "Boat", "count": 2}]
    # Counted by the reason, without what each file was taken for.
    assert outcome["why"] == [{"why": fw.NOT_SURE_WHERE, "count": 1}]
    assert (downloads / "old.txt").is_file()
    job = one.done_lately()[-1]
    assert (job["text"], job["details"], job["sort"]) == ("Moved 2 files from Downloads", "Boat 2", outcome["id"])
    assert list(one.run_once(agent))[-1]["looked"] == 0  # nothing new now
    everything = list(one.run_once(agent, everything=True))[-1]
    assert everything["looked"] == 2 and not (downloads / "old.txt").exists()  # old.txt went too
    assert one.done_lately()[-1]["text"] == "Moved 1 file from Downloads"
    assert one.undo(outcome["id"]) == 2 and (downloads / "p0.txt").is_file()  # the whole pass goes back as one


def test_a_file_named_is_looked_at_again(home):
    one = make(home, now=later())
    path = land(home, "notes.txt", "eggs")
    one.look()
    assert len(one.last_skipped()) == 1
    path.write_text("eggs, and the boat's mooring fee", encoding="utf-8")
    one.look()
    assert path.is_file()  # judged once, and left: not looked at again by itself
    outcome = [step for step in one.run_once(one.active[NAME], only=[path]) if isinstance(step, dict)][0]
    assert outcome["looked"] == 1 and outcome["moved"] == 1 and one.last_skipped() == []


def test_a_file_looked_at_again_and_left_again_has_one_reason_on_record(home):
    one = make(home, now=later())
    path = land(home, "notes.txt", "eggs")
    (home / "Downloads" / "setup.exe").write_bytes(bytes(range(256)) * 8)
    one.look()
    assert len(one.last_skipped()) == 2
    outcome = [step for step in one.run_once(one.active[NAME], only=[path]) if isinstance(step, dict)][0]
    assert outcome["looked"] == 1 and outcome["moved"] == 0 and outcome["left"] == 1  # judged again, the same answer
    # Asked why it stayed, it is said once: the newest reason takes the place of the one before.
    assert sorted(item["name"] for item in one.last_skipped()) == ["notes.txt", "setup.exe"]
    list(one.run_once(one.active[NAME], everything=True))  # and so when the whole folder is gone through again
    assert sorted(item["name"] for item in one.last_skipped()) == ["notes.txt", "setup.exe"]


def test_one_odd_file_does_not_end_a_pass_and_what_moved_can_still_go_back(home):
    downloads = home / "Downloads"
    land(home, "a-engine.txt", "boat")
    land(home, "b-odd.txt", "odd")
    land(home, "c-engine.txt", "boat")
    now = later()
    one = make(home, now=now)

    def breaks_on_the_odd_one():
        if "odd" in one.ollama.asked[-1][1]:
            raise ValueError("a reply nobody could read")

    one.ollama.while_asked = breaks_on_the_odd_one
    outcome = list(one.run_once(one.active[NAME], everything=True))[-1]
    assert outcome["moved"] == 2 and outcome["left"] == 1
    assert outcome["why"] == [{"why": "something went wrong reading it (ValueError)", "count": 1}]
    assert one.undo(outcome["id"]) == 2 and (downloads / "a-engine.txt").is_file()
    # The same kind of file while watching: recorded with that reason, and the watching goes on.
    now[0] += 60
    land(home, "d-odd.txt", "odd")
    land(home, "e-engine.txt", "boat")
    one.look()
    assert one.last_skipped(1)[0]["name"] == "d-odd.txt" and (downloads / "Boat" / "e-engine.txt").is_file()


def test_a_pass_cut_short_still_writes_down_what_it_moved(home):
    """The files of a pass are moved without a record each and written down together at the
    end. A pass that never reached its end left moves nobody could undo."""
    land(home, "a-engine.txt", "boat")
    land(home, "b-engine.txt", "boat")
    one = make(home, now=later())
    passing = one.run_once(one.active[NAME], everything=True)
    next(passing)
    next(passing)  # a-engine.txt is moved, b-engine.txt is next
    passing.close()  # the chat was closed in the middle
    job = one.done_lately()[-1]
    assert job["text"] == "Moved 1 file from Downloads" and job["undo"] is True
    assert one.undo(job["sort"]) == 1 and (home / "Downloads" / "a-engine.txt").is_file()
    assert one.doing() == "" and one._passing == 0


# ------------------------------------------------------------ a move the user orders


def test_a_file_placed_by_hand_is_moved_and_kept_as_an_example(home):
    downloads = home / "Downloads"
    agent = card(downloads)
    store.save(agent)
    one = make(home, now=later(), agent=agent)
    told = []
    one.moved = told.append
    path = land(home, "winch-manual.txt", "eggs")
    one.look()
    assert len(one.last_skipped()) == 1
    move = one.place(agent, path, "Tools")
    assert move == {"from": str(path), "to": str(downloads / "Tools" / "winch-manual.txt")}
    assert (downloads / "Tools" / "winch-manual.txt").is_file()
    saved = store.find_agent(NAME).slots
    assert saved["choices"] == "Boat, Garden, Tools"
    assert saved["examples"] == [{"name": "winch-manual.txt", "choice": "Tools"}]
    assert one.last_skipped() == [] and told == []  # the chat says it, not a note on the screen
    job = one.done_lately()[-1]
    assert (job["text"], job["details"]) == ("Put winch-manual.txt in Tools", "from Downloads")
    # The built-in model is shown the example with the next file.
    land(home, "anchor-manual.txt", "eggs")
    one.look()
    assert "WHAT THE USER TOLD YOU BEFORE\n- winch-manual.txt: Tools\n" in one.ollama.told[-1]
    assert one.ollama.schemas[-1]["properties"]["choice"]["enum"] == ["Boat", "Garden", "Tools", LEAVE, UNSURE]
    assert one.undo(job["sort"]) == 1 and path.is_file()


def test_a_folder_named_another_way_is_the_folder_the_card_has(home):
    downloads = home / "Downloads"
    agent = card(downloads, choices="Boat, Garden plans")
    store.save(agent)
    one = make(home, now=later(), agent=agent)
    move = one.place(agent, land(home, "beds.txt", "x"), "plans for the garden")
    assert move["to"] == str(downloads / "Garden plans" / "beds.txt")
    assert agent.slots["choices"] == "Boat, Garden plans"  # no second folder for the same thing
    assert agent.slots["examples"] == [{"name": "beds.txt", "choice": "Garden plans"}]


def test_only_the_newest_examples_are_kept(home):
    agent = card(home / "Downloads")
    one = make(home, now=later(), agent=agent)
    for number in range(parts.MAX_EXAMPLES + 2):
        assert one.place(agent, land(home, f"file{number}.txt", "x"), "Boat")
    kept = agent.slots["examples"]
    assert len(kept) == parts.MAX_EXAMPLES == 8
    assert kept[0] == {"name": "file2.txt", "choice": "Boat"} and kept[-1]["name"] == f"file{parts.MAX_EXAMPLES + 1}.txt"


def test_nothing_is_placed_when_there_is_nothing_to_place(home):
    agent = card(home / "Downloads")
    one = make(home, now=later(), agent=agent)
    path = land(home)
    assert one.place(agent, home / "Downloads" / "missing.txt", "Tools") is None
    assert one.place(agent, path, " .. ") is None and one.place(agent, path, "") is None  # no folder's name
    writer = card(home / "Downloads", then=NOTE, name="Reading log")
    assert one.place(writer, path, "Tools") is None  # a card that writes notes moves nothing
    assert path.is_file() and "examples" not in agent.slots and agent.slots["choices"] == "Boat, Garden"
    move = one.place(agent, path, r"..\..\Elsewhere/Tools")
    # A folder's name, never a way out of where the card's folders are kept.
    assert Path(move["to"]).parent.parent == home / "Downloads" and not (home.parent / "Elsewhere").exists()


# ------------------------------------------------------------ writing notes


def test_a_card_that_writes_notes_goes_first_and_its_notes_file_is_never_a_file_to_handle(home):
    downloads = home / "Downloads"
    one = make(home, now=later())  # the card that moves is switched on first
    writer = card(downloads, then=NOTE, name="Reading log")
    one.switch(writer, True)
    told, stayed = [], []
    one.moved, one.stayed = told.append, stayed.append
    land(home)
    one.look()
    notes = (downloads / "Reading log.md").read_text(encoding="utf-8")
    assert notes.startswith("## engine.txt · 20") and notes.endswith("\nThis is a paper about the boat.\n\n")
    assert (downloads / "Boat" / "engine.txt").is_file()  # written about first, then moved
    assert [note["folder"] for note in told] == ["Reading log.md", "Boat"]
    assert told[0]["sort"] == "" and told[0]["to"] == str(downloads / "Reading log.md")
    assert told[0]["text"] == "Wrote about engine.txt in Reading log.md"  # not "Put engine.txt in ..."
    assert told[0]["steps"][-1] == "Wrote about it in Reading log.md"
    jobs = one.done_lately()
    assert [job["text"] for job in jobs] == ["Wrote about engine.txt in Reading log.md", "Put engine.txt in Boat"]
    assert jobs[0]["undo"] is False and jobs[0]["where"] == str(downloads / "Reading log.md")
    one.look()
    one.look()
    # (A note is two small forms, a move is one.) The notes file never lands.
    assert (downloads / "Reading log.md").is_file() and len(one.ollama.asked) == 3
    assert one.count_files(writer) == 0 and one.count_files(one.active[NAME]) == 0
    land(home, "seeds.txt", "Plant list")
    one.look()
    notes = (downloads / "Reading log.md").read_text(encoding="utf-8")
    assert notes.count("## ") == 2 and notes.index("## engine.txt") < notes.index("## seeds.txt")  # added at the end


def test_a_file_that_settles_while_notes_are_being_written_is_written_about_before_it_moves(home):
    """Going first in a look was not enough. Each card works out for itself which files have
    stood still, so a file that settled while the card that writes notes was busy with
    another one was moved before that card had seen it, and nothing was ever written."""
    downloads = home / "Downloads"
    now = [time.time()]
    one = make(home, now=now)  # the card that moves
    one.switch(card(downloads, then=NOTE, name="Reading log"), True)
    one.ollama.while_asked = lambda: now.__setitem__(0, now[0] + 2)  # every form takes the model two seconds
    os.utime(land(home, "a-engine.txt", "boat engine"), (now[0] - 100, now[0] - 100))  # stood still long ago
    os.utime(land(home, "b-engine.txt", "boat engine, part two"), (now[0] - 1.5, now[0] - 1.5))  # not yet
    one.look()
    assert (downloads / "Boat" / "b-engine.txt").is_file()  # it had settled by the time the card that moves looked
    notes = (downloads / "Reading log.md").read_text(encoding="utf-8")
    assert notes.index("## a-engine.txt") < notes.index("## b-engine.txt") and notes.count("## ") == 2
    asked = len(one.ollama.asked)
    one.look()
    assert len(one.ollama.asked) == asked == 6 and one.last_skipped() == []  # nothing is left over for either card


def test_a_file_a_pass_or_the_user_takes_is_written_about_before_it_leaves(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    one.switch(card(downloads, then=NOTE, name="Reading log"), True)
    told = []
    one.moved = told.append
    land(home)
    outcome = list(one.run_once(one.active[NAME]))[-1]  # asked for in the chat before the look came round
    assert outcome["moved"] == 1 and (downloads / "Boat" / "engine.txt").is_file()
    notes = downloads / "Reading log.md"
    assert notes.read_text(encoding="utf-8").startswith("## engine.txt · 20")
    assert [note["text"] for note in told] == ["Wrote about engine.txt in Reading log.md"]  # the move is the chat's to tell
    placed = land(home, "winch-manual.txt", "how the winch is taken apart")
    assert one.place(one.active[NAME], placed, "Tools")  # "put it in Tools", a moment after it landed
    assert "## winch-manual.txt" in notes.read_text(encoding="utf-8") and (downloads / "Tools" / "winch-manual.txt").is_file()
    one.look()
    assert len(one.ollama.asked) == 5  # two notes, of two forms each, and one move: nothing is left for the look
    # A file the card that writes notes has had already is not written about again.
    stays = land(home, "list.txt", "eggs, milk")
    one.look()
    list(one.run_once(one.active[NAME], only=[stays]))
    assert notes.read_text(encoding="utf-8").count("## ") == 3


def test_nothing_is_written_when_the_rule_asks_for_nothing(home):
    downloads = home / "Downloads"
    writer = card(downloads, then=NOTE, name="Reading log")
    one = make(home, now=later(), agent=writer)
    stayed = []
    one.stayed = stayed.append
    path = land(home, "phone-bill.txt", "Amount due")
    one.look()
    assert path.is_file() and not (downloads / "Reading log.md").exists()
    assert one.last_skipped()[0]["why"] == "the rule asks for nothing about it: a bill"
    assert one.done_lately() == [] and stayed == []  # it never moves a file: "it stayed" is no news of its


def test_a_notes_file_that_cannot_be_written_is_said_so(home):
    kept_in = home / "Notes"
    (kept_in / "Reading log.md").mkdir(parents=True)  # a folder where the notes file would be
    writer = card(home / "Downloads", then=NOTE, name="Reading log", notes=str(kept_in))
    one = make(home, now=later(), agent=writer)
    path = land(home)
    one.look()
    assert path.is_file() and one.last_skipped()[0]["why"] == fw.NOTES_NOT_WRITTEN and one.done_lately() == []


def test_a_pass_of_a_card_that_writes_notes(home):
    downloads = home / "Downloads"
    land(home, "engine.txt", "boat engine")
    land(home, "seeds.txt", "Plant list")
    land(home, "phone-bill.txt", "Amount due")
    writer = card(downloads, then=NOTE, name="Reading log", notes=str(home / "Desktop" / "What arrived"))
    one = make(home, now=later(), agent=writer)
    outcome = list(one.run_once(writer, everything=True))[-1]
    assert outcome["moved"] == 2 and outcome["left"] == 1 and outcome["id"] == ""  # nothing to undo
    assert outcome["why"] == [{"why": fw.NOTHING_ASKED, "count": 1}]
    notes = home / "Desktop" / "What arrived.md"  # named without an ending: still a file
    assert notes.read_text(encoding="utf-8").count("## ") == 2
    job = one.done_lately()[-1]
    assert (job["text"], job["details"], job["sort"]) == ("Wrote about 2 files from Downloads", "in What arrived.md", "")
    assert sorted(path.name for path in downloads.iterdir()) == ["engine.txt", "phone-bill.txt", "seeds.txt"]


def test_a_notes_file_is_not_taken_for_a_new_file_once_its_card_is_switched_off(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    writer = card(downloads, then=NOTE, name="Reading log")
    one.switch(writer, True)
    land(home)
    one.look()
    asked = len(one.ollama.asked)
    one.switch(writer, False)  # from now on nothing leaves its notes file out of the listing
    one.look()
    assert (downloads / "Reading log.md").is_file() and len(one.ollama.asked) == asked
    again = watch(home, now=later())  # and after a restart
    again.refresh([card(downloads)])
    again.look()
    assert (downloads / "Reading log.md").is_file() and again.ollama.asked == []
    # Deleted rather than switched off, the same.
    other = card(downloads, then=NOTE, name="Second log")
    one.switch(other, True)
    land(home, "seeds.txt", "Plant list")
    one.look()
    one.forget("Second log")
    one.look()
    assert (downloads / "Second log.md").is_file()


@pytest.mark.parametrize("change", ["its notes are kept somewhere else now", "the same, switched on with no refresh",
                                    "it was given another name", "it moves files now", "it is gone"])
def test_a_notes_file_left_behind_by_a_change_is_not_taken_for_a_new_file(home, change):
    """A notes file is left out of every listing only while its card is on and writes there.
    After a card's notes were moved to another place, its old notes file landed as a new
    file: it was written about in the new one, and then moved away by the card that moves."""
    downloads = home / "Downloads"
    one = make(home, now=later())
    mover = one.active[NAME]
    one.switch(card(downloads, then=NOTE, name="Reading log"), True)
    land(home)
    one.look()
    left_behind = downloads / "Reading log.md"
    written, asked = left_behind.read_text(encoding="utf-8"), len(one.ollama.asked)
    elsewhere = home / "Desktop" / "Log.md"
    changed = {"it was given another name": card(downloads, then=NOTE, name="Boat diary"),
               "it moves files now": card(downloads, name="Reading log"),
               "it is gone": None}.get(change, card(downloads, then=NOTE, name="Reading log", notes=str(elsewhere)))
    if "no refresh" not in change:
        one.refresh([mover, *([changed] if changed else [])])  # what a saved change does: the agents as they are now
    if changed:
        one.switch(changed, True)
    one.look()
    one.look()
    assert len(one.ollama.asked) == asked  # nobody took the old notes file for a file that had landed
    assert left_behind.read_text(encoding="utf-8") == written and not elsewhere.exists()
    assert str(left_behind) in state_of(home)["seen"][NAME]  # nor will anybody after a restart
    land(home, "seeds.txt", "Plant list")
    one.look()
    assert (downloads / "Garden" / "seeds.txt").is_file() and left_behind.read_text(encoding="utf-8") == written


# ------------------------------------------------------------ reading a file


def test_every_kind_of_file_is_read_as_far_as_it_can_be(home):
    import zipfile

    downloads = home / "Downloads"
    one = make(home, now=later())
    told = []
    one.moved = told.append
    (downloads / "a-practice.ipynb").write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# Fuel use of the boat\n"]},
        {"cell_type": "code", "source": ["import pandas as pd\n"]}]}), encoding="utf-8")
    with zipfile.ZipFile(downloads / "b-beds.xlsx", "w") as inside:
        inside.writestr("xl/sharedStrings.xml", "<sst><si><t>Seed order for the spring</t></si></sst>")
        inside.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    with zipfile.ZipFile(downloads / "c-packed.zip", "w") as inside:
        inside.writestr("engine/manual.txt", "x")
    land(home, "d-script.py", "# boat log reader\nprint('hours')\n")
    one.look()
    given = [given for _, given in one.ollama.asked]
    assert "Fuel use of the boat" in given[0] and "import pandas" in given[0]  # the notebook's cells
    assert "Seed order for the spring" in given[1]  # the spreadsheet's words
    assert "Files inside: engine/manual.txt" in given[2]  # a zip by the names inside it
    assert [note["steps"][1] for note in told] == ["Read its first lines", "Read its first lines",
                                                   "Read the names of the files inside", "Read its first lines"]
    assert sorted(path.name for path in (downloads / "Boat").iterdir()) == ["a-practice.ipynb", "c-packed.zip", "d-script.py"]
    assert (downloads / "Garden" / "b-beds.xlsx").is_file()


def test_only_the_beginning_of_a_file_is_read(home):
    one = make(home, now=later())
    land(home, "long.txt", "boat " * 5000)
    one.look()
    given = one.ollama.asked[0][1]
    assert fw.READ_CHARS == 3000 and len(given) <= len("File name: long.txt\n\nWhat is inside (the beginning):\n") + fw.READ_CHARS


def test_a_big_file_is_not_read_to_its_end_to_keep_its_beginning(home, monkeypatch):
    """A 301 MB export was read whole and run through a regex to keep 3,000 characters of
    it: seven seconds and 1.6 GB of memory, with every other file waiting behind it."""
    read_whole = []
    monkeypatch.setattr(fw, "read_pages", lambda path: read_whole.append(path.name) or [(None, path.read_text(encoding="utf-8"))])
    monkeypatch.setattr(fw, "WHOLE_BYTES", 2000)
    one = make(home, now=later())
    big = land(home, "export.csv", "boat engine hours, " * 5000)
    land(home, "export.html", "<p>plant</p> <b>list</b> " * 5000)
    land(home, "short.csv", "plant list, seeds")
    one.look()
    assert read_whole == ["short.csv"]  # a small file is read as it always was
    given = {given.splitlines()[0]: given for _, given in one.ollama.asked}
    assert "boat engine hours, boat engine hours" in given["File name: export.csv"]  # the big ones gave their beginning
    assert "plant list plant list" in given["File name: export.html"]  # markup still without its tags
    assert not big.is_file() and (home / "Downloads" / "Boat" / "export.csv").is_file()
    assert fw.PIECE_CHARS >= 2 * fw.READ_CHARS  # room for text that is mostly spaces to still fill what is kept
    monkeypatch.setattr(fw, "PIECE_CHARS", 12)  # and each piece is cut before the spaces in it are closed up
    assert one._text(home / "Downloads" / "Boat" / "export.csv") == "boat engine"


def text_pdf(path: Path, pages: list[str]) -> None:
    """A PDF with one line of text on each page, the kind pypdf reads back as text."""
    kids = " ".join(f"{4 + 2 * number} 0 R" for number in range(len(pages)))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for number, line in enumerate(pages):
        stream = f"BT /F1 11 Tf 50 750 Td ({line}) Tj ET".encode("cp1252")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * number} 0 R "
                       "/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def test_a_pdf_is_read_only_as_far_as_its_first_pages(home, monkeypatch):
    import pypdf

    taken = []
    extract = pypdf.PageObject.extract_text
    monkeypatch.setattr(pypdf.PageObject, "extract_text", lambda page, *a, **more: taken.append(1) or extract(page, *a, **more))
    downloads = home / "Downloads"
    text_pdf(downloads / "manual.pdf", ["Service record for the boat engine", "Page two of it", "Page three of it"])
    one = make(home, now=later())
    told = []
    one.moved = told.append
    assert [text for _, text in fw.read_start(downloads / "manual.pdf")][1:] == ["Page two of it", "Page three of it"]
    taken.clear()
    monkeypatch.setattr(fw, "READ_CHARS", 20)  # the first page fills what is kept
    list(one.run_once(one.active[NAME], everything=True))
    assert len(taken) == 1  # the pages after it were never read
    assert "Service record for t" in one.ollama.asked[0][1] and "Page two" not in one.ollama.asked[0][1]
    monkeypatch.setattr(fw, "READ_CHARS", 3000)
    assert one._text(downloads / "manual.pdf").split("\n") == ["Service record for the boat engine", "Page two of it",
                                                                "Page three of it"]


def test_its_own_model_reads_pictures_when_it_can_see_and_nothing_else_is_loaded(home):
    one = make(home, Model(sees=True), now=later())
    assert one.seer() == "noir"
    said = one._see(b"\xff\xd8 a picture")
    assert said == "A picture. The words in it: Engine service log: 40 hours. What it shows: a photo of a logbook"
    assert one.ollama.asked[0][0] == "noir" and one.ollama.told[0] == fw.SEE_NOTE
    assert one.ollama.options == [None]  # as it is loaded: another amount of room would load it twice
    one._release_helper()
    assert one.ollama.unloaded == []


def test_a_helper_model_sees_only_when_its_own_cannot_and_leaves_after_the_look(home):
    downloads = home / "Downloads"
    one = make(home, Model(sees=False), now=later())
    told = []
    one.moved = told.append
    assert one.seer() == HELPER
    (downloads / "deck.png").write_bytes(b"\x89PNG a picture")
    one.look()
    assert (downloads / "Boat" / "deck.png").is_file()  # by the words the picture showed
    assert one.ollama.seen and one.ollama.seen[0]  # the picture went to the model that can see
    assert one.ollama.options[0] == {"num_ctx": fw.SEE_CONTEXT} and one.ollama.kept_alive[0] == fw.SEE_KEEP_ALIVE
    assert told[0]["steps"][1] == f"Looked at the picture through {HELPER}"
    assert "The words in it: Engine service log: 40 hours" in one.ollama.asked[1][1]
    assert one.ollama.unloaded == [HELPER]  # at the end of the look, not five minutes later
    one.look()
    assert one.ollama.unloaded == [HELPER]  # nothing to free when nothing was seen
    (downloads / "sail.png").write_bytes(b"\x89PNG another picture")
    assert one.item(one.active[NAME], downloads / "sail.png").how == f"a picture: read through {HELPER}"
    list(one.run_once(one.active[NAME]))
    assert one.ollama.unloaded == [HELPER, HELPER]  # and at the end of a pass


def test_a_picture_stays_when_no_model_here_can_see_it(home):
    one = make(home, Model(sees=False, helper=False), now=later())
    stayed = []
    one.stayed = stayed.append
    path = home / "Downloads" / "boat.png"
    path.write_bytes(b"\x89PNG a picture")
    one.look()
    assert one.seer() == "" and path.is_file() and one.ollama.asked == []
    assert stayed[0]["why"] == fw.NO_TEXT
    assert stayed[0]["steps"][1:] == ["A picture, and no model here that can see it",
                                      f"Stayed in Downloads: {fw.NO_TEXT}"]


def test_why_a_picture_gave_nothing_is_said_as_it_was(home, monkeypatch):
    """It said "no model here that can see it" of every picture that gave nothing, also with
    such a model installed, when the picture was too big for it or the look had failed."""
    monkeypatch.setattr(fw, "MAX_IMAGE_MB", 0.001)  # about a thousand bytes
    downloads = home / "Downloads"
    one = make(home, Model(sees=True), now=later())
    stayed, opened = [], []
    one.stayed = stayed.append
    (downloads / "a-big.png").write_bytes(b"\x89PNG" + b"x" * 2000)
    (downloads / "b-small.png").write_bytes(b"\x89PNG a picture")
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: opened.append(path.name) or read_bytes(path))
    one.ollama.down = True  # the model that can see is there, and can't be reached this once
    one.look()
    assert one.seer() == "noir"
    assert [report["steps"][1] for report in stayed] == ["A picture too big to look at",
                                                         "A picture, and it couldn't be looked at just now"]
    assert all(report["why"] == fw.NO_TEXT for report in stayed)
    assert opened == ["b-small.png"] and len(one.ollama.asked) == 1  # the big one was never read into memory


def test_a_scanned_page_is_read_through_its_picture(home):
    from PIL import Image

    downloads = home / "Downloads"
    one = make(home, Model(sees=True), now=later())
    told = []
    one.moved = told.append
    Image.new("RGB", (600, 800), "white").save(downloads / "scan.pdf", "PDF")  # a page with no words, only a picture
    one.look()
    assert one.ollama.seen and one.ollama.seen[0]  # its first page's picture was looked at
    assert told[0]["steps"][1] == "A scanned page: read it with the built-in model"
    assert (downloads / "Boat" / "scan.pdf").is_file()


def test_a_big_picture_is_shrunk_and_given_room_before_the_model_sees_it(home):
    import base64
    import io

    from PIL import Image

    big = io.BytesIO()
    Image.new("RGB", (3300, 2550), "white").save(big, "JPEG")
    small = fw.shrink(big.getvalue())
    assert max(Image.open(io.BytesIO(small)).size) == fw.SEE_PIXELS and len(small) < len(big.getvalue())
    assert fw.shrink(b"not a picture") == b"not a picture"
    one = watch(home, Model(sees=False))
    assert one._see(big.getvalue()).startswith("A picture. The words in it:")
    sent = base64.b64decode(one.ollama.seen[-1][0])
    assert max(Image.open(io.BytesIO(sent)).size) == fw.SEE_PIXELS
    assert one.ollama.options == [{"num_ctx": fw.SEE_CONTEXT}]
    assert one._see(b"x" * (fw.MAX_IMAGE_MB * 1024 * 1024 + 1)) == "" and len(one.ollama.asked) == 1  # too big to show


def test_a_judged_file_keeps_its_model_no_longer_than_a_chat_answer_does(home):
    one = make(home, now=later())
    land(home)
    one.look()
    assert one.ollama.kept_alive == [noir.KEEP_ALIVE]


# --------------------------------------------------- a deleted card, and restarts


def test_a_deleted_card_takes_what_was_kept_about_it_with_it(home):
    downloads = home / "Downloads"
    one = make(home, now=later())
    old = land(home, "old-engine.txt", "boat engine")
    land(home, "phone-bill.txt", "Amount due")
    one.look()
    assert one.made[NAME] == ["Boat"] and one.skipped[NAME] and one._seen[NAME] and one.since[NAME]
    changed = []
    one.changed = lambda: changed.append(True)
    one.forget(NAME)
    assert not one.is_on(NAME) and changed
    assert one.made == {} and one.skipped == {} and one._seen == {} and one.since == {} and one.last_skipped() == []
    state = state_of(home)
    assert state == {"on": [], "made": {}, "seen": {}, "skipped": {}, "since": {}}
    # A new one of the same name starts from nothing: what is there now is old.
    waiting = land(home, "waiting-engine.txt", "boat engine")
    one.refresh([card(downloads)])
    assert not one.is_on(NAME)
    one.switch(card(downloads), True)
    one.look()
    assert waiting.is_file() and not old.is_file()


def test_forgetting_waits_for_the_file_in_hand_so_nothing_is_written_back(home):
    reading, let_go = threading.Event(), threading.Event()
    one = make(home, now=later())
    one.ollama.while_asked = lambda: (reading.set(), let_go.wait(5))
    land(home)
    looking = threading.Thread(target=one.look, daemon=True)
    looking.start()
    assert reading.wait(5)
    forgetting = threading.Thread(target=one.forget, args=(NAME,), daemon=True)
    forgetting.start()
    time.sleep(0.2)
    assert one.is_on(NAME)  # still waiting its turn: the file in hand comes first
    let_go.set()
    looking.join(5)
    forgetting.join(5)
    # The move made a folder, and forgetting came after it: nothing of the agent is left behind.
    assert not one.is_on(NAME) and one.made == {} and one._seen == {}
    assert NAME not in (home / fw.STATE_NAME).read_text(encoding="utf-8")


def test_an_agent_coming_back_after_a_restart_is_watching_from_then(home):
    one = make(home, now=later())
    one.forget(NAME)  # as if this run had never had it
    (home / fw.STATE_NAME).write_text(json.dumps({"on": [NAME], "seen": {}, "made": {}, "skipped": {}}), encoding="utf-8")
    one.refresh([card(home / "Downloads")])
    # Written down by an older version with no "since": it counts as watched from the restart,
    # so the chores line says "On since ..." instead of a job from before.
    assert one.is_on(NAME) and one.since[NAME] > 0


def test_when_it_was_switched_on_survives_a_restart(home):
    now = [1_000_000.0]
    make(home, now=now)
    now[0] += 5000
    again = watch(home, now=now)
    again.refresh([card(home / "Downloads")])
    assert again.since[NAME] == 1_000_000.0  # since it was switched on, not since the app started


def test_a_changed_folder_is_watched_from_now_whatever_the_file_says(home):
    one = make(home, now=later())
    one.since[NAME] = 100.0
    one._write_state()  # the state file says it has been on since long ago
    (home / "Documents").mkdir()
    one.refresh([card(home / "Documents")])  # the saved agent now watches another folder
    assert one.since[NAME] > 100.0  # reading the file again mustn't bring the old time back


def test_the_files_it_had_under_its_old_names_are_taken_over_once(home):
    downloads = home / "Downloads"
    (downloads / "Boat").mkdir()
    (downloads / "Boat" / "engine.txt").write_text("boat engine", encoding="utf-8")
    move = {"from": str(downloads / "engine.txt"), "to": str(downloads / "Boat" / "engine.txt")}
    (home / "organizer.json").write_text(json.dumps([{"id": "7-0", "when": time.time(), "moves": [move], "agent": NAME}]),
                                         encoding="utf-8")
    (home / "organizer_done.json").write_text(json.dumps([{"when": time.time(), "text": "Put engine.txt in Boat",
                                                           "undo": True, "details": "", "sort": "7-0", "agent": NAME,
                                                           "where": str(downloads / "Boat")}]), encoding="utf-8")
    # Why files stayed, in the words of what ran before: one waits for an answer nobody is
    # asked for any more, and both were given by a way of judging that is gone.
    left = [{"name": "phone-bill.txt", "where": str(downloads), "why": "which folder wasn't clear", "when": 5.0},
            {"name": "boat.png", "where": str(downloads), "why": "waiting for your yes on .png files", "when": 6.0}]
    (home / "organizer_state.json").write_text(json.dumps({
        "on": [NAME], "made": {NAME: ["Boat"]}, "seen": {NAME: [str(downloads / "phone-bill.txt")]},
        "skipped": {NAME: left}, "since": {NAME: 100.0},
        # What an older version also kept there: read by nothing now, and gone at the next write.
        "kinds": {NAME: {".png": "no"}}, "subjects": {NAME: {"X": "no"}}, "asking": [{"id": "kind:x", "files": []}]}),
        encoding="utf-8")
    one = watch(home, now=later())
    assert not any((home / name).exists() for name in (fw.OLD_LOG, fw.OLD_DONE, fw.OLD_STATE))
    # Told to the user as the reason today, the old reasons would be untrue: they are not taken over.
    assert "skipped" not in state_of(home) and state_of(home)["made"] == {NAME: ["Boat"]}
    one.refresh([card(downloads)])
    assert one.is_on(NAME) and one.made == {NAME: ["Boat"]} and one.since[NAME] == 100.0
    assert one.last_skipped() == [] and one.skipped == {} and one._seen[NAME] == {str(downloads / "phone-bill.txt")}
    assert one.last_moves()[0]["name"] == "engine.txt" and one.done_lately()[0]["undo"] is True
    one.switch(card(downloads), True)  # writes the state down again
    assert sorted(state_of(home)) == ["made", "on", "seen", "since", "skipped"]
    assert one.undo("7-0") == 1 and (downloads / "engine.txt").is_file()  # the old moves can still go back
    # Once: old files that turn up later never replace what is kept now.
    (home / fw.OLD_STATE).write_text('{"on": []}', encoding="utf-8")
    again = watch(home, now=later())
    again.refresh([card(downloads)])
    assert again.is_on(NAME) and (home / fw.OLD_STATE).is_file()


def test_a_state_file_nobody_can_read_stops_nothing(home):
    (home / fw.STATE_NAME).write_text("[1, 2", encoding="utf-8")
    one = watch(home, now=later())
    one.refresh([card(home / "Downloads")])
    assert not one.is_on(NAME)
    (home / fw.STATE_NAME).write_text('["a list, not what was kept"]', encoding="utf-8")
    one.refresh([card(home / "Downloads")])
    one.switch(card(home / "Downloads"), True)
    assert state_of(home)["on"] == [NAME]


# ------------------------------------------------------------ the dry run


def aged(home: Path, name: str, text: str, age: float) -> Path:
    """A file in Downloads that last changed `age` seconds ago."""
    path = land(home, name, text)
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def test_a_dry_run_says_what_would_happen_and_changes_nothing(home):
    downloads = home / "Downloads"
    aged(home, "engine.txt", "Service record for the boat engine", 40)
    aged(home, "seeds.txt", "Plant list", 30)
    aged(home, "phone-bill.txt", "Amount due", 20)
    aged(home, "eggs.txt", "eggs, milk", 10)
    agent = card(downloads)  # never saved, never switched on
    slots = json.loads(json.dumps(agent.slots))
    one = watch(home)
    told = []
    one.changed = lambda: told.append("changed")
    one.moved = one.stayed = one.working = told.append
    before = everything_in(home)
    rows = one.rehearse(agent)
    assert rows == [
        {"name": "eggs.txt", "ending": ".txt", "what": "can't tell", "choice": "", "new": False,
         "why": "not sure where it goes: can't tell", "note": ""},
        {"name": "phone-bill.txt", "ending": ".txt", "what": "a bill", "choice": "", "new": False,
         "why": "the rule leaves it: a bill", "note": ""},
        {"name": "seeds.txt", "ending": ".txt", "what": "a plant list", "choice": "Garden", "new": False, "why": "",
         "note": ""},
        {"name": "engine.txt", "ending": ".txt", "what": "a paper about the boat", "choice": "Boat", "new": False,
         "why": "", "note": ""}]  # newest first
    assert everything_in(home) == before  # nothing moved, made or written: not a folder, not a state file, not a log
    assert told == [] and agent.slots == slots and store.list_agents() == []
    assert (one.active, one._seen, one.skipped, one.made, one.since, one._landing, one._now) == ({}, {}, {}, {}, {}, {}, {})
    assert one.done_lately() == [] and one.last_moves() == [] and one.last_skipped() == []
    assert one._steps == [] and one.doing() == "" and one.ollama.warmed == []


def test_a_dry_run_of_a_card_that_is_on_leaves_its_files_new(home):
    one = make(home, now=later())
    land(home)
    before, state = everything_in(home), json.dumps([sorted(one._seen[NAME]), one.skipped, one.made], default=str)
    assert one.rehearse(one.active[NAME])[0]["choice"] == "Boat"
    assert everything_in(home) == before
    assert json.dumps([sorted(one._seen[NAME]), one.skipped, one.made], default=str) == state
    one.look()
    assert (home / "Downloads" / "Boat" / "engine.txt").is_file()  # still new to the real thing


def test_a_dry_run_takes_the_newest_files_newest_first(home):
    for number in range(11):
        aged(home, f"engine{number:02}.txt", "boat engine", 1000 - number)  # engine10 is the newest
    one = watch(home)
    agent = card(home / "Downloads")
    assert [row["name"] for row in one.rehearse(agent, limit=3)] == ["engine10.txt", "engine09.txt", "engine08.txt"]
    assert fw.REHEARSE_FILES == 8 and len(one.rehearse(agent)) == 8
    assert one.rehearse(agent, limit=0) == []


def test_a_dry_run_leaves_out_what_is_never_a_file_to_handle(home):
    downloads = home / "Downloads"
    one = make(home, now=later(), agent=card(downloads, then=NOTE, name="Other log"))  # another card's notes file
    aged(home, "Other log.md", "## boat\nnotes", 5)
    aged(home, "Reading log.md", "## boat\nnotes", 5)  # its own
    aged(home, ".boat.txt", "boat", 5)
    aged(home, "boat.pdf.crdownload", "boat", 5)
    aged(home, "engine.txt", "boat engine", 5)  # settled or not
    writer = card(downloads, then=NOTE, name="Reading log")
    before = everything_in(home)
    rows = one.rehearse(writer)
    assert rows == [{"name": "engine.txt", "ending": ".txt", "what": "a paper about the boat", "choice": "",
                     "new": False, "why": "", "note": "This is a paper about the boat."}]
    assert everything_in(home) == before  # nothing was added to the notes file


def test_a_dry_run_shows_the_beginning_of_a_note_and_writes_nothing(home):
    class Wordy(Model):
        def note_for(self, what):
            return "A long note. " * 40

    aged(home, "engine.txt", "boat engine", 20)
    aged(home, "phone-bill.txt", "Amount due", 10)
    one = watch(home, Wordy())
    rows = one.rehearse(card(home / "Downloads", then=NOTE, name="Reading log"))
    assert rows[0] == {"name": "phone-bill.txt", "ending": ".txt", "what": "a bill", "choice": "", "new": False,
                       "why": "the rule asks for nothing about it: a bill", "note": ""}
    # Enough of it for a try-out to show the note, not only how it begins.
    assert fw.REHEARSE_NOTE_CHARS == 400
    assert rows[1]["note"] == ("A long note. " * 40)[:400] and rows[1]["why"] == "" and rows[1]["choice"] == ""
    assert not (home / "Downloads" / "Reading log.md").exists()


def test_a_dry_run_shows_files_that_can_be_read_before_ones_that_cannot(home):
    downloads = home / "Downloads"
    for number in range(3):  # the newest three are programs
        (downloads / f"setup{number}.exe").write_bytes(b"MZ" * 64)
        os.utime(downloads / f"setup{number}.exe", (time.time() - number, time.time() - number))
    aged(home, "engine.txt", "boat engine", 50)
    aged(home, "seeds.txt", "Plant list", 60)
    one = watch(home)
    agent = card(downloads)
    assert [row["name"] for row in one.rehearse(agent, limit=2)] == ["engine.txt", "seeds.txt"]
    rows = one.rehearse(agent, limit=4)  # room left: the newest that can't be read say so
    assert [row["name"] for row in rows] == ["setup0.exe", "setup1.exe", "engine.txt", "seeds.txt"]
    assert rows[0] == {"name": "setup0.exe", "ending": ".exe", "what": "", "choice": "", "new": False,
                       "why": fw.NO_TEXT, "note": ""}
    assert all("setup" not in given for _, given in one.ollama.asked)  # no model is asked about them
    # A card that goes by names can "read" every file.
    by_name = card(downloads, looks_at=NAME_ONLY)
    assert [row["name"] for row in one.rehearse(by_name, limit=2)] == ["setup0.exe", "setup1.exe"]


def test_a_dry_run_keeps_the_folders_it_would_have_made(home):
    downloads = home / "Downloads"
    aged(home, "trip-to-oslo.txt", "The trip, day by day", 30)
    aged(home, "trip-home.txt", "The trip back", 20)
    aged(home, "engine.txt", "boat engine", 10)
    agent = card(downloads, choices="Boat", open=OPEN_YES)
    one = watch(home)
    rows = one.rehearse(agent)
    assert [(row["name"], row["choice"], row["new"]) for row in rows] == [
        ("engine.txt", "Boat", False), ("trip-home.txt", "Trips", True), ("trip-to-oslo.txt", "Trips", True)]
    # Judged oldest first, as they landed: by the second trip file the folder is one "so far".
    assert "(none yet)" not in one.ollama.told[0] and "- Boat\n- Trips\n" not in one.ollama.told[0]
    assert "spelled the same way:\n- Boat\n- Trips\n" in one.ollama.told[1]
    assert agent.slots["choices"] == "Boat" and not (downloads / "Trips").exists()


def test_a_dry_run_waits_its_turn_and_frees_a_helper_model_after(home):
    downloads = home / "Downloads"
    (downloads / "deck.png").write_bytes(b"\x89PNG a picture")
    one = watch(home, Model(sees=False))
    rows = []
    with one._work:  # a file is in hand
        trying = threading.Thread(target=lambda: rows.append(one.rehearse(card(downloads))), daemon=True)
        trying.start()
        time.sleep(0.2)
        assert rows == [] and one.ollama.asked == []
    trying.join(5)
    assert rows and rows[0][0]["choice"] == "Boat"
    assert one.ollama.unloaded == [HELPER]


def test_a_dry_run_survives_a_model_that_cannot_be_reached_and_a_file_that_breaks(home):
    aged(home, "engine.txt", "boat engine", 20)
    aged(home, "odd.txt", "odd", 10)
    one = watch(home)

    def breaks_on_the_odd_one():
        if "odd.txt" in one.ollama.asked[-1][1]:
            raise ValueError("a reply nobody could read")

    one.ollama.while_asked = breaks_on_the_odd_one
    rows = one.rehearse(card(home / "Downloads"))
    assert [(row["name"], row["why"]) for row in rows] == [("odd.txt", "something went wrong reading it (ValueError)"),
                                                           ("engine.txt", "")]
    one.ollama.while_asked = lambda: None
    one.ollama.down = True
    assert {row["why"] for row in one.rehearse(card(home / "Downloads"))} == {fw.NO_MODEL}


# ------------------------------------------------------------ what it may know


def test_nothing_in_the_runtime_knows_what_a_card_is_for():
    """No subject and no kind of agent in anything a model or a person reads from here."""
    tree = ast.parse(Path(fw.__file__).read_text(encoding="utf-8"))
    old_names = {fw.OLD_LOG, fw.OLD_DONE, fw.OLD_STATE}  # the files it takes over, named as they were
    words = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and node.value not in old_names]
    # The words the catalog and the designer are held to (test_parts, test_designer), and a few more.
    banned = re.compile(r"\b(courses?|school|college|class|lectures?|homework|syllabus|exams?|quiz|midterm|physics|"
                        r"math\w*|tuition|subjects?|bank|tax|bills?|invoices?|receipts?|organi[sz]\w*|summar\w*|"
                        r"translat\w*)\b", re.IGNORECASE)
    assert not [(found.group(), text) for text in words if (found := banned.search(text))]
    # The one note a model reads from here ends where its question ends: no kinds of picture
    # are listed after it. Given a list, the model answered with a word off the list.
    assert fw.SEE_NOTE.endswith("say in a few words what kind of picture it is.")
    assert not re.search(r"\blike \"|\bsuch as\b|\be\.g\.", fw.SEE_NOTE)
    assert fw.LOOK_SECONDS == 2 and fw.SETTLE_SECONDS == 3  # what the card's facts tell the user ("a few seconds")


# ------------------------------------------------------------ beside the folder runtime
# What the same nights taught about Noir's own model and the chores line. These tests lived
# with the organizer's and guard code that is still there.


def test_noirs_model_is_let_go_once_it_sits_unused():
    class Loaded:
        refreshed = 0
        used: dict = {}

        def capabilities(self, name):
            return ["completion"]

        def loaded(self):
            return [{"name": "noir:latest"}]

        def refresh(self, name, keep_alive):
            self.refreshed += 1

        def unload(self, name):
            pass

    chat = noir.NoirChat(Loaded())
    chat.check_in()
    assert chat.ollama.refreshed == 0  # never used: nothing to keep
    chat.ollama.used = {"noir": time.time()}
    chat.check_in()
    assert chat.ollama.refreshed == 1  # used a moment ago: kept
    chat.ollama.used = {"noir": time.time() - noir.IDLE_UNLOAD_SECONDS - 1}
    chat.check_in()
    assert chat.ollama.refreshed == 1  # idle: no check-in, so Ollama lets it go
    chat.close()


def test_the_client_notes_each_use_of_a_model(monkeypatch):
    from concierge.ollama import Ollama

    client = Ollama()
    monkeypatch.setattr(client, "_post", lambda path, body: {"message": {"content": "{}"}})
    client.chat_json("noir:latest", [], {})
    assert time.time() - client.used["noir"] < 5


def test_a_chores_line_says_what_is_happening_now_then_the_last_thing_then_that_nothing_landed():
    now = time.time()
    job = {"agent": NAME, "sort": "1-1", "text": "Put engine.txt in Boat", "when": now - 120}
    entry = {"name": NAME, "on": True, "how": "Watches Downloads.", "now": "Reading seeds.txt now", "since": now - 600}

    def line(entry, done):
        return chores.listing({}, done, [entry], [], now)["chores"][1]["last"]

    assert line(entry, [job]) == "Reading seeds.txt now"
    assert line({**entry, "now": ""}, [job]) == "Put engine.txt in Boat · 2 min ago"
    # The last job was before it was switched on (an earlier agent of the same name): not its work.
    quiet = line({**entry, "now": "", "since": now - 60}, [job])
    assert quiet == f"On since {chores.clock_time(now - 60, now)}. Nothing new has landed since."
    assert line({**entry, "now": "", "since": now - 60}, []) == quiet
    # A file that landed and was left is the last thing it did: never "nothing new has landed".
    left = {"name": "boat-setup.exe", "why": fw.NO_TEXT, "when": now - 30}
    assert line({**entry, "now": "", "since": now - 60, "left": left}, [job]) == \
        f"Left boat-setup.exe where it was: {fw.NO_TEXT} · just now"
    assert line({**entry, "now": "", "left": {**left, "when": now - 300}}, [job]) == "Put engine.txt in Boat · 2 min ago"
