from concierge import events
from concierge.engine import ElainaEngine
from concierge.events import (
    AgentCard,
    AgentList,
    ElainaDone,
    ElainaText,
    Error,
    Progress,
    Question,
    Result,
    SystemInfo,
)
from concierge.fake_engine import FakeEngine


def types(evts):
    return [type(e) for e in evts]


def test_startup_sends_system_info_then_agents():
    assert types(FakeEngine(delay=0).startup()) == [SystemInfo, AgentList]


def test_chat_streams_then_finishes():
    evts = list(FakeEngine(delay=0).send("hello"))
    assert all(isinstance(e, ElainaText) for e in evts[:-1])
    assert isinstance(evts[-1], ElainaDone)


def test_full_agent_setup_flow():
    engine = FakeEngine(delay=0)
    evts = list(engine.send("make an agent for my contracts"))
    assert isinstance(evts[-1], Question) and evts[-1].id == "folder"

    evts = list(engine.send("Desktop/Work"))
    question = evts[-1]
    assert isinstance(question, Question) and question.choices

    (card,) = engine.choose(question.id, "PDF only")
    assert isinstance(card, AgentCard)
    assert "Desktop/Work" in card.reads[0]

    evts = list(engine.choose(card.id, "Create it"))
    assert Progress in types(evts) and Result in types(evts)
    assert evts[-1] == AgentList(["Contracts helper"])


def test_cancel_and_unknown_choice():
    engine = FakeEngine(delay=0)
    list(engine.send("make an agent"))
    list(engine.send("Documents"))
    card = next(engine.choose("file_types", "Everything"))
    assert ElainaDone in types(engine.choose(card.id, "Cancel"))
    assert types(engine.choose("nope", "x")) == [Error]


def test_running_an_agent_returns_sources():
    evts = list(FakeEngine(delay=0).send("ask contracts helper who signed"))
    result = next(e for e in evts if isinstance(e, Result))
    assert result.sources


def test_events_become_json_ready_dicts():
    card = AgentCard("card", "X", "Ask my documents", ["a"], ["b"], ["c"], "model")
    data = events.to_dict(card)
    assert data["type"] == "AgentCard"
    assert data["actions"] == ["Create it", "Change something", "Cancel"]


def test_both_engines_offer_the_same_methods():
    for name in ("startup", "send", "choose", "reset", "close"):
        assert callable(getattr(FakeEngine, name))
        assert callable(getattr(ElainaEngine, name))
