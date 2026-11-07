import json
import os
import threading
import time
from ctypes import wintypes

import pytest

from concierge.agents.recipe import CUSTOM, IN_CHAT, WHILE_ON, describe
from concierge.agents.store import Agent
from concierge.quick import glow
from concierge.quick.tidy import (MIN_FILES, NO_VIDEO_SUMMARY, NOT_NOW, SETTLE_SECONDS, SORT, VIDEO, VIDEO_QUESTION, YES,
                                  TidyWatch, can_undo, loose_files, shelf_for, sort_folder, undo_sort)
from concierge.quick.watching import looks_like_lecture
from concierge.ui.mini import ASKING, IDLE, WORKING, draw_frames, is_click

LONG_AGO = time.time() - SETTLE_SECONDS * 10


@pytest.fixture(autouse=True)
def noticing_allowed(monkeypatch):
    """Most tests are about what it does once the user said it may notice things."""
    monkeypatch.setattr(TidyWatch, "_read_settings", lambda self: {"noticing": True})


def make(folder, name, text="x"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    os.utime(path, (LONG_AGO, LONG_AGO))
    return path


def fill(folder, count):
    for number in range(count):
        make(folder, f"file{number}.pdf")


class Lights:
    """Records what the real light would show."""

    def __init__(self):
        self.seen = []
        self.done = threading.Event()

    def started(self):
        self.seen.append("started")

    def finished(self):
        self.seen.append("finished")
        self.done.set()

    def failed(self):
        self.seen.append("failed")
        self.done.set()

    def close(self):
        pass


def watch_for(folder, answer, lights=None, quiet=True):
    return TidyWatch(folder, folder / "log" / "last_sort.json", lights or Lights(),
                     ask=lambda text, cancel: answer, quiet=lambda: quiet)


def test_only_finished_loose_files_count(tmp_path):
    keep = make(tmp_path, "report.pdf")
    make(tmp_path, "movie.mp4.crdownload")
    make(tmp_path, "desktop.ini")
    make(tmp_path, ".hidden")
    (tmp_path / "Pictures").mkdir()
    make(tmp_path / "Pictures", "old.png")
    (tmp_path / "just_arrived.zip").write_text("x")  # may still be downloading
    assert loose_files(tmp_path) == [keep]


def test_a_missing_folder_is_just_empty(tmp_path):
    assert loose_files(tmp_path / "nowhere") == []


def test_files_go_to_a_shelf_by_their_kind(tmp_path):
    assert shelf_for(tmp_path / "a.JPG") == "Pictures"
    assert shelf_for(tmp_path / "setup.exe") == "Installers"
    assert shelf_for(tmp_path / "no_ending") == "Other"


def test_sorting_moves_files_and_undo_puts_them_back(tmp_path):
    report, photo = make(tmp_path, "report.pdf", "words"), make(tmp_path, "photo.png", "picture")
    log = tmp_path / "log" / "last_sort.json"
    assert sort_folder(tmp_path, log) == 2
    assert (tmp_path / "Documents" / "report.pdf").read_text() == "words"
    assert (tmp_path / "Pictures" / "photo.png").read_text() == "picture"
    assert not report.exists() and can_undo(log)

    assert undo_sort(log) == 2
    assert report.read_text() == "words" and photo.read_text() == "picture"
    assert not (tmp_path / "Documents").exists() and not can_undo(log)


def test_nothing_is_ever_overwritten(tmp_path):
    (tmp_path / "Documents").mkdir()
    make(tmp_path / "Documents", "report.pdf", "older")
    make(tmp_path, "report.pdf", "newer")
    sort_folder(tmp_path, tmp_path / "log.json")
    assert (tmp_path / "Documents" / "report.pdf").read_text() == "older"
    assert (tmp_path / "Documents" / "report (2).pdf").read_text() == "newer"


def test_undo_leaves_what_the_user_changed_since(tmp_path):
    make(tmp_path, "report.pdf", "words")
    make(tmp_path, "photo.png", "picture")
    log = tmp_path / "log.json"
    sort_folder(tmp_path, log)
    (tmp_path / "Pictures" / "mine.png").write_text("added later")
    (tmp_path / "Documents" / "report.pdf").unlink()  # the user deleted it
    make(tmp_path, "photo.png", "a new one in the way")

    assert undo_sort(log) == 0
    assert (tmp_path / "photo.png").read_text() == "a new one in the way"
    assert (tmp_path / "Pictures" / "photo.png").read_text() == "picture"  # kept, not lost
    assert (tmp_path / "Pictures" / "mine.png").exists()


def test_yes_sorts_and_shows_both_lights(tmp_path, monkeypatch):
    monkeypatch.setattr("concierge.quick.tidy.MIN_JOB_SECONDS", 0)
    fill(tmp_path, MIN_FILES)
    lights = Lights()
    watch = watch_for(tmp_path, YES, lights)
    watch.look()
    assert lights.done.wait(5)
    assert lights.seen == ["started", "finished"]
    assert len(list((tmp_path / "Documents").iterdir())) == MIN_FILES
    assert watch.can_undo()


def test_a_tidy_folder_gets_no_question(tmp_path):
    fill(tmp_path, MIN_FILES - 1)
    asked = []
    TidyWatch(tmp_path, tmp_path / "log.json", Lights(), ask=lambda text, cancel: asked.append(text),
              quiet=lambda: True).look()
    assert asked == []


def test_she_says_how_many_files_there_are(tmp_path):
    fill(tmp_path, 40)
    asked = []
    TidyWatch(tmp_path, tmp_path / "log.json", Lights(), ask=lambda text, cancel: asked.append(text),
              quiet=lambda: True).look()
    assert asked == ["Sort 40 files in Downloads?"]


def test_not_now_means_she_stays_quiet_even_after_a_restart(tmp_path):
    fill(tmp_path, MIN_FILES)
    log = tmp_path / "log" / "last_sort.json"
    first = TidyWatch(tmp_path, log, Lights(), ask=lambda text, cancel: NOT_NOW, quiet=lambda: True)
    first.look()
    asked = []
    again = TidyWatch(tmp_path, log, Lights(), ask=lambda text, cancel: asked.append(text), quiet=lambda: True)
    again.look()
    assert asked == []
    assert len(loose_files(tmp_path)) == MIN_FILES  # nothing moved


def test_she_waits_while_the_user_is_busy(tmp_path):
    fill(tmp_path, MIN_FILES)
    asked = []
    busy = [False, False, True]
    watch = TidyWatch(tmp_path, tmp_path / "log.json", Lights(), ask=lambda text, cancel: asked.append(text),
                      quiet=lambda: busy.pop(0))
    watch._stopping.wait = lambda seconds: False  # no real waiting in the test
    watch.look()
    assert len(asked) == 1 and busy == []


def test_a_failed_job_never_shows_green(tmp_path, monkeypatch):
    def broken(folder, log):
        raise RuntimeError("disk trouble")

    monkeypatch.setattr("concierge.quick.tidy.sort_folder", broken)
    lights = Lights()
    watch_for(tmp_path, YES, lights).sort_now()
    assert lights.done.wait(5)
    assert lights.seen == ["started", "failed"]


def test_practice_moves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("concierge.quick.tidy.PRACTICE_JOB_SECONDS", 0)
    monkeypatch.setattr("concierge.quick.tidy.MIN_JOB_SECONDS", 0)
    keep = make(tmp_path, "report.pdf")
    lights = Lights()
    watch = TidyWatch(tmp_path, tmp_path / "log.json", lights, ask=lambda text, cancel: YES, quiet=lambda: True,
                      practice=True)
    watch.look()
    assert lights.done.wait(5)
    assert keep.exists() and not watch.can_undo()
    assert json.loads(json.dumps(lights.seen)) == ["started", "finished"]


def test_today_says_what_she_noticed_and_it_goes_after_not_now(tmp_path):
    fill(tmp_path, MIN_FILES)
    watch = watch_for(tmp_path, YES)
    noticed = watch.today()["noticed"]
    assert noticed["id"] == SORT and str(MIN_FILES) in noticed["text"]
    watch.answer(SORT, False)
    assert watch.today()["noticed"] is None


def test_today_lists_finished_jobs_newest_first_and_only_todays(tmp_path, monkeypatch):
    monkeypatch.setattr("concierge.quick.tidy.MIN_JOB_SECONDS", 0)
    fill(tmp_path, MIN_FILES)
    lights = Lights()
    watch = watch_for(tmp_path, YES, lights)
    watch._done = [{"when": time.time() - 3 * 86400, "text": "Old job", "undo": False}]
    watch.sort_now()
    assert lights.done.wait(5)
    time.sleep(0.05)

    today = watch.today()
    assert [job["text"] for job in today["done"]] == [f"Sorted {MIN_FILES} files into folders"]
    assert today["can_undo"] and today["working"] is None and today["noticed"] is None
    # Kept across a restart.
    assert watch_for(tmp_path, YES).today()["done"] == today["done"]


def test_today_says_what_is_running(tmp_path):
    watch = watch_for(tmp_path, YES)
    assert watch._job.acquire(blocking=False)
    watch._doing = "Sorting your Downloads folder"
    assert watch.today()["working"] == "Sorting your Downloads folder"


def test_practice_can_be_seen_in_today_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("concierge.quick.tidy.PRACTICE_JOB_SECONDS", 0)
    monkeypatch.setattr("concierge.quick.tidy.MIN_JOB_SECONDS", 0)
    keep = make(tmp_path, "report.pdf")
    lights = Lights()
    watch = TidyWatch(tmp_path, tmp_path / "log.json", lights, ask=lambda text, cancel: YES, quiet=lambda: True,
                      practice=True)
    assert "60 files" in watch.today()["noticed"]["text"]
    watch.answer(SORT, True)
    assert lights.done.wait(5)
    time.sleep(0.05)
    today = watch.today()
    assert today["noticed"] is None and today["done"][0]["text"] == "Sorted 60 files into folders"
    assert not today["can_undo"] and keep.exists()
    assert not (tmp_path / "tidy_done.json").exists()


def video_watch(tmp_path, answer, lights=None, title="Lecture 5 - YouTube", practice=False):
    asked = []

    def ask(text, cancel):
        asked.append(text)
        return answer

    watch = TidyWatch(tmp_path, tmp_path / "log" / "last_sort.json", lights or Lights(), ask=ask, quiet=lambda: True,
                      watching=lambda: title, practice=practice)
    return watch, asked


def test_she_only_asks_about_a_video_on_the_second_look(tmp_path):
    watch, asked = video_watch(tmp_path, NOT_NOW)
    watch.look_for_video()
    assert asked == []
    watch.look_for_video()
    assert asked == [VIDEO_QUESTION]


def test_she_never_asks_twice_about_the_same_video(tmp_path):
    watch, asked = video_watch(tmp_path, None)  # left alone
    for _ in range(4):
        watch.look_for_video()
    assert asked == [VIDEO_QUESTION]


def test_no_means_no_more_video_questions_for_a_while(tmp_path):
    titles = iter(["Lecture 1", "Lecture 1", "Lecture 2", "Lecture 2"])
    watch, asked = video_watch(tmp_path, NOT_NOW)
    watch._watching = lambda: next(titles)
    for _ in range(4):
        watch.look_for_video()
    assert asked == [VIDEO_QUESTION]


def test_yes_to_a_video_says_plainly_it_isnt_built(tmp_path):
    lights = Lights()
    watch, _ = video_watch(tmp_path, YES, lights)
    watch.look_for_video()
    watch.look_for_video()
    today = watch.today()
    assert today["done"][0]["text"] == NO_VIDEO_SUMMARY
    assert today["noticed"] is None
    assert lights.seen == []  # no job ran, so no light says one did


def test_practice_video_runs_with_both_lights(tmp_path, monkeypatch):
    monkeypatch.setattr("concierge.quick.tidy.PRACTICE_JOB_SECONDS", 0)
    monkeypatch.setattr("concierge.quick.tidy.MIN_JOB_SECONDS", 0)
    lights = Lights()
    watch, asked = video_watch(tmp_path, YES, lights, title="Practice lecture", practice=True)
    watch.look_for_video()  # practice needs only one look
    assert asked == [VIDEO_QUESTION]
    assert lights.done.wait(5)
    assert lights.seen == ["started", "finished"]


def test_a_video_question_answered_in_a_window_never_pops_up(tmp_path):
    watch, asked = video_watch(tmp_path, YES)
    watch._video_waiting = True
    watch.answer(VIDEO, False)
    assert watch._put_question(VIDEO_QUESTION, lambda: watch._video_waiting) is None
    assert asked == []


def test_she_holds_questions_while_the_full_window_is_open(tmp_path):
    fill(tmp_path, MIN_FILES)
    asked = []
    watch = TidyWatch(tmp_path, tmp_path / "log.json", Lights(), ask=lambda text, cancel: asked.append(text),
                      quiet=lambda: True)
    held = [True, True, False]
    watch.held = lambda: held.pop(0)
    watch._stopping.wait = lambda seconds: False
    watch.look()
    assert len(asked) == 1 and held == []


def test_lectures_are_recognised_from_the_window_title():
    assert looks_like_lecture("MIT 6.006 Lecture 5 - YouTube - Google Chrome", "chrome.exe")
    assert looks_like_lecture("물리학 강의 3강 - YouTube - Chrome", "chrome.exe")
    assert looks_like_lecture("calculus lecture 3.mp4 - VLC media player", "vlc.exe")
    assert not looks_like_lecture("funny cats - YouTube - Google Chrome", "chrome.exe")
    assert not looks_like_lecture("Lecture notes.pdf - Google Chrome", "chrome.exe")  # not on a video site
    assert not looks_like_lecture("Lecture 5 - YouTube", "notepad.exe")
    assert not looks_like_lecture("family holiday.mp4 - VLC media player", "vlc.exe")


def test_a_click_on_the_circle_is_recognised_from_a_real_windows_message():
    # A real message, because reading the wrong field of one stopped the circle dead.
    up, down = 0x0202, 0x0201
    assert is_click(wintypes.MSG(hWnd=1234, message=up), 1234)
    assert not is_click(wintypes.MSG(hWnd=1234, message=down), 1234)
    assert not is_click(wintypes.MSG(hWnd=999, message=up), 1234)


def test_every_state_of_the_circle_is_a_full_set_of_whole_pictures():
    for state in (IDLE, WORKING, ASKING):
        frames = draw_frames(state, 40, count=4)
        assert len(frames) == 4 and all(len(frame) == 40 * 40 * 4 for frame in frames)
    assert draw_frames(WORKING, 40, count=2)[0] != draw_frames(IDLE, 40, count=2)[0]


def test_an_agent_is_described_in_the_users_words():
    chat = describe(Agent("Grammar Fixer", CUSTOM, {"instruction": "Fix it.", "when": IN_CHAT}))
    assert chat["does"] == "Fix it."
    assert dict(chat["facts"])["How it answers"] == "In the chat"
    assert "How long it stays" not in dict(chat["facts"])

    on = describe(Agent("Explainer", CUSTOM, {"instruction": "Explain it.", "when": WHILE_ON, "show": "Both"}))
    assert dict(on["facts"])["How it answers"] == "Both"

    files = describe(Agent("Files", "documents_qa", {"folder": "C:/Users/me/Papers"}, contents=["a.pdf"]))
    assert dict(files["facts"])["Reads"] == "Papers" and dict(files["facts"])["Knows"] == "1 file"


def test_light_is_brightest_at_the_edge_and_fades_to_nothing():
    reach = 130
    strengths = [glow.light_at(distance, reach) for distance in range(reach)]
    assert strengths[0] == glow.BRIGHTEST
    assert strengths[-1] < 0.01
    assert strengths == sorted(strengths, reverse=True)


def test_pixels_are_blue_first_and_dimmed():
    assert glow.pixel((200, 100, 50), 0.5) == bytes((25, 50, 100, 128))


def test_the_light_runs_both_ways_round_and_meets_in_the_far_corner():
    start, middle, end = (glow.reached(p, 2560, 1440) for p in (0, 0.5, 1))
    assert set(start.values()) == {0}
    assert middle == {"right": 1440, "bottom": 2000, "top": 560, "left": 0}
    assert end == {"right": 1440, "bottom": 2560, "top": 2560, "left": 1440}


def test_she_notices_nothing_until_the_user_says_yes(tmp_path, monkeypatch):
    monkeypatch.setattr(TidyWatch, "_read_settings", lambda self: {})
    fill(tmp_path, MIN_FILES)
    asked = []
    watch = TidyWatch(tmp_path, tmp_path / "log" / "sorts.json", Lights(), ask=lambda text, cancel: asked.append(text),
                      quiet=lambda: True)
    watch.look()
    assert asked == [] and watch.today()["noticing"] is None and watch.today()["noticed"] is None


def test_the_users_answer_about_noticing_is_kept(tmp_path, monkeypatch):
    monkeypatch.undo()
    log = tmp_path / "log" / "sorts.json"
    TidyWatch(tmp_path, log, Lights(), quiet=lambda: True).set_noticing(False)
    assert TidyWatch(tmp_path, log, Lights(), quiet=lambda: True).noticing is False


def test_every_answer_is_counted_on_this_computer(tmp_path):
    fill(tmp_path, MIN_FILES)
    watch = watch_for(tmp_path, NOT_NOW)
    watch.look()
    watch.answer(SORT, True)
    assert watch.answers()[SORT] == {"yes": 1, "no": 1, "ignored": 0}
    assert json.loads((tmp_path / "log" / "questions.json").read_text())[SORT]["no"] == 1


def test_an_unanswered_question_counts_as_ignored(tmp_path):
    fill(tmp_path, MIN_FILES)
    watch = watch_for(tmp_path, None)
    watch.look()
    assert watch.answers()[SORT]["ignored"] == 1


def test_the_question_comes_with_where_everything_would_go(tmp_path):
    fill(tmp_path, MIN_FILES)
    make(tmp_path, "photo.jpg")
    plan = watch_for(tmp_path, None).today()["noticed"]["plan"]
    assert plan == [{"shelf": "Documents", "count": MIN_FILES}, {"shelf": "Pictures", "count": 1}]


def test_each_sort_can_be_undone_on_its_own_for_a_week(tmp_path):
    log = tmp_path / "log" / "sorts.json"
    make(tmp_path, "a.pdf")
    sort_folder(tmp_path, log)
    first = json.loads(log.read_text())[0]["id"]
    make(tmp_path, "b.jpg")
    sort_folder(tmp_path, log)
    assert undo_sort(log, first) == 1
    assert (tmp_path / "a.pdf").exists() and (tmp_path / "Pictures" / "b.jpg").exists()
    assert can_undo(log) and not can_undo(log, first)


def test_a_sort_older_than_a_week_cant_be_undone(tmp_path):
    log = tmp_path / "log" / "sorts.json"
    make(tmp_path, "a.pdf")
    sort_folder(tmp_path, log)
    sorts = json.loads(log.read_text())
    sorts[0]["when"] -= 8 * 86400
    log.write_text(json.dumps(sorts))
    assert not can_undo(log) and undo_sort(log) == 0


def test_a_sort_saved_by_the_earlier_version_can_still_be_undone(tmp_path):
    log = tmp_path / "log" / "sorts.json"
    log.parent.mkdir()
    moved = tmp_path / "Documents" / "a.pdf"
    moved.parent.mkdir()
    moved.write_text("x")
    log.write_text(json.dumps([{"from": str(tmp_path / "a.pdf"), "to": str(moved)}]))
    assert undo_sort(log) == 1 and (tmp_path / "a.pdf").exists()


def test_today_says_where_the_files_went_and_offers_undo(tmp_path):
    fill(tmp_path, 2)
    lights = Lights()
    watch = watch_for(tmp_path, YES, lights)
    watch.sort_now()
    assert lights.done.wait(10)
    for _ in range(50):
        if watch.today()["working"] is None:
            break
        time.sleep(0.05)
    job = watch.today()["done"][0]
    assert job["details"] == "Documents 2" and job["undo"] is True and job["sort"]


def test_files_kept_only_in_the_cloud_are_never_moved(tmp_path, monkeypatch):
    from concierge.quick import tidy

    real = os.stat(make(tmp_path, "online.pdf"))
    fake = type("Info", (), {"st_mtime": real.st_mtime, "st_mode": real.st_mode, "st_file_attributes": 0x400000})()
    monkeypatch.setattr(tidy.Path, "stat", lambda self, **kw: fake)
    assert loose_files(tmp_path) == []
