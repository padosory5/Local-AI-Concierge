"""A setup talked through (agents/conductor.py): the model fills a form each turn, and
code checks it, keeps the draft and shows the card. The model here is a script of forms
written in advance, so what is tested is what code does with whatever a model says."""

import json
from pathlib import Path

import pytest

from concierge import noir
from concierge.agents import builder as builder_mod
from concierge.agents import store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import CARD, CREATE_IT, AgentBuilder, short_place
from concierge.agents.conductor import (CALLED_OFF, CARD_COMES, CARD_IS_UP, CONDUCT, INSIDE, MOVED_ON, NOTHING_MISSING,
                                        STILL_ASKING, Conductor, ConductorError, read_form, schema_for, talker_form,
                                        tidy_say)
from concierge.engine import NoirEngine
from concierge.events import AgentCard, NoirText, Question, Thinking
from concierge.hardware import GPU, HardwareReport
from concierge.organizer import CONTENT

REQUEST = "can you make me an agent that sorts my files into folders"


def form(status=STILL_ASKING, say="", asks="", folder=("", ""), into=("", ""), by="", groups="", name="") -> dict:
    """An organizer's form the way a model fills it."""
    return {"folder": {"place": folder[0], "name": folder[1]}, "into": {"place": into[0], "name": into[1]},
            "by": by, "groups": groups, "name": name, "status": status, "asks": asks, "say": say}


