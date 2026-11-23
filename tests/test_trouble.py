"""Trouble with a helper ("it's not showing anything"): code looks at the mechanics, which
are the same whatever a helper is for, and says what it finds, with a fix to click where
there is one. What a helper does with a text is its rule, and no code reads a rule to
judge it: when the mechanics are in order, the report opens the conversation in which a
helper is changed by talking, or, with no model to hold one, says what was checked and
how the rule is changed."""

import re
import sys
from pathlib import Path

import pytest

from concierge import noir
from concierge.agents import builder as builder_mod
from concierge.agents import designer as designer_mod
from concierge.agents import parts, store
from concierge.agents.designer import DESIGN, STILL_ASKING, Designer, DesignModel
from concierge.agents.recipe import BUBBLE, CLIPBOARD, CUSTOM, IN_CHAT, WHILE_ON
from concierge.agents.router import wants_change
from concierge.conversations import ChatBook
from concierge.engine import FIX_AGENT, TROUBLE, NoirEngine, _fix_words
from concierge.events import AgentCard, AgentList, NoirText, Question, Thinking
from concierge.ollama import OllamaError
from concierge.quick.agents import ANSWERED, BOTH, LEFT_OUT, NO_MODEL, NOTHING_BACK, QuickAgents

NAME = "Word explainer"
RULE = "Explain this word in simple words, in one sentence."


class FakeOllama:
    reached = True

    def capabilities(self, name):
        return ["completion"]

    def chat(self, *args, **kwargs):
        yield "ok"

    def refresh(self, *args):
        pass

    def loaded(self):
        if not self.reached:
            raise OllamaError("no Ollama")
        return [{"name": "noir:latest"}]


class Asks:
    """A design model that only asks one thing back, and keeps what it was given to read."""

    def __init__(self):
        self.turns = []

    def fill(self, note, turns, schema):
        self.turns.append([dict(turn) for turn in turns])
        filled = {}
        for key, spec in schema["properties"].items():
            choices = spec.get("enum")
            filled[key] = {"place": "", "name": ""} if spec.get("type") == "object" else "" if not choices else (
                "" if "" in choices else choices[0])
        return {**filled, "status": STILL_ASKING, "say": "What does it get wrong?"}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(sys, "platform", "win32")  # highlights can be read
    # Nothing of the real computer: a helper worked out by talking is told what the places people name hold.
    for place in parts.PLACE_NAMES:
        (tmp_path / place).mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for module in (designer_mod, builder_mod, parts):
        monkeypatch.setattr(module, "known_folder", lambda name, home=None: tmp_path / name)
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


def designing(engine) -> Asks:
    """Give the engine a model that can work a helper out by talking; returns it."""
    asks = Asks()
    model = DesignModel(asks.fill, "Test model", here=True)
    engine.designer = Designer(FakeOllama(), "noir", None, lambda agent: [], lambda: model, lambda: "Small model")
    return asks


def highlighter(engine, on=True, name=NAME, **slots) -> store.Agent:
    """A saved card that works on highlights and shows its result, switched on unless said otherwise."""
    agent = store.Agent(name, CUSTOM, {"instruction": RULE, "when": WHILE_ON, "then": parts.SHOW, "show": BUBBLE,
                                       "keep": "Until you unhighlight the text", "skip_language": "", "name": name,
                                       **slots})
    store.save(agent)
    if on:
        engine.quick.switch(agent, True)
    return agent


def said(events) -> str:
    return " ".join(e.text for e in events if isinstance(e, (NoirText, Question)))


def broken_agent():
    """The user's agent after the conversation that went wrong, as it was saved."""
    store.save(store.Agent("Highlight Translator", CUSTOM, {
        "instruction": "When I highlight a sentence it should display it in Korean above",
        "when": IN_CHAT, "show": BUBBLE, "keep": "Until you unhighlight the text",
        "name": "Highlight Translator"}))


# ------------------------------------------------------------ the mechanics, with a fix to click


def test_a_problem_report_gets_a_diagnosis_and_a_fix(engine):
    broken_agent()
    events = list(engine.send("Noir is not showing any translated words"))
    step = next(e for e in events if isinstance(e, Thinking))
    assert "only when you ask in the chat" in step.text
    question = events[-1]
    assert isinstance(question, Question) and question.choices == ["Fix it", "Leave it"]
    assert question.text == ("I found why: it's set to work only when you ask in the chat, so it ignores highlights. "
                             "Should I make it work on highlights, and switch it on?")

    events = list(engine.choose(question.id, "Fix it"))
    agent = store.find_agent("Highlight Translator")
    assert agent.slots["when"] == WHILE_ON
    assert engine.quick.is_on("Highlight Translator")
    assert isinstance(events[-1], AgentList) and events[-1].active == ["Highlight Translator"]
    # It is a card that works on highlights now, and says everything such a card can say.
    assert agent.slots["skip_language"] == ""


