from datetime import datetime

import pytest

from concierge.reservations import DAILY, ONCE, RUN, SORT, TURN_ON, WEEKLY, ReservationError, Reservations

NOW = datetime(2026, 11, 2, 8, 0)


def booked(path=None, when="2026-11-02T09:00", repeat=ONCE):
    book = Reservations(path)
    item = book.add("", SORT, "", when, repeat, now=NOW)
    return book, item


def test_a_booking_waits_for_its_time():
    book, _ = booked()
    assert book.take_due(datetime(2026, 11, 2, 8, 59)) == []


def test_a_one_time_booking_runs_once():
    book, item = booked()
    due = book.take_due(datetime(2026, 11, 2, 9, 0))
    assert [one.id for one in due] == [item.id]
    assert book.take_due(datetime(2026, 11, 2, 9, 1)) == []
    assert book.items[0].active is False and book.items[0].last_run


def test_a_daily_booking_moves_to_tomorrow():
    book, _ = booked(repeat=DAILY)
    assert len(book.take_due(datetime(2026, 11, 2, 9, 0))) == 1
    assert book.items[0].when == "2026-11-03T09:00" and book.items[0].active


def test_a_weekly_booking_moves_a_week():
    book, _ = booked(repeat=WEEKLY)
    book.take_due(datetime(2026, 11, 2, 9, 0))
    assert book.items[0].when == "2026-11-09T09:00"


def test_a_one_time_booking_missed_while_closed_is_not_run_late():
    book, _ = booked()
    book.catch_up(datetime(2026, 11, 3, 10, 0))
    assert book.items[0].missed is True and book.items[0].active is False
    assert book.take_due(datetime(2026, 11, 3, 10, 0)) == []


def test_a_repeating_booking_missed_while_closed_waits_for_its_next_time():
    book, _ = booked(repeat=DAILY)
    book.catch_up(datetime(2026, 11, 5, 10, 0))
    assert book.items[0].when == "2026-11-06T09:00"
    assert book.items[0].missed is False
    assert book.take_due(datetime(2026, 11, 5, 10, 0)) == []


def test_a_paused_booking_does_not_run():
    book, item = booked(repeat=DAILY)
    book.set_active(item.id, False)
    assert book.take_due(datetime(2026, 11, 2, 9, 0)) == []


def test_starting_a_paused_booking_again_carries_on_from_its_next_time():
    book, item = booked(repeat=DAILY)
    book.set_active(item.id, False)
    book.set_active(item.id, True, now=datetime(2026, 11, 4, 10, 0))
    assert book.items[0].when == "2026-11-05T09:00"


def test_bookings_are_kept_when_the_app_closes(tmp_path):
    path = tmp_path / "reservations.json"
    booked(path, repeat=DAILY)
    again = Reservations(path)
    assert again.items[0].action == SORT and again.items[0].repeat == DAILY


def test_a_damaged_file_starts_empty(tmp_path):
    path = tmp_path / "reservations.json"
    path.write_text("not json", encoding="utf-8")
    assert Reservations(path).items == []


def test_removing_a_booking():
    book, item = booked()
    book.remove(item.id)
    assert book.items == []


@pytest.mark.parametrize("agent, action, text, when, words", [
    ("", SORT, "", "2020-01-01T09:00", "future"),
    ("", SORT, "", "", "date"),
    ("Grammar Fixer", RUN, "  ", "2026-11-02T09:00", "should do"),
    ("", TURN_ON, "", "2026-11-02T09:00", "agent"),
])
def test_a_booking_that_cant_work_says_why(agent, action, text, when, words):
    with pytest.raises(ReservationError, match=words):
        Reservations().add(agent, action, text, when, now=NOW)


def test_the_list_shows_what_is_coming_first():
    book = Reservations()
    book.add("", SORT, "", "2026-11-05T09:00", now=NOW)
    first = book.add("", SORT, "", "2026-11-03T09:00", now=NOW)
    done = book.add("", SORT, "", "2026-11-02T09:00", now=NOW)
    book.set_active(done.id, False)
    assert [item["id"] for item in book.listing()][0] == first.id
    assert book.listing()[-1]["id"] == done.id


def test_each_booking_runs_on_the_watching_thread_and_one_failure_stops_nothing(monkeypatch):
    import threading

    from concierge import reservations

    monkeypatch.setattr(reservations, "CHECK_SECONDS", 0.01)
    book = Reservations()
    long_ago = datetime(2019, 1, 1)  # so both are due by the real clock
    first = book.add("", SORT, "", "2020-01-01T09:00", now=long_ago)
    second = book.add("", SORT, "", "2020-01-01T09:00", now=long_ago)
    ran, finished = [], threading.Event()

    def run(item):
        ran.append(item.id)
        if len(ran) == 1:
            raise RuntimeError("this job failed")
        finished.set()

    monkeypatch.setattr(book, "catch_up", lambda: None)  # these are due, not missed
    book.start(run)
    assert finished.wait(2)
    book.stop()
    assert ran == [first.id, second.id]
