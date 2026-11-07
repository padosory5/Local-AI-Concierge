import pytest

from concierge import noir
from concierge.agents import store
from concierge.agents.builder import AgentBuilder
from concierge.agents.planner import IdeaPlanner
from concierge.agents.recipe import CUSTOM, IN_CHAT, WHILE_ON, is_switchable
from concierge.agents.router import refers_to, wants_change
from concierge.agents.starters import asks_for, load_starters
from concierge.conversations import ChatBook
from concierge.engine import NoirEngine
from concierge.events import AgentList, NoirText
from concierge.fake_engine import FakeEngine
from concierge.quick.agents import QuickAgents


class NoModel:
    """Adding a starter must never need the model."""

    def capabilities(self, name):
        return ["completion"]

    def chat(self, *args, **kwargs):
        raise AssertionError("the model should not be asked")

    def chat_json(self, *args, **kwargs):
        raise AssertionError("the model should not be asked")

    def refresh(self, *args):
        pass


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    e = NoirEngine(NoModel())
    e.book = ChatBook(None)
    e.chat = noir.NoirChat(NoModel())
    e.quick = QuickAgents(NoModel(), "noir", None,
                          lambda *a: type("W", (), {"start": lambda s: None, "stop": lambda s: None})(),
                          lambda: type("B", (), {"close": lambda s: None, "pressed": lambda s, x, y: None})())
    e.builder = AgentBuilder(NoModel(), "noir", None, e.blueprints)
    e.planner = IdeaPlanner(NoModel(), "noir", None, lambda: None, e.blueprints)
    return e


def said(events):
    return "".join(e.text for e in events if isinstance(e, NoirText))


def last_list(events):
    return [e for e in events if isinstance(e, AgentList)][-1]


@pytest.mark.parametrize("text, name", [
    ("turn on the highlight explainer", "Highlight Explainer"),
    ("Activate Highlight Explainer", "Highlight Explainer"),
    ("install Grammar Fixer", "Grammar Fixer"),
    ("add the summarizer", "Quick Summarizer"),
])
def test_short_requests_name_a_starter(text, name):
    assert asks_for(text).name == name


@pytest.mark.parametrize("text", [
    "what does an explainer video cost?",
    "uninstall Grammar Fixer",
    "please turn on the explainer because I would really like to use it today",
])
def test_other_messages_do_not(text):
    assert asks_for(text) is None


def test_saying_turn_on_adds_it_and_switches_it_on(engine):
    events = list(engine.send("turn on the highlight explainer"))
    agent = store.find_agent("Highlight Explainer")
    assert agent.blueprint == CUSTOM and agent.slots["when"] == WHILE_ON
    assert is_switchable(agent, engine.blueprints)
    assert last_list(events).active == ["Highlight Explainer"]
    assert "is on" in said(events)


def test_saying_install_adds_it_but_leaves_it_off(engine):
    events = list(engine.send("install Highlight Explainer"))
    assert last_list(events).active == []
    assert 'turn on Highlight Explainer' in said(events)


def test_a_chat_starter_says_how_to_use_it(engine):
    events = list(engine.send("install Grammar Fixer"))
    assert store.find_agent("Grammar Fixer").slots["when"] == IN_CHAT
    assert "Grammar Fixer: your text here" in said(events)
    assert last_list(events).switchable == []


def test_adding_again_keeps_what_the_user_changed(engine):
    list(engine.send("install Grammar Fixer"))
    agent = store.find_agent("Grammar Fixer")
    agent.slots["instruction"] = "Fix it, but in British English."
    store.save(agent)
    list(engine.send("install Grammar Fixer"))
    assert store.find_agent("Grammar Fixer").slots["instruction"] == "Fix it, but in British English."


def test_turning_off_a_started_agent_works_like_any_other(engine):
    list(engine.send("turn on the highlight explainer"))
    events = list(engine.send("turn off the highlight explainer"))
    assert last_list(events).active == []


def test_the_create_form_always_means_a_new_agent(engine):
    # Its words can sound like a change to a similar agent the user has.
    list(engine.send("install Highlight Explainer"))
    agents = store.list_agents()
    text = ("Make a new agent: Explain hard words I highlight in simple Korean. It should work on "
            "text I highlight. Show the result in a bubble above the text.")
    assert refers_to(text, agents, engine.blueprints) is not None
    assert not wants_change(text, agents[0])


def test_every_starter_is_a_whole_agent():
    for starter in load_starters():
        assert starter.instruction and starter.words and starter.when in (WHILE_ON, IN_CHAT)


def test_the_fake_engine_adds_them_too():
    engine = FakeEngine(delay=0)
    events = list(engine.send("turn on the highlight explainer"))
    agents = last_list(events)
    assert "Highlight Explainer" in agents.agents and agents.active == ["Highlight Explainer"]
    assert "Grammar Fixer" not in last_list(engine.send("install Grammar Fixer")).switchable
