"""A plain chat message walks the whole way from send() to her answer, with her own
model and nothing picked in the menu. This is the path every message takes, and a
merge once broke it without any test noticing."""

import pytest

from concierge import elaina
from concierge.agents import store
from concierge.agents.router import Route
from concierge.conversations import ChatBook
from concierge.engine import ElainaEngine
from concierge.events import ElainaDone, ElainaText, Error


class Ollama:
    def __init__(self):
        self.asked = 0

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked += 1
        return iter(["Tokyo."])

    def capabilities(self, name):
        return ["completion"]

    def show(self, name):
        return {"system": "You are Elaina."}

    def models(self):
        return []

    def refresh(self, *args):
        pass


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(elaina, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    made = ElainaEngine(Ollama())
    made.book = ChatBook(None)
    made.chat = elaina.ElainaChat(made.ollama)
    from concierge.agents.builder import AgentBuilder
    from concierge.agents.planner import IdeaPlanner
    made.builder = AgentBuilder(made.ollama, "elaina", None, made.blueprints)
    made.planner = IdeaPlanner(made.ollama, "elaina", None, lambda: None, made.blueprints)
    return made


def test_a_plain_message_gets_her_answer_and_no_error(engine):
    events = list(engine.send("what's the capital of Japan?"))
    assert not [e for e in events if isinstance(e, Error)]
    assert "".join(e.text for e in events if isinstance(e, ElainaText)) == "Tokyo."
    done = next(e for e in events if isinstance(e, ElainaDone))
    assert done.where == "here" and done.saved == 0  # her own model, nothing to save from
    assert engine.ollama.asked == 1
    assert engine.chat.history[-1]["content"] == "Tokyo."


def test_shorter_and_more_detail_walk_the_same_path(engine):
    list(engine.send("what's the capital of Japan?"))
    for which in ("shorter", "more"):
        events = list(engine.follow_up(which))
        assert not [e for e in events if isinstance(e, Error)]
        assert any(isinstance(e, ElainaText) for e in events)
    assert engine.after_answer("Tokyo.")["follow_ups"] is True