class Script:
    """A conductor whose forms were written in advance; it keeps what it was shown."""

    def __init__(self, *forms):
        self.forms, self.notes, self.turns, self.schemas, self.released = list(forms), [], [], [], False

    def fill(self, note, turns, schema):
        self.notes.append(note)
        self.turns.append([dict(turn) for turn in turns])
        self.schemas.append(schema)
        filled = self.forms.pop(0)
        if isinstance(filled, Exception):
            raise filled
        return filled

    def release(self):
        self.released = True


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home: the places people name, and nothing of the real computer."""
    for place in ("Downloads", "Desktop", "Documents", "Pictures"):
        (tmp_path / place).mkdir()
    (tmp_path / "Downloads" / "hw5.pdf").write_bytes(b"%PDF")
    (tmp_path / "Downloads" / "notes.txt").write_text("notes", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(builder_mod, "known_folder", lambda name, home=None: tmp_path / name)
    monkeypatch.setattr(builder_mod, "is_blocked", lambda folder: False)  # the test folder lives under AppData
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    return tmp_path


def talked(*forms) -> tuple[AgentBuilder, Script]:
    script = Script(*forms)
    builder = AgentBuilder(None, "noir", None, load_blueprints())
    builder.conductor = lambda: Conductor(script.fill, "Test model", here=True, release=script.release)
    return builder, script


def said(events) -> str:
    return " ".join(e.text for e in events if isinstance(e, (NoirText, Question)))


EVERYTHING = dict(folder=("Downloads", ""), into=("Desktop", "College"), groups="phys 122, cse 163")


# ----------------------------------------------------------------- the form


def test_the_form_has_every_setting_and_no_way_to_say_it_is_made():
    organizer = load_blueprints()["organizer"]
    schema = schema_for(organizer)
    fields = schema["properties"]
    assert set(fields) == {"folder", "into", "by", "groups", "name", "status", "asks", "say"}
    assert list(fields)[-1] == "say"  # the words come last, after what they are about
    assert "Downloads" in fields["folder"]["properties"]["place"]["enum"]
    assert INSIDE in fields["into"]["properties"]["place"]["enum"] and INSIDE not in fields["folder"]["properties"]["place"]["enum"]
    assert fields["by"]["enum"] == ["", "What's inside each file", "The file's name"]
    assert fields["status"]["enum"] == [STILL_ASKING, NOTHING_MISSING, CALLED_OFF, MOVED_ON]
    # The message that starts a setup can't be "never mind" or "something else".
    assert schema_for(organizer, first=True)["properties"]["status"]["enum"] == [STILL_ASKING, NOTHING_MISSING]


def test_a_form_is_read_out_of_whatever_is_around_it():
    assert read_form('Here you go:\n```json\n{"say": "Hi", "status": "asking"}\n```') == {"say": "Hi", "status": "asking"}
    with pytest.raises(ConductorError):
        read_form("I'd be happy to help you organize your files!")
    with pytest.raises(ConductorError):
        read_form('{"say": "Hi", ')


def test_a_plan_model_gets_one_message_and_its_json_is_read():
    class Talker:
        def chat(self, model, messages, **more):
            self.messages = messages
            yield '```json\n{"say": "Which folder?",'
            yield ' "status": "asking"}\n```'

    talker = Talker()
    filled = talker_form(talker)("THE NOTE", [{"role": "user", "content": "organize my files"},
                                              {"role": "assistant", "content": "Sure."}], {"type": "object"})
    assert filled == {"say": "Which folder?", "status": "asking"}
    assert len(talker.messages) == 1 and talker.messages[0]["role"] == "user"  # the plans' apps drop system messages
    prompt = talker.messages[0]["content"]
    assert "THE NOTE" in prompt and "Them: organize my files" in prompt and "You: Sure." in prompt
    assert json.dumps({"type": "object"}) in prompt


def test_a_plan_that_cannot_answer_is_a_conductor_error():
    class Talker:
        def chat(self, model, messages, **more):
            raise RuntimeError("signed out")
            yield ""

    with pytest.raises(ConductorError):
        talker_form(Talker())("note", [{"role": "user", "content": "hi"}], {})


# ------------------------------------------------------------ the builder


def test_one_message_that_says_everything_ends_in_the_card_and_makes_nothing(home):
    builder, script = talked(form(NOTHING_MISSING, "Here it is, the card below has the button.", **EVERYTHING))
    events = list(builder.start("organizer", REQUEST))
    slots = builder.draft.slots
    assert slots["folder"] == str(home / "Downloads")
    assert slots["into"] == str(home / "Desktop" / "College")
    assert slots["groups"] == "PHYS122, CSE163"  # course codes, as when typed in the request
    assert slots["by"] == CONTENT and slots["name"] == "File organizer"  # the usual values, not asked
    assert "Here it is" in said(events) and any(isinstance(e, AgentCard) for e in events)
    assert store.list_agents() == []  # only the card makes it

    list(builder.choose(CARD, CREATE_IT))
    assert [a.name for a in store.list_agents()] == ["File organizer"]
    assert builder.conducted and script.released  # its model leaves memory as soon as the setup ends


def test_whatever_the_model_says_about_done_nothing_is_made(home):
    builder, _ = talked(form("confirmed", "It is on now!", **EVERYTHING),
                        form(NOTHING_MISSING, "All done, I created it.", **EVERYTHING))
    list(builder.start("organizer", REQUEST))
    assert builder.active and store.list_agents() == []
    list(builder.answer("great, thanks for explaining"))
    assert builder.active and store.list_agents() == []


def test_ready_with_something_missing_goes_back_once_then_code_asks_plainly(home):
    builder, script = talked(form(NOTHING_MISSING, "It's all ready!"), form(NOTHING_MISSING, "It's all ready!"))
    events = list(builder.start("organizer", REQUEST))
    assert "Still not known: Watches" in script.notes[1]  # told what is missing, the second time
    assert not any(isinstance(e, AgentCard) for e in events)
    question = next(e for e in events if isinstance(e, Question))
    assert question.id == "folder" and question.text.startswith("Which folder should it watch?")
    assert "ready" not in said(events)  # what it claimed is not passed on


def test_a_folder_that_is_not_there_is_refused_and_said(home):
    builder, script = talked(
        form(say="Okay, I'll watch Scool. Where should the folders go?", asks="into", folder=("", "Scool")),
        form(say="I can't find a folder called Scool. Which one did you mean?", asks="folder"))
    events = list(builder.start("organizer", REQUEST))
    assert "folder" not in builder.draft.slots
    # Told why not and to ask, and not to use the name anywhere else: hinted that it might
    # be where the folders go, the model made a mistyped folder into a new destination.
    assert 'There is no folder called "Scool" on this computer' in script.notes[1]
    assert "don't put that name in any other setting" in script.notes[1]
    question = next(e for e in events if isinstance(e, Question))
    assert question.id == "folder" and "Which one did you mean?" in question.text


def test_a_refused_change_keeps_what_was_known_and_is_not_said_again_and_again(home):
    wrong = dict(folder=("", "College"))  # where the folders should go, put in the folder to watch
    builder, script = talked(form(say="Where should the sorted folders go?", asks="into", folder=("Downloads", "")),
                             form(say="Okay, College it is.", **wrong), form(say="Okay, College it is.", **wrong),
                             form(say="No, only files that land from now on. Where should the folders go?", asks="into", **wrong),
                             form(say="Sorry, which folder is College in?", asks="folder", **wrong),
                             form(say="Sorry, which folder is College in?", asks="folder", **wrong))
    list(builder.start("organizer", REQUEST))
    events = list(builder.answer("put them in a folder called College"))
    words = said(events)
    assert builder.draft.slots["folder"] == str(home / "Downloads")  # what was known stays
    assert 'I can\'t find a folder called "College", so that stays as it was (Watches: Downloads).' in words
    assert "Where should the sorted folders go?" in words and "College it is" not in words
    # Sent again while the user talks about something else, it is passed over without a word.
    events = list(builder.answer("wait will it move my old files too?"))
    assert "only files that land from now on" in said(events) and "can't find" not in said(events)
    assert len(script.notes) == 4  # one go: nothing was refused this time
    # Named again by the user, it is refused again and said.
    events = list(builder.answer("no i mean watch my College folder"))
    assert 'I can\'t find a folder called "College"' in said(events)


def test_refused_twice_code_says_its_own_plain_line(home):
    wrong = form(say="Okay, I'll watch Scool. Where should the folders go?", folder=("", "Scool"))
    builder, _ = talked(wrong, dict(wrong))
    events = list(builder.start("organizer", REQUEST))
    words = said(events)
    assert 'I can\'t find a folder called "Scool".' in words and "Which folder should it watch?" in words
    assert "I'll watch Scool" not in words


def test_the_card_waits_in_a_turn_where_something_was_refused(home):
    # Asked for a folder that isn't there, the model guessed Downloads for the rest; with that
    # nothing is missing, but the card would be for a folder the user never named.
    guessed = dict(into=(INSIDE, ""), groups="Decide as you go")
    builder, _ = talked(form(say="Okay, watching Scool.", folder=("", "Scool"), **guessed),
                        form(say="I can't find a folder called Scool. Which folder should I watch?", asks="folder",
                             folder=("Downloads", ""), **guessed),
                        form(NOTHING_MISSING, "Downloads it is.", folder=("Downloads", "")))
    events = list(builder.start("organizer", REQUEST))
    assert not any(isinstance(e, AgentCard) for e in events)
    assert next(e for e in events if isinstance(e, Question)).text.endswith("Which folder should I watch?")
    events = list(builder.answer("oops i meant downloads"))
    assert any(isinstance(e, AgentCard) for e in events)


def test_a_place_the_model_guessed_is_not_said_back(home):
    wrong = form(say="Okay!", folder=("Documents", "Scool"))
    builder, script = talked(wrong, dict(wrong))
    events = list(builder.start("organizer", REQUEST))
    assert "Documents" not in script.notes[1].split("PROBLEMS")[1].split("Fill in the form")[0]
    assert "Documents" not in said(events)


def test_a_folder_named_with_the_wrong_place_is_still_found(home):
    (home / "Desktop" / "School").mkdir()
    builder, _ = talked(form(say="Where should the sorted folders go?", asks="into", folder=("Documents", "School")))
    list(builder.start("organizer", REQUEST))
    assert builder.draft.slots["folder"] == str(home / "Desktop" / "School")


def test_once_the_card_is_up_the_model_is_told_so(home):
    builder, script = talked(form(NOTHING_MISSING, "Here it is.", **EVERYTHING), form(say="Only new ones.", **EVERYTHING))
    list(builder.start("organizer", REQUEST))
    list(builder.answer("will it move my old files?"))
    assert CARD_COMES in script.notes[0] and CARD_IS_UP not in script.notes[0]
    assert CARD_IS_UP in script.notes[1] and CARD_COMES not in script.notes[1]


def test_an_opening_offer_that_says_nothing_is_taken_off():
    assert tidy_say("I can certainly help you with that. Which folder should I watch?") == "Which folder should I watch?"
    assert tidy_say("Sure! I can do that for you. where should the notes go?") == "Where should the notes go?"
    assert tidy_say("I can certainly set that up for you.") == "I can certainly set that up for you."  # never down to nothing
    kept = "I can watch your Downloads folder and sort new files. Should I?"
    assert tidy_say(kept) == kept  # an offer that says what it would do stays
    assert tidy_say('  "Which\nfolder?"  ') == "Which folder?"


def test_a_closing_offer_is_taken_off_but_a_real_question_stays():
    assert tidy_say("I have renamed the folder to School. Is there anything else you would like to change?") == \
        "I have renamed the folder to School."
    assert tidy_say("Let me know if you need anything else.") == "Let me know if you need anything else."  # never down to nothing
    asked = "I'll watch Downloads. Where should the sorted folders go?"
    assert tidy_say(asked) == asked
    assert tidy_say("I have updated the folder's name to School. Shall we get started?") == "I have updated the folder's name to School."


def test_a_new_folder_needs_a_place_and_the_watched_folder_is_inside(home):
    builder, script = talked(form(say="Where?", folder=("Downloads", ""), into=("", "College")),
                             form(say="On the Desktop or in Documents?", asks="into"),
                             form(NOTHING_MISSING, "Here it is.", into=("Downloads", ""), groups="Decide as you go"))
    list(builder.start("organizer", REQUEST))
    assert "into" not in builder.draft.slots and 'ask where the "College" folder should be made' in script.notes[1]
    list(builder.answer("just keep them in downloads"))
    assert builder.draft.slots["into"] == ""  # the watched folder itself means inside it
    assert builder.draft.slots["groups"] == "Decide as you go"


def test_an_empty_value_never_erases_a_known_one(home):
    builder, _ = talked(form(say="Where should they go?", asks="into", folder=("Downloads", "")),
                        form(say="And the folders' names?", asks="groups", into=(INSIDE, "")))
    list(builder.start("organizer", REQUEST))
    list(builder.answer("inside it"))
    assert builder.draft.slots["folder"] == str(home / "Downloads") and builder.draft.slots["into"] == ""


def test_a_name_the_user_never_said_is_not_taken(home):
    builder, _ = talked(form(NOTHING_MISSING, "Here it is.", name="School Files", **EVERYTHING))
    list(builder.start("organizer", REQUEST))
    assert builder.draft.slots["name"] == "File organizer"

    builder, _ = talked(form(NOTHING_MISSING, "Here it is.", name="Homework sorter", **EVERYTHING))
    list(builder.start("organizer", REQUEST + " and call it Homework sorter"))
    assert builder.draft.slots["name"] == "Homework sorter"

    # A name said for a folder is not the agent's name.
    builder, _ = talked(form(NOTHING_MISSING, "Here it is.", name="School", **EVERYTHING))
    list(builder.start("organizer", REQUEST + ", and can you call the folder School"))
    assert builder.draft.slots["name"] == "File organizer"


def test_never_mind_drops_the_setup_and_something_else_hands_the_message_back(home):
    builder, script = talked(form(say="Which folder?", asks="folder"), form(CALLED_OFF, "No problem, I'll leave it."))
    list(builder.start("organizer", REQUEST))
    events = list(builder.answer("hmm actually i don't need it"))
    assert not builder.active and "No problem" in said(events) and script.released

    builder, _ = talked(form(say="Which folder?", asks="folder"), form(MOVED_ON, "Paris!"))
    list(builder.start("organizer", REQUEST))
    list(builder.answer("what's the capital of France?"))
    assert not builder.active and builder.handoff == "what's the capital of France?"


def test_the_first_message_cannot_be_something_else(home):
    builder, _ = talked(form(MOVED_ON, "Which folder should I watch?"))
    list(builder.start("organizer", REQUEST))
    assert builder.active and builder.handoff is None


def test_a_conductor_that_fails_leaves_the_plain_questions(home):
    builder, script = talked(ConductorError("no answer"))
    events = list(builder.start("organizer", REQUEST))
    assert any(isinstance(e, Thinking) and "plain questions" in e.text for e in events)
    question = next(e for e in events if isinstance(e, Question))
    assert question.id == "folder" and builder.draft.conductor is None and script.released
    # From here on it is the setup it always was: a click sets the setting, the next is asked.
    events = list(builder.choose("pick_folder", str(home / "Downloads")))
    assert builder.draft.slots["folder"] == str(home / "Downloads")
    assert next(e for e in events if isinstance(e, Question)).id == "into"


def test_a_click_on_a_button_is_taken_in_code_and_said_to_the_model(home):
    builder, script = talked(form(say="Where should the sorted folders go?", asks="into", folder=("Downloads", "")),
                             form(say="And what should the folders be called?", asks="groups"))
    events = list(builder.start("organizer", REQUEST))
    question = next(e for e in events if isinstance(e, Question))
    assert question.id == "into" and question.choices == ["Inside that folder"]
    list(builder.choose("into", "Inside that folder"))
    assert builder.draft.slots["into"] == ""
    assert script.turns[1][-1] == {"role": "user", "content": "Inside that folder"}
    assert "- Puts the folders in: Inside that folder" in script.notes[1]  # the draft it reads is code's


def test_a_plain_yes_at_the_card_creates_but_ok_but_is_a_change(home):
    builder, _ = talked(form(NOTHING_MISSING, "Here it is.", **EVERYTHING),
                        form(NOTHING_MISSING, "Documents it is.", into=("Documents", "College")))
    list(builder.start("organizer", REQUEST))
    events = list(builder.answer("ok but put them in documents"))
    assert store.list_agents() == [] and builder.draft.slots["into"] == str(home / "Documents" / "College")
    assert any(isinstance(e, AgentCard) for e in events)  # the card again, with the change
    list(builder.answer("ok sounds good"))
    assert [a.slots["into"] for a in store.list_agents()] == [str(home / "Documents" / "College")]


def test_a_question_at_the_card_is_answered_without_the_card_again(home):
    builder, _ = talked(form(NOTHING_MISSING, "Here it is.", **EVERYTHING),
                        form(say="No, only files that land from now on."))
    list(builder.start("organizer", REQUEST))
    events = list(builder.answer("will it move my old files?"))
    assert "only files that land from now on" in said(events)
    assert not any(isinstance(e, AgentCard) for e in events) and builder.draft.waiting == CARD
    list(builder.answer("yes"))
    assert len(store.list_agents()) == 1


def test_with_nothing_missing_the_card_comes_even_while_the_model_asks(home):
    builder, _ = talked(form(say="Would you like me to go by the files' names instead?", asks="by", **EVERYTHING),
                        form(NOTHING_MISSING, "By their names, then.", by="The file's name"))
    events = list(builder.start("organizer", REQUEST))
    assert "go by the files' names" in said(events) and any(isinstance(e, AgentCard) for e in events)
    # A yes now answers what was just asked; it is not a yes to the card.
    events = list(builder.answer("yes"))
    assert store.list_agents() == [] and builder.draft.slots["by"] == "The file's name"
    assert any(isinstance(e, AgentCard) for e in events)  # the card again, as it now is
    # The button creates whether or not a question is open.
    list(builder.choose(CARD, CREATE_IT))
    assert len(store.list_agents()) == 1


def test_the_button_works_while_a_question_is_open_at_the_card(home):
    builder, _ = talked(form(say="Shall I also go by the files' names?", **EVERYTHING))
    list(builder.start("organizer", REQUEST))
    assert builder.draft.waiting != CARD
    list(builder.choose(CARD, CREATE_IT))
    assert len(store.list_agents()) == 1


def test_change_something_is_said_in_words(home):
    builder, script = talked(form(NOTHING_MISSING, "Here it is.", **EVERYTHING),
                             form(NOTHING_MISSING, "By name now.", by="The file's name"))
    list(builder.start("organizer", REQUEST))
    events = list(builder.choose(CARD, "Change something"))
    assert [e.id for e in events if isinstance(e, Question)] == [CONDUCT]
    list(builder.answer("go by the file names instead"))
    assert builder.draft.slots["by"] == "The file's name"
    assert script.turns[1][-2:] == [{"role": "assistant", "content": "What should I change?"},
                                    {"role": "user", "content": "go by the file names instead"}]


def test_the_model_reads_places_by_name_never_the_whole_path(home):
    builder, script = talked(form(say="Where should they go?", asks="into", folder=("Downloads", "")),
                             form(NOTHING_MISSING, "Here it is.", into=("Desktop", "College"), groups="School"))
    list(builder.start("organizer", REQUEST))
    list(builder.answer("desktop, in College"))
    assert all(str(home) not in note for note in script.notes)  # the user's name is in that path
    assert "- Watches: Downloads" in script.notes[1]
    assert "Downloads has 2 files in it right now" in script.notes[0]
    assert "hw5.pdf" not in script.notes[0]  # how many and which kinds, never their names
    assert short_place(home / "Desktop" / "College") == str(Path("Desktop") / "College")


def test_what_code_reads_in_the_request_is_filled_in_first(home, monkeypatch):
    monkeypatch.setattr(builder_mod, "watched_from", lambda text: home / "Downloads")
    builder, script = talked(form(say="Where should the folders go?", asks="into"))
    list(builder.start("organizer", "organize the files from Downloads into phys122 and cse163 by name"))
    assert "- Watches: Downloads" in script.notes[0] and "- Folders: PHYS122, CSE163" in script.notes[0]
    assert "- Tells files apart by: The file's name" in script.notes[0]
    assert "into" not in builder.draft.slots  # where they go is left to the conversation


def test_a_blueprint_without_facts_is_asked_the_plain_way(home):
    class Plain:  # the plain questions ask the small model which folder the words name
        def chat_json(self, model, messages, schema, think=None):
            return {"folder": "", "place": "not said"}

    builder, script = talked(form(say="Hello"))
    builder.ollama = Plain()
    events = list(builder.start("documents_qa", "I want to ask questions about my contracts"))
    assert script.notes == [] and builder.draft.conductor is None
    assert "Ask my documents" in said(events)


def test_the_summary_writer_is_talked_through_the_same_way(home):
    summary = {"folder": {"place": "Downloads", "name": ""}, "notes": "A Summaries.md file in that folder", "length": "",
               "name": "", "status": NOTHING_MISSING, "asks": "", "say": "Here it is."}
    builder, _ = talked(summary)
    events = list(builder.start("summarizer", "write me a short summary of every pdf that lands in my downloads"))
    assert builder.draft.slots["notes"] == "" and builder.draft.slots["length"] == "Three short lines"
    card = next(e for e in events if isinstance(e, AgentCard))
    assert "Summaries.md" in " ".join(card.can_do)


def test_the_evals_check_for_claims_tells_now_from_later():
    from concierge.conductor_eval import claims_done

    assert claims_done("It is now on, and you can undo any move.")
    assert claims_done("Great, I've created it for you.")
    assert claims_done("Everything is up and running.")
    assert not claims_done("It will only move new ones that arrive while it is running.")
    assert not claims_done("Once it is on, new files get sorted as they land.")
    assert not claims_done("The card below has the button to create it.")


# ------------------------------------------------------------- who conducts


class Installed:
    def __init__(self, *tags):
        self.tags = list(tags)

    def list_models(self):
        return self.tags

    def capabilities(self, name):
        return ["completion"]


def report(card_gb: float | None) -> HardwareReport:
    gpus = [GPU("Test card", "nvidia", card_gb, card_gb, True, "test")] if card_gb else []
    return HardwareReport("windows", "11", "x86_64", "Test", 8, 16, 32.0, 20.0, 100.0, "C:", gpus)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")

    def made(tags, card_gb=16.0, chosen=None):
        e = NoirEngine(Installed(*tags))
        e.chat = noir.NoirChat(e.ollama)
        e._hardware = lambda: (report(card_gb), 3.8)
        e.menu.chosen = lambda: chosen
        return e

    return made


def test_a_listed_model_conducts_when_installed_and_it_fits(engine):
    conductor = engine(["noir:latest", "gemma4:12b"])._conductor()
    assert conductor is not None and conductor.name == "Gemma 4 12B" and conductor.here


def test_nobody_conducts_without_a_listed_model_or_the_room_for_it(engine):
    assert engine(["noir:latest", "qwen3.5:9b", "qwen3.6:35b-a3b"])._conductor() is None  # bigger isn't better
    assert engine(["noir:latest", "gemma4:12b"], card_gb=8.0)._conductor() is None  # no room beside Noir
    assert engine(["noir:latest", "gemma4:12b"], card_gb=None)._conductor() is None  # never on the processor
    off = engine(["noir:latest", "gemma4:12b"])
    off.conducts = False
    assert off._conductor() is None


def test_a_plan_or_key_model_conducts_before_any_local_one(engine):
    e = engine(["noir:latest", "gemma4:12b"], chosen={"here": False, "name": "Claude Sonnet 5.5", "model": "x"})
    e.chat.talker = object()  # not its own model
    e.talker_name = "Claude Sonnet 5.5"
    conductor = e._conductor()
    assert conductor.name == "Claude Sonnet 5.5" and not conductor.here


def test_a_local_model_picked_in_the_menu_does_not_conduct_unless_listed(engine):
    e = engine(["noir:latest", "qwen3.6:35b-a3b"], chosen={"here": True, "name": "Qwen 3.6 35B", "model": "qwen3.6:35b-a3b"})
    e.chat.talker = object()
    assert e._conductor() is None
