import pytest

from concierge import auto, elaina, usage
from concierge.events import ElainaDone, ElainaText, Error, Thinking
from concierge.fake_engine import FakeEngine


def never_asked(text):
    raise AssertionError(f"the model was asked about a clear message: {text!r}")


@pytest.mark.parametrize("case", auto.load_cases(), ids=lambda c: c["text"][:40])
def test_every_example_is_placed_right_by_code_alone(case):
    # On the weakest computer, with no model to ask: the same answer on every computer.
    decision = auto.decide(case["text"], base_model="qwen3.5:4b", after=case.get("after", ""), ask_model=never_asked)
    assert decision.where == case["expect"]


def test_fifty_examples():
    cases = auto.load_cases()
    assert len(cases) == 50
    assert {c["expect"] for c in cases} == {auto.HERE, auto.CLOUD}


def test_a_bigger_model_keeps_more_here():
    essay = "help me write a cover letter for a junior data analyst job"
    assert auto.decide(essay, base_model="qwen3.5:4b").where == auto.CLOUD
    assert auto.decide(essay, base_model="qwen3:14b").where == auto.HERE
    explain = "explain the difference between TCP and UDP"
    assert auto.decide(explain, base_model="qwen3:8b").where == auto.HERE
    assert auto.decide(explain, base_model="qwen3:1.7b").where == auto.CLOUD
    # Code never stays here, however big her model is.
    assert auto.decide("write SQL for the top 5 customers", base_model="llama3:70b").where == auto.CLOUD


def test_unknown_model_size_counts_as_small():
    assert auto.strength("elaina") == auto.SMALL
    assert auto.strength("hf.co/someone/Model-12B-GGUF:Q4_K_M") == auto.MEDIUM


def test_a_plan_nearly_used_up_keeps_more_here_and_a_used_up_one_everything():
    plan = "plan a 5-day trip to Tokyo"
    assert auto.decide(plan, base_model="qwen3:8b").where == auto.CLOUD
    assert auto.decide(plan, base_model="qwen3:8b", plan_used=0.85).where == auto.HERE
    used_up = auto.decide("write a Python script", plan_used=0.99)
    assert used_up.where == auto.HERE and used_up.kind == "used_up"


def test_unclear_messages_ask_the_model_and_doubt_goes_to_the_plan():
    asked = []
    feelings = "I've been feeling stressed lately"
    assert auto.decide(feelings, ask_model=lambda t: asked.append(t) or "small_talk").where == auto.HERE
    assert asked == [feelings]
    assert auto.decide(feelings, ask_model=lambda t: "nonsense").where == auto.CLOUD
    assert auto.decide(feelings, ask_model=lambda t: 1 / 0).where == auto.CLOUD  # the model failing
    assert auto.decide(feelings).by == "unsure"


def test_a_long_document_goes_to_the_plan():
    assert auto.decide("what's this about?", attached_chars=20_000).where == auto.CLOUD


def test_the_model_form_only_allows_the_kinds():
    seen = {}

    class Model:
        def chat_json(self, model, messages, schema, think=None):
            seen.update(schema=schema, think=think)
            return {"kind": "code"}

    assert auto.model_form(Model(), "elaina")("hm") == "code"
    assert seen["schema"]["properties"]["kind"]["enum"] == list(auto.KINDS) and seen["think"] is False


def test_her_reasons_are_plain():
    line = auto.say(auto.Decision(auto.CLOUD, "code", "code"), "Claude Sonnet 5.5")
    assert line == "Auto: this is about code, so I'll ask Claude Sonnet 5.5."
    assert "save your tokens" in auto.say(auto.Decision(auto.HERE, "quick_fact", "code"), "GPT", plan=False)


def test_asking_again_is_counted():
    auto.record("quick_fact")
    auto.record("quick_fact", asked_again=True)
    assert auto.counts()["quick_fact"] == {"here": 1, "asked_again": 1}


# ------------------------------------------------------------ the model menu


def practice_with_auto():
    engine = FakeEngine(delay=0)
    engine.menu.accounts.sign_in("claude_code")
    engine.menu.pick("claude_code", "practice-1")  # remembered as what Auto asks
    engine.menu.pick("auto", "")
    return engine


def test_auto_in_the_menu_sends_hard_questions_to_the_last_plan_model_picked():
    engine = practice_with_auto()
    chosen = engine.menu.chosen()
    assert chosen["auto"] and chosen["name"] == "Auto" and chosen["cloud"]["name"] == "Claude (practice)"
    assert engine.menu.info()["auto"]["cloud"] == "Claude (practice)"


def test_auto_without_any_plan_or_key_is_her_own_model():
    engine = FakeEngine(delay=0)
    engine.menu.pick("auto", "")
    assert engine.menu.chosen() is None and engine.menu.info()["auto"]["cloud"] == ""


def test_plan_used_reads_the_meter():
    engine = practice_with_auto()
    usage.record_limits("claude_code", [{"id": "five_hour", "used": 0.4, "resets_at": 4_000_000_000}])
    assert engine.menu.plan_used("claude_code") == 0.4 and engine.menu.plan_used("anthropic") == 0


# ------------------------------------------------------------ in the chat


def test_practice_chat_says_where_each_answer_comes_from():
    engine = practice_with_auto()
    small = list(engine.send("thanks!"))
    assert any(isinstance(e, Thinking) and e.text.startswith("Auto: just chatting") for e in small)
    done = next(e for e in small if isinstance(e, ElainaDone))
    assert done.by and done.instead == "Claude (practice)"

    hard = list(engine.send("write a Python script that sorts my photos"))
    done = next(e for e in hard if isinstance(e, ElainaDone))
    assert done.by == "Claude (practice)" and done.instead == ""

    again = list(engine.ask_again())
    assert next(e for e in again if isinstance(e, ElainaDone)).by == "Claude (practice)"


