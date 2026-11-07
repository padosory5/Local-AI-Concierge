import pytest

from concierge import noir
from concierge.agents import store
from concierge.agents.recipe import BUBBLE, CLIPBOARD, CUSTOM, IN_CHAT, WHILE_ON
from concierge.agents.router import wants_change
from concierge.conversations import ChatBook
from concierge.engine import NoirEngine
from concierge.events import AgentList, NoirText, Question, Thinking
from concierge.quick.agents import QuickAgents


class FakeOllama:
    def capabilities(self, name):
        return ["completion"]

    def chat(self, *args, **kwargs):
        yield "ok"

    def refresh(self, *args):
        pass


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    e = NoirEngine(FakeOllama())
    e.book = ChatBook(None)
    e.chat = noir.NoirChat(FakeOllama())
    e.quick = QuickAgents(FakeOllama(), "noir", None,
                          lambda *a: type("W", (), {"start": lambda s: None, "stop": lambda s: None})(),
                          lambda: type("B", (), {"close": lambda s: None, "pressed": lambda s, x, y: None})())
    from concierge.agents.builder import AgentBuilder
    from concierge.agents.planner import IdeaPlanner
    e.builder = AgentBuilder(FakeOllama(), "noir", None, e.blueprints)
    e.planner = IdeaPlanner(FakeOllama(), "noir", None, lambda: None, e.blueprints)
    return e


def broken_agent():
    """The user's agent after the conversation that went wrong, as it was saved."""
    store.save(store.Agent("Highlight Translator", CUSTOM, {
        "instruction": "When I highlight a sentence it should display it in Korean above",
        "when": IN_CHAT, "show": BUBBLE, "keep": "Until you unhighlight the text",
        "name": "Highlight Translator"}))


def test_a_problem_report_gets_a_diagnosis_and_a_fix(engine):
    broken_agent()
    events = list(engine.send("Noir is not showing any translated words"))
    step = next(e for e in events if isinstance(e, Thinking))
    assert "only when you ask in the chat" in step.text and "instead of a clear job" in step.text
    question = events[-1]
    assert isinstance(question, Question) and question.choices == ["Fix it", "Leave it"]
    assert "switch it on" in question.text

    events = list(engine.choose(question.id, "Fix it"))
    agent = store.find_agent("Highlight Translator")
    assert agent.slots["when"] == WHILE_ON
    assert agent.slots["instruction"] == "Translate the text into Korean."
    assert engine.quick.is_on("Highlight Translator")
    assert isinstance(events[-1], AgentList) and events[-1].active == ["Highlight Translator"]


def test_copying_instead_of_showing_is_found(engine):
    store.save(store.Agent("Korean translator", CUSTOM, {
        "instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": CLIPBOARD,
        "name": "Korean translator"}))
    question = list(engine.send("the translator doesn't show anything"))[-1]
    assert "copies the result to the clipboard instead of showing it" in question.text
    list(engine.choose(question.id, "Fix it"))
    assert store.find_agent("Korean translator").slots["show"] == BUBBLE


def test_switched_off_is_the_first_thing_to_check(engine):
    store.save(store.Agent("Korean translator", CUSTOM, {
        "instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE,
        "name": "Korean translator"}))
    question = list(engine.send("nothing happens when I highlight"))[-1]
    assert question.text == "Korean translator is switched off right now. Switch it on?"
    list(engine.choose(question.id, "Switch it on"))
    assert engine.quick.is_on("Korean translator")


def test_all_fine_explains_where_it_works(engine):
    agent = store.Agent("Korean translator", CUSTOM, {
        "instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE,
        "name": "Korean translator"})
    store.save(agent)
    engine.quick.switch(agent, True)
    events = list(engine.send("the translator is not working"))
    text = "".join(e.text for e in events if isinstance(e, NoirText))
    assert "set up right" in text and "Chrome" in text


def test_leave_it_changes_nothing(engine):
    broken_agent()
    question = list(engine.send("Noir is not showing any translated words"))[-1]
    list(engine.choose(question.id, "Leave it"))
    assert store.find_agent("Highlight Translator").slots["when"] == IN_CHAT


def test_wanting_the_agent_to_do_something_is_a_change():
    agent = store.Agent("Highlight Translator", CUSTOM, {"instruction": "Translate the text into Korean."})
    assert wants_change("I want to fix the agent. I want the agent to translate the word I highlight", agent)
    assert not wants_change("Highlight Translator: I want to go home", agent)
