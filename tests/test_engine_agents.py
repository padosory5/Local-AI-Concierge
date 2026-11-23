"""The engine and the helpers people make (concierge/engine.py): a request for one goes to
the conversation in which it is worked out whenever a model can hold that conversation,
and to the plain questions when none can; what follows once a helper is made goes by what
its card is made of; and what people ask a helper that works on a folder's files is
answered from its card and its records.

Nothing in the engine knows what any helper is for, so nothing here is about one either:
the rules, folders and files below are made up, and the models are pretend ones that fill
whichever form they are handed."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

from concierge import chores, hardware, noir, research, safety
from concierge import folderwatch as fw
from concierge.agents import builder as builder_mod
from concierge.agents import designer as designer_mod
from concierge.agents import parts, planner, store
from concierge.agents.builder import CARD, CREATE_IT, DUPLICATE, AgentBuilder
from concierge.agents.designer import (DESIGN, DESIGN_CONTEXT, MOVED_ON, NO_DESIGNER, NOT_CLEAR, NOTHING_MISSING,
                                       PART_OF_THIS, SOMETHING_ELSE, STILL_ASKING, Designer, DesignModel)
from concierge.agents.parts import (ANSWER, CUSTOM, DOCUMENTS_QA, IN_CHAT, INSIDE_FILE, MOVE, NAME_ONLY, NEW_FILE, NOTE,
                                    OPEN_NO, SHOW, WHILE_ON)
from concierge.agents.planner import IdeaPlanner
from concierge.agents.router import Route, route
from concierge.agents.worker import FILE_IT, LEAVE, UNSURE
from concierge.conversations import ChatBook
from concierge.engine import (ABOUT_CHORES, ALL_NOW, ASKS_FOR_WORK, CARRY_ON, CARRY_ON_YES, CHANGE_THE_RULE,
                              CHANGED_HELPERS, CHANGED_TOLD, DELETE_AGENT, DELETE_IT, DROP_IT, FIRST_PASS, FIX_AGENT,
                              GO_THROUGH, JUST_THIS_ONE, LEAVE_IT, LEAVE_THEM, NEEDS_TALKING, ONLY_NEW, RULE_FROM_MOVE,
                              SWITCH_IT_ON, WANTS_ANSWER,
                              WANTS_EVERYTHING, WANTS_PASS, WANTS_PLACE, WANTS_STATUS, WANTS_WHERE, WANTS_WHY,
                              NoirEngine, _mentions)
from concierge.events import AgentCard, AgentList, IdeaCard, NoirText, Question, Result, Thinking
from concierge.folderwatch import FolderWatch
from concierge.hardware import GPU, HardwareReport
from concierge.quick.agents import BUBBLE, UNTIL_UNHIGHLIGHT, QuickAgents

NAME = "Paper sorter"
RULE = "Anything about the boat goes in Boat, plant lists go in Garden. Leave bills where they are."
LEFT = fw.LEFT_BY_RULE  # why a file stays when the rule says so, in the folder watcher's own words
ASKED = "whenever a pdf lands in my downloads, tell me what it is"  # standing work on new files: decided in code


class BuiltIn:
    """The built-in model as the engine, the router, the planner and the folder watcher ask
    it: it fills whichever form it is handed, by the form's own fields. It follows the
    made-up rule above by the words in what it is given."""

    def __init__(self):
        self.choice = "chat"  # what the router's form comes back with
        self.plan: dict = {}  # what the idea planner's form comes back with
        self.chats: list = []
        self.unloaded: list = []

    def capabilities(self, name):
        return ["completion"]

    def loaded(self):
        return [{"name": "noir:latest"}]

    def list_models(self):
        return ["noir:latest"]

    def unload(self, name):
        self.unloaded.append(name)

    def refresh(self, *args):
        pass

    def show(self, name):
        return {"system": "You are Noir."}

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.chats.append(messages)
        yield "Tokyo."

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        fields = schema["properties"]
        given = messages[-1]["content"]
        if "steps" in fields:  # the idea planner
            return self.plan
        if "changes" in fields:  # whether the answer changes over time (the web)
            return {"changes": "no"}
        if "example" in fields:  # the one instruction of a helper that works on text
            return {"name": "Word fixer", "instruction": "Fix the spelling of the text.", "example": "teh cat"}
        if "what" not in fields:  # the router
            return {"choice": self.choice}
        low = given.lower()
        if "bill" in low:
            what, folder = "a bill", LEAVE
        elif "boat" in low:
            what, folder = "a paper about the boat", "Boat"
        elif "plant" in low:
            what, folder = "a plant list", "Garden"
        else:
            what, folder = "can't tell", UNSURE
        if "write" in fields:  # writing about a file, the first of its two forms: is anything asked about this one?
            return {"what": what, "write": "Nothing to write" if folder == LEAVE else "Write about it"}
        if "note" in fields:  # writing about a file
            return {"what": what, "note": "" if folder == LEAVE else f"This is {what}."}
        if "folder" in fields:  # it may make folders: only a name is asked for
            named = folder not in (LEAVE, UNSURE)
            return {"what": what, "choice": FILE_IT if named else folder, "folder": folder if named else ""}
        return {"what": what, "choice": folder if folder in fields["choice"]["enum"] else UNSURE}


class Script:
    """A design model whose forms were written in advance: one for each thing the user has
    said so far, however often code asks for it in that turn. What a form leaves out is
    filled in as "not said", so a form added later to the real one doesn't matter here."""

    def __init__(self, *forms):
        self.forms, self.turns, self.released = list(forms), [], 0
        self.decided: list[str] = []  # the messages it was asked about on their own: part of this, or something else

    def fill(self, note, turns, schema):
        if "about" in schema["properties"]:
            # Asked first, on its own, whether what they typed is part of the conversation.
            typed = turns[0]["content"].rsplit("THEY HAVE JUST WRITTEN\n", 1)[-1]
            self.decided.append(typed)
            return {"about": SOMETHING_ELSE if self.elsewhere(typed) else PART_OF_THIS}
        self.turns.append([dict(turn) for turn in turns])
        said = sum(turn["role"] == "user" for turn in turns)
        given = self.forms[min(said, len(self.forms)) - 1]
        filled = {key: _not_said(spec) for key, spec in schema["properties"].items()}
        for key, value in given.items():
            filled[key] = {"place": value[0], "name": value[1]} if isinstance(value, tuple) else value
        return filled

    def elsewhere(self, typed: str) -> bool:
        return False

    def release(self):
        self.released += 1

    def model(self, here=True) -> DesignModel:
        return DesignModel(self.fill, "Test model", here=here, release=self.release)


def _not_said(spec: dict):
    """What a form's field holds when the model has nothing to say for it."""
    if spec.get("type") == "object":
        return {"place": "", "name": ""}
    choices = spec.get("enum")
    if not choices:
        return ""
    return next((value for value in ("", NOT_CLEAR, STILL_ASKING) if value in choices), choices[0])


ASIDE = "what's the capital of Japan?"  # a message about something else: the router's own model says "chat"


class Wanders(Script):
    """A design model that takes some messages for something else than the helper, the way
    the real one decides it: by reading them. Which ones is written in advance. On this
    computer it is asked about each message on its own first; off it, it says so in the
    whole form."""

    def __init__(self, *forms, asides=(ASIDE,)):
        super().__init__(*forms)
        self.asides = asides

    def elsewhere(self, typed: str) -> bool:
        return typed in self.asides

    def fill(self, note, turns, schema):
        ends = schema["properties"].get("status", {}).get("enum", ())
        if turns[-1]["content"] in self.asides and MOVED_ON in ends:
            self.turns.append([dict(turn) for turn in turns])
            filled = {key: _not_said(spec) for key, spec in schema["properties"].items()}
            return {**filled, "status": MOVED_ON, "say": "That is not about the helper."}
        return super().fill(note, turns, schema)


# A whole card that moves files, the way a model fills it in when nothing is missing.
MOVER = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""), choices="Boat, Garden", instruction=RULE,
             name=NAME, status=NOTHING_MISSING, say="Here it is.")
ASKING = dict(status=STILL_ASKING, say="What should happen to them?")


class Flow:
    """Stands in for the designing conversation or the plain questions once they are done:
    what the last Create it or Save changes left for the engine."""
    active, handoff, sketch, aside = False, None, None, None

    def __init__(self, created=None, edited=False, replaced=None):
        self.created, self.edited, self.replaced = created, edited, replaced

    def take_created(self):
        created, self.created = self.created, None
        return created

    def available(self):
        return True


def card(folder: Path, then: str = MOVE, name: str = NAME, **more) -> store.Agent:
    """A made-up card that works on the new files of `folder`: one that moves them, or one
    that writes about them."""
    slots = {"when": NEW_FILE, "then": then, "instruction": RULE, "folder": str(folder), "looks_at": INSIDE_FILE,
             "name": name}
    slots.update({"choices": "Boat, Garden", "open": OPEN_NO, "into": ""} if then == MOVE else {"notes": ""})
    return store.Agent(name=name, blueprint=CUSTOM, slots={**slots, **more})