def test_code_fixes_how_a_helper_is_set_up_and_never_its_rule(engine):
    """This rule says when and where instead of what to do, and code used to write it again
    as "Translate the text into Korean." for a helper it took for a translator. No kind of
    helper is known any more: the mechanics are fixed, the rule is the user's to change."""
    broken_agent()
    step = next(e for e in engine.send("Noir is not showing any translated words") if isinstance(e, Thinking))
    assert "instead of a clear job" not in step.text and "language" not in step.text
    list(engine.choose(FIX_AGENT, "Fix it"))
    assert store.find_agent("Highlight Translator").slots["instruction"] == (
        "When I highlight a sentence it should display it in Korean above")
    assert _fix_words({"when": WHILE_ON, "show": BUBBLE, "instruction": "x"}) == [
        "make it work on highlights", "show the result in a bubble above the text"]


def test_no_question_about_a_language_is_ever_asked(engine):
    store.save(store.Agent("Highlight Translator", CUSTOM, {
        "instruction": "Translate the highlighted text.", "when": WHILE_ON, "show": BUBBLE, "name": "Highlight Translator"}))
    question = list(engine.send("the translator doesn't show anything"))[-1]
    assert question.text == "Highlight Translator is switched off right now. Switch it on?"
    assert question.choices == ["Switch it on", "Leave it"]
    # And a language typed as an answer rewrites nothing.
    list(engine.choose(question.id, "Korean"))
    assert store.find_agent("Highlight Translator").slots["instruction"] == "Translate the highlighted text."


def test_copying_instead_of_showing_is_found(engine):
    highlighter(engine, on=False, show=CLIPBOARD)
    question = list(engine.send("the explainer doesn't show anything"))[-1]
    assert "copies the result to the clipboard instead of showing it" in question.text
    list(engine.choose(question.id, "Fix it"))
    assert store.find_agent(NAME).slots["show"] == BUBBLE and store.find_agent(NAME).slots["instruction"] == RULE


def test_switched_off_is_the_first_thing_to_check(engine):
    highlighter(engine, on=False)
    question = list(engine.send("nothing happens when I highlight"))[-1]
    assert question.text == f"{NAME} is switched off right now. Switch it on?"
    list(engine.choose(question.id, "Switch it on"))
    assert engine.quick.is_on(NAME)


def test_leave_it_changes_nothing(engine):
    broken_agent()
    question = list(engine.send("Noir is not showing any translated words"))[-1]
    list(engine.choose(question.id, "Leave it"))
    assert store.find_agent("Highlight Translator").slots["when"] == IN_CHAT


def test_highlights_can_only_be_read_on_windows_and_that_is_said(engine):
    highlighter(engine, on=False)
    engine.quick = None  # as on a Mac
    events = list(engine.send("the explainer is not working"))
    assert said(events) == (f"{NAME} works on text you highlight, which I can read on Windows only for now, so it "
                            "can't work on this computer.")
    assert engine.fixing is None  # nothing is offered to be switched on that could never work


def test_a_helper_asked_in_the_chat_is_not_made_to_work_on_highlights_where_they_cannot_be_read(engine):
    store.save(store.Agent("Speller", CUSTOM, {"instruction": "Fix the spelling.", "when": IN_CHAT, "name": "Speller"}))
    engine.quick = None
    text = said(engine.send("the speller is not working"))
    assert 'it works when it is asked in the chat, by a message that starts with "Speller:"' in text
    assert 'Its rule is: "Fix the spelling."' in text and 'say "change Speller"' in text
    assert store.find_agent("Speller").slots["when"] == IN_CHAT and engine.fixing is None


def test_a_helper_that_answers_from_documents_is_told_how_it_is_asked(engine, tmp_path):
    store.save(store.Agent("Manuals", parts.DOCUMENTS_QA, {"folder": str(tmp_path), "name": "Manuals"}))
    text = said(engine.send("Manuals is not working"))
    assert text.startswith("Manuals only answers when you ask it in the chat.") and '"Manuals: your text here"' in text
    assert "highlight" not in text and "set up right" not in text


# ------------------------------------------------------------ switched on and set up right


def test_all_fine_explains_where_it_works(engine):
    highlighter(engine)
    text = said(engine.send("the explainer is not working"))
    assert "set up right" in text and "Chrome" in text
    assert "no highlighted text has reached it since it was switched on" in text


def test_the_model_that_cannot_be_reached_is_said(engine):
    highlighter(engine)
    engine.ollama.reached = False
    text = said(engine.send("the explainer is not working"))
    assert "I can't reach Ollama, the program that runs my model" in text and "Chrome" not in text
    # It can be reached again, but couldn't be at the last highlight: that was why.
    engine.ollama.reached = True
    engine.quick.last[NAME] = NO_MODEL
    text = said(engine.send("the explainer is not working"))
    assert "The last time you highlighted something I couldn't reach Ollama" in text
    assert "I can reach it now: highlight the text once more." in text


