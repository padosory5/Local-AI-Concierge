"""The drawer's pull from the screen's edge (quick/drawer.py) and the chores list it shows (chores.py)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from concierge import chores
from concierge.quick.drawer import EDGE_PIXELS, OPEN_PIXELS, EdgePull

SCREEN = (0, 0, 1920, 1032, 1.0)


class Button:
    name = "left"


class Right:
    name = "right"


class Ctrl:
    name = "ctrl_l"


class Pull:
    """Records what the gesture tells the window."""

    def __init__(self, open_rect=None):
        self.pulls, self.releases = [], []
        self.open_rect = open_rect
        self.gesture = EdgePull(lambda d, s, c: self.pulls.append((d, c)), lambda d, s, c: self.releases.append((d, c)),
                                lambda: self.open_rect, screen=lambda x, y: SCREEN)

    def ctrl_drag(self, start_x, moves, release_x, ctrl=True, button=Button()):
        if ctrl:
            self.gesture.pressed(Ctrl())
        self.gesture.clicked(start_x, 500, button, True)
        for x in moves:
            self.gesture.moved(x, 500)
        self.gesture.clicked(release_x, 500, button, False)
        if ctrl:
            self.gesture.released(Ctrl())
        time.sleep(0.05)  # the release is handed to a thread of its own


def test_ctrl_and_a_pull_from_the_right_edge_opens_the_drawer():
    pull = Pull()
    pull.ctrl_drag(1915, [1880, 1800, 1700], 1700)
    assert pull.pulls == [(0, False), (35, False), (115, False), (215, False)]
    assert pull.releases == [(215, False)]
    assert pull.releases[0][0] >= OPEN_PIXELS


def test_a_short_pull_is_let_go_of_and_the_window_decides():
    pull = Pull()
    pull.ctrl_drag(1919, [1900], 1900)
    assert pull.releases == [(19, False)] and 19 < OPEN_PIXELS


def test_without_ctrl_or_away_from_the_edge_nothing_happens():
    pull = Pull()
    pull.ctrl_drag(1915, [1800], 1800, ctrl=False)
    pull.ctrl_drag(1915 - EDGE_PIXELS - 1, [1800], 1800)
    pull.ctrl_drag(1915, [1800], 1800, button=Right())
    assert pull.pulls == [] and pull.releases == []


def test_pulling_the_wrong_way_counts_as_nothing():
    pull = Pull()
    pull.ctrl_drag(1915, [1919], 1919)
    assert pull.pulls == [(0, False), (0, False)] and pull.releases == [(0, False)]


def test_with_the_drawer_open_a_push_on_it_to_the_right_closes_it():
    pull = Pull(open_rect=(1540, 16, 380, 1000))
    pull.ctrl_drag(1600, [1650, 1760], 1760)
    assert pull.pulls == [(50, True), (160, True)]
    assert pull.releases == [(160, True)]


def test_with_the_drawer_open_only_a_press_on_it_counts():
    pull = Pull(open_rect=(1540, 16, 380, 1000))
    pull.ctrl_drag(1915, [1700], 1700)  # on the drawer, dragged the wrong way for a push: nothing moves
    pull.ctrl_drag(300, [200], 200)  # off the drawer: not a pull at all
    assert pull.pulls == [(0, True)] and pull.releases == [(0, True)]


# ------------------------------------------------------------- the list

NOW = datetime(2026, 11, 8, 14, 0).timestamp()


def job(text, hours_ago, **more):
    return {"when": NOW - hours_ago * 3600, "text": text, "undo": False, "details": "", "sort": "", **more}


def test_the_list_names_every_kind_of_chore_and_whether_it_is_on():
    today = {"noticing": True, "noticed": None, "working": None}
    agents = [{"name": "Korean Translator", "kind": "highlight", "on": False, "how": "While it's on, highlights go through it."}]
    bookings = [{"id": "b1", "agent": "Contracts helper", "action": "run", "text": "Any new deadlines?",
                 "when": "2026-11-09T09:00", "repeat": "daily", "active": True, "missed": False}]
    listing = chores.listing(today, [job("Sorted 12 files into folders", 2, sort="s1")], agents, bookings, now=NOW)
    names = [(chore["kind"], chore["name"], chore["on"]) for chore in listing["chores"]]
    assert names == [("tidy", "Keep Downloads tidy", True), ("agent", "Korean Translator", False),
                     ("booking", "Ask Contracts helper", True)]
    assert listing["chores"][0]["last"] == "Sorted 12 files into folders · 2 h ago"
    assert listing["chores"][2]["how"] == "Any new deadlines? · every day at Mon 09:00"


def test_a_helpers_line_is_made_of_what_the_engine_says_whatever_the_helper_is():
    # The list knows no kind of helper: what the engine calls one is not read, and not passed on.
    entry = {"name": "Reading log", "kind": "anything at all", "on": True, "how": "Watches Downloads.", "now": "",
             "since": NOW - 7200, "left": None}
    wrote = job("Wrote about pump.txt in Reading log.md", 0.5, agent="Reading log")  # a note: nothing to undo, no sort

    def line(entry, done):
        return chores.listing({}, done, [entry], [], now=NOW)["chores"][1]

    assert line(entry, [wrote]) == {"id": "agent:Reading log", "kind": "agent", "name": "Reading log", "on": True,
                                    "how": "Watches Downloads.",
                                    "last": "Wrote about pump.txt in Reading log.md · 30 min ago"}
    # A job with nothing to undo is still the last thing it did: counted out, the line said
    # nothing new had landed right after a note was written.
    assert "Nothing new has landed" in line(entry, [])["last"]
    # Another helper's job, and files put back by hand, are not its work.
    others = [job("Put engine.txt in Boat", 0.2, agent="Paper sorter", sort="s2"), job("Put 1 file back", 0.1, agent="")]
    assert line(entry, [wrote, *others])["last"] == "Wrote about pump.txt in Reading log.md · 30 min ago"
    # What it is doing this moment comes first, in the engine's own words.
    assert line({**entry, "now": "Reading pump.txt now"}, [wrote])["last"] == "Reading pump.txt now"
    # One the engine gives no record for (no "since") has no line of its own.
    assert line({"name": "Korean Translator", "on": True, "how": "While it's on."}, [])["last"] == ""


def test_a_helper_that_is_off_for_a_reason_says_the_reason_for_as_long_as_it_is_off():
    # Said only once in the chat, a helper that an update had switched off was simply "Off" in the list.
    entry = {"name": "Paper sorter", "kind": "files", "on": False, "how": "Watches Downloads.", "now": "", "since": 0,
             "left": None, "why_off": "its rule needs talking through"}
    moved = job("Put engine.txt in Boat", 30, agent="Paper sorter", sort="s2")  # what it did before it was switched off

    def last(entry):
        return chores.listing({}, [moved], [entry], [], now=NOW)["chores"][1]["last"]

    assert last(entry) == "Off: its rule needs talking through"
    # Switched on, or with no reason given, the line is what it always was.
    assert last({**entry, "on": True, "since": NOW - 60}) == "On since 1:59 PM. Nothing new has landed since."
    assert last({**entry, "why_off": ""}) == "Put engine.txt in Boat · 1 day ago"


def test_jobs_are_grouped_by_day_newest_first_like_notes():
    done = [job("Sorted 9 downloads", 30), job("Sorted 12 downloads", 5), job("Put 3 files back", 1),
            job("Sorted 4 downloads", 24 * 6 + 2)]
    days = chores.days(done, NOW)
    assert [day["day"] for day in days] == ["Today", "Yesterday", "Nov 2"]
    assert [j["text"] for j in days[0]["jobs"]] == ["Put 3 files back", "Sorted 12 downloads"]
    assert days[0]["jobs"][0]["time"] == "13:00"


def test_a_missed_booking_and_an_untold_watch_read_plainly():
    bookings = [{"id": "b2", "agent": "", "action": "sort", "text": "", "when": "2026-11-07T18:00", "repeat": "once",
                 "active": False, "missed": True}]
    listing = chores.listing({"noticing": None}, [], [], bookings, now=NOW)
    assert listing["chores"][0]["on"] is False  # never told it may notice things
    booking = listing["chores"][1]
    assert booking["name"] == "Sort Downloads" and booking["on"] is False and booking["last"].startswith("Missed")


def test_ago_reads_like_a_person():
    assert chores.ago(NOW - 20, NOW) == "just now"
    assert chores.ago(NOW - 15 * 60, NOW) == "15 min ago"
    assert chores.ago(NOW - 3 * 3600, NOW) == "3 h ago"
    assert chores.ago(NOW - 2 * 86400, NOW) == "2 days ago"


def test_the_drawer_retires_the_buttons_of_earlier_questions_and_cards_once_anything_else_is_said():
    """Left live, Create it on an earlier card in the drawer made the newest card: the engine
    knows only the card on screen. The full window has always retired them (app.js begin())."""
    import re
    from pathlib import Path

    page = (Path(chores.__file__).parent / "ui" / "web" / "glass.js").read_text(encoding="utf-8")
    retire = re.search(r"function retireChoices\(\) \{(.*?)\n  \}", page, re.S)
    assert retire and 'querySelectorAll(".choice")' in retire.group(1) and "disabled = true" in retire.group(1)
    talk = re.search(r"async function talk\(call, words\) \{(.*?)\n  \}", page, re.S).group(1)
    assert "retireChoices();" in talk.split("await call()")[0]  # whatever is said in the drawer, a click included
    mirror = re.search(r"function mirror\(change\) \{(.*?)\n  \}", page, re.S).group(1)
    assert "retireChoices();" in mirror.split("} else {")[0]  # and whatever is said in the full window
