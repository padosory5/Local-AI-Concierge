import time

from concierge import activity
from concierge.agents import store
from concierge.events import AgentList
from concierge.engine import NoirEngine
from concierge.fake_engine import FakeEngine
from concierge.quick.tidy import TidyWatch
from concierge.ui.window import Overlay, TodayBridge


def test_the_week_counts_each_kind_of_job():
    activity.record(activity.EXPLAINED)
    activity.record(activity.EXPLAINED)
    activity.record(activity.SORTED, 46)
    assert activity.this_week() == {"explained": 2, "sorted": 46}


def test_only_the_last_seven_days_count_and_a_month_is_kept():
    now = time.time()
    activity.record(activity.POLISHED, now=now - 10 * 86400)
    activity.record(activity.POLISHED, now=now - 40 * 86400)
    activity.record(activity.POLISHED, now=now)
    assert activity.this_week(now) == {"polished": 1}
    assert len(activity._read()) == 2  # older than a month is dropped


def test_the_log_never_holds_words():
    activity.record(activity.ANSWERED)
    assert set(activity._read()[0]) == {"when", "kind", "count"}


class LocalOnly:
    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        return iter(["Could you send the report?"])

    def refresh(self, name, keep_alive):
        pass

    def capabilities(self, name):
        return []


class Thinker(LocalOnly):
    """A model that thinks unless told not to, like Noir's own."""

    def __init__(self):
        self.asked = []

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked.append(think)
        return iter(["A happy accident."])

    def capabilities(self, name):
        return ["completion", "thinking"]


def test_a_spot_job_is_counted_by_what_it_did(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    engine = NoirEngine(LocalOnly())
    engine.spot_run("polish", "hey send report", "")
    engine.spot_run("translate:Korean", "hello", "")
    assert activity.this_week() == {"polished": 1, "translated": 1}


def test_a_switch_on_help_me_adds_the_agent_quietly(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    events = list(NoirEngine(LocalOnly()).switch_agent("Grammar Fixer", True))
    assert len(events) == 1 and isinstance(events[0], AgentList)  # nothing said in the chat
    assert "Grammar Fixer" in events[0].agents and store.find_agent("Grammar Fixer")


def test_switching_off_something_never_added_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    list(NoirEngine(LocalOnly()).switch_agent("Grammar Fixer", False))
    assert store.find_agent("Grammar Fixer") is None


def test_the_speed_test_times_real_jobs_on_this_computer(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    result = NoirEngine(LocalOnly()).measure()
    assert len(result["results"]) == 3 and all(job["seconds"] >= 0 for job in result["results"])
    assert result["device"]


def test_the_speed_test_never_lets_the_model_think_first(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    model = Thinker()
    engine = NoirEngine(model)  # measured before startup, as the first-run page does
    engine.measure()
    engine.spot_run("explain", "serendipity", "")
    assert model.asked == [False] * 4


def test_the_practice_app_switches_and_measures_without_a_model():
    fake = FakeEngine(delay=0)
    events = list(fake.switch_agent("Highlight Explainer", True))
    assert "Highlight Explainer" in events[-1].active
    assert fake.measure()["results"] and fake.activity()


def test_the_first_run_choice_is_kept_and_the_practice_run_keeps_nothing(tmp_path, monkeypatch):
    from concierge.ui import window

    monkeypatch.setattr(window, "data_dir", lambda: tmp_path)
    real = Overlay(FakeEngine(delay=0), TidyWatch(tmp_path, tmp_path / "sorts.json", quiet=lambda: False))
    bridge = TodayBridge(real.hub, real)
    assert bridge.welcome()["welcomed"] is False and bridge.welcome()["spot"] is True
    bridge.set_welcomed("student")
    again = Overlay(FakeEngine(delay=0), TidyWatch(tmp_path, tmp_path / "sorts.json", quiet=lambda: False))
    assert TodayBridge(again.hub, again).welcome()["role"] == "student"
    practice = Overlay(FakeEngine(delay=0), TidyWatch(practice=True))
    practice.remember(welcomed=True)
    assert not (tmp_path / "window.json").read_text().count("practice")
    assert practice._settings_path is None
