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
