"""A plain chat message walks the whole way from send() to her answer, with her own
model and nothing picked in the menu. This is the path every message takes, and a
merge once broke it without any test noticing."""

import pytest

from concierge import elaina
from concierge.agents import store
from concierge.agents.router import Route
from concierge.conversations import ChatBook
from concierge.engine import ElainaEngine
from concierge.events import ElainaDone, ElainaText, Error, Thinking


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


class ThinkingOllama(Ollama):
    """A model that can think, and says when it was asked to."""

    def __init__(self, loaded=("elaina:latest",)):
        super().__init__()
        self.thought = 0
        self._loaded = list(loaded)

    def capabilities(self, name):
        return ["completion", "thinking"]

    def chat_parts(self, model, messages, think=None, options=None, keep_alive=None):
        self.thought += 1
        yield "thought", "Let me see."
        yield "text", "Tokyo."

    def loaded(self):
        return [{"name": name} for name in self._loaded]


@pytest.fixture
def thinking_engine(engine):
    engine.ollama = ThinkingOllama()
    engine.chat = elaina.ElainaChat(engine.ollama)
    return engine


def test_small_talk_is_answered_without_thinking_even_with_think_on(thinking_engine):
    """Her model thought to its limit over "how are you" and then wrote the answer a
    second time, so a greeting took longer than anything. Code skips the thinking."""
    own = thinking_engine.ollama
    list(thinking_engine.send("hey how are you doing tdy", think=True))
    assert own.thought == 0 and own.asked == 1
    list(thinking_engine.send("what's the capital of Japan?", think=True))
    assert own.thought == 1  # a real question still gets her thinking when asked


def test_she_says_when_her_model_has_to_load_first(thinking_engine):
    """The first message after the app opens loads her model, a few seconds with
    nothing on screen unless she says what's happening."""
    thinking_engine.ollama._loaded = []
    events = list(thinking_engine.send("hello"))
    assert any(isinstance(e, Thinking) and "Loading my model" in e.text for e in events)
    thinking_engine.ollama._loaded = ["elaina:latest"]
    events = list(thinking_engine.send("hello again"))
    assert not any(isinstance(e, Thinking) and "Loading my model" in e.text for e in events)


def test_startup_rebuilds_elaina_when_her_prompt_changed(tmp_path, monkeypatch):
    """A fix to her persona or the facts she gets is a new prompt. The app rebuilds
    her from the same base model at startup, so the fix reaches the user without
    running setup; an unchanged prompt is left alone."""
    from concierge import hardware
    from concierge.hardware import GPU, HardwareReport
    from concierge.agents import store

    class SetUpOllama(ThinkingOllama):
        def __init__(self):
            super().__init__()
            self.created = []

        def ensure_running(self):
            pass

        def has_model(self, name):
            return name in ("elaina", "qwen3.5:4b")

        def create(self, name, base, system, parameters=None):
            self.created.append((name, base, system))

        def unload(self, name):
            pass

    report = HardwareReport("windows", "11", "x86_64", "CPU", 8, 16, 32.0, 16.0, 200.0, "C:",
                            [GPU("Card", "nvidia", 16.0, 12.0, True, "test")])
    monkeypatch.setattr(hardware, "detect", lambda: report)
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(elaina, "data_dir", lambda: tmp_path)
    elaina.save_state({"base_model": "qwen3.5:4b", "prompt_hash": "from an older version"})
    own = SetUpOllama()
    made = ElainaEngine(own)
    list(made.startup())
    assert [(name, base) for name, base, _ in own.created] == [("elaina", "qwen3.5:4b")]
    assert "only when asked" in own.created[0][2]
    made.close()

    own.created.clear()
    list(ElainaEngine(own).startup())  # the saved hash now matches: nothing to rebuild
    assert own.created == []


def test_shorter_and_more_detail_walk_the_same_path(engine):
    list(engine.send("what's the capital of Japan?"))
    for which in ("shorter", "more"):
        events = list(engine.follow_up(which))
        assert not [e for e in events if isinstance(e, Error)]
        assert any(isinstance(e, ElainaText) for e in events)
    assert engine.after_answer("Tokyo.")["follow_ups"] is True