def test_text_the_card_leaves_out_is_why_nothing_was_shown(engine):
    highlighter(engine, skip_language="Korean")
    engine.quick.last[NAME] = LEFT_OUT
    text = said(engine.send("the explainer is not showing anything"))
    assert ("The last text you highlighted is one it leaves out: text that is already in Korean, or that has no "
            "letters in it. So nothing was shown for it.") in text
    assert "change" not in text  # nobody here could take the setting off by talking
    designing(engine)
    engine.quick.last[NAME] = LEFT_OUT
    text = said(engine.send("the explainer is not showing anything"))
    assert f'If it should work on such text too, say "change {NAME}" and tell me.' in text
    assert not engine.designer.active  # said, and left to them


# ------------------------------------------------------------ nothing mechanical is wrong


def test_with_nothing_mechanical_wrong_the_helper_is_revised_by_talking(engine):
    asks = designing(engine)
    agent = highlighter(engine)
    engine.quick.last[NAME] = ANSWERED
    events = list(engine.send("the explainer is not working right"))
    step = next(e for e in events if isinstance(e, Thinking))
    assert step.text == (f"Checked {NAME}: it is switched on, it shows its result in a bubble above the text, and it "
                         "gave a result for the last text that was highlighted. So how it is set up isn't the trouble. "
                         "What it does with the text is its rule, and that we can put right by talking.")
    question = events[-1]
    assert isinstance(question, Question) and question.id == DESIGN and question.text == "What does it get wrong?"
    # The conversation is the one in which a helper they have is changed, about this helper,
    # and it starts from their words with what code checked.
    sketch = engine.designer.sketch
    assert engine.designer.active and sketch.editing and sketch.replaces == NAME
    assert sketch.slots["instruction"] == RULE
    first = asks.turns[0][0]
    assert first["role"] == "user" and first["content"].startswith("the explainer is not working right\n")
    assert "Checked by the app just now: it is switched on" in first["content"]
    assert "How it is set up is not the trouble." in first["content"]
    # A model reads that as the user's turn, so nothing in it says "you" or "I".
    assert not re.search(r"\b(you|your|I)\b", first["content"].split("\n", 1)[1])
    # Nothing is changed by the report itself: only the card's button saves anything.
    assert store.find_agent(NAME).slots == agent.slots and engine.quick.is_on(NAME)
    assert not any(isinstance(e, AgentCard) for e in events)


def test_what_was_checked_says_how_the_card_shows_its_result_and_what_came_back(engine):
    designing(engine)
    highlighter(engine, show=BOTH)
    engine.quick.last[NAME] = NOTHING_BACK
    step = next(e for e in engine.send("the explainer is not working") if isinstance(e, Thinking))
    assert "it shows its result above the text and copies it" in step.text
    assert "the built-in model gave nothing back for the last text that was highlighted" in step.text


def test_without_a_model_to_talk_it_through_what_was_checked_is_said_and_how_the_rule_is_changed(engine):
    highlighter(engine)
    engine.quick.last[NAME] = ANSWERED
    events = list(engine.send("the explainer is not working right"))
    assert said(events) == (
        f"I checked {NAME}: it is switched on, it shows its result in a bubble above the text, and it gave a result "
        f"for the last text that was highlighted. So how it is set up isn't the trouble. Its rule is: \"{RULE}\" If that "
        f"isn't what it should do, say \"change {NAME}\" and tell me what it should do instead, and I'll change its "
        "rule.")
    assert engine.fixing is None and not engine.builder.active


# ------------------------------------------------------------ what counts as trouble, and as a change


def test_trouble_is_told_by_what_goes_wrong_never_by_what_the_helper_is_for():
    for text in ("it's not showing anything", "the explainer doesn't work", "nothing happens when I highlight",
                 "my helper is broken", "안 나와"):
        assert TROUBLE.search(text), text
    # A word for what one helper does is no word for trouble.
    assert not TROUBLE.search("it doesn't translate into Japanese")
    assert "translat" not in TROUBLE.pattern


def test_wanting_the_agent_to_do_something_is_a_change():
    agent = store.Agent("Highlight Translator", CUSTOM, {"instruction": "Translate the text into Korean."})
    assert wants_change("I want to fix the agent. I want the agent to translate the word I highlight", agent)
    assert not wants_change("Highlight Translator: I want to go home", agent)
    # No kind of helper is named in what counts as a change: "fix my helper" is one, whatever the helper does.
    assert wants_change("please fix my helper", agent) and not wants_change("please fix my translator", agent)