def text_card(name: str, when: str = IN_CHAT, **more) -> store.Agent:
    slots = {"instruction": "Fix the spelling of the text.", "when": when, "then": SHOW if when == WHILE_ON else ANSWER,
             "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT, "name": name}
    return store.Agent(name=name, blueprint=CUSTOM, slots={**slots, **more})


def write(folder: Path, name: str, words: str) -> Path:
    path = folder / name
    path.write_text(words, encoding="utf-8")
    return path


def said(events) -> str:
    return " ".join(e.text for e in events if isinstance(e, (NoirText, Question, Result)))


def one(events, kind):
    return next(e for e in events if isinstance(e, kind))


def lists(events) -> AgentList:
    return [e for e in events if isinstance(e, AgentList)][-1]


def report(card_gb: float | None) -> HardwareReport:
    gpus = [GPU("Test card", "nvidia", card_gb, card_gb, True, "test")] if card_gb else []
    return HardwareReport("windows", "11", "x86_64", "Test", 8, 16, 32.0, 20.0, 100.0, "C:", gpus)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home: the places people name, a data folder of its own, and nothing of
    the real computer."""
    for place in parts.PLACE_NAMES:
        (tmp_path / place).mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for module in (designer_mod, builder_mod, parts):
        monkeypatch.setattr(module, "known_folder", lambda name, home=None: tmp_path / name)
    for module in (designer_mod, builder_mod):
        monkeypatch.setattr(module, "is_blocked", lambda folder: False)  # the test folder lives under AppData
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(noir, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(planner, "ideas_path", lambda: tmp_path / "ideas.json")
    monkeypatch.setattr(sys, "platform", "win32")  # highlights are offered
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture
def engine(home, monkeypatch):
    """An engine with pretend models and nothing started: `engine(design)` gives one whose
    design model is `design` (None: nobody can design)."""
    made = []

    def make(design: DesignModel | None = None, routes: Route | None = None, ollama: BuiltIn | None = None) -> NoirEngine:
        model = ollama or BuiltIn()
        e = NoirEngine(model)
        e.book = ChatBook(None)
        e.chat = noir.NoirChat(model)
        # An hour ahead, so every file written counts as having stood still; it never looks
        # by itself: the tests look by hand.
        e.folderwatch = FolderWatch(model, "noir", home / "data" / "folderwatch.json",
                                    home / "data" / "folderwatch_done.json", clock=lambda: time.time() + 3600,
                                    look_seconds=3600)
        e._design_model = lambda: design
        e._hardware = lambda: (report(16.0), 3.8)
        e.designer = Designer(model, "noir", None, e.folderwatch.rehearse, lambda: e._design_model(), lambda: "Small model")
        e.builder = AgentBuilder(model, "noir", None, e.blueprints)
        e.planner = IdeaPlanner(model, "noir", None, e._hardware, e.blueprints)
        e.quick = QuickAgents(model, "noir", None,
                              lambda *a: type("W", (), {"start": lambda s: None, "stop": lambda s: None})(),
                              lambda: type("B", (), {"close": lambda s: None, "pressed": lambda s, x, y: None})())
        if routes is not None:
            monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: routes)
        made.append(e)
        return e

    yield make
    for e in made:
        e.close()


def watching(e: NoirEngine, home: Path, then: str = MOVE, on: bool = True, **more) -> store.Agent:
    """A saved card that works on Downloads' new files, switched on unless said otherwise."""
    agent = card(home / "Downloads", then, **more)
    store.save(agent)
    e.folderwatch.refresh(store.list_agents())
    if on:
        e.folderwatch.switch(agent, True)
        e.folderwatch.stop()
    return agent


# ------------------------------------------------- a helper is wanted: who makes it


def test_a_request_for_a_helper_is_worked_out_in_a_conversation_that_starts_from_nothing(engine, home):
    script = Script(ASKING)
    e = engine(script.model())
    events = list(e.send(ASKED))
    assert e.designer.active and not e.builder.active and not e.planner.active
    assert one(events, Question).id == DESIGN and one(events, Question).text == "What should happen to them?"
    # The conversation's first turn is the user's own words, and nothing was filled in for them.
    assert script.turns[0] == [{"role": "user", "content": ASKED}] and e.designer.sketch.slots == {}
    assert store.list_agents() == []


def test_what_the_router_made_of_the_request_is_not_passed_on(engine, home):
    # The router's model may say which blueprint's words fit; the conversation starts from nothing all the same.
    script = Script(ASKING)
    e = engine(script.model(), routes=Route("new_agent", blueprint=DOCUMENTS_QA, request="x"))
    list(e.send("I want to ask questions about my papers"))
    assert e.designer.active and not e.builder.active
    assert e.designer.sketch.slots == {} and e.designer.sketch.request == "I want to ask questions about my papers"


def test_what_is_typed_and_clicked_while_a_helper_is_worked_out_goes_to_that_conversation(engine, home):
    script = Script(ASKING, dict(status=STILL_ASKING, say="Should it only go by the names?", asks="looks_at",
                                 when=NEW_FILE, then=MOVE, folder=("Downloads", "")),
                    dict(status=STILL_ASKING, say="And which folders?"))
    e = engine(script.model())
    list(e.send(ASKED))
    events = list(e.send("the ones about my boat"))  # no router, no web: the conversation's own turn
    question = one(events, Question)
    assert question.id == "looks_at" and question.choices == [INSIDE_FILE, NAME_ONLY]
    events = list(e.choose("looks_at", NAME_ONLY))  # a click on its own question
    assert e.designer.sketch.slots["looks_at"] == NAME_ONLY and one(events, Question).text == "And which folders?"
    assert script.turns[-1][-1] == {"role": "user", "content": NAME_ONLY}  # said to the model like anything typed
    events = list(e.choose(CARD, "Cancel"))
    assert not e.designer.active and script.released == 1 and store.list_agents() == []


def test_without_a_model_to_design_a_helper_for_files_is_told_so_and_nothing_else(engine, home):
    e = engine(None)
    events = list(e.send(ASKED))
    assert said(events) == NO_DESIGNER
    assert not (e.designer.active or e.builder.active or e.planner.active) and store.list_agents() == []


def test_without_a_model_the_plain_questions_still_make_a_helper_that_answers_from_documents(engine, home):
    e = engine(None, routes=Route("new_agent", blueprint=DOCUMENTS_QA, request="x"))
    events = list(e.send("I want to ask questions about my papers"))
    assert e.builder.active and not e.designer.active and events[-1].id == "folder"


def test_without_a_model_an_idea_made_of_file_parts_is_told_so_not_half_made(engine, home):
    e = engine(None, routes=Route("idea", request="keep my papers in order"))
    e.ollama.plan = {"title": "Paper keeper", "steps": [{"block": "new_file", "detail": ""}, {"block": "folder_files", "detail": ""},
                                                        {"block": "classify", "detail": ""}, {"block": "move_files", "detail": ""}]}
    events = list(e.send("keep my papers in order"))
    assert said(events) == NO_DESIGNER and not any(isinstance(event, (IdeaCard, AgentCard)) for event in events)
    assert not e.builder.active and not e.planner.active


def test_without_a_model_a_helper_that_works_on_text_is_made_the_plain_way_and_switched_on(engine, home):
    e = engine(None, routes=Route("idea", request="fix the spelling of what I highlight"))
    e.ollama.plan = {"title": "Word fixer", "steps": [{"block": "while_on", "detail": ""}, {"block": "selected_text", "detail": ""},
                                                      {"block": "rewrite", "detail": ""}, {"block": "show_popup", "detail": ""}]}
    events = list(e.send("fix the spelling of what I highlight"))
    assert one(events, AgentCard).kind == WHILE_ON and e.builder.active
    events = list(e.choose(CARD, CREATE_IT))
    assert "Word fixer is ready." in said(events) and "It's on. Highlight text in any program" in said(events)
    assert e.quick.is_on("Word fixer") and lists(events).active == ["Word fixer"]
    assert store.find_agent("Word fixer").slots["then"] == SHOW


def test_an_idea_that_waited_is_worked_out_by_talking_once_a_model_can(engine, home):
    e = engine(None, routes=Route("idea", request="copy every screenshot"))
    e.ollama.plan = {"title": "Word fixer", "steps": [{"block": "on_request", "detail": ""}, {"block": "rewrite", "detail": ""},
                                                      {"block": "hotkey", "detail": "Ctrl+F1"}]}
    card_shown = one(list(e.send("fix my spelling when I press Ctrl+F1")), IdeaCard)
    assert card_shown.level == "not_built" and e.planner.active
    # They pick a plan in the menu, and a later idea that can be made goes to the conversation.
    e.planner.draft = None
    script = Script(ASKING)
    e._design_model = lambda: script.model()
    events = list(e._make(CUSTOM, "fix my spelling", ["on_request", "rewrite"]))
    assert e.designer.active and one(events, Question).id == DESIGN


def test_a_change_to_a_card_is_talked_through_and_without_a_model_only_what_the_plain_way_can(engine, home):
    script = Script(dict(status=STILL_ASKING, say="What should be different?"))
    e = engine(script.model())
    sorter, fixer = watching(e, home), text_card("Word fixer")
    store.save(fixer)
    events = list(e.send(f"change {NAME} so that bills go in Bills"))
    assert e.designer.active and e.designer.sketch.editing and e.designer.sketch.replaces == NAME
    assert any(isinstance(event, Thinking) and "change to your Paper sorter" in event.text for event in events)
    list(e.choose(CARD, "Cancel"))

    e = engine(None)
    events = list(e.send(f"change {NAME} so that bills go in Bills"))
    assert said(events) == f"I can't change {NAME} by myself. {NO_DESIGNER}" and not e.builder.active
    assert store.find_agent(NAME).slots == sorter.slots  # and never set by words meant for another kind of card
    events = list(e.send("change Word fixer to copy it to the clipboard"))
    assert e.builder.active and one(events, AgentCard).actions[0] == "Save changes"


def test_the_question_about_a_helper_they_already_have_is_the_conversations_own(engine, home):
    script = Script(dict(MOVER, name="Another sorter"), dict(status=STILL_ASKING, say="What should this one do then?"))
    e = engine(script.model())
    watching(e, home)
    events = list(e.send(ASKED))
    question = one(events, Question)
    assert question.id == DUPLICATE and question.choices[0] == f"Use {NAME}"
    assert not any(isinstance(event, AgentCard) for event in events)
    events = list(e.choose(DUPLICATE, f"Use {NAME}"))  # passed on: the engine asks no such question of its own
    assert not e.designer.active and not any(isinstance(event, Question) for event in events)
    assert [a.name for a in store.list_agents()] == [NAME]


def test_a_new_chat_leaves_a_helper_being_worked_out_and_frees_its_model(engine, home):
    script = Script(ASKING)
    e = engine(script.model())
    list(e.send(ASKED))
    list(e.new_chat())
    assert not e.designer.active and script.released == 1


def test_loading_noirs_model_is_not_announced_while_a_helper_is_worked_out(engine, home):
    # A design model on this computer has Noir's own make room on purpose.
    script = Script(ASKING, ASKING)
    e = engine(script.model())
    e.ollama.loaded = lambda: []
    first = list(e.send(ASKED))
    assert any(isinstance(event, Thinking) and "Loading my model" in event.text for event in first)
    again = list(e.send("the boat ones"))
    assert not any(isinstance(event, Thinking) and "Loading my model" in event.text for event in again)


# ------------------------------------ a message about something else, in the middle


def test_a_message_about_something_else_is_answered_first_and_the_helper_waits(engine, home):
    script = Wanders(ASKING)
    e = engine(script.model())
    list(e.send(ASKED))
    assert e.designer.active
    events = list(e.send(ASIDE))
    # What they asked is answered first and whole: the conversation about the helper says
    # nothing in words on its way out. Then one question of the engine's own, with two buttons.
    read = [event for event in events if isinstance(event, (NoirText, Question, Result))]
    assert [type(event) for event in read] == [NoirText, Question] and read[0].text == "Tokyo."
    assert events[-1] is read[1]
    assert (read[1].id, read[1].text, read[1].choices) == (CARRY_ON, "Carry on with the helper we were working out?",
                                                           [CARRY_ON_YES, DROP_IT])
    # The helper is kept, and it is not the one that is talked to.
    assert not e.designer.active and e.designer.aside is not None and e.designer.handoff is None
    assert script.released == 1  # a design model on this computer leaves the graphics memory while it waits
    # Its conversation stands as it stood: their aside is not in it.
    assert e.designer.aside.turns == [{"role": "user", "content": ASKED},
                                      {"role": "assistant", "content": "What should happen to them?"}]
    assert store.list_agents() == []


def test_nothing_is_routed_to_a_helper_set_aside_and_carrying_on_takes_it_up_where_it_stood(engine, home):
    script = Wanders(ASKING, dict(status=STILL_ASKING, say="And which folder do they land in?"))
    e = engine(script.model())
    list(e.send(ASKED))
    list(e.send(ASIDE))
    fills = len(script.turns)
    # The next message is an ordinary one too, whatever it says: the design model is not asked.
    events = list(e.send("the ones about my boat"))
    assert len(script.turns) == fills and said(events).startswith("Tokyo.") and events[-1].id == CARRY_ON
    events = list(e.choose(CARRY_ON, CARRY_ON_YES))
    assert e.designer.active and e.designer.aside is None
    asked = [event for event in events if isinstance(event, Question)]
    # One line that says where things stood, which was a question: it is asked again, and only it.
    assert [(q.id, q.text) for q in asked] == [(DESIGN, "Back to the helper we were working out. What should happen "
                                                        "to them?")]
    assert len(script.turns) == fills  # no model was asked for that
    events = list(e.send("the ones about my boat"))
    assert one(events, Question).text == "And which folder do they land in?"
    # The model reads the conversation as if nothing had come between.
    assert script.turns[-1] == [{"role": "user", "content": ASKED},
                                {"role": "assistant", "content": "What should happen to them?"},
                                {"role": "user", "content": "the ones about my boat"}]


def test_carrying_on_at_the_card_shows_it_again_with_the_try_out_it_had_and_asks_no_model(engine, home):
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    write(downloads, "phone_bill.txt", "Your bill for March")
    script = Wanders(MOVER)
    e = engine(script.model())
    first = list(e.send(ASKED))
    card_shown, tried = one(first, AgentCard), one(first, Result)
    list(e.send(ASIDE))
    assert e.designer.aside is not None and store.list_agents() == []
    fills, judged = len(script.turns), []
    judge = e.ollama.chat_json
    e.ollama.chat_json = lambda *args, **more: judged.append(args) or judge(*args, **more)
    events = list(e.choose(CARRY_ON, CARRY_ON_YES))
    assert len(script.turns) == fills and judged == []  # neither the design model nor the built-in one was asked
    assert one(events, AgentCard) == card_shown
    again = one(events, Result)
    assert again.agent == designer_mod.TRY_OUT
    assert again.text.splitlines()[0] == "The try-out from before, on 2 files in Downloads. Nothing was moved."
    assert again.text.splitlines()[1:] == tried.text.splitlines()[1:]  # each file as it came out then
    assert f"Here is {NAME} as we left it" in said(events) and (downloads / "boat_manual.txt").is_file()
    # The card is up again and nothing was asked: a plain yes is a yes to it.
    events = list(e.send("yes"))
    assert store.find_agent(NAME) is not None and e.folderwatch.is_on(NAME) and one(events, Question).id == FIRST_PASS


def test_the_question_comes_once_under_each_answer_and_never_again_once_they_said_drop_it(engine, home):
    script = Wanders(ASKING)
    e = engine(script.model())
    list(e.send(ASKED))
    # Two asides in a row: the question under each answer, once. (The buttons of the first
    # stop working when the second message is typed, so only the last one can be clicked.)
    for text in (ASIDE, "and of Korea?"):
        events = list(e.send(text))
        assert [event.id for event in events if isinstance(event, Question)] == [CARRY_ON], text
    events = list(e.choose(CARRY_ON, DROP_IT))
    assert said(events) == "Okay, I won't create it." and e.designer.aside is None and not e.designer.active
    events = list(e.send("and of France?"))
    assert said(events) == "Tokyo." and not any(isinstance(event, Question) for event in events)
    assert said(list(e.choose(CARRY_ON, CARRY_ON_YES))) == "That question has already been answered."
    # Taken up and set aside a second time, it is asked about again.
    list(e.send(ASKED))
    list(e.send(ASIDE))
    list(e.choose(CARRY_ON, CARRY_ON_YES))
    events = list(e.send(ASIDE))
    assert events[-1].id == CARRY_ON and e.designer.aside is not None


def test_a_yes_or_no_typed_right_under_the_question_answers_it(engine, home):
    script = Wanders(ASKING)
    e = engine(script.model())
    list(e.send(ASKED))
    list(e.send(ASIDE))
    chats = len(e.ollama.chats)
    events = list(e.send("Yes please"))
    assert e.designer.active and one(events, Question).text.startswith("Back to the helper we were working out.")
    assert len(e.ollama.chats) == chats  # not answered as a message of its own
    list(e.send(ASIDE))
    # "Not now" says neither yes nor no here: the helper goes on waiting, and is not thrown away for it.
    events = list(e.send("not now"))
    assert e.designer.aside is not None and said(events).startswith("Tokyo.") and events[-1].id == CARRY_ON
    events = list(e.send("Drop it."))  # a button's own words, typed
    assert said(events) == "Okay, I won't create it." and e.designer.aside is None
    assert said(list(e.send("no"))) == "Tokyo."  # nothing is asked any more: a message like any other


def test_an_answer_that_asks_something_itself_comes_whole_before_the_question_about_the_helper(engine, home):
    weather = "what's the weather in Seoul today?"
    script = Wanders(ASKING, asides=(weather,))
    e = engine(script.model())
    list(e.send(ASKED))
    events = list(e.send(weather))  # the first time anything is to be looked up, that is asked about first
    assert [event.id for event in events if isinstance(event, Question)] == [research.WEB]
    # Two questions at once would leave a typed yes with no one question to answer: the helper waits.
    assert e.designer.aside is not None and not e.carry_asked
    events = list(e.choose(research.WEB, research.NO_LOOK))
    assert said(events).startswith("Tokyo.") and events[-1].id == CARRY_ON  # now what they asked is answered


def test_beginning_another_helper_leaves_the_one_set_aside(engine, home):
    another = "every time a file arrives in Documents, tell me what it is"
    script = Wanders(ASKING, asides=(ASIDE, another))
    e = engine(script.model())
    list(e.send(ASKED))
    first = e.designer.sketch
    list(e.send(ASIDE))
    events = list(e.send(another))  # with one set aside, they ask for another
    assert e.designer.active and e.designer.sketch is not first and e.designer.sketch.request == another
    assert e.designer.aside is None
    assert any(isinstance(event, Thinking) and "left the helper we were working out before" in event.text
               for event in events)
    assert [event.id for event in events if isinstance(event, Question)] == [DESIGN]  # the new one's own question only
    assert said(list(e.choose(CARRY_ON, CARRY_ON_YES))) == "That question has already been answered."
    # Asked for in the middle of working one out, the model takes it for something else, and the same holds.
    second = e.designer.sketch
    events = list(e.send(another))
    assert e.designer.active and e.designer.sketch is not second and e.designer.aside is None
    assert [event.id for event in events if isinstance(event, Question)] == [DESIGN]
    assert store.list_agents() == []


def test_a_helper_begun_the_plain_way_also_leaves_the_one_set_aside(engine, home, monkeypatch):
    e = engine(Wanders(ASKING).model())
    list(e.send(ASKED))
    list(e.send(ASIDE))
    # Nobody can work a helper out any more (another model was picked), and the plain questions begin one.
    e._design_model = lambda: None
    monkeypatch.setattr("concierge.engine.route",
                        lambda *args, **kwargs: Route("new_agent", blueprint=DOCUMENTS_QA, request="x"))
    events = list(e.send("I want to ask questions about my papers"))
    assert e.builder.active and events[-1].id == "folder"  # its own question, and no second one under it
    assert e.designer.aside is None


def test_a_helper_set_aside_is_left_when_the_chat_changes_or_the_app_closes(engine, home):
    e = engine(Wanders(ASKING).model())
    list(e.send("hello"))  # an earlier conversation to come back to
    earlier = e.book.current.id
    list(e.new_chat())
    for leave in (lambda: list(e.new_chat()), lambda: list(e.open_chat(earlier)),
                  lambda: list(e.delete_chat(e.book.current.id))):
        list(e.send(ASKED))
        list(e.send(ASIDE))
        assert e.designer.aside is not None and e.carry_asked
        leave()
        assert e.designer.aside is None and not e.designer.active and not e.carry_asked
        # Nothing waits in the conversation they are in now: a yes is a message like any other.
        events = list(e.send("yes"))
        assert said(events) == "Tokyo." and not e.designer.active
    list(e.send(ASKED))
    list(e.send(ASIDE))
    e.close()
    assert e.designer.aside is None and not e.designer.active


class OneCard(BuiltIn):
    """The built-in model and a design model installed beside it, on a graphics card that
    holds one of them at a time: which one is in memory is kept the way Ollama knows it."""

    def __init__(self, script):
        super().__init__()
        self.script, self.in_memory = script, ["noir:latest"]

    def list_models(self):
        return ["noir:latest", "gemma4:12b"]

    def loaded(self):
        return [{"name": name} for name in self.in_memory]

    def unload(self, name):
        super().unload(name)
        self.in_memory = [tag for tag in self.in_memory if tag != name and tag.split(":")[0] != name]

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.in_memory = list(dict.fromkeys([*self.in_memory, "noir:latest"]))
        yield from super().chat(model, messages, think, options, keep_alive)

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        if model == "gemma4:12b":
            self.in_memory = list(dict.fromkeys([*self.in_memory, model]))
            return self.script.fill(messages[0]["content"], messages[1:], schema)
        self.in_memory = list(dict.fromkeys([*self.in_memory, "noir:latest"]))
        return super().chat_json(model, messages, schema, think, keep_alive, options)


def test_a_design_model_on_this_computer_leaves_memory_while_the_helper_waits_and_loads_again_after(engine, home):
    script = Wanders(ASKING, ASKING)
    both = OneCard(script)
    e = engine(ollama=both)
    del e._design_model  # the engine's own choice: the listed model that is installed and fits beside Noir's own
    e.menu.chosen = lambda: None
    list(e.send(ASKED))
    assert both.in_memory == ["gemma4:12b"]  # Noir's own made room when it came in
    events = list(e.send(ASIDE))
    # Set aside, it lets go of the graphics memory, and Noir's own comes back to answer.
    assert both.in_memory == ["noir:latest"] and said(events).startswith("Tokyo.")
    fills = len(script.turns)
    list(e.choose(CARRY_ON, CARRY_ON_YES))
    assert len(script.turns) == fills and both.in_memory == ["noir:latest"]  # carrying on asks no model
    list(e.send("the ones about my boat"))
    # At its next turn it is back by itself, the same model as before, and Noir's own has made room again.
    assert both.in_memory == ["gemma4:12b"] and len(script.turns) == fills + 1


def test_a_message_from_someone_in_trouble_sets_the_helper_aside_and_no_question_follows_the_reply(engine, home):
    write(home / "Downloads", "boat_manual.txt", "How to start the boat engine")
    script = Wanders(MOVER)
    e = engine(script.model())
    list(e.send(ASKED))  # the card is up: a plain "ok" typed now would create the helper
    fills = len(script.turns)
    trouble = "I want to die"
    events = list(e.send(trouble))
    assert said(events) == safety.crisis_reply(trouble)  # the fixed reply, and nothing under it
    assert not e.designer.active and e.designer.aside is not None and len(script.turns) == fills
    # What they type next is not read as part of the helper's conversation.
    events = list(e.send("ok"))
    assert store.list_agents() == [] and said(events).startswith("Tokyo.") and events[-1].id == CARRY_ON
    # With one waiting already: the reply again, no question under it, and a yes typed then answers nothing.
    events = list(e.send(trouble))
    assert said(events) == safety.crisis_reply(trouble) and e.designer.aside is not None
    events = list(e.send("yes"))
    assert not e.designer.active and e.designer.aside is not None and said(events).startswith("Tokyo.")


def test_a_change_set_aside_is_asked_about_by_the_helpers_name_and_dropping_it_leaves_the_helper_as_it_was(engine, home):
    script = Wanders(dict(status=STILL_ASKING, say="What should be different?"))
    e = engine(script.model())
    sorter = watching(e, home)
    list(e.send(f"change {NAME} so that bills go in Bills"))
    assert e.designer.active and e.designer.sketch.editing
    events = list(e.send(ASIDE))
    assert said(events).startswith("Tokyo.")
    assert (events[-1].id, events[-1].text) == (CARRY_ON, f"Carry on with the changes to {NAME}?")
    events = list(e.send("no"))
    assert said(events) == f"Okay, I left {NAME} as it was." and e.designer.aside is None
    assert store.find_agent(NAME).slots == sorter.slots


# ------------------------------------------------------------------ who designs


class Installed:
    def __init__(self, *tags):
        self.tags = list(tags)
        self.in_memory, self.unloaded, self.options = [], [], []

    def list_models(self):
        return self.tags

    def capabilities(self, name):
        return ["completion"]

    def loaded(self):
        return [{"name": tag} for tag in self.in_memory]

    def unload(self, name):
        self.unloaded.append(name)
        self.in_memory = [tag for tag in self.in_memory if tag != name]

    def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
        self.options.append(options)
        self.in_memory.append(model)
        return {}


@pytest.fixture
def designing(home):
    def made(tags, card_gb=16.0, chosen=None):
        e = NoirEngine(Installed(*tags))
        e.chat = noir.NoirChat(e.ollama)
        e._hardware = lambda: (report(card_gb), 3.8)
        e.menu.chosen = lambda: chosen
        return e

    return made


def test_a_listed_model_designs_when_installed_and_it_fits(designing):
    model = designing(["noir:latest", "gemma4:12b"])._design_model()
    assert model is not None and model.name == "Gemma 4 12B" and model.here


def test_noirs_own_model_makes_room_whenever_a_local_design_model_comes_in(designing):
    e = designing(["noir:latest", "gemma4:12b"])
    model = e._design_model()
    assert model.waking()  # not in memory yet: the first turn says so
    turn = [{"role": "user", "content": "my downloads are a mess"}]
    model.form("note", turn, {"type": "object", "properties": {}})
    # The two together, with the desktop's share, fill a 16 GB card.
    assert e.ollama.unloaded == ["noir"] and e.ollama.options[0]["num_ctx"] == DESIGN_CONTEXT == 8192
    model.form("note", turn, {"type": "object", "properties": {}})
    assert e.ollama.unloaded == ["noir"]  # only when the design model comes in, not at every turn
    model.done()  # a try-out is the built-in model's work: the design model leaves for it
    assert e.ollama.unloaded == ["noir", "gemma4:12b"]
    model.form("note", turn, {"type": "object", "properties": {}})
    assert e.ollama.unloaded == ["noir", "gemma4:12b", "noir"]  # and Noir's own makes room again when it comes back


def test_nobody_designs_without_a_listed_model_or_the_room_for_it(designing):
    assert designing(["noir:latest", "qwen3.5:9b", "qwen3.6:35b-a3b"])._design_model() is None  # bigger isn't better
    assert designing(["noir:latest", "gemma4:12b"], card_gb=8.0)._design_model() is None  # no room beside Noir
    assert designing(["noir:latest", "gemma4:12b"], card_gb=None)._design_model() is None  # never on the processor
    off = designing(["noir:latest", "gemma4:12b"])
    off.designs = False
    assert off._design_model() is None
    assert NoirEngine(Installed("noir:latest", "gemma4:12b"))._design_model() is None  # before it has started


def test_a_plan_or_key_model_designs_before_any_local_one(designing):
    e = designing(["noir:latest", "gemma4:12b"], chosen={"here": False, "name": "Claude Sonnet 5.5", "model": "x"})
    e.chat.talker = object()  # not its own model
    e.talker_name = "Claude Sonnet 5.5"
    model = e._design_model()
    assert model.name == "Claude Sonnet 5.5" and not model.here


def test_a_local_model_picked_in_the_menu_does_not_design_unless_listed(designing):
    e = designing(["noir:latest", "qwen3.6:35b-a3b"], chosen={"here": True, "name": "Qwen 3.6 35B", "model": "qwen3.6:35b-a3b"})
    e.chat.talker = object()
    assert e._design_model() is None


def test_the_designer_is_built_with_the_folder_watchers_dry_run_and_the_engines_choice_of_model(home, monkeypatch):
    class SetUp(BuiltIn):
        def ensure_running(self):
            pass

        def has_model(self, name):
            return name == "noir"

    monkeypatch.setattr(hardware, "detect", lambda: report(16.0))
    e = NoirEngine(SetUp())
    list(e.startup())
    assert e.designer.rehearse == e.folderwatch.rehearse and e.designer.design_model == e._design_model
    assert e.designer.available() is False  # nothing listed is installed, and nothing is picked
    e.close()


# -------------------------------------------------- what follows once one is made


def test_a_helper_for_a_folders_new_files_is_switched_on_and_the_files_already_there_are_asked_about(engine, home):
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    write(downloads, "phone_bill.txt", "Your bill for March")
    e = engine(Script(MOVER).model())
    events = list(e.send(ASKED))
    assert one(events, AgentCard).name == NAME and one(events, Result).agent == designer_mod.TRY_OUT
    assert (downloads / "boat_manual.txt").is_file()  # a try-out moves nothing
    events = list(e.choose(CARD, CREATE_IT))
    assert e.folderwatch.is_on(NAME) and lists(events).active == [NAME] and lists(events).switchable == [NAME]
    question = one(events, Question)
    assert question.id == FIRST_PASS and question.choices == [GO_THROUGH, ONLY_NEW]
    assert question.text == ("It's on: new files in Downloads are handled as they land, and everything it does shows "
                             "in your chores. There are 2 files there already. Go through them now?")
    assert said(events).startswith(f"{NAME} is ready.")
    # Only what lands from now on counts: what was there is left alone unless they say yes.
    e.folderwatch.look()
    assert (downloads / "boat_manual.txt").is_file() and e.folderwatch.done_lately() == []
    events = list(e.choose(FIRST_PASS, GO_THROUGH))
    assert one(events, Result).text == (f"Moved 1 file: Boat 1. 1 left where it was: {LEFT}. "
                                        "Undo is in your chores.")
    assert (downloads / "Boat" / "boat_manual.txt").is_file() and (downloads / "phone_bill.txt").is_file()


def test_only_new_files_from_now_on_means_it(engine, home):
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    e = engine(Script(MOVER).model())
    list(e.send(ASKED))
    list(e.choose(CARD, CREATE_IT))
    events = list(e.choose(FIRST_PASS, ONLY_NEW))
    assert said(events) == "Okay, only new files from now on."
    e.folderwatch.look()
    assert (downloads / "boat_manual.txt").is_file()


def test_a_yes_typed_right_under_go_through_them_answers_it_and_a_later_one_does_not(engine, home, monkeypatch):
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    e = engine(Script(MOVER).model())
    list(e.send(ASKED))
    list(e.choose(CARD, CREATE_IT))
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    assert said(list(e.send("what's the capital of Japan?"))).endswith("Tokyo.")
    assert said(list(e.send("yes"))).endswith("Tokyo.")  # a yes to something else by now: nothing moves
    assert (downloads / "boat_manual.txt").is_file()
    e.going_through, e.just_asked = NAME, True  # as it stands right after the question
    events = list(e.send("Yes please"))
    assert one(events, Result).text.startswith("Moved 1 file: Boat 1.") and (downloads / "Boat" / "boat_manual.txt").is_file()


def test_a_helper_for_an_empty_folder_only_says_it_is_on(engine, home):
    e = engine()
    made = card(home / "Downloads", NOTE, name="Paper notes")
    store.save(made)
    e.designer = Flow(created=made)
    events = list(e._made(iter([])))
    assert e.folderwatch.is_on("Paper notes") and not any(isinstance(event, Question) for event in events)
    assert said(events) == ("It's on: new files in Downloads are handled as they land, and everything it does shows "
                            "in your chores.")
    # A card that never opens a file is not said to read one.
    by_name = card(home / "Documents", name="By name", looks_at=NAME_ONLY)
    store.save(by_name)
    e.designer = Flow(created=by_name)
    step = one(list(e._made(iter([]))), Thinking)
    assert "file's name is judged" in step.text and "read" not in step.text


def test_a_helper_that_works_on_highlights_is_switched_on_and_says_how_it_is_used(engine, home):
    e = engine()
    made = text_card("Word fixer", WHILE_ON)
    store.save(made)
    e.designer = Flow(created=made)
    events = list(e._made(iter([])))
    assert e.quick.is_on("Word fixer") and lists(events).active == ["Word fixer"]
    assert said(events) == ('It\'s on. Highlight text in any program and the result appears right above it. '
                            'Say "turn off Word fixer" or use its switch to stop it.')
    # Where highlights can't be read, it is made all the same and says so.
    e.quick = None
    e.designer = Flow(created=made)
    assert "on Windows only for now" in said(list(e._made(iter([]))))


def test_a_helper_that_is_asked_in_the_chat_says_how_to_ask_it(engine, home):
    e = engine()
    made = text_card("Word fixer")
    store.save(made)
    e.builder = Flow(created=made)  # the plain way leaves the same three things, and gets the same treatment
    events = list(e._made(iter([])))
    assert said(events) == 'To use it, start your message with its name, like "Word fixer: your text here".'
    assert not e.quick.is_on("Word fixer")
    assert list(e._made(iter([]))) == []  # taken once


def test_a_changed_helper_stays_as_it_was_on_or_off(engine, home):
    e = engine()
    agent = watching(e, home)
    changed = card(home / "Downloads", choices="Boat, Garden, Bills")
    store.save(changed)
    e.designer = Flow(created=changed, edited=True)
    events = list(e._made(iter([])))
    assert e.folderwatch.active[NAME].slots["choices"] == "Boat, Garden, Bills"  # the one that is on works by the change
    assert said(events) == "It's on, and works the new way from the next file that lands."
    # One that was off is not switched on behind their back: it is asked about.
    e.folderwatch.switch(agent, False)
    e.designer = Flow(created=changed, edited=True)
    question = one(list(e._made(iter([]))), Question)
    assert question.id == FIX_AGENT and question.choices == [SWITCH_IT_ON, LEAVE_IT] and not e.folderwatch.is_on(NAME)
    events = list(e.choose(FIX_AGENT, SWITCH_IT_ON))
    assert e.folderwatch.is_on(NAME) and lists(events).active == [NAME] and f"{NAME} is on." in said(events)


def test_a_change_that_renamed_a_helper_leaves_nothing_under_the_old_name(engine, home):
    e = engine()
    watching(e, home)
    write(home / "Downloads", "odd.txt", "nothing to go by")
    e.folderwatch.look()
    assert e.folderwatch.skipped[NAME]
    store.delete(store.find_agent(NAME))
    renamed = card(home / "Downloads", name="Boat papers")
    store.save(renamed)
    e.designer = Flow(created=renamed, edited=True, replaced=NAME)
    # As it happens in a turn: the conversation's own list of agents comes first, and by
    # then the lists are in step with what is saved, so the old name is no longer on.
    events = list(e._full_lists(e._made(iter([AgentList(["Boat papers"])]))))
    assert not e.folderwatch.is_on(NAME) and NAME not in e.folderwatch.skipped and NAME not in e.folderwatch.since
    assert e.folderwatch.is_on("Boat papers") and lists(events).active == ["Boat papers"]  # it was on: it carries on
    assert e.designer.replaced is None  # honoured once


def test_a_helper_changed_into_another_kind_of_card_stops_what_it_did_before(engine, home):
    e = engine()
    watching(e, home)
    now_chat = text_card(NAME)
    store.save(now_chat)
    e.designer = Flow(created=now_chat, edited=True)
    events = list(e._made(iter([])))
    assert not e.folderwatch.is_on(NAME) and NAME not in e.folderwatch.since and lists(events).active == []
    # And the other way round: one that worked on highlights and now works on a folder.
    fixer = text_card("Word fixer", WHILE_ON)
    store.save(fixer)
    e.quick.switch(fixer, True)
    now_files = card(home / "Documents", name="Word fixer")
    store.save(now_files)
    e.designer = Flow(created=now_files, edited=True)
    list(e._made(iter([])))
    assert not e.quick.is_on("Word fixer")


# --------------------------------- what people ask a helper that works on files


@pytest.fixture
def worked(engine, home):
    """An engine whose card has just handled two files: one it moved, one it left."""
    e = engine(routes=Route("chat"))
    watching(e, home)
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    write(downloads, "phone_bill.txt", "Your bill for March")
    e.folderwatch.look()
    assert (downloads / "Boat" / "boat_manual.txt").is_file()
    return e


def test_where_a_file_went_is_answered_from_the_record_as_the_whole_path(worked, home):
    events = list(worked.send("where did you put the boat manual?"))
    assert said(events) == f"boat_manual.txt is in {home / 'Downloads' / 'Boat'} (just now). Undo is in your chores."
    assert worked.ollama.chats == []  # never the chat model, which once said it couldn't move files
    events = list(worked.send("where is the folder?"))
    assert f"{NAME} keeps its folders in {home / 'Downloads'} (Boat, Garden)." in said(events)
    events = list(worked.send("where's the phone bill?"))
    assert said(events) == f"phone_bill.txt is still in {home / 'Downloads'}, where it stayed: {LEFT}: a bill."
    events = list(worked.send("where did they go?"))  # a moment after: the files, not the world
    assert "boat_manual.txt is in" in said(events)


def test_why_a_file_stayed_or_moved_is_answered_from_what_was_decided_about_it(worked, home):
    events = list(worked.send("why didn't you move the phone bill?"))
    assert said(events) == (f"phone_bill.txt stayed in {home / 'Downloads'}: {LEFT}: a bill. If that's "
                            'wrong, tell me how its rule should change, or say "put <file> in <folder>" and I\'ll '
                            "move it and keep that as an example.")
    events = list(worked.send("why did you move the boat manual?"))
    assert f"I put boat_manual.txt in {home / 'Downloads' / 'Boat'} (just now), following its rule." in said(events)


def test_what_it_did_is_said_from_its_card_and_its_records(worked, home):
    text = said(list(worked.send("what did you do?")))
    how, job = parts.how(store.find_agent(NAME)), worked.chore_done()[-1]["text"]  # its card's line, and the record's
    assert text.startswith(f"{NAME} is on: {how[0].lower()}{how[1:]}")
    assert f"Lately: {job[0].lower()}{job[1:]} (just now). Undo is in your chores." in text and "boat_manual.txt" in job
    assert f"Left where they were: phone_bill.txt ({LEFT}: a bill)." in text


def test_a_file_put_somewhere_by_hand_is_moved_and_kept_as_an_example(worked, home):
    events = list(worked.send("put the phone bill in Bills"))
    assert said(events) == (f"Put phone_bill.txt in {home / 'Downloads' / 'Bills'}. {NAME} keeps that as an example "
                            "for later files. Undo is in your chores.")
    saved = store.find_agent(NAME)
    assert parts.choices_of(saved.slots) == ["Boat", "Garden", "Bills"]
    assert saved.slots["examples"] == [{"name": "phone_bill.txt", "choice": "Bills"}]
    events = list(worked.send("put the tax file in Taxes"))
    assert said(events) == "I can't see a file like that in Downloads. Which file do you mean? Its name is enough."
    # An order that isn't about a file at all is no order to the helper: it is answered as any message.
    events = list(worked.send("move the meeting to Friday"))
    assert said(events).endswith("Tokyo.")


def test_of_several_files_the_words_could_mean_the_one_they_name_best_is_moved(worked, home):
    downloads = home / "Downloads"
    # Two files that share most of their name: any shared word used to do, and the first by
    # name was taken, so the spring list was moved when the summer one was asked for.
    write(downloads, "price_list_spring.txt", "Prices for spring")
    write(downloads, "price_list_summer.txt", "Prices for summer")
    list(worked.send("put the summer price list in Prices"))
    assert (downloads / "Prices" / "price_list_summer.txt").is_file() and (downloads / "price_list_spring.txt").is_file()
    # A whole name typed out is that file, whatever else shares its words.
    write(downloads, "price_list_summer.txt", "Prices for summer, again")
    list(worked.send("put price_list_spring.txt in Old prices"))
    assert (downloads / "Old prices" / "price_list_spring.txt").is_file() and (downloads / "price_list_summer.txt").is_file()
    # Two that the words fit equally: the newer one, which is the one they just saw land.
    older, newer = write(downloads, "rota_november.txt", "Who works when"), write(downloads, "rota_december.txt", "Who works when")
    os.utime(older, (time.time() - 3600, time.time() - 3600))
    list(worked.send("put the rota in Staff"))
    assert (downloads / "Staff" / newer.name).is_file() and older.is_file()


def test_a_file_the_helper_put_in_the_wrong_folder_is_the_one_moved_when_they_say_where_it_belongs(worked, home):
    """The helper had put the summer price list in the wrong folder. "Put the summer price
    list in Staff" then moved the spring one: only files still loose in the watched folder
    could be meant, and the one that was named was no longer among them."""
    downloads = home / "Downloads"
    write(downloads, "price_list_spring.txt", "Prices for spring")
    write(downloads, "boat_price_list_summer.txt", "For the boat: prices for summer")
    worked.folderwatch.look()
    assert (downloads / "Boat" / "boat_price_list_summer.txt").is_file() and (downloads / "price_list_spring.txt").is_file()
    events = list(worked.send("put the summer price list in Prices"))
    assert (downloads / "Prices" / "boat_price_list_summer.txt").is_file()
    assert not (downloads / "Boat" / "boat_price_list_summer.txt").exists() and (downloads / "price_list_spring.txt").is_file()
    assert f"Put boat_price_list_summer.txt in {downloads / 'Prices'}." in said(events)
    saved = store.find_agent(NAME)
    assert {"name": "boat_price_list_summer.txt", "choice": "Prices"} in saved.slots["examples"]
    # Undo puts it back where it was taken from: the folder the helper had put it in.
    job = next(job for job in worked.chore_done() if "boat_price_list_summer.txt" in job["text"] and "Prices" in job["text"])
    assert worked.undo_move(job["sort"]) == 1 and (downloads / "Boat" / "boat_price_list_summer.txt").is_file()
    # A file that was moved and is no longer there (they took it out themselves) is not one that can be meant.
    for gone in ("boat_manual.txt", "boat_price_list_summer.txt"):
        (downloads / "Boat" / gone).unlink()
    events = list(worked.send("put the boat manual file in Manuals"))
    assert "I can't see a file like that" in said(events) and not (downloads / "Manuals").exists()
    assert (downloads / "price_list_spring.txt").is_file() and (downloads / "phone_bill.txt").is_file()


def test_go_through_them_takes_what_has_landed_and_says_what_was_looked_at_when_nothing_has(worked, home):
    downloads = home / "Downloads"
    events = list(worked.send("go through the new files"))
    assert one(events, Result).text == (f"Nothing new has landed in Downloads since {NAME} was switched on. Looked at "
                                        f"already: phone_bill.txt ({LEFT}: a bill). Say \"put <file> in "
                                        "<folder>\" to place one yourself, or name a file to have it looked at again.")
    write(downloads, "plants.txt", "A plant list for spring")
    events = list(worked.send("I just downloaded a file"))
    assert one(events, Result).text == "Moved 1 file: Garden 1. Undo is in your chores."
    assert (downloads / "Garden" / "plants.txt").is_file()
    # Everything in the folder, the files from before it too, is counted and asked about first.
    events = list(worked.send("go through everything in downloads"))
    question = one(events, Question)
    assert (question.id, question.choices) == (ALL_NOW, [GO_THROUGH, LEAVE_THEM]) and not any(
        isinstance(event, Result) for event in events)
    assert question.text == (f"There is 1 file in Downloads, the ones from before {NAME} was switched on as well. Go "
                             "through all of them now?")
    events = list(worked.choose(ALL_NOW, GO_THROUGH))
    assert one(events, Result).text == f"Nothing moved. 1 left where it was: {LEFT}."


def test_a_helper_that_is_off_is_never_run_over_a_folder_it_has_not_been_watching(engine, home):
    # Switched off, there is no "since it was switched on": a pass would take every file for a new one.
    e = engine(routes=Route("chat"))
    watching(e, home, on=False)
    old = write(home / "Downloads", "boat_manual.txt", "How to start the boat engine")
    events = list(e.send("organize it"))
    question = one(events, Question)
    assert question.id == FIX_AGENT and "switched off" in question.text and old.is_file()
    list(e.choose(FIX_AGENT, LEAVE_IT))
    assert not e.folderwatch.is_on(NAME) and old.is_file()
    events = list(e.send("go through everything"))  # said in so many words, it is theirs to ask for, and asked first
    assert one(events, Question).text == (f"There is 1 file in Downloads. {NAME} is switched off, so it hasn't been "
                                          "watching. Go through all of them now?") and old.is_file()
    events = list(e.send("yes, go ahead"))
    assert one(events, Result).text.startswith("Moved 1 file: Boat 1.")


def test_a_yes_or_no_typed_under_switch_it_on_answers_it_like_its_button(engine, home):
    e = engine(routes=Route("chat"))
    watching(e, home, on=False)
    list(e.send("organize it"))
    events = list(e.send("no thanks"))
    assert said(events) == "Okay, I left it as it is." and not e.folderwatch.is_on(NAME) and e.ollama.chats == []
    assert said(list(e.send("no thanks"))).endswith("Tokyo.")  # nothing is waiting any more: a message like any other
    list(e.send("organize it"))
    events = list(e.send("Yes please!"))
    assert e.folderwatch.is_on(NAME) and f"{NAME} is on." in said(events) and lists(events).active == [NAME]


def test_only_a_whole_yes_or_no_answers_a_question_that_has_buttons(engine, home):
    from concierge.engine import _plain_answer

    assert _plain_answer("yes") is True and _plain_answer("Sure!") is True and _plain_answer("네") is True
    assert _plain_answer("no") is False and _plain_answer("No thanks.") is False
    assert _plain_answer("yes but only the pdfs") is None and _plain_answer("go through them") is None
    # With more after it, it is a message of its own: its first word switches nothing on.
    e = engine(routes=Route("chat"))
    watching(e, home, on=False)
    list(e.send("organize it"))
    events = list(e.send("yes but what is the capital of Japan?"))
    assert not e.folderwatch.is_on(NAME) and said(events).endswith("Tokyo.")


def test_a_helper_that_writes_notes_answers_in_its_own_words(engine, home):
    e = engine(routes=Route("chat"))
    watching(e, home, NOTE)
    downloads = home / "Downloads"
    write(downloads, "boat_manual.txt", "How to start the boat engine")
    write(downloads, "phone_bill.txt", "Your bill for March")
    events = list(e.send("go through them now"))
    assert one(events, Result).text == (f"Wrote about 1 file in {NAME}.md. Nothing written about 1 file: "
                                        f"{fw.NOTHING_ASKED}.")
    assert "boat_manual.txt" in (downloads / f"{NAME}.md").read_text(encoding="utf-8")
    assert f"{NAME} writes in {downloads / (NAME + '.md')}." in said(list(e.send("where is the folder?")))
    # "Put X in Y" is for a helper that moves files; with none, it is a message like any other.
    assert said(list(e.send("put the phone bill in Bills"))).endswith("Tokyo.")


def test_a_question_about_the_work_goes_to_the_chat_model_with_the_facts_and_never_to_the_web(worked, home):
    events = list(worked.send("is it still watching my downloads?"))
    assert said(events).endswith("Tokyo.")
    note = worked.chat.jobs
    assert note.startswith("YOUR CHORES RIGHT NOW") and f"- {NAME} is on: it watches {home / 'Downloads'}." in note
    assert f'Its rule: "{RULE}"' in note  # the model that answers is on this computer
    assert f"- boat_manual.txt was put in {home / 'Downloads' / 'Boat'}" in note
    assert "- phone_bill.txt stayed in" in note and f"{LEFT}: a bill" in note
    # How such helpers work is said in the catalog's own facts, for a question about them only.
    assert all(f"- {fact}" in note for fact in parts.WHENS[NEW_FILE].facts + parts.THENS[MOVE].facts)
    assert "- No model here can see" in note
    list(worked.send("what's the capital of Japan?"))
    assert "YOUR CHORES RIGHT NOW" in worked.chat.jobs and "Its rule" not in worked.chat.jobs
    assert parts.WHENS[NEW_FILE].facts[0] not in worked.chat.jobs
    assert NoirEngine._lookup_kind(worked, "can it also sort the latest pictures today?") is None
    assert NoirEngine._lookup_kind(worked, ASKED) is None  # a request for new work is never a lookup


def test_a_message_about_their_own_folders_files_or_photos_is_never_looked_up_on_the_web(engine, home):
    """A request to tidy the Downloads folder, typed in Korean with a question mark, and one
    about hundreds of photos nobody could find were both asked "Shall I look it up on the web?"."""
    e = engine(routes=Route("chat"))
    for text in ("다운로드 폴더가 너무 지저분해요. 좀 정리해 줄 수 있어요?",
                 "i have hundreds of photos of my hives in my pictures folder and i can never find the ones from one inspection",
                 "can you help me keep my downloads folder tidy", "why are there so many screenshots on my desktop?",
                 "which of our documents are the newest?", "바탕화면에 있는 사진 좀 보여줘"):
        assert e._lookup_kind(text) is None, text
    # What is out in the world is still looked up.
    assert e._lookup_kind("is it going to rain in seattle tomorrow") == research.WEATHER
    assert e._lookup_kind("show me a picture of a kingfisher") == research.IMAGES


def test_of_the_files_on_record_a_question_is_answered_about_the_ones_it_names_best(worked, home):
    """ "Where did the velo invoice go?" was answered with every invoice there was, and a
    delivery note from Velo as well."""
    downloads = home / "Downloads"
    for name in ("boat_engine_invoice.txt", "boat_sail_invoice.txt", "boat_engine_note.txt"):
        write(downloads, name, "For the boat")
    worked.folderwatch.look()
    text = said(list(worked.send("where did the boat engine invoice go?")))
    assert text == f"boat_engine_invoice.txt is in {downloads / 'Boat'} (just now). Undo is in your chores."
    text = said(list(worked.send("why did you move the boat sail invoice?")))
    assert "boat_sail_invoice.txt" in text and "boat_engine" not in text


def test_a_plan_model_gets_the_record_but_never_the_rule(worked, home):
    class Plan:
        asked = []

        def chat(self, model, messages, think=None, options=None, keep_alive=None):
            self.asked.append(messages[-1]["content"])
            yield "It is."

        def capabilities(self, name):
            return []

    worked.chat.talker = Plan()
    worked.talker_name = "Claude"
    events = list(worked.send("is it still watching my downloads?"))
    assert "It is." in said(events)
    sent = Plan.asked[-1]
    assert sent.startswith("YOUR CHORES RIGHT NOW") and "The user asks: is it still watching my downloads?" in sent
    assert "Its rule" not in sent and RULE not in sent  # a rule is their own words about their own things
    # What the designing conversation sends such a model, and no more: places by name, and
    # of each file only its kind. Not a file's name, a whole path with the user's name in
    # it, or what a file was read as.
    assert f"- a .txt file was put in {Path('Downloads') / 'Boat'} (just now)." in sent
    assert f"- a .txt file stayed in Downloads: {LEFT}." in sent
    assert "boat_manual" not in sent and "phone_bill" not in sent and str(home) not in sent and "a bill" not in sent
    assert any("folders by name and no file's name" in event.text for event in events if isinstance(event, Thinking))
    # The record went with that one question: its memory of the chat keeps what was asked.
    assert worked.chat.history[-2] == {"role": "user", "content": "is it still watching my downloads?"}
    list(worked.send("thanks! and what's a good name for a cat?"))
    assert "a .txt file" not in json.dumps(Plan.asked[-1]) and "YOUR CHORES" not in Plan.asked[-1]


def test_a_question_that_only_has_a_word_for_files_in_it_is_answered_the_usual_way(worked, home):
    """ "How do I zip a folder on windows?" went to a plan model with the record of every
    file the helper had handled, and with Auto it was sent there for that reason alone."""
    class Plan:
        asked = []

        def chat(self, model, messages, think=None, options=None, keep_alive=None):
            self.asked.append(messages[-1]["content"])
            yield "Right-click it and pick Compressed folder."

        def capabilities(self, name):
            return []

    worked.chat.talker = Plan()
    worked.talker_name = "Claude"
    events = list(worked.send("how do I zip a folder on windows?"))
    assert "Compressed folder" in said(events) and not any("your chores" in event.text for event in events
                                                            if isinstance(event, Thinking))
    assert "YOUR CHORES" not in Plan.asked[-1] and "boat_manual" not in Plan.asked[-1]


def test_those_words_mean_nothing_special_without_such_a_helper(engine, home):
    e = engine(routes=Route("chat"))
    store.save(text_card("Word fixer"))
    for text in ("where is the file?", "what did you do?", "organize it", "why didn't you move the bill?"):
        assert said(list(e.send(text))).endswith("Tokyo."), text
    assert e.chat.jobs == ""


def test_trouble_with_a_helper_for_files_is_answered_from_whether_it_is_on_and_what_it_did(worked, home):
    text = said(list(worked.send(f"{NAME} isn't working")))
    assert text.startswith(f"{NAME} is on:") and "Left where they were: phone_bill.txt" in text
    worked.folderwatch.switch(store.find_agent(NAME), False)
    question = one(list(worked.send(f"{NAME} isn't working")), Question)
    assert question.id == FIX_AGENT and "switched off right now" in question.text
    list(worked.choose(FIX_AGENT, SWITCH_IT_ON))
    assert worked.folderwatch.is_on(NAME)


def test_it_is_switched_by_words_like_any_other(worked, home):
    events = list(worked.send(f"turn off {NAME}"))
    assert not worked.folderwatch.is_on(NAME) and said(events) == f"{NAME} is off." and lists(events).active == []
    events = list(worked.send(f"turn on {NAME}"))
    assert worked.folderwatch.is_on(NAME)
    assert said(events) == f"{NAME} is on. {parts.how(store.find_agent(NAME))} Only files that land from now on are handled."


def test_asked_by_name_it_goes_through_the_folder_or_answers(worked, home):
    write(home / "Downloads", "plants.txt", "A plant list for spring")
    events = list(worked._run_agent(NAME, "go through the new files", f"{NAME}: go through the new files"))
    assert one(events, Result).text == "Moved 1 file: Garden 1. Undo is in your chores."
    events = list(worked._run_agent(NAME, "is it on?", f"is {NAME} on?"))
    assert said(events).endswith("Tokyo.") and "YOUR CHORES RIGHT NOW" in worked.chat.jobs


# -------------------------------- a file put somewhere by hand can become the rule

BILLS_TOO = "Anything about the boat goes in Boat, plant lists go in Garden, and bills go in Bills."
PLACED = "put the phone bill in Bills"


def test_after_a_file_is_put_somewhere_by_hand_it_is_asked_whether_that_should_be_the_rule(engine, home):
    script = Script(dict(status=NOTHING_MISSING, say="Bills go in Bills from now on.", instruction=BILLS_TOO,
                         choices="Boat, Garden, Bills"))
    e = engine(script.model())
    watching(e, home)
    downloads = home / "Downloads"
    write(downloads, "phone_bill.txt", "Your bill for March")
    events = list(e.send(PLACED))
    # What it does today comes first, as it was: the file is moved and kept as an example.
    assert said(events).startswith(f"Put phone_bill.txt in {downloads / 'Bills'}. {NAME} keeps that as an example "
                                   "for later files. Undo is in your chores.")
    assert store.find_agent(NAME).slots["examples"] == [{"name": "phone_bill.txt", "choice": "Bills"}]
    # Then one question, with two buttons. Nothing is begun before they say yes.
    question = events[-1]
    assert (question.id, question.choices) == (RULE_FROM_MOVE, [CHANGE_THE_RULE, JUST_THIS_ONE])
    assert question.text == (f"Should files like phone_bill.txt always go in Bills? If so, we put that into the rule of "
                             f"{NAME} together.")
    assert not e.designer.active and script.turns == []

    events = list(e.choose(RULE_FROM_MOVE, CHANGE_THE_RULE))
    # A yes opens the conversation in which the helper is changed, with one plain sentence
    # that says what they did and that files like it should go there.
    assert e.designer.active and e.designer.sketch.editing and e.designer.sketch.replaces == NAME
    assert script.turns[0] == [{"role": "user", "content": f'I put phone_bill.txt in Bills myself (I said: "{PLACED}"). '
                                                           "Files like it should always go in Bills."}]
    # It ends as any change does: a try-out, the card with Save changes, and nothing saved before that.
    assert one(events, Result).agent == designer_mod.TRY_OUT and one(events, AgentCard).actions[0] == "Save changes"
    assert store.find_agent(NAME).slots["instruction"] == RULE
    events = list(e.choose(CARD, "Save changes"))
    saved = store.find_agent(NAME)
    assert saved.slots["instruction"] == BILLS_TOO and parts.choices_of(saved.slots) == ["Boat", "Garden", "Bills"]
    assert saved.slots["examples"] == [{"name": "phone_bill.txt", "choice": "Bills"}]  # what they taught it stays
    assert f"Saved the changes to {NAME}." in said(events) and e.folderwatch.active[NAME].slots["instruction"] == BILLS_TOO


def test_no_file_is_asked_about_twice_and_a_no_stands_for_that_helper_while_the_app_is_open(engine, home):
    e = engine(Script(ASKING).model())
    watching(e, home)
    downloads = home / "Downloads"
    write(downloads, "phone_bill.txt", "Your bill for March")
    assert list(e.send(PLACED))[-1].id == RULE_FROM_MOVE
    # Left unanswered, put back and placed again: the same file is not asked about a second time.
    assert e.undo_move(e.chore_done()[-1]["sort"]) == 1 and (downloads / "phone_bill.txt").is_file()
    events = list(e.send(PLACED))
    assert "Put phone_bill.txt in" in said(events) and not any(isinstance(event, Question) for event in events)
    # Another file is asked about. A no is said in a word, and kept.
    write(downloads, "gas_letter.txt", "Your bill for gas")
    assert list(e.send("put the gas letter in Bills"))[-1].id == RULE_FROM_MOVE
    events = list(e.choose(RULE_FROM_MOVE, JUST_THIS_ONE))
    assert said(events) == "Okay, just this one." and not e.designer.active
    write(downloads, "water_note.txt", "Your bill for water")
    events = list(e.send("put the water note in Bills"))
    assert "Put water_note.txt in" in said(events) and not any(isinstance(event, Question) for event in events)
    assert said(list(e.choose(RULE_FROM_MOVE, CHANGE_THE_RULE))) == "That question has already been answered."
    assert not e.designer.active and store.find_agent(NAME).slots["instruction"] == RULE
    # Another helper of theirs is still asked about: the no was for that one.
    other = card(home / "Documents", name="Desk sorter")
    store.save(other)
    e.folderwatch.refresh(store.list_agents())
    write(home / "Documents", "old_lease.txt", "The lease for the flat")
    assert list(e.send("put the old lease in Home"))[-1].id == RULE_FROM_MOVE


def test_a_yes_or_no_typed_right_under_that_question_answers_it(engine, home):
    downloads = home / "Downloads"

    def asked():
        e = engine(Script(dict(status=STILL_ASKING, say="Which bills do you mean?")).model())
        watching(e, home)
        write(downloads, "phone_bill.txt", "Your bill for March")
        assert list(e.send(PLACED))[-1].id == RULE_FROM_MOVE
        return e

    e = asked()
    assert said(list(e.send("No thanks."))) == "Okay, just this one." and NAME in e.rule_refused
    e = asked()
    events = list(e.send("Yes please"))
    assert e.designer.active and e.designer.sketch.replaces == NAME and one(events, Question).id == DESIGN
    # Only right under it: after another message, a yes is a message like any other.
    e = asked()
    list(e.send("how do I get to the harbour?"))
    events = list(e.send("yes"))
    assert said(events) == "Tokyo." and not e.designer.active and e.ruling is None


def test_it_is_not_asked_without_a_model_nor_while_another_helper_is_worked_out_or_waits(engine, home):
    # Nobody can talk a change through: what was done is said, and nothing more.
    e = engine(None)
    watching(e, home)
    write(home / "Downloads", "phone_bill.txt", "Your bill for March")
    events = list(e.send(PLACED))
    assert "Put phone_bill.txt in" in said(events) and not any(isinstance(event, Question) for event in events)
    assert e.ruling is None and e.rule_asked == set()
    # In the middle of working another helper out, the move is done and that helper waits:
    # the one question under it is about the helper, not a second one about the file.
    script = Wanders(ASKING, asides=(PLACED,))
    e = engine(script.model())
    watching(e, home)
    write(home / "Downloads", "phone_bill.txt", "Your bill for March")
    list(e.send(ASKED))
    events = list(e.send(PLACED))
    assert "Put phone_bill.txt in" in said(events) and e.designer.aside is not None
    assert [event.id for event in events if isinstance(event, Question)] == [CARRY_ON] and e.ruling is None
    # And with one waiting: the same.
    write(home / "Downloads", "gas_letter.txt", "Your bill for gas")
    events = list(e.send("put the gas letter in Bills"))
    assert "Put gas_letter.txt in" in said(events)
    assert [event.id for event in events if isinstance(event, Question)] == [CARRY_ON] and e.ruling is None


def test_a_model_off_this_computer_reads_what_they_typed_and_the_folder_never_the_files_name(engine, home):
    script = Script(dict(status=STILL_ASKING, say="Which ones do you mean?"))
    e = engine(script.model(here=False))
    watching(e, home)
    write(home / "Downloads", "phone_bill.txt", "Your bill for March")
    list(e.send(PLACED))
    list(e.choose(RULE_FROM_MOVE, CHANGE_THE_RULE))
    assert script.turns[0] == [{"role": "user", "content": f'I put a file in Bills myself (I said: "{PLACED}"). Files '
                                                           "like it should always go in Bills."}]
    assert "phone_bill" not in json.dumps(script.turns)


# ------------------------------------------------------------- the words in code


def test_the_ways_people_ask_for_the_folder_to_be_gone_through():
    assert WANTS_PASS.search("can you move the files in downloads to where they belong")
    assert WANTS_PASS.search("go through everything in downloads") and WANTS_PASS.search(parts.SAMPLE_FILES)
    assert WANTS_PASS.search("handle them now") and not WANTS_PASS.search("how are you")
    assert WANTS_EVERYTHING.search("go through everything in downloads")
    assert not WANTS_EVERYTHING.search("organize it")


def test_questions_about_what_was_done_are_recognised():
    assert WANTS_WHERE.search("where did they go?") and WANTS_WHERE.search("where did it end up")
    assert WANTS_WHERE.search("where did you write that?") and not WANTS_WHERE.search("where is Seoul")
    assert ABOUT_CHORES.search("what do you do when something new lands?")
    for text in ("why didn't you move the letter?", "why is my statement still in downloads?",
                 "why did you put my letter in Garden", "Why did you not move the files in downloads"):
        assert WANTS_WHY.search(text), text
    assert not WANTS_WHY.search("why is the sky blue")
    assert not WANTS_STATUS.search("why didn't you move the letter?")
    assert _mentions("why is my statement still in downloads?", "BankStatement.pdf")
    assert _mentions("where did you put the boat manual", "Boat - Manual.pdf")
    assert not _mentions("why didn't you move the letter?", "Boat - Manual.pdf")


def test_a_question_about_the_work_is_a_question_not_a_change_or_a_new_helper():
    from concierge.agents.router import WANTS_NEW, wants_change

    for text in ("is it still on? what does it watch", "can it also sort pictures?", "which files did you move today"):
        assert ABOUT_CHORES.search(text), text
    assert not ABOUT_CHORES.search("who won the election")
    asks = "can it also sort pictures?"
    assert WANTS_ANSWER.search(asks) and not WANTS_NEW.search(asks)
    assert not wants_change(asks, card(Path("C:/x/Downloads")))
    assert WANTS_NEW.search("make a new agent that sorts my pictures")  # that one is a helper to make
    assert not WANTS_ANSWER.search("organize it")
    new_work = "when a pdf lands in my downloads, write me a few lines about it"
    assert ABOUT_CHORES.search(new_work) and ASKS_FOR_WORK.search(new_work)  # never taken for a question about a chore
    assert not ASKS_FOR_WORK.search("is it still on?") and not ASKS_FOR_WORK.search("can it also sort pictures?")


def test_the_words_for_placing_a_file():
    assert WANTS_PLACE.match("put output.pdf in Letters").groups() == ("output.pdf", "Letters")
    assert WANTS_PLACE.match("Move the scan to Taxes please.").groups() == ("the scan", "Taxes")
    assert WANTS_PLACE.match("can you move the scan to the Taxes folder").groups() == ("the scan", "Taxes")
    assert WANTS_PLACE.match("put it into a folder called Misc").groups() == ("it", "Misc")
    assert not WANTS_PLACE.match("where did you put output.pdf")


def test_standing_work_on_new_files_is_a_helper_to_make_decided_in_code():
    class NeverAsked:
        def chat_json(self, *a, **k):
            raise AssertionError("the model was asked")

    for text in (ASKED, "every time a file arrives in Downloads, put it where it belongs",
                 "tidy my downloads into folders as I download them",
                 "when a pdf lands in my downloads, write me a few lines about it in a notes file",
                 "whenever a picture is saved to my desktop, move it to Pictures",
                 "I want something to happen each time a new file appears in Documents"):
        where = route(NeverAsked(), "noir", text, {}, [])
        assert (where.kind, where.blueprint, where.request) == ("idea", None, text), text  # a helper is wanted: not which
    # A question about how things are, a file that is only new, and a story about a problem
    # with those words in it are no such request: they are left to the model.
    model = BuiltIn()
    for text in ("what happens when a file lands in my downloads?", "how do I make a new document in Word?",
                 "when I download the file it shows an error", "once I downloaded the update, my screen went black",
                 "every time the window appears I get a warning"):
        assert route(model, "noir", text, {}, []).kind == "chat", text
    assert route(NeverAsked(), "noir", "how do I make a helper for each new file that lands?", {}, []).kind == "idea"


def test_a_helper_for_files_is_known_by_its_name_not_by_the_words_of_its_rule():
    from concierge.agents.router import refers_to

    sorter = card(Path("C:/x/Downloads"))
    fixer = text_card("Word fixer")
    assert refers_to("should I leave my bills unpaid", [sorter, fixer]) is None  # "leave", "bills": words of its rule
    assert refers_to("the paper sorter keeps things tidy", [sorter, fixer]) is sorter
    assert refers_to("the spelling is still wrong", [sorter, fixer]) is fixer  # a text card's own words still count


def test_the_chore_the_chores_page_suggests_is_one_a_helper_can_be_made_for(home):
    class NeverAsked:
        def chat_json(self, *a, **k):
            raise AssertionError("the model was asked")

    page = (Path(__file__).parent.parent / "concierge" / "ui" / "web" / "chores.js").read_text(encoding="utf-8")
    suggested = re.search(r'placeholder = "Tell Noir a chore, like: ([^"]+)"', page).group(1)
    # Typed as it stands, it is standing work on a folder's new files: a helper to work out, decided in code.
    where = route(NeverAsked(), "noir", suggested, {}, [])
    assert (where.kind, where.request) == ("idea", suggested)
    assert "name my downloads" not in page  # what it suggested before: no helper renames a file


# --------------------------------------------------------- outside the contract


def test_the_lists_get_each_helpers_line_and_what_it_is_doing(engine, home):
    e = engine()
    watching(e, home)
    fixer = text_card("Word fixer", WHILE_ON)
    store.save(fixer)
    store.save(text_card("Chat fixer"))
    e.folderwatch._clock = time.time  # on the real clock, a file that has just landed still waits
    landed = write(home / "Downloads", "boat_manual.txt", "How to start the boat engine")
    e.folderwatch.look()
    rows = {row["name"]: row for row in e.chore_agents()}
    assert sorted(rows) == [NAME, "Word fixer"]  # one that is only asked in the chat is no chore
    row = rows[NAME]
    assert sorted(row) == ["how", "kind", "left", "name", "now", "on", "since", "why_off"]
    assert row["on"] is True and row["how"] == parts.how(store.find_agent(NAME)) and row["since"] > 0
    assert row["why_off"] == ""  # it is on; and switched off by hand there is no reason to give either
    # What it is doing this moment is the folder watcher's own line, passed on as it is.
    assert row["now"] == e.folderwatch.status(NAME) and "boat_manual.txt" in row["now"] and row["left"] is None
    assert e.chore_doing() == e.folderwatch.doing() and e.chore_doing().startswith(f"{NAME}: ")
    assert rows["Word fixer"] == {"name": "Word fixer", "kind": "highlight", "on": False, "how": parts.how(fixer)}
    landed.unlink()
    (home / "Downloads" / "setup.exe").write_bytes(b"MZ" * 64)
    e.folderwatch._clock = lambda: time.time() + 3600
    e.folderwatch.look()
    left = e.chore_agents()[0]["left"]
    assert left["name"] == "setup.exe" and left["why"]  # what it looked at and left, for the list
    assert e.chore_doing() == ""


def test_what_was_done_can_be_listed_and_undone_and_an_agents_page_comes_from_its_card(worked, home):
    job = worked.chore_done()[-1]
    assert "boat_manual.txt" in job["text"] and job["agent"] == NAME and job["undo"] is True
    assert worked.undo_move(job["sort"]) == 1 and (home / "Downloads" / "boat_manual.txt").is_file()
    assert worked.undo_move("no such job") == 0
    page = worked.details(NAME)
    assert page == parts.describe(store.find_agent(NAME)) and page["does"] == RULE and page["sample"] == parts.SAMPLE_FILES
    assert worked.details("Nobody") == {}


def test_the_help_me_switch_and_the_agent_list_go_by_what_a_card_is_made_of(engine, home):
    e = engine()
    watching(e, home, on=False)
    store.save(text_card("Word fixer", WHILE_ON))
    store.save(text_card("Chat fixer"))
    found = lists(list(e.switch_agent(NAME, True)))
    assert found.agents == ["Chat fixer", NAME, "Word fixer"] and found.switchable == [NAME, "Word fixer"]
    assert found.active == [NAME] and e.folderwatch.is_on(NAME)
    assert lists(list(e.switch_agent("Word fixer", True))).active == [NAME, "Word fixer"]
    e.quick = None  # where highlights can't be read, only the folder's helper can be switched
    assert lists(list(e.switch_agent(NAME, False))).switchable == [NAME]
    assert [name for name, _rule in e._helpers()] == ["Chat fixer"]  # the Spot offers only what is asked in the chat


def test_deleting_a_helper_forgets_what_was_kept_about_its_folder(worked, home):
    assert worked.folderwatch.skipped[NAME] and worked.folderwatch.made[NAME] == ["Boat"]
    worked.deleting = NAME
    events = list(worked._finish_delete(DELETE_IT))
    assert not worked.folderwatch.is_on(NAME) and worked.folderwatch.skipped == {} and worked.folderwatch.made == {}
    assert NAME not in worked.folderwatch.since and store.find_agent(NAME) is None and f"Deleted {NAME}." in said(events)


# ------------------------------------------------------------------- old agents


def test_an_agent_of_the_last_version_comes_back_as_a_card_switched_off_and_is_said_once(home, monkeypatch):
    """The user's own: made before there were cards, on when the app last closed, with a
    move that can still be undone."""
    from concierge.quick import tidy

    data, downloads, sorted_into = home / "data", home / "Downloads", home / "Desktop" / "바탕 화면"
    (sorted_into / "Boat").mkdir(parents=True)
    moved = sorted_into / "Boat" / "boat_manual.txt"
    moved.write_text("How to start the boat engine", encoding="utf-8")
    sort_id = tidy.record_moves(data / "organizer.json", [{"from": str(downloads / "boat_manual.txt"), "to": str(moved)}],
                                agent="File organizer")
    (data / "organizer_done.json").write_text(json.dumps([{"when": time.time(), "text": "Put boat_manual.txt in Boat",
                                                           "undo": True, "details": "", "sort": sort_id,
                                                           "agent": "File organizer", "where": str(moved.parent)}]),
                                              encoding="utf-8")
    (data / "organizer_state.json").write_text(json.dumps({"on": ["File organizer"], "made": {"File organizer": ["Boat"]},
                                                           "seen": {"File organizer": []}, "since": {"File organizer": 1.0}}),
                                               encoding="utf-8")
    store.save(store.Agent("File organizer", "organizer", {"folder": str(downloads), "into": str(sorted_into),
                                                           "groups": "Decide as you go", "by": "What's inside each file",
                                                           "name": "File organizer"}))

    class SetUp(BuiltIn):
        def ensure_running(self):
            pass

        def has_model(self, name):
            return name == "noir"

    monkeypatch.setattr(hardware, "detect", lambda: report(16.0))
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    e = NoirEngine(SetUp())
    started = list(e.startup())
    agent = store.find_agent("File organizer")
    assert agent.blueprint == CUSTOM and parts.watches(agent) and parts.then_of(agent.slots) == MOVE
    assert agent.slots["folder"] == str(downloads) and agent.slots["into"] == str(sorted_into)
    assert parts.choices_of(agent.slots) == ["Boat"] and agent.slots["instruction"]
    found = lists(started)
    assert found.switchable == ["File organizer"] and found.active == [] and not e.folderwatch.is_on("File organizer")
    assert e.chore_done()[-1]["undo"] is True  # its moves can still be undone
    assert noir.load_state()[CHANGED_HELPERS] == ["File organizer"]
    # Its line in the chores list says why it is off, before a word is said in the chat.
    row = e.chore_agents()[0]
    assert row["on"] is False and row["why_off"] == NEEDS_TALKING

    def line() -> str:
        return chores.listing({}, e.chore_done(), e.chore_agents(), [])["chores"][1]["last"]

    assert line() == "Off: its rule needs talking through"

    # Closed before a word was said: the next start still knows it has to be told.
    e.close()
    e = NoirEngine(SetUp())
    list(e.startup())
    assert e.changed_over == ["File organizer"]
    e.book = ChatBook(None)
    text = said(list(e.send("hello")))
    assert text.startswith("File organizer works a new way since this update") and "switched off for now" in text
    assert agent.slots["instruction"] in text and text.endswith("Tokyo.")
    # Nobody here can talk a rule through, so it is not told to say "change ...", which
    # would only be refused: it can be switched on as it is.
    assert 'Say "change File organizer"' not in text and "You can switch it on as it is" in text
    assert "works a new way" not in said(list(e.send("hello again")))  # once
    # Said once in the chat, and the list goes on saying it: the names stay in the app's state.
    assert noir.load_state()[CHANGED_HELPERS] == noir.load_state()[CHANGED_TOLD] == ["File organizer"]
    assert line() == "Off: its rule needs talking through"
    assert e.undo_move(sort_id) == 1 and (downloads / "boat_manual.txt").is_file()
    e.close()

    # Another start: the chat does not say it a second time, and the line is still there.
    e = NoirEngine(SetUp())
    list(e.startup())
    e.book = ChatBook(None)
    assert e.changed_over == [] and e.changed_off == ["File organizer"]
    assert "works a new way" not in said(list(e.send("hello")))
    assert line() == "Off: its rule needs talking through"
    # Until they switch it on. Switched off again by their own hand, there is no reason to give.
    list(e.toggle_agent("File organizer"))
    assert e.folderwatch.is_on("File organizer") and e.chore_agents()[0]["why_off"] == ""
    assert CHANGED_HELPERS not in noir.load_state() and CHANGED_TOLD not in noir.load_state()
    list(e.toggle_agent("File organizer"))
    assert not e.folderwatch.is_on("File organizer") and e.chore_agents()[0]["why_off"] == "" and "Off:" not in line()
    e.close()


def test_a_card_from_before_cards_could_say_what_they_leave_out_goes_on_working_as_it_did(home, monkeypatch):
    """The user's own kind of card. Text already in Korean was left alone because code read
    the rule for the word "translate"; no code does that any more, so the card is given the
    setting once, at the first start, without a word: nothing about it changed for them."""
    saved = {"instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT,
             "name": "Korean Translator"}
    store.save(store.Agent("Korean Translator", CUSTOM, dict(saved)))
    store.save(text_card("Word fixer", WHILE_ON))  # one whose rule says nothing of a language

    class SetUp(BuiltIn):
        def ensure_running(self):
            pass

        def has_model(self, name):
            return name == "noir"

    monkeypatch.setattr(hardware, "detect", lambda: report(16.0))
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    e = NoirEngine(SetUp())
    started = list(e.startup())
    card = store.find_agent("Korean Translator")
    assert card.slots == {**saved, "skip_language": "Korean"}
    assert store.find_agent("Word fixer").slots["skip_language"] == ""
    assert lists(started).switchable == ["Korean Translator", "Word fixer"]
    # Nothing to tell: it was not turned into anything, and it was not switched off.
    assert e.changed_over == [] and CHANGED_HELPERS not in noir.load_state()
    e.book = ChatBook(None)
    assert "works a new way" not in said(list(e.send("hello")))
    assert dict(e.details("Korean Translator")["facts"])["Leaves out"] == "Text that is already in Korean"
    # And it runs as it did: a highlight already in Korean is passed over, any other is worked on.
    shown = []
    bubble = type("B", (), {"show": lambda s, text, *a, **k: shown.append(text), "close": lambda s: None,
                            "pressed": lambda s, x, y: None, "hide": lambda s: None})
    e.quick = QuickAgents(e.ollama, "noir", None,
                          lambda *a: type("W", (), {"start": lambda s: None, "stop": lambda s: None})(), bubble,
                          highlighted=lambda: "")
    e.quick.switch(card, True)
    e.quick.handle(card, e.quick._serial, "안녕하세요 반가워요", (0, 0, 0, 0))
    assert shown == []
    e.quick.handle(card, e.quick._serial, "Good morning", (0, 0, 0, 0))
    assert shown == ["Working on it...", "Tokyo."]
    e.close()


def test_a_helper_an_update_switched_off_stops_saying_so_once_it_is_changed_or_gone(engine, home):
    e = engine()
    watching(e, home, on=False)
    store.save(card(home / "Documents", name="Desk sorter"))
    noir.save_state({"base_model": "x", CHANGED_HELPERS: [NAME, "Desk sorter", "One that is gone"], CHANGED_TOLD: [NAME]})
    e._keep_changed([])  # as at a later start: nothing new was turned into a card
    assert e.changed_off == [NAME, "Desk sorter"] and e.changed_over == ["Desk sorter"]
    assert noir.load_state()[CHANGED_HELPERS] == [NAME, "Desk sorter"]  # one that is gone has nothing left to say

    def why() -> dict:
        return {row["name"]: row["why_off"] for row in e.chore_agents()}

    assert why() == {NAME: NEEDS_TALKING, "Desk sorter": NEEDS_TALKING}
    # Changed by talking and saved: its rule has been looked at, whether or not it is switched on yet.
    changed = card(home / "Downloads", choices="Boat, Garden, Bills")
    store.save(changed)
    e.designer = Flow(created=changed, edited=True)
    list(e._made(iter([])))
    assert not e.folderwatch.is_on(NAME) and why() == {NAME: "", "Desk sorter": NEEDS_TALKING}
    assert noir.load_state() == {"base_model": "x", CHANGED_HELPERS: ["Desk sorter"]}
    # Deleted before the chat said a word about it: nothing is left to say, there or in the list.
    e.deleting = "Desk sorter"
    list(e._finish_delete(DELETE_IT))
    assert e.changed_off == [] and e.changed_over == [] and noir.load_state() == {"base_model": "x"}
    assert "works a new way" not in said(list(e.send("hello")))


def test_how_a_helper_an_update_switched_off_is_made_theirs_is_what_can_be_done_here(engine, home):
    """Told to say "change X" on a computer where nobody can design, they said it, and the
    change was refused: working a helper out needs a stronger model."""
    for design in (Script(ASKING).model(), None):
        e = engine(design, routes=Route("chat"))
        watching(e, home, on=False)
        e._keep_changed([NAME])
        text = said(list(e.send("hello")))
        if design is not None:
            assert f'Say "change {NAME}" and tell me what it should do with your files' in text
        else:
            assert f'Say "change {NAME}"' not in text and "You can switch it on as it is, if that rule is right." in text
            assert NO_DESIGNER[1:] in text
        noir.save_state({})
        store.delete(store.find_agent(NAME))


# ------------------------------------- what code takes for a helper's, and what it leaves


def _starters_saved():
    from concierge.agents.starters import install, load_starters

    return {starter.name: install(starter) for starter in load_starters()}


@pytest.mark.parametrize("text", ["can you organize all my desktop files too?",
                                  "could you sort the photos in my Pictures folder by year?",
                                  "put every new download in a folder by what it's about"])
def test_a_request_for_work_somewhere_else_or_on_new_files_is_never_taken_for_the_folder_of_a_helper_they_have(
        engine, home, text):
    """With a helper that moves Downloads' files, the first went through everything in
    Downloads, the second was told nothing new had landed there, and the third, the one the
    Chores page suggests, was asked "Which file do you mean?". None reached the conversation
    in which a helper is worked out."""
    from concierge.agents.router import IDEA_OPTION

    script = Script(ASKING)
    e = engine(script.model())
    e.ollama.choice = IDEA_OPTION  # what the router's model makes of it, when code leaves it to the model
    watching(e, home)
    downloads = home / "Downloads"
    old = [write(downloads, "old_boat_paper.txt", "the boat engine manual"), write(downloads, "plant_list.txt", "plant list")]
    events = list(e.send(text))
    assert all(path.is_file() for path in old) and not (downloads / "Boat").exists()
    assert e.designer.active and script.turns[0] == [{"role": "user", "content": text}]
    assert not any(isinstance(event, Result) for event in events)


@pytest.mark.parametrize("on", [False, True])
def test_a_question_with_the_words_for_going_through_a_folder_moves_nothing(engine, home, on):
    """ "How do I organize all my recipes?", with the helper off, moved what had been in
    Downloads all along: "organize" and "all my" were taken for "go through everything"."""
    e = engine(routes=Route("chat"))
    old = write(home / "Downloads", "boat_insurance.txt", "Insurance for the boat, renewed every May.")
    watching(e, home, on=on)
    for text in ("how do I organize all my recipes?", "I downloaded all my photos from the camera, how do I back them up?",
                 "how should I organize my week?", "organize my week for me"):
        events = list(e.send(text))
        assert old.is_file() and said(events).endswith("Tokyo.") and not any(
            isinstance(event, Question) for event in events), text
    # Named, a helper that works on a folder's files is not run over all of it by the words "all my" either.
    events = list(e._run_agent(NAME, "show me all my files", f"{NAME}, show me all my files"))
    assert old.is_file() and not any(isinstance(event, Result) and "Moved" in event.text for event in events)
    # Said in so many words, everything is counted and asked about first, and only a yes moves it.
    events = list(e._run_agent(NAME, "go through everything", f"{NAME}: go through everything"))
    assert one(events, Question).id == ALL_NOW and old.is_file()
    assert said(list(e.choose(ALL_NOW, LEAVE_THEM))) == "Okay, I left them where they are." and old.is_file()


def test_everyday_messages_are_not_taken_for_questions_about_a_helper_for_files(engine, home):
    e = engine(routes=Route("chat"))
    watching(e, home)
    for text in ("where should I go on vacation this summer?", "why do people still use fax machines?",
                 "what are you doing this weekend?", "put this word in a sentence: serendipity",
                 "how do I zip a folder on windows?"):
        events = list(e.send(text))
        # Answered as any message is (or offered a look on the web), never from the helper's record.
        assert NAME not in said(events) and "Downloads" not in said(events), text
        assert all(event.id == research.WEB for event in events if isinstance(event, Question)), text
    # Switched off, "how should I organize my week?" was asked "Switch it on?".
    e.folderwatch.switch(store.find_agent(NAME), False)
    assert said(list(e.send("how should I organize my week?"))) == "Tokyo."
    e.folderwatch.switch(store.find_agent(NAME), True)
    # Right after a word about the files, a question with "it" in it is still about the world
    # unless it asks where something is or went, or why.
    assert "Downloads" in said(list(e.send("where did my files go?")))
    events = list(e.send("is it going to rain in Seattle tomorrow?"))
    assert one(events, Question).id == research.WEB
    # Asked on its own, what the helpers are doing is still theirs to answer.
    assert said(list(e.send("what are you doing?"))).startswith(f"{NAME} is on:")


def test_delete_or_remove_with_no_helper_named_is_a_job_on_text(engine, home):
    e = engine(routes=Route("chat"))
    store.save(text_card("Word fixer"))
    store.save(text_card("Grammar checker"))
    for text in ("remove the duplicates from this list: apple, pear, apple", "remove the grammar mistakes"):
        events = list(e.send(text))
        assert said(events) == "Tokyo." and e.deleting is None, text
    # Named, or called by a word of its name with nothing more said, it is asked about first.
    for text in ("delete Word fixer", "please delete my fixer"):
        question = one(list(e.send(text)), Question)
        assert question.id == DELETE_AGENT and question.text.startswith("Delete Word fixer?"), text
    # With the word for a helper and no name, which one is asked.
    from concierge.engine import PICK_AGENT_TO_DELETE

    assert one(list(e.send("remove a helper")), Question).id == PICK_AGENT_TO_DELETE


def test_a_helper_is_switched_or_changed_in_code_only_when_the_message_names_it(engine, home):
    """By a word its rule shares, "start a helper for explaining code" switched the Highlight
    Explainer on, "stop explaining and just give me the answer" switched it off, and
    "explain why I should update my drivers" began a conversation that changed it."""
    from concierge.agents.router import IDEA_OPTION

    saved = _starters_saved()
    script = Script(ASKING)
    e = engine(script.model())
    events = list(e.send("start a helper for explaining code"))
    assert not e.quick.is_on("Highlight Explainer") and not any("This switches" in event.text for event in events
                                                               if isinstance(event, Thinking))
    e.quick.switch(saved["Highlight Explainer"], True)
    for text in ("stop explaining and just give me the answer", "can you explain why I should update my drivers?",
                 "should I fix the grammar in my essay before I send it?",
                 "can you keep it simple and explain what a mortgage is"):
        events = list(e.send(text))
        assert "Tokyo." in said(events) and not e.designer.active, text
        assert e.quick.is_on("Highlight Explainer"), text
    assert script.turns == []
    # Named, or called by a word of its name in so many words, it is switched and changed in code as before.
    assert said(list(e.send("turn off the explainer"))) == "Highlight Explainer is off."
    list(e.send("make the Grammar Fixer give shorter answers"))
    assert e.designer.active and e.designer.sketch.editing and e.designer.sketch.replaces == "Grammar Fixer"
    # A ready-made helper is taken only when it is all that is asked for: what one should do is worked out.
    e = engine(Script(ASKING).model())
    e.ollama.choice = IDEA_OPTION
    for agent in store.list_agents():
        store.delete(agent)
    list(e.send("add a summarizer for my downloads folder"))
    assert e.designer.active and store.list_agents() == []


def test_a_message_only_the_routers_model_took_for_a_change_is_answered_when_the_design_model_hands_it_back(
        engine, home):
    """What code does not decide about a helper is left to the router's model, which can
    still take "explain why I should update my drivers" for a change to the helper whose
    rule explains. The design model reads the helper and the message, and on the first turn
    may hand it back: it is answered as a chat, and nothing waits to be carried on."""
    text = "can you explain why I should update my drivers?"
    explainer = text_card("Word explainer", instruction="Explain the word simply.")
    store.save(explainer)
    script = Wanders(ASKING, asides=(text,))
    e = engine(script.model(), routes=Route("change_agent", agent="Word explainer"))
    events = list(e.send(text))
    assert "Tokyo." in said(events) and not e.designer.active and e.designer.aside is None
    assert not any(isinstance(event, Question) for event in events)  # no "Carry on with the changes?"
    assert e.designer.handoff is None and store.find_agent("Word explainer").slots == explainer.slots
    # A change the design model takes on is worked out as before.
    script = Script(ASKING)
    e = engine(script.model(), routes=Route("change_agent", agent="Word explainer"))
    list(e.send("could the explanations be a little shorter"))
    assert e.designer.active and e.designer.sketch.editing and e.designer.sketch.replaces == "Word explainer"


def test_trouble_that_names_no_helper_is_a_helpers_only_when_it_is_about_what_such_a_helper_does(engine, home):
    from concierge.quick.agents import ANSWERED

    e = engine(Script(ASKING).model(), routes=Route("chat"))
    fixer = text_card("Word fixer", WHILE_ON)
    store.save(fixer)
    e.quick.switch(fixer, True)
    e.quick.last["Word fixer"] = ANSWERED
    for text in ("my wifi isn't working", "my printer doesn't work"):
        events = list(e.send(text))
        assert said(events) == "Tokyo." and not e.designer.active, text
    explainer = _starters_saved()["Highlight Explainer"]
    store.delete(fixer)
    e.quick.refresh(store.list_agents())
    e.quick.switch(explainer, True)
    e.quick.last[explainer.name] = ANSWERED
    assert said(list(e.send("explain why my code doesn't work"))) == "Tokyo." and not e.designer.active
    # About what such a helper does, it is the one helper's trouble, and talked through.
    list(e.send("the bubble is not showing anything useful"))
    assert e.designer.active and e.designer.sketch.replaces == explainer.name


def test_a_helper_made_to_answer_in_the_chat_is_never_fixed_into_one_for_highlights(engine, home):
    """Told it "isn't working", a helper worked out to answer in the chat was offered a fix
    that made it work on every highlight in every program, and switched it on."""
    name = "Hive Log Formatter"
    store.save(text_card(name, instruction="Rewrite my rough notes as one tidy entry for my log."))
    e = engine(None, routes=Route("chat"))
    text = said(list(e.send("hive log formatter isnt working")))
    assert "ignores highlights" not in text and e.fixing is None
    assert f'it works when it is asked in the chat, by a message that starts with "{name}:"' in text
    assert store.find_agent(name).slots["when"] == IN_CHAT and not e.quick.is_on(name)
    # With a model to talk it through, the report opens a change, like any rule that isn't right.
    e = engine(Script(ASKING).model(), routes=Route("chat"))
    list(e.send("hive log formatter doesn't work, it leaves out the date"))
    assert e.designer.active and e.designer.sketch.editing and e.designer.sketch.replaces == name


def test_after_the_reply_to_someone_in_trouble_an_ok_makes_nothing_the_plain_way_either(engine, home):
    folder = home / "Documents" / "Papers"
    folder.mkdir()
    write(folder, "lease.txt", "The lease runs for two years.")
    e = engine(None, routes=Route("chat"))
    assert any(isinstance(event, AgentCard) for event in e._made(e.builder.start_for_folder(DOCUMENTS_QA, folder, "")))
    text = "I want to end my life"
    assert safety.crisis(text)
    list(e.send(text))
    assert not e.builder.active and not e.planner.active
    list(e.send("ok"))
    assert store.list_agents() == []


def test_a_file_name_they_typed_is_not_sent_to_a_model_off_this_computer(engine, home):
    script = Script(dict(status=STILL_ASKING, say="Which ones do you mean?"))
    e = engine(script.model(here=False))
    watching(e, home)
    write(home / "Downloads", "dentist_invoice_march.txt", "Your bill for March")
    list(e.send("put dentist_invoice_march.txt in Bills"))
    list(e.choose(RULE_FROM_MOVE, CHANGE_THE_RULE))
    assert script.turns[0] == [{"role": "user", "content": 'I put a file in Bills myself (I said: "put a file in Bills"). '
                                                           "Files like it should always go in Bills."}]
    assert "dentist" not in json.dumps(script.turns)


def test_a_question_asked_in_one_chat_is_not_answered_by_a_yes_typed_in_the_next(engine, home):
    e = engine(None, routes=Route("chat"))
    watching(e, home, on=False)
    assert one(list(e.send(f"{NAME} isn't working")), Question).id == FIX_AGENT
    list(e.new_chat())
    events = list(e.send("yes"))
    assert not e.folderwatch.is_on(NAME) and said(events) == "Tokyo."


def test_a_folder_added_while_a_helper_is_worked_out_leaves_that_one_first(engine, home):
    """It started the plain questions beside it, and Create it on their card went to the
    other conversation, which asked its question again: nothing was made, and both stayed."""
    folder = home / "Documents" / "Papers"
    folder.mkdir()
    write(folder, "lease.txt", "The lease runs for two years.")
    script = Script(ASKING)
    e = engine(script.model())
    list(e.send(ASKED))
    events = list(e.send_files("", [str(folder)]))
    assert not e.designer.active and e.designer.aside is None and e.builder.active
    assert any(isinstance(event, Thinking) and "I've left the helper we were working out: nothing was created"
               in event.text for event in events)
    assert one(events, AgentCard) and not any(isinstance(event, Question) and event.id == CARRY_ON for event in events)
    asked = len(script.turns)
    list(e.choose(CARD, CREATE_IT))
    assert len(script.turns) == asked and [agent.blueprint for agent in store.list_agents()] == [DOCUMENTS_QA]


def test_a_helper_deleted_while_it_is_being_changed_is_not_saved_again(engine, home):
    e = engine(Script(MOVER).model())
    watching(e, home)
    assert one(list(e.send(f"change {NAME}: leave the garden lists alone too")), AgentCard)
    list(e.delete_agent(NAME))
    events = list(e.choose(DELETE_AGENT, DELETE_IT))
    assert said(events) == f"Deleted {NAME}. I stopped changing it, since it is deleted." and not e.designer.active
    events = list(e.choose(CARD, "Save changes"))
    assert store.find_agent(NAME) is None and not any(isinstance(event, Question) for event in events)


@pytest.mark.parametrize("typed, moved", [("yes, go through them", True), ("go through them please", True),
                                          ("no, leave them", False)])
def test_a_yes_or_a_no_with_more_words_answers_go_through_them_now(engine, home, typed, moved):
    """ "Yes, go through them" was taken for a pass over what had landed since, and answered
    "Nothing new has landed" while the file they had said yes to waited."""
    downloads = home / "Downloads"
    write(downloads, "boat_insurance.txt", "Insurance for the boat")
    e = engine(Script(MOVER).model())
    list(e.send(ASKED))
    assert one(list(e.choose(CARD, CREATE_IT)), Question).id == FIRST_PASS
    events = list(e.send(typed))
    if moved:
        assert one(events, Result).text.startswith("Moved 1 file: Boat 1.")
        assert (downloads / "Boat" / "boat_insurance.txt").is_file()
    else:
        assert said(events) == "Okay, only new files from now on." and (downloads / "boat_insurance.txt").is_file()