class Talker:
    """A plan's model or her own, answering or refusing."""

    def __init__(self, words="", refuse=None):
        self.words, self.refuse, self.asked = words, refuse, []

    def chat(self, model, messages, think=None, keep_alive=None):
        self.asked.append(messages[-1]["content"])
        if self.refuse:
            raise self.refuse
        yield self.words

    def capabilities(self, name):
        return ["completion"]


def real_engine_with_auto(monkeypatch, plan_talker):
    from concierge.engine import ElainaEngine

    own = Talker("From this computer.")
    engine = ElainaEngine.__new__(ElainaEngine)
    engine.ollama = own
    engine.chat = elaina.ElainaChat.__new__(elaina.ElainaChat)
    engine.chat.ollama, engine.chat.model, engine.chat.talker = own, "elaina", own
    engine.chat.history, engine.chat._context, engine.chat._images, engine.chat.about = [], "", [], ""
    engine.chat.think = None
    engine.chat.kind, engine.chat._asked = "", ""  # how to answer (voice.py) goes with each question
    engine.auto_cloud, engine.auto_last, engine.auto_kind = plan_talker, "", ""
    engine.talker_name = "Claude Sonnet 5.5"

    class Menu:
        def chosen(self):
            return {"auto": True, "cloud": {"provider": "claude_code", "name": "Claude Sonnet 5.5"}}

        def plan_used(self, provider):
            windows = usage.summary().get(provider, {}).get("limits", [])
            return max((w["used"] for w in windows), default=0.0)

    class Book:
        def record(self, text, events):
            yield from events

    engine.menu, engine.book = Menu(), Book()
    engine._full_lists = lambda events: events
    monkeypatch.setattr(elaina, "load_state", lambda: {"base_model": "qwen3.5:4b"})
    return engine, own


def test_the_real_engine_keeps_small_things_here_and_restores_her_model(monkeypatch):
    plan = Talker("From your plan.")
    engine, own = real_engine_with_auto(monkeypatch, plan)
    usage.record_tokens("claude_code", "m", 29_000, 10)  # what Claude Code reads on top, measured
    own.last_tokens = (400, 20)
    events = list(engine._reply("what's the capital of Japan?", False))
    assert "".join(e.text for e in events if isinstance(e, ElainaText)) == "From this computer."
    assert events[-1] == ElainaDone(by="Qwen 3.5 4B", instead="Claude Sonnet 5.5", where="here", saved=29_020)
    assert plan.asked == [] and usage.summary()["claude_code"]["today"]["saved"] == 29_020

    usage.record_limits("claude_code", [{"id": "five_hour", "used": 0.6, "resets_at": 4_000_000_000}])
    events = list(engine._reply("write a Python script that renames photos", False))
    assert "".join(e.text for e in events if isinstance(e, ElainaText)) == "From your plan."
    assert events[-1] == ElainaDone(by="Claude Sonnet 5.5", where="cloud", plan_used=0.6)
    assert engine.chat.talker is own  # agents and the router stay on her model


def test_a_reopened_chat_keeps_who_answered():
    from concierge.conversations import ChatBook

    book = ChatBook(None)
    answer = [ElainaText("Tokyo."), ElainaDone(by="Qwen 3.5 4B", where="here", saved=29_020)]
    list(book.record("capital of Japan?", iter(answer)))
    list(book.record("a script please", iter([ElainaText("Here."), ElainaDone(by="Claude", where="cloud", plan_used=0.7)])))
    items = book.transcript().items
    assert (items[1].by, items[1].where, items[1].saved) == ("Qwen 3.5 4B", "here", 29_020)
    assert (items[3].where, items[3].plan_used) == ("cloud", 0.7)
    assert items[0].where == ""  # the user's own messages have no dot


def test_practice_answers_carry_their_dot():
    engine = practice_with_auto()
    here = next(e for e in engine.send("thanks!") if isinstance(e, ElainaDone))
    cloud = next(e for e in engine.send("write SQL for my orders") if isinstance(e, ElainaDone))
    assert here.where == "here" and here.saved > 0
    assert cloud.where == "cloud" and 0 < cloud.plan_used <= 1


def test_when_the_plan_refuses_she_answers_herself(monkeypatch):
    from concierge.cloud import CloudError

    engine, own = real_engine_with_auto(monkeypatch, Talker(refuse=CloudError("you're signed out")))
    events = list(engine._reply("write a Python script that renames photos", False))
    assert any(isinstance(e, Thinking) and "couldn't answer (you're signed out)" in e.text for e in events)
    assert "".join(e.text for e in events if isinstance(e, ElainaText)) == "From this computer."
    assert len(engine.chat.history) == 2  # the question once, and her answer


def test_ask_again_replaces_her_answer_with_the_plans(monkeypatch):
    plan = Talker("From your plan.")
    engine, _ = real_engine_with_auto(monkeypatch, plan)
    list(engine._reply("what's the capital of Japan?", False))
    events = list(engine.ask_again())
    # The question goes with the note on how to answer (voice.guide), so only its start is checked.
    assert len(plan.asked) == 1 and plan.asked[0].startswith("what's the capital of Japan?")
    assert engine.chat.history[-1] == {"role": "assistant", "content": "From your plan."}
    assert len(engine.chat.history) == 2
    assert auto.counts()["quick_fact"]["asked_again"] == 1
    assert not any(isinstance(e, Error) for e in events)
