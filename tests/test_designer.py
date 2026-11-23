"""The conversation in which an agent is worked out (agents/designer.py): the design model
fills one form a turn, and code checks it, keeps the card, tries it out and shows it. The
model here is a script of forms written in advance, so what is tested is what code does
with whatever a model says. The rules, folders and files are made up."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

from concierge.agents import builder as builder_mod
from concierge.agents import designer as designer_mod
from concierge.agents import parts, planner, store
from concierge.agents.builder import CARD, CREATE_IT, DUPLICATE, MAKE_ANOTHER, SAVE_CHANGES
from concierge.agents.designer import (CALLED_OFF, CANT_BE_MADE, CARD_COMES, CARD_IS_UP, CARD_SAVES, CARD_WAITS,
                                       DESIGN, DESIGN_CONTEXT, EDITING, FORM_NOTE, HOW_TO_DESIGN, MAX_TURNS, MOVED_ON,
                                       NO_DESIGNER, NONE_FIT, NOT_CLEAR, NOT_TOLD, NOTHING_MISSING, PART_OF_THIS,
                                       SOMETHING_ELSE, STILL_ASKING, THEN, TOLD, VOICE,
                                       WHEN, Designer, DesignerError, DesignModel, local_form, names_in, note_for,
                                       read_form, row_line, schema_for, talker_form, tidy_say)
from concierge.agents.parts import (ANSWER, DOCUMENTS, IN_CHAT, INSIDE, INSIDE_FILE, MOVE, NAME_ONLY, NEW_FILE, NOTE,
                                    OPEN_NO, OPEN_YES, PLACE_NAMES, SHOW, WHILE_ON)
from concierge.events import AgentCard, AgentList, NoirText, Question, Result, Thinking
from concierge.ollama import OllamaError
from concierge.quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT

REQUEST = "my downloads are a mess, can you help"
RULE = "Put anything about the boat in Boat and anything about the garden in Garden. Leave the rest where it is."
# A whole card that moves files, the way a model fills it in.
MOVER = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""), choices="Boat, Garden", rule=RULE, name="Paper sorter")
# What a dry run on three files comes back with.
ROWS = [{"name": "boat_insurance.pdf", "ending": ".pdf", "what": "an insurance letter for a boat", "choice": "Boat",
         "new": False, "why": "", "note": ""},
        {"name": "tulips.docx", "ending": ".docx", "what": "a planting plan", "choice": "Garden", "new": False,
         "why": "", "note": ""},
        {"name": "setup.exe", "ending": ".exe", "what": "", "choice": "", "new": False,
         "why": "nothing inside it could be read", "note": ""}]


def form(status=STILL_ASKING, say="", asks="", when=NOT_CLEAR, then=NOT_CLEAR, wants="", folder=("", ""), looks_at="",
         show="", keep="", choices="", open="", into=("", ""), notes=("", ""), rule="", name="", try_on="",
         changes="") -> dict:
    """The form the way a model fills it."""
    return {"wants": wants, "changes": changes, "when": when, "then": then, "skip_language": "",
            "folder": {"place": folder[0], "name": folder[1]},
            "looks_at": looks_at, "show": show, "keep": keep, "choices": choices, "open": open,
            "into": {"place": into[0], "name": into[1]}, "notes": {"place": notes[0], "name": notes[1]},
            "instruction": rule, "name": name, "try_on": try_on, "status": status, "asks": asks, "say": say}


class Script:
    """A design model whose forms were written in advance; it keeps what it was shown."""

    def __init__(self, *forms, log=None):
        self.forms, self.notes, self.turns, self.schemas, self.released = list(forms), [], [], [], 0
        self.opening, self.openings = {"heard": TOLD, "question": ""}, []
        self.rewrites, self.rules = [], []  # what the writer or the mender answers, and what each was given
        self.elsewhere, self.asides = set(), []  # the messages it takes for something else, and what it was asked each time
        self.log = log if log is not None else []

    def fill(self, note, turns, schema):
        if "about" in schema["properties"]:
            # The aside: whether their message is part of the conversation at all, decided
            # on its own. Unless a test says otherwise, it is.
            self.asides.append((note, turns[0]["content"]))
            typed = turns[0]["content"].rsplit("THEY HAVE JUST WRITTEN\n", 1)[-1]
            return {"about": SOMETHING_ELSE if typed in self.elsewhere else PART_OF_THIS}
        if "heard" in schema["properties"]:
            # The opening: the first message read on its own. Unless a test says otherwise,
            # it says what they want done, and the whole form follows.
            self.openings.append(note)
            return dict(self.opening)
        if list(schema["properties"]) == ["rule"]:
            # The writer or the mender: a rule written again from a short note. Unless a test
            # says otherwise, it gives nothing back, and the rule stays as it was.
            self.rules.append((note, turns[0]["content"]))
            answer = self.rewrites.pop(0) if self.rewrites else ""
            if isinstance(answer, Exception):
                raise answer
            return {"rule": answer}
        self.notes.append(note)
        self.turns.append([dict(turn) for turn in turns])
        self.schemas.append(schema)
        filled = self.forms.pop(0)
        if isinstance(filled, Exception):
            raise filled
        return filled

    def release(self):
        self.released += 1
        self.log.append("release")


class Rehearsal:
    """A dry run that returns rows written in advance, and counts how often it was asked."""

    def __init__(self, *runs, log=None):
        self.runs, self.calls, self.agents = list(runs), 0, []
        self.log = log if log is not None else []

    def __call__(self, agent):
        self.calls += 1
        self.agents.append(agent)
        self.log.append("rehearse")
        if not self.runs:
            return []
        return [dict(row) for row in self.runs[min(self.calls, len(self.runs)) - 1]]


class BuiltIn:
    """The built-in model: it does a text helper's job, and gives a documents helper its test drive."""

    def __init__(self, log=None):
        self.asked = []
        self.log = log if log is not None else []

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked.append(messages)
        self.log.append("built-in")
        yield messages[-1]["content"].upper()

    def chat_json(self, model, messages, schema, think=None, **more):
        if "question" in schema["properties"]:
            return {"question": "How do I start the washer?"}
        return {"answer": "Press the green button twice.", "used": [1]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home: the places people name, and nothing of the real computer."""
    for place in PLACE_NAMES:
        (tmp_path / place).mkdir()
    (tmp_path / "Downloads" / "report.pdf").write_bytes(b"%PDF")
    (tmp_path / "Downloads" / "notes.txt").write_text("notes", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for module in (designer_mod, builder_mod, parts):
        monkeypatch.setattr(module, "known_folder", lambda name, home=None: tmp_path / name)
    monkeypatch.setattr(designer_mod, "is_blocked", lambda folder: False)  # the test folder lives under AppData
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(planner, "ideas_path", lambda: tmp_path / "ideas.json")
    monkeypatch.setattr(sys, "platform", "win32")  # highlights are offered: one test below says otherwise
    return tmp_path


def designing(*forms, rows=(), here=True, ollama=None, log=None) -> tuple[Designer, Script, Rehearsal]:
    script = Script(*forms, log=log)
    rehearsal = Rehearsal(*rows, log=log)
    designer = Designer(ollama or BuiltIn(log), "noir", None, rehearsal,
                        lambda: DesignModel(script.fill, "Test model", here=here, release=script.release),
                        lambda: "Small model")
    return designer, script, rehearsal


def said(events) -> str:
    return " ".join(e.text for e in events if isinstance(e, (NoirText, Question)))


def one(events, kind):
    return next(e for e in events if isinstance(e, kind))


def has(events, kind) -> bool:
    return any(isinstance(e, kind) for e in events)


# ----------------------------------------------------------------- the form


def test_the_form_has_every_field_in_order_and_no_way_to_say_it_is_made(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    keys = [setting.key for setting in parts.all_settings()]
    schema = schema_for()
    fields = schema["properties"]
    # What their last message asks to be changed is written before the settings it changes:
    # said only in the words at the end, a correction was left out of the rule.
    assert list(fields) == ["wants", "changes", "when", "then", *keys, "try_on", "status", "asks", "say"]
    assert fields["wants"] == fields["changes"] == {"type": "string"}
    assert schema["required"] == list(fields)  # "" is how a field says "not known"
    assert list(fields)[-1] == "say"  # the words come last, after what they are about
    assert fields["when"]["enum"] == [WHILE_ON, IN_CHAT, NEW_FILE, NOT_CLEAR, NONE_FIT]
    assert fields["then"]["enum"] == [SHOW, ANSWER, MOVE, NOTE, DOCUMENTS, NOT_CLEAR, NONE_FIT]
    assert fields["folder"]["properties"]["place"]["enum"] == [*PLACE_NAMES, ""]  # must exist: never "inside"
    assert fields["into"]["properties"]["place"]["enum"] == [*PLACE_NAMES, INSIDE, ""]
    assert fields["notes"] == fields["into"]
    assert fields["looks_at"]["enum"] == [INSIDE_FILE, NAME_ONLY, ""]
    assert fields["choices"] == fields["instruction"] == fields["name"] == fields["try_on"] == {"type": "string"}
    assert fields["status"]["enum"] == [STILL_ASKING, NOTHING_MISSING, CALLED_OFF, MOVED_ON, CANT_BE_MADE]
    assert fields["asks"]["enum"] == ["", "when", "then", *keys]
    # The message that starts it can't be "never mind" or "something else".
    assert schema_for(first=True)["properties"]["status"]["enum"] == [STILL_ASKING, NOTHING_MISSING, CANT_BE_MADE]


def test_a_form_is_read_out_of_whatever_is_around_it():
    assert read_form('Here you go:\n```json\n{"say": "Hi", "status": "asking"}\n```') == {"say": "Hi", "status": "asking"}
    with pytest.raises(DesignerError):
        read_form("I'd be happy to help you with your files!")
    with pytest.raises(DesignerError):
        read_form('{"say": "Hi", ')


def test_a_plan_model_gets_one_message_and_its_json_is_read():
    class Talker:
        def chat(self, model, messages, **more):
            self.messages = messages
            yield '```json\n{"say": "Which folder?",'
            yield ' "status": "asking"}\n```'

    talker = Talker()
    filled = talker_form(talker)("THE NOTE", [{"role": "user", "content": "tidy my files"},
                                              {"role": "assistant", "content": "Sure."}], {"type": "object"})
    assert filled == {"say": "Which folder?", "status": "asking"}
    assert len(talker.messages) == 1 and talker.messages[0]["role"] == "user"  # the plans' apps drop system messages
    prompt = talker.messages[0]["content"]
    assert "THE NOTE" in prompt and "Them: tidy my files" in prompt and "You: Sure." in prompt
    assert json.dumps({"type": "object"}) in prompt


def test_a_plan_that_cannot_answer_is_a_designer_error():
    class Talker:
        def chat(self, model, messages, **more):
            raise RuntimeError("signed out")
            yield ""

    with pytest.raises(DesignerError):
        talker_form(Talker())("note", [{"role": "user", "content": "hi"}], {})


def test_a_model_on_this_computer_is_forced_into_the_form_with_room_to_read_the_note():
    class Local:
        def __init__(self, fails=False):
            self.calls, self.fails = [], fails

        def capabilities(self, tag):
            return ["completion", "thinking"]

        def chat_json(self, model, messages, schema, think=None, keep_alive=None, options=None):
            if self.fails:
                raise OllamaError("Ollama stopped")
            self.calls.append((model, messages, schema, think, keep_alive, options))
            return {"say": "Hi"}

    local = Local()
    turns = [{"role": "user", "content": "tidy my files"}]
    assert local_form(local, "big:12b")("THE NOTE", turns, {"type": "object"}) == {"say": "Hi"}
    model, messages, schema, think, keep_alive, options = local.calls[0]
    assert model == "big:12b" and messages == [{"role": "system", "content": "THE NOTE"}, *turns]
    assert think is False  # a thinking model left to itself thinks first, and a turn takes ten times as long
    assert options["num_ctx"] == DESIGN_CONTEXT == 8192 and keep_alive
    with pytest.raises(DesignerError):
        local_form(Local(fails=True), "big:12b")("note", turns, {})


def test_a_design_model_reads_the_last_turns_and_must_fill_a_form():
    seen = []
    model = DesignModel(lambda note, turns, schema: seen.append(turns) or {"say": "Hi"}, "Test model", here=True)
    turns = [{"role": "user", "content": str(number)} for number in range(MAX_TURNS + 6)]
    assert model.fill("note", turns, {}) == {"say": "Hi"}
    assert seen[0] == turns[-MAX_TURNS:]
    assert not model.waking()  # nobody can say whether it is loaded: nothing is said about loading
    with pytest.raises(DesignerError):
        DesignModel(lambda note, turns, schema: "Sure!", "Test model", here=True).fill("note", turns, {})

    def stopped(note, turns, schema):
        raise OllamaError("Ollama stopped")

    with pytest.raises(DesignerError):
        DesignModel(stopped, "Test model", here=True).fill("note", turns, {})

    def gone():
        raise RuntimeError("Ollama already stopped")

    DesignModel(stopped, "Test model", here=True, release=gone).done()  # nothing is loaded: nothing to say
    assert DesignModel(stopped, "Test model", here=True, loaded=lambda: False).waking()


# ----------------------------------------------------------------- the note


def test_the_note_has_its_sections_in_order_and_says_how_to_fill_every_field(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    note = note_for(["nothing yet"], ["Downloads has 2 files in it right now (1 .pdf, 1 .txt)."],
                    tryout=["THE TRY-OUT", "- Into Boat: 1 file (1 .pdf)"], problems=["Something was wrong."])
    sections = [VOICE, "\nHOW TO DESIGN\n", "\nWHAT A HELPER CAN BE MADE OF\n", "\nHOW THESE WORK (you may tell the user; "
                "say nothing that isn't here)\n", "\nKNOWN SO FAR (checked by code)\n- nothing yet\n",
                "\nABOUT THIS COMPUTER (read by code just now)\n- Downloads has 2 files", "\nTHE TRY-OUT\n- Into Boat",
                "\nPROBLEMS WITH YOUR LAST FORM", "\nFORM NOTE\n"]
    places = [note.index(section) for section in sections]
    assert places == sorted(places)
    assert HOW_TO_DESIGN in note and "- Something was wrong." in note
    how_to_fill = note.split("FORM NOTE")[1]
    for name in ("wants", "when", "then", "try_on", "status", "asks", "say", *(s.key for s in parts.all_settings())):
        assert re.search(rf"\b{name}\b", how_to_fill), name
    # Every part there is, with what it does, what goes with it and how each setting is filled.
    for part in [*parts.WHENS.values(), *parts.THENS.values()]:
        assert f'- "{part.key}": {part.about}' in note
        assert all(f"- {fact}" in note for fact in part.facts)
        assert all(f"(`{setting.key}`" in note and setting.how in note for setting in part.settings)
    assert f'Its THEN can be: "{MOVE}", "{NOTE}".' in note
    assert "(`looks_at`, has a usual value)" in note and "- Folder it watches (`folder`):" in note
    assert f'(no rule for "{DOCUMENTS}")' in note and parts.RULE.how in note and parts.NAME.how in note


def test_what_the_note_says_of_the_parts_agrees_with_itself_and_with_the_code(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    note = note_for(["nothing yet"], [])
    # For a helper that moves files, which thing goes where is the whole rule, and two other
    # lines of the note need it there; the line on how to write a rule once read as a ban on it.
    assert "For a helper that moves files, say which things go into which of its folders" in parts.RULE.how
    assert "where a result goes" not in note and "the rule must then say how a new folder is named" in note
    # A picture is read by another model on this computer when the built-in one can't see.
    assert "(a picture or a scanned page by a model on this computer that can see, which may be another one)" in note
    assert "on this computer by the built-in model." not in note


def test_the_note_says_whether_the_first_message_can_be_called_off_and_which_card_line_applies():
    first = note_for([], [], first=True)
    later = note_for([], [])
    assert f'"{CALLED_OFF}"' not in first and f'"{MOVED_ON}"' not in first
    assert f'"{CALLED_OFF}" if they no longer want it' in later and f'"{MOVED_ON}"' in later
    assert CARD_COMES in later and CARD_IS_UP not in later and EDITING not in later
    assert CARD_IS_UP in note_for([], [], card_up=True) and CARD_COMES not in note_for([], [], card_up=True)
    changing = note_for([], [], editing=True)
    assert EDITING in changing and CARD_SAVES in changing and CARD_COMES not in changing
    # After a form in which something could not be used no card follows, so none is promised.
    for waiting in (note_for([], [], waits=True), note_for([], [], editing=True, waits=True)):
        assert CARD_WAITS in waiting and CARD_COMES not in waiting and CARD_SAVES not in waiting
    assert CARD_IS_UP in note_for([], [], card_up=True, waits=True)  # the card that is up is still there


def test_nothing_the_model_reads_is_an_example_of_a_name_or_a_subject(monkeypatch):
    """Given a folder's name as an example, a model offered it to the user as if it were
    theirs, and a smaller one filled it in as the answer."""
    monkeypatch.setattr(sys, "platform", "win32")
    banned = re.compile(r"\b(course|school|college|class|lecture|homework|exam|bank|tax|bill|invoice|receipt|"
                        r"organi[sz]er|summar\w*|translat\w*|physics|math\w*)\b|\blike \"|\bsuch as\b|\be\.g\.",
                        re.IGNORECASE)
    texts = [VOICE, HOW_TO_DESIGN, FORM_NOTE, CARD_COMES, CARD_SAVES, CARD_IS_UP, CARD_WAITS, EDITING, WHEN.ask,
             THEN.ask, NO_DESIGNER, note_for(["nothing yet"], [], first=True)]
    for text in texts:
        assert not banned.search(text), banned.search(text)
    # And nothing in the file knows what any one agent is for. ("Of course" is an opening it takes off.)
    source = Path(designer_mod.__file__).read_text(encoding="utf-8")
    subject = re.compile(r"\b((?<!of )course|school|college|lecture|homework|bank|organi[sz]er|summar\w*|translat\w*|"
                         r"physics)\b", re.IGNORECASE)
    assert not subject.search(source), subject.search(source)


def test_highlights_are_not_offered_off_windows(home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert schema_for()["properties"]["when"]["enum"] == [IN_CHAT, NEW_FILE, NOT_CLEAR, NONE_FIT]
    assert schema_for()["properties"]["then"]["enum"] == [ANSWER, MOVE, NOTE, DOCUMENTS, NOT_CLEAR, NONE_FIT]
    designer, script, _ = designing(form(say="What should it do with the text?", when=WHILE_ON, then=SHOW))
    list(designer.start("explain what I highlight"))
    note = script.notes[0]
    assert f'- "{WHILE_ON}"' not in note and f'- "{SHOW}"' not in note and f'- "{IN_CHAT}"' in note
    assert "Highlighting works on Windows only" in note
    assert "when" not in designer.sketch.slots  # a plan model's form is only text: what isn't offered isn't taken


# ----------------------------------------------------------------- the words


def test_an_opening_offer_that_says_nothing_is_taken_off():
    assert tidy_say("I can certainly help you with that. Which folder should I watch?") == "Which folder should I watch?"
    assert tidy_say("Sure! I can do that for you. where should the notes go?") == "Where should the notes go?"
    assert tidy_say("I can certainly set that up for you.") == "I can certainly set that up for you."  # never down to nothing
    kept = "I can watch your Downloads folder and move new files. Should I?"
    assert tidy_say(kept) == kept  # an offer that says what it would do stays
    assert tidy_say('  "Which\nfolder?"  ') == "Which folder?"
    assert tidy_say(None) == "" and tidy_say(12) == ""
    # Only a pair of quotes around the whole of it comes off: one at either end is part of what is said.
    for kept in ('It will go into "Boat"', '"Boat" is where they go.', 'I named it "Paper sorter."',
                 '"Boat" and "Garden"'):
        assert tidy_say(kept) == kept


def test_a_closing_offer_is_taken_off_but_a_real_question_stays():
    assert tidy_say("I have renamed the folder to Sorted. Is there anything else you would like to change?") == \
        "I have renamed the folder to Sorted."
    assert tidy_say("Let me know if you need anything else.") == "Let me know if you need anything else."  # never down to nothing
    asked = "I'll watch Downloads. Where should the folders go?"
    assert tidy_say(asked) == asked
    assert tidy_say("I have changed the folder's name to Sorted. Shall we get started?") == "I have changed the folder's name to Sorted."
    assert len(tidy_say("One more thing to know. " * 60)) <= 600


def test_before_the_card_a_question_about_what_they_want_stays():
    # Working a helper out is asking what people would like; at the card the same words
    # would make the next yes an answer to them instead of a yes to the card.
    wants = "It would watch your Downloads. Do you want me to leave the pictures alone?"
    assert tidy_say(wants, asking=True) == wants
    assert tidy_say(wants) == "It would watch your Downloads."
    more = "It would watch your Downloads. Would you like it to make folders as it goes?"
    assert tidy_say(more, asking=True) == more
    # An offer of more help asks nothing, before the card or at it.
    assert tidy_say("It watches Downloads. Is there anything else you would like?", asking=True) == "It watches Downloads."
    assert tidy_say("It watches Downloads. Let me know if you need more.", asking=True) == "It watches Downloads."
    assert tidy_say("It watches Downloads. Shall we begin?", asking=True) == "It watches Downloads."


def test_a_list_of_folders_however_it_was_written():
    assert names_in("Boat, Garden") == ["Boat", "Garden"]
    assert names_in("Boat and Garden") == ["Boat", "Garden"]
    assert names_in("Boat, Garden and Tools") == ["Boat", "Garden", "Tools"]
    assert names_in("Boat, Garden, and Tools") == ["Boat", "Garden", "Tools"]
    assert names_in("Boat\nGarden; Tools") == ["Boat", "Garden", "Tools"]
    assert names_in("Sand castles, Andes") == ["Sand castles", "Andes"]  # "and" inside a word is no break
    # A name in double quotes is one name, so a folder can have "and" in it.
    assert names_in('Boat, "Rock and Roll"') == ["Boat", "Rock and Roll"]
    assert names_in('"Rock and Roll", Boat') == ["Rock and Roll", "Boat"]
    assert names_in('Boat and "Rock and Roll"') == ["Boat", "Rock and Roll"]  # wherever it stands
    assert names_in('“Rock and Roll” and Boat') == ["Rock and Roll", "Boat"]
    assert names_in('Boat, "Rope, sails"') == ["Boat", "Rope sails"]  # a comma can't be kept in a name
    # A name with no letter in it is a name too, when it is a sign or a small picture.
    assert names_in("📚, ★ and Boat") == ["📚", "★", "Boat"] and parts.same_folder("📚", ["Boat", "📚"]) == "📚"
    assert names_in("&, ...") == []  # punctuation alone is not
    # The names are the user's own: kept as given, none twice, nothing a folder can't be called.
    assert names_in("C++, C#, boat, Boat") == ["C++", "C#", "boat"]
    assert names_in("R&D, Old/New") == ["R&D", "Old New"]
    assert names_in("") == [] and names_in(" , ; ") == []


def test_one_file_of_a_try_out_as_the_user_reads_it():
    # A file that would be moved says what the built-in model took it for, as one that stays
    # does in its reason: a name, an arrow and a folder showed nobody that a file was being
    # taken for something it was not.
    assert row_line(ROWS[0], MOVE) == "boat_insurance.pdf → Boat (read as an insurance letter for a boat)"
    assert row_line({**ROWS[0], "what": ""}, MOVE) == "boat_insurance.pdf → Boat"
    assert (row_line({**ROWS[0], "choice": "Sails", "new": True}, MOVE)
            == "boat_insurance.pdf → Sails (a new folder; read as an insurance letter for a boat)")
    assert row_line(ROWS[2], MOVE) == "setup.exe: stays (nothing inside it could be read)"
    assert row_line({**ROWS[2], "why": ""}, MOVE) == "setup.exe: stays"
    # After a change, an outcome that is different says what it was.
    assert row_line({**ROWS[1], "choice": ""}, MOVE, was=ROWS[1]) == "tulips.docx: stays now (was Garden)"
    assert (row_line({**ROWS[1], "choice": "", "why": "the rule leaves it: a planting plan"}, MOVE, was=ROWS[1])
            == "tulips.docx: stays now (was Garden; the rule leaves it: a planting plan)")
    assert (row_line({**ROWS[1], "choice": "Boat"}, MOVE, was=ROWS[1])
            == "tulips.docx → Boat now (was Garden; read as a planting plan)")
    assert row_line({**ROWS[2], "choice": "Boat"}, MOVE, was=ROWS[2]) == "setup.exe → Boat now (stayed before)"
    assert row_line(ROWS[0], MOVE, was=ROWS[0]) == "boat_insurance.pdf → Boat (read as an insurance letter for a boat)"
    wrote = {"name": "letter.pdf", "note": "A letter from the harbour office.\nIt asks for the mooring fee."}
    nothing = {"name": "letter.pdf", "note": "", "why": "the rule asks for nothing about it: a letter"}
    # The note as it would be written, its lines one after the other: shown only how it
    # begins, nobody could see whether what they had asked for was in it.
    whole = "A letter from the harbour office. It asks for the mooring fee."
    assert row_line(wrote, NOTE) == f"letter.pdf: {whole}"
    assert row_line(nothing, NOTE) == "letter.pdf: nothing to write (the rule asks for nothing about it: a letter)"
    assert row_line(nothing, NOTE, was=wrote) == f"letter.pdf: nothing to write now (was: {whole})"
    assert row_line(wrote, NOTE, was=nothing) == f"letter.pdf: {whole} (nothing before)"
    # A long one is cut at the end of a word, and says that it goes on.
    long = row_line({"name": "letter.pdf", "note": "The mooring fee is due in March. " * 20}, NOTE)
    assert len(long) <= len("letter.pdf: ") + designer_mod.NOTE_SHOWN + 3 and long.endswith("...")
    assert not long[:-3].endswith(" ") and long[:-3].split()[-1] in ("The", "mooring", "fee", "is", "due", "in", "March.")


# ------------------------------------------------------------ the conversation


def test_the_first_turn_with_nothing_known_asks_and_makes_nothing(home):
    designer, script, rehearsal = designing(form(say="What bothers you most about your Downloads?",
                                                 wants="A tidier Downloads folder"))
    events = list(designer.start(REQUEST))
    assert [type(e) for e in events] == [Thinking, Question]
    assert "Test model talks it through with you" in events[0].text
    question = events[1]
    assert (question.id, question.text, question.choices) == (DESIGN, "What bothers you most about your Downloads?", None)
    assert designer.active and designer.sketch.slots == {} and designer.sketch.wants == "A tidier Downloads folder"
    assert store.list_agents() == [] and rehearsal.calls == 0
    assert "KNOWN SO FAR (checked by code)\n- nothing yet" in script.notes[0]
    assert script.turns[0] == [{"role": "user", "content": REQUEST}]
    assert script.schemas[0] == schema_for(first=True)
    # What it understood is in the next note, with what is still not known.
    script.forms.append(form(say="And where do they land?", when=NEW_FILE))
    list(designer.answer("the pdfs pile up"))
    assert "- What they want: A tidier Downloads folder" in script.notes[1]
    assert "- When it works: not known yet" in script.notes[1] and script.schemas[1] == schema_for()


def test_one_message_that_says_everything_ends_in_the_try_out_and_the_card_and_makes_nothing(home):
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is, the card below has the button.", **MOVER),
                                            rows=[ROWS])
    events = list(designer.start(REQUEST))
    slots = dict(designer.sketch.slots)
    assert (slots["when"], slots["then"]) == (NEW_FILE, MOVE)
    assert slots["folder"] == str(home / "Downloads")
    assert slots["choices"] == "Boat, Garden" and slots["instruction"] == RULE and slots["name"] == "Paper sorter"
    assert (slots["looks_at"], slots["open"], slots["into"]) == (INSIDE_FILE, OPEN_NO, "")  # the usual values, not asked
    assert "Here it is" in said(events)
    result, card = one(events, Result), one(events, AgentCard)
    words = next(e for e in events if isinstance(e, NoirText))
    assert events.index(words) < events.index(result) < events.index(card)  # the words, the try-out, then the card
    assert (card.id, card.name, card.actions) == (CARD, "Paper sorter", [CREATE_IT, "Change something", "Cancel"])
    assert card.kind == "When a new file lands in Downloads" and f"Rule: {RULE}" in card.can_do
    assert card.runs_on.startswith("Small model (the built-in model)")
    assert not any("already there" in line for line in card.reads)  # how many are there is the watcher's to say
    assert store.list_agents() == [] and designer.take_created() is None  # only the card makes it
    assert rehearsal.calls == 1 and designer.sketch.waiting == CARD

    events = list(designer.choose(CARD, CREATE_IT))
    agent = store.list_agents()[0]
    assert (agent.name, agent.blueprint, agent.slots) == ("Paper sorter", "custom", slots)
    assert "Paper sorter is ready." in said(events) and one(events, AgentList).agents == ["Paper sorter"]
    assert not designer.active and not designer.edited and designer.replaced is None
    assert designer.take_created().name == "Paper sorter" and designer.take_created() is None  # once
    assert script.released  # its model leaves memory as soon as it is over


def test_what_was_understood_is_shown_as_it_goes(home):
    designer, _, _ = designing(form(say="Which folders should they go into?", when=NEW_FILE, then=MOVE,
                                    folder=("Downloads", "")))
    events = list(designer.start(REQUEST))
    understood = [e.text for e in events if isinstance(e, Thinking) and e.text.startswith("Understood so far")]
    assert understood == [f"Understood so far: when it works: {NEW_FILE}; what it does then: {MOVE}; folder it "
                          "watches: Downloads."]


def test_whatever_the_model_says_about_done_nothing_is_made(home):
    designer, _, _ = designing(form("confirmed", "It is on now!", **MOVER),
                               form(NOTHING_MISSING, "All done, I created it.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.active and store.list_agents() == []
    list(designer.answer("great, thanks for explaining"))
    assert designer.active and store.list_agents() == []


def test_ready_with_something_missing_goes_back_once_then_code_asks_plainly(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "It's all ready!"), form(NOTHING_MISSING, "It's all ready!"))
    events = list(designer.start(REQUEST))
    assert "Still not known: When it works, The rule. Don't say it is ready." in script.notes[1]  # told what is missing
    assert "The rule is yours to write" in script.notes[1]  # or it asks the user to say the rule for it
    assert not has(events, AgentCard)
    question = one(events, Question)
    assert question.id == DESIGN and question.text == WHEN.ask
    assert "ready" not in said(events)  # what it claimed is not passed on


def test_an_answer_that_asks_nothing_while_something_is_missing_goes_back_once(home):
    designer, script, _ = designing(form(say="Only new files, from then on.", when=NEW_FILE, then=MOVE),
                                    form(say="Only new files, from then on. Which folder should I watch?",
                                         asks="folder", when=NEW_FILE, then=MOVE))
    events = list(designer.start(REQUEST))
    assert "You asked nothing, and this is still not known: Folder it watches" in script.notes[1]
    assert one(events, Question).text.endswith("Which folder should I watch?")
    # A question about what they would like is a question: nothing goes back.
    designer, script, _ = designing(form(say="It would watch your Downloads. Do you want me to leave the pictures alone?",
                                         when=NEW_FILE, then=MOVE))
    events = list(designer.start(REQUEST))
    assert len(script.notes) == 1 and "leave the pictures alone?" in one(events, Question).text


def test_a_when_and_a_then_that_do_not_go_together_are_refused(home):
    wrong = form(say="I'll show it in a bubble when a file lands. Which folder?", when=NEW_FILE, then=SHOW)
    designer, script, _ = designing(wrong, form(say="Which folder should I watch?", asks="folder", when=NEW_FILE, then=NOTE))
    events = list(designer.start(REQUEST))
    assert "That way of working and that result don't go together" in script.notes[1]
    assert f'with "{NEW_FILE}", THEN can only be "{MOVE}", "{NOTE}"' in script.notes[1]
    assert (designer.sketch.slots["when"], designer.sketch.slots["then"]) == (NEW_FILE, NOTE)  # put right the second time
    assert one(events, Question).text == "Which folder should I watch?"

    # Given twice, neither is taken, and code asks its own plain question.
    designer, _, _ = designing(wrong, dict(wrong))
    events = list(designer.start(REQUEST))
    assert designer.sketch.slots == {} and one(events, Question).text == WHEN.ask
    assert "bubble" not in said(events)


def test_no_card_comes_in_the_turn_a_pair_was_refused(home):
    # Refused a bubble for each new file, a model picked a notes file instead: with that
    # nothing is missing, but the card would be for a helper nobody asked for.
    whole = dict(folder=("Downloads", ""), rule="Say in one line what this file is.", name="What came in")
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "A bubble for each new file.", when=NEW_FILE, then=SHOW, **whole),
        form(NOTHING_MISSING, "It can't pop up a bubble for a new file. It could write a line about each in a notes "
                              "file instead. The card below has the button to create it.",
             when=NEW_FILE, then=NOTE, **whole),
        form(NOTHING_MISSING, "A notes file it is.", when=NEW_FILE, then=NOTE, **whole), rows=[ROWS])
    events = list(designer.start("pop up a bubble telling me what each new download is"))
    told = script.notes[1].split("PROBLEMS WITH YOUR LAST FORM")[1].split("FORM NOTE")[0]
    assert "Don't pick another pair for them" in told and f'choose "{NONE_FIT}"' in told
    assert CARD_WAITS in script.notes[1]
    assert not has(events, AgentCard) and not has(events, Result) and rehearsal.calls == 0
    assert designer.sketch.waiting == DESIGN and "card" not in said(events)
    list(designer.answer("yes"))  # so a yes typed now makes nothing: it is said to the model
    assert store.list_agents() == [] and script.turns[2][-1] == {"role": "user", "content": "yes"}
    assert designer.sketch.waiting == CARD  # the card came once they had answered


def test_one_of_the_two_given_alone_joins_what_is_known(home):
    designer, _, _ = designing(form(say="What should happen to each file?", when=NEW_FILE),
                               form(say="Which folder should I watch?", then=NOTE),
                               form(say="Which folder should I watch?", when="Whenever", then="Something"))
    list(designer.start(REQUEST))
    assert designer.sketch.slots == {"when": NEW_FILE}
    list(designer.answer("write me a line about each"))
    assert designer.sketch.slots == {"when": NEW_FILE, "then": NOTE}
    list(designer.answer("hmm"))
    assert designer.sketch.slots == {"when": NEW_FILE, "then": NOTE}  # what is on no list erases nothing
    # A THEN alone, with no WHEN known, brings the one WHEN it goes with.
    designer, _, _ = designing(form(say="Which folder should I watch?", then=MOVE))
    list(designer.start(REQUEST))
    assert designer.sketch.slots == {"when": NEW_FILE, "then": MOVE}


def test_settings_of_parts_that_were_not_chosen_are_ignored(home):
    designer, _, _ = designing(form(NOTHING_MISSING, 'Write "Grammar fixer:" and your text.', when=IN_CHAT,
                                    then=ANSWER, name="Grammar fixer",
                                    rule="Correct the grammar and spelling of the text. Keep its meaning.",
                                    folder=("Downloads", ""), looks_at=NAME_ONLY, choices="Boat", show=BOTH,
                                    into=("Desktop", "Sorted"), notes=("Documents", "Log")))
    list(designer.start("fix my grammar when I ask"))
    assert set(designer.sketch.slots) == {"when", "then", "instruction", "name"}


def test_changing_the_when_drops_what_no_longer_belongs(home):
    asked = "Say which of my folders a file with this name would belong in."
    designer, _, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                       form(NOTHING_MISSING, "Then it answers when you ask.", when=IN_CHAT, then=ANSWER,
                                            rule=asked), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("actually I'd rather just ask it"))
    assert designer.sketch.slots == {"when": IN_CHAT, "then": ANSWER, "instruction": asked, "name": "Paper sorter"}
    assert one(events, AgentCard).kind == IN_CHAT


def test_changing_only_the_then_keeps_what_the_when_needs(home):
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(NOTHING_MISSING, "It writes about them now.", when=NEW_FILE, then=NOTE,
                                    rule="Say in one line what this file is."), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("don't move them, just write me a line about each"))
    slots = designer.sketch.slots
    assert slots["folder"] == str(home / "Downloads") and slots["looks_at"] == INSIDE_FILE
    assert not {"choices", "open", "into"} & set(slots) and slots["notes"] == ""


def test_a_folder_that_is_not_there_is_refused_and_said(home):
    designer, script, _ = designing(
        form(say="Okay, I'll watch Papres. Which folders should they go into?", when=NEW_FILE, then=MOVE,
             folder=("", "Papres")),
        form(say="I can't find a folder called Papres. Which one did you mean?", asks="folder", when=NEW_FILE, then=MOVE))
    events = list(designer.start(REQUEST))
    assert "folder" not in designer.sketch.slots
    # Told why not and to ask, and not to use the name anywhere else: hinted that it might
    # be meant for another setting, a model made a mistyped folder into a new place for the results.
    assert 'There is no folder called "Papres" on this computer' in script.notes[1]
    assert "don't put that name in any other setting" in script.notes[1]
    question = one(events, Question)
    assert question.id == DESIGN and "Which one did you mean?" in question.text


def test_a_refused_change_keeps_what_was_known_and_is_not_said_again_and_again(home):
    wrong = dict(when=NEW_FILE, then=MOVE, folder=("", "Keepers"))  # where the folders should go, put in the folder to watch
    designer, script, _ = designing(
        form(say="Which folders should they go into?", when=NEW_FILE, then=MOVE, folder=("Downloads", "")),
        form(say="Okay, Keepers it is.", **wrong), form(say="Okay, Keepers it is.", **wrong),
        form(say="No, only files that land from now on. Which folders should they go into?", **wrong),
        form(say="Sorry, where is Keepers?", asks="folder", **wrong),
        form(say="Sorry, where is Keepers?", asks="folder", **wrong))
    list(designer.start(REQUEST))
    events = list(designer.answer("put them in a folder called Keepers"))
    words = said(events)
    assert designer.sketch.slots["folder"] == str(home / "Downloads")  # what was known stays
    assert 'I can\'t find a folder called "Keepers", so that stays as it was (Folder it watches: Downloads).' in words
    assert "Which folders should the files go into?" in words and "Keepers it is" not in words
    # Sent again while the user talks about something else, it is passed over without a word.
    events = list(designer.answer("wait will it move my old files too?"))
    assert "only files that land from now on" in said(events) and "can't find" not in said(events)
    assert len(script.notes) == 4  # one go: nothing was refused this time
    # Named again by the user, it is refused again and said.
    events = list(designer.answer("no i mean watch my Keepers folder"))
    assert 'I can\'t find a folder called "Keepers"' in said(events)


def test_refused_twice_code_says_its_own_plain_line(home):
    wrong = form(say="Okay, I'll watch Papres. Which folders should they go into?", when=NEW_FILE, then=MOVE,
                 folder=("", "Papres"))
    designer, _, _ = designing(wrong, dict(wrong))
    events = list(designer.start(REQUEST))
    words = said(events)
    assert 'I can\'t find a folder called "Papres".' in words and "Which folder should it watch for new files?" in words
    assert "I'll watch Papres" not in words


def test_the_card_waits_in_a_turn_where_something_was_refused(home):
    # Asked for a folder that isn't there, the model guessed Downloads for the rest; with that
    # nothing is missing, but the card would be for a folder the user never named.
    guessed = dict(when=NEW_FILE, then=MOVE, choices="Boat", rule=RULE)
    designer, _, rehearsal = designing(
        form(say="Okay, watching Papres.", folder=("", "Papres"), **guessed),
        form(say="I can't find a folder called Papres. Which folder should I watch?", asks="folder",
             folder=("Downloads", ""), **guessed),
        form(NOTHING_MISSING, "Downloads it is.", folder=("Downloads", ""), **guessed), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert not has(events, AgentCard) and not has(events, Result) and rehearsal.calls == 0
    assert one(events, Question).text.endswith("Which folder should I watch?")
    events = list(designer.answer("oops i meant downloads"))
    assert has(events, AgentCard) and rehearsal.calls == 1


def test_words_that_point_at_a_card_are_not_said_when_no_card_follows(home):
    # The second form of such a turn was still told that the card comes, and said "The card
    # below has the button to create it" with nothing below.
    guessed = dict(when=NEW_FILE, then=MOVE, choices="Boat", rule=RULE)
    designer, script, _ = designing(
        form(NOTHING_MISSING, "Watching Papres. The card below has the button.", folder=("", "Papres"), **guessed),
        form(NOTHING_MISSING, "I couldn't find Papres, so it will watch Downloads. The card below has the button to "
                              "create it.", folder=("Downloads", ""), **guessed), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert CARD_COMES in script.notes[0] and CARD_WAITS not in script.notes[0]
    assert CARD_WAITS in script.notes[1] and CARD_COMES not in script.notes[1]  # told that no card follows
    assert said(events) == "I couldn't find Papres, so it will watch Downloads."  # and taken off in code all the same
    assert not has(events, AgentCard) and designer.sketch.waiting == DESIGN
    # When it said nothing else, code says what it could not use.
    designer, _, _ = designing(
        form(NOTHING_MISSING, "Watching Papres.", folder=("", "Papres"), **guessed),
        form(NOTHING_MISSING, "The card below has the button.", folder=("Downloads", ""), **guessed), rows=[ROWS])
    assert said(list(designer.start(REQUEST))) == 'I can\'t find a folder called "Papres".'


def test_a_place_the_model_guessed_is_not_said_back(home):
    wrong = form(say="Okay!", when=NEW_FILE, then=MOVE, folder=("Documents", "Papres"))
    designer, script, _ = designing(wrong, dict(wrong))
    events = list(designer.start(REQUEST))
    assert "Documents" not in script.notes[1].split("PROBLEMS WITH YOUR LAST FORM")[1].split("FORM NOTE")[0]
    assert "Documents" not in said(events)


def test_a_folder_named_with_the_wrong_place_is_still_found(home):
    (home / "Desktop" / "Papers").mkdir()
    designer, _, _ = designing(form(say="Which folders should they go into?", when=NEW_FILE, then=MOVE,
                                    folder=("Documents", "Papers")))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["folder"] == str(home / "Desktop" / "Papers")


def test_a_place_written_as_a_name_is_the_place_and_more_than_one_folder_is_asked_about(home):
    designer, _, _ = designing(form(say="Which folders?", when=NEW_FILE, then=MOVE, folder=("", "downloads")))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["folder"] == str(home / "Downloads")

    (home / "Desktop" / "Papers").mkdir()
    (home / "Documents" / "Papers").mkdir()
    two = form(say="Okay, Papers.", when=NEW_FILE, then=MOVE, folder=("", "Papers"))
    designer, script, _ = designing(two, dict(two))
    events = list(designer.start(REQUEST))
    assert "folder" not in designer.sketch.slots and "Ask which one they mean." in script.notes[1]
    # Code's own line asks already, so the setting's plain question is not asked on top of it.
    asked = one(events, Question).text
    assert asked.startswith('I found more than one folder called "Papers": ') and asked.endswith(". Which one do you mean?")
    assert str(Path("Desktop") / "Papers") in asked and str(Path("Documents") / "Papers") in asked


def test_a_system_folder_is_never_taken(home, monkeypatch):
    monkeypatch.setattr(designer_mod, "is_blocked", lambda folder: folder.name == "Downloads")
    wrong = form(say="Okay.", when=NEW_FILE, then=MOVE, folder=("Downloads", ""))
    designer, _, _ = designing(wrong, dict(wrong))
    events = list(designer.start(REQUEST))
    assert "folder" not in designer.sketch.slots and "That's a system folder" in said(events)


def test_the_same_folder_is_not_looked_for_again_each_turn(home, monkeypatch):
    (home / "Desktop" / "Papers").mkdir()
    looked = []
    real = designer_mod.find_folders
    monkeypatch.setattr(designer_mod, "find_folders", lambda name, place, limit=6: looked.append(name) or real(name, place, limit))
    same = dict(when=NEW_FILE, then=MOVE, folder=("", "Papers"))
    designer, _, _ = designing(form(say="Which folders?", **same), form(say="And what stays?", **same))
    list(designer.start(REQUEST))
    list(designer.answer("boat things"))
    assert looked == ["Papers"] and designer.sketch.slots["folder"] == str(home / "Desktop" / "Papers")


def test_once_the_card_is_up_the_model_is_told_so_and_reads_the_try_out(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(say="Only new ones.", **MOVER),
                                    rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("will it move my old files?"))
    # (How to design speaks of "THE TRY-OUT" in every note; its own section has a heading that says what was tried.)
    assert CARD_COMES in script.notes[0] and CARD_IS_UP not in script.notes[0] and "\nTHE TRY-OUT (" not in script.notes[0]
    assert CARD_IS_UP in script.notes[1] and CARD_COMES not in script.notes[1]
    assert "\nTHE TRY-OUT (" in script.notes[1] and "The card is already on their screen, below the try-out." in script.notes[1]
    # What the built-in model took each file for is there to put a rule right by.
    assert "In brackets after each file: what the small model took it for, or why it stays." in script.notes[1]
    assert "- boat_insurance.pdf → Boat (read as an insurance letter for a boat)" in script.notes[1]
    assert "on the newest files in their folder; nothing was changed" in script.notes[1]  # what was really tried


def test_a_new_folder_needs_a_place_and_the_watched_folder_is_inside(home):
    base = dict(when=NEW_FILE, then=MOVE)
    designer, script, _ = designing(form(say="Where?", folder=("Downloads", ""), into=("", "Sorted"), **base),
                                    form(say="On the Desktop or in Documents?", asks="into", **base),
                                    form(NOTHING_MISSING, "Here it is.", into=("Downloads", ""), choices="Boat", rule=RULE,
                                         **base), rows=[ROWS])
    list(designer.start(REQUEST))
    assert "into" not in designer.sketch.slots and 'ask where "Sorted" should be made' in script.notes[1]
    list(designer.answer("just keep them in downloads"))
    assert designer.sketch.slots["into"] == ""  # the watched folder itself means inside it


def test_a_folder_named_for_the_results_can_be_the_one_it_watches_and_they_then_stay_inside_it(home):
    # Asked which folder to watch, someone named the one their results were to go into. The
    # setup before this one refused that folder; a card takes it, and has one place, not two.
    (home / "Desktop" / "Sorted").mkdir()
    base = dict(when=NEW_FILE, then=MOVE)
    designer, _, _ = designing(form(say="Which folder do the new files land in?", into=("Desktop", "Sorted"), **base),
                               form(say="Which folders should they go into?", folder=("Desktop", "Sorted"), **base))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["into"] == str(home / "Desktop" / "Sorted") and "folder" not in designer.sketch.slots
    list(designer.answer("that same one, Sorted on my desktop"))
    assert designer.sketch.slots["folder"] == str(home / "Desktop" / "Sorted")
    assert designer.sketch.slots["into"] == ""  # the same folder: its results go inside it


def test_where_the_results_go(home):
    base = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""))
    designer, script, _ = designing(form(say="Which folders?", into=("Desktop", "Sorted"), **base),
                                    form(say="Which folders?", into=(INSIDE, "Sorted")),
                                    form(say="Which folders?", into=("", str(home / "Documents" / "Filed"))),
                                    form(say="Which folders?", into=(INSIDE, "")))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["into"] == str(home / "Desktop" / "Sorted")  # a new folder in a place they named
    list(designer.answer("no, inside downloads"))
    assert designer.sketch.slots["into"] == str(home / "Downloads" / "Sorted")
    list(designer.answer("a path"))
    assert f"- Where those folders are kept: {Path('Downloads') / 'Sorted'}" in script.notes[2]
    assert designer.sketch.slots["into"] == str(home / "Documents" / "Filed")  # a path they typed
    list(designer.answer("no, right inside"))
    assert designer.sketch.slots["into"] == ""
    # A notes file is a place too: its name is taken as they said it.
    designer, _, _ = designing(form(say="What should it write?", when=NEW_FILE, then=NOTE, folder=("Downloads", ""),
                                    notes=("Documents", "Reading log")))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["notes"] == str(home / "Documents" / "Reading log")


def test_their_own_name_for_a_place_is_kept_as_they_gave_it(home):
    # Cleaned the way a made-up name is, "C++ projects" became "C projects": a new folder
    # beside the one they have.
    (home / "Desktop" / "C++ projects").mkdir()
    (home / "Desktop" / "Mom's papers").mkdir()
    base = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""))
    designer, _, _ = designing(form(say="Which folders?", into=("Desktop", "C++ projects"), **base),
                               form(say="Which folders?", into=("Desktop", "moms papers")),
                               form(say="Which folders?", into=("Desktop", "Dad's  things.")),
                               form(say="Which folders?", into=(INSIDE, "R&D [old]")))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["into"] == str(home / "Desktop" / "C++ projects")
    list(designer.answer("no, with mom's papers"))
    assert designer.sketch.slots["into"] == str(home / "Desktop" / "Mom's papers")  # the folder that is there, as it is spelled
    list(designer.answer("no, a new one for dad"))
    assert designer.sketch.slots["into"] == str(home / "Desktop" / "Dad's things")  # a new one, named as they said
    list(designer.answer("no, inside downloads"))
    assert designer.sketch.slots["into"] == str(home / "Downloads" / "R&D [old]")
    # A notes file's name is theirs too, whole and with its marks.
    long_name = "A very long name for my notes file about everything that ever lands here"
    noter = dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""))
    designer, _, _ = designing(form(say="What should it write?", notes=("Documents", "Dad's log"), **noter),
                               form(say="What should it write?", notes=("Documents", "C# notes.txt")),
                               form(say="What should it write?", notes=("Documents", long_name)))
    list(designer.start(REQUEST))
    assert parts.notes_path(designer.sketch.slots) == home / "Documents" / "Dad's log.md"
    list(designer.answer("call it C# notes.txt"))
    assert parts.notes_path(designer.sketch.slots) == home / "Documents" / "C# notes.txt"
    list(designer.answer("no, a long name"))
    assert parts.notes_path(designer.sketch.slots) == home / "Documents" / f"{long_name}.md"


def test_a_folder_it_has_said_again_the_way_the_note_shows_it_is_no_change(home, tmp_path_factory):
    """The model fills every setting in again each turn, as KNOWN SO FAR shows it. Looked up
    like a new folder, one outside the home folder or deep inside it couldn't be found, and
    the user was told that a folder which was set didn't exist."""
    inbox = tmp_path_factory.mktemp("another drive") / "Inbox"  # outside the home folder: shown by its own name
    inbox.mkdir()
    old = store.Agent("Paper sorter", "custom",
                      {"when": NEW_FILE, "then": MOVE, "folder": str(inbox), "looks_at": INSIDE_FILE, "choices": "Boat",
                       "open": OPEN_NO, "into": "", "instruction": RULE, "name": "Paper sorter"})
    store.save(old)
    again = dict(when=NEW_FILE, then=MOVE, folder=("", "Inbox"))
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY, **again), rows=[ROWS])
    events = list(designer.edit(old, "make Paper sorter go by the file names only"))
    assert "- Folder it watches: Inbox" in script.notes[0] and len(script.notes) == 1  # nothing was refused
    assert designer.sketch.slots["folder"] == str(inbox) and has(events, AgentCard) and "can't find" not in said(events)

    # Somewhere else in the home folder: shown, and said again, from the home folder.
    (home / "Projects" / "Papers").mkdir(parents=True)
    (home / "Projects" / "Sorted").mkdir()
    base = dict(when=NEW_FILE, then=MOVE)
    designer, script, _ = designing(
        form(say="Which folders?", folder=("", "Papers"), into=("", str(home / "Projects" / "Sorted")), **base),
        form(say="No, only new ones. Which folders?", folder=("", str(Path("Projects") / "Papers")),
             into=("", str(Path("Projects") / "Sorted")), **base),
        form(say="Which folders?", folder=("", "projects/papers"), into=("", "Sorted"), **base))
    list(designer.start(REQUEST))
    kept = (str(home / "Projects" / "Papers"), str(home / "Projects" / "Sorted"))
    for words in ("will it touch old files?", "hm"):
        events = list(designer.answer(words))
        assert (designer.sketch.slots["folder"], designer.sketch.slots["into"]) == kept
        assert "can't find" not in said(events) and "Where should" not in said(events)
    assert len(script.notes) == 3  # one form a turn: nothing went back

    # Deep inside one of the places people name, said again as that place and its own name.
    deep = home / "Documents" / "Projects" / "2026" / "Autumn" / "Inbox"
    deep.mkdir(parents=True)
    (home / "Desktop" / "Inbox").mkdir()
    store.save(store.Agent("Paper sorter", "custom", {**old.slots, "folder": str(deep)}))
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY, when=NEW_FILE, then=MOVE,
                                         folder=("Documents", "Inbox")),
                                    form(NOTHING_MISSING, "The one on the Desktop now.", when=NEW_FILE, then=MOVE,
                                         folder=("Desktop", "Inbox")), rows=[ROWS])
    events = list(designer.edit(store.find_agent("Paper sorter"), "go by the file names only"))
    assert designer.sketch.slots["folder"] == str(deep) and has(events, AgentCard) and len(script.notes) == 1
    # A folder of the same name in another place is another folder.
    list(designer.answer("watch the Inbox on my desktop instead"))
    assert designer.sketch.slots["folder"] == str(home / "Desktop" / "Inbox")


def test_an_empty_value_never_erases_a_known_one(home):
    designer, _, _ = designing(form(say="What should stay where it is?", when=NEW_FILE, then=MOVE,
                                    folder=("Downloads", ""), choices="Boat", looks_at=NAME_ONLY),
                               form(say="And what else?"))
    list(designer.start(REQUEST))
    list(designer.answer("only boat things move"))
    slots = designer.sketch.slots
    assert (slots["when"], slots["then"], slots["folder"]) == (NEW_FILE, MOVE, str(home / "Downloads"))
    assert (slots["choices"], slots["looks_at"]) == ("Boat", NAME_ONLY)


def test_a_choice_that_is_not_one_of_the_choices_is_not_taken(home):
    designer, _, _ = designing(form(say="Which folders?", when=NEW_FILE, then=MOVE, folder=("Downloads", ""),
                                    looks_at="By its name", open="yes"))
    list(designer.start(REQUEST))
    assert "looks_at" not in designer.sketch.slots and "open" not in designer.sketch.slots


def test_more_folders_than_can_be_named_are_refused_never_cut(home):
    many = ", ".join(f"Box {number}" for number in range(parts.MAX_CHOICES + 1))
    wrong = form(say="All of them, then.", when=NEW_FILE, then=MOVE, folder=("Downloads", ""), choices=many, rule=RULE)
    designer, script, _ = designing(wrong, dict(wrong))
    events = list(designer.start(REQUEST))
    assert "choices" not in designer.sketch.slots and "at most 12 can be named" in script.notes[1]
    assert "I can keep at most 12 folders by name, and that was 13." in said(events) and not has(events, AgentCard)


def test_a_card_that_has_more_folders_than_a_new_list_may_name_can_still_be_changed(home):
    # A card that makes folders as it goes, or one from before there were cards, may hold
    # more than twelve: its own list, filled in again, was refused as too long.
    boxes = [f"Box {number}" for number in range(parts.MAX_CHOICES + 1)]
    old = store.Agent("Paper sorter", "custom",
                      {"when": NEW_FILE, "then": MOVE, "folder": str(home / "Downloads"), "looks_at": INSIDE_FILE,
                       "choices": ", ".join(boxes), "open": OPEN_YES, "into": "", "instruction": RULE,
                       "name": "Paper sorter"})
    store.save(old)
    base = dict(when=NEW_FILE, then=MOVE)
    renamed = ", ".join(["Crate 0", *boxes[1:]])
    longer = ", ".join([*boxes, "One more"])
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY, choices=", ".join(boxes), **base),
                                    form(NOTHING_MISSING, "Renamed.", choices=renamed, **base),
                                    form(NOTHING_MISSING, "One more.", choices=longer, **base),
                                    form(NOTHING_MISSING, "One more.", choices=longer, **base), rows=[ROWS])
    events = list(designer.edit(old, "make Paper sorter go by the file names only"))
    assert has(events, AgentCard) and len(script.notes) == 1 and "at most" not in said(events)
    assert designer.sketch.slots["choices"] == ", ".join(boxes) and designer.sketch.slots["looks_at"] == NAME_ONLY
    list(designer.answer("call the first box Crate 0"))
    assert designer.sketch.slots["choices"] == renamed  # as many as it had: taken
    events = list(designer.answer("and add one more"))
    assert designer.sketch.slots["choices"] == renamed  # more than it had, and more than may be named: said
    assert "I can keep at most 12 folders by name, and that was 14." in said(events)


def test_a_folder_with_and_in_its_name_is_not_taken_apart_when_the_list_is_said_again(home):
    # The model fills the list in again as it reads it. Shown without its quotes, one folder
    # came back as two, and the card changed under a question about something else.
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **{**MOVER, "choices": 'Boat, "Rock and Roll"'}),
        form(say="Only new ones.", **{**MOVER, "choices": "Boat, Rock and Roll"}),
        form(say="Yes.", **{**MOVER, "choices": 'Boat, "Rock and Roll"'}),
        form(say="Yes.", **{**MOVER, "choices": 'rock and roll, boat'}),
        form(NOTHING_MISSING, "Three folders now.", **{**MOVER, "choices": "Boat, Rock, Roll"}), rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.sketch.slots["choices"] == "Boat, Rock and Roll"
    for words in ("will it touch old files?", "sure?", "really?"):
        events = list(designer.answer(words))
        assert designer.sketch.slots["choices"] == "Boat, Rock and Roll"
        assert not has(events, AgentCard) and not has(events, Result) and rehearsal.calls == 1
    # It reads the list the way it must be written back.
    assert '- Folders it moves files into: Boat, "Rock and Roll"' in script.notes[1]
    # Told that they are two folders, it can still say so.
    events = list(designer.answer("no, Rock and Roll are two folders"))
    assert designer.sketch.slots["choices"] == "Boat, Rock, Roll" and has(events, AgentCard)
    # A card they have with such a folder is read the same way.
    old = store.Agent("Old sorter", "custom", {**designer.sketch.slots, "choices": "Boat, Rock and Roll",
                                               "folder": str(home / "Desktop"), "name": "Old sorter"})
    store.save(old)
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", when=NEW_FILE, then=MOVE, looks_at=NAME_ONLY,
                                         choices="Boat, Rock and Roll"), rows=[ROWS])
    list(designer.edit(old, "go by the file names only"))
    assert '- Folders it moves files into: Boat, "Rock and Roll"' in script.notes[0]
    assert designer.sketch.slots["choices"] == "Boat, Rock and Roll"


def test_folders_may_stay_unnamed_when_it_may_make_them(home):
    free = {**MOVER, "choices": "", "open": OPEN_YES}
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **free), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert designer.sketch.slots["choices"] == "" and designer.sketch.slots["open"] == OPEN_YES
    assert "Move each file the rule covers into a folder, made when the rule calls for one" in one(events, AgentCard).can_do


def test_folders_named_with_a_sign_or_a_small_picture_are_folders(home):
    # Such a name has no letter in it, and counted for nothing: the folders they had named
    # were dropped without a word, and they were asked which folders the files should go into.
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "choices": "📚, ★"}), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert designer.sketch.slots["choices"] == "📚, ★" and len(script.notes) == 1
    assert "Move each file the rule covers into one of: 📚, ★" in one(events, AgentCard).can_do


def test_a_rule_that_is_too_long_goes_back_once_then_is_cut_at_a_sentence(home):
    long_rule = " ".join(f"Sentence number {number} says what to leave alone." for number in range(20))
    assert len(long_rule) > parts.MAX_RULE
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "rule": long_rule}),
                                    form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert "can be at most 600" in script.notes[1] and designer.sketch.slots["instruction"] == RULE
    assert has(events, AgentCard)  # put right by its second form: the card comes in the same turn

    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "rule": long_rule}),
                               form(NOTHING_MISSING, "Here it is.", **{**MOVER, "rule": long_rule}), rows=[ROWS])
    events = list(designer.start(REQUEST))
    rule = designer.sketch.slots["instruction"]
    assert len(rule) <= parts.MAX_RULE and rule.endswith("alone.") and long_rule.startswith(rule)
    assert f"Rule: {rule}" in one(events, AgentCard).can_do  # the card shows the rule as it will be followed


def test_the_rule_is_kept_as_one_paragraph(home):
    designer, _, _ = designing(form(say="Which folder?", when=NEW_FILE, then=NOTE,
                                    rule='"Say what the file is.\n\nLeave out anything marked "private"."'))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["instruction"] == '"Say what the file is. Leave out anything marked "private"."'
    designer, _, _ = designing(form(say="Which folder?", when=NEW_FILE, then=NOTE, rule='"Say what the file is."'))
    list(designer.start(REQUEST))
    assert designer.sketch.slots["instruction"] == "Say what the file is."  # only quotes around the whole of it come off


# ------------------------------------------------------------------ the name


def test_the_models_name_is_taken_until_the_card_and_then_only_the_users(home):
    designer, _, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                       form(say="Only new ones.", **{**MOVER, "name": "File tidier"}),
                                       form(NOTHING_MISSING, "Renamed.", **{**MOVER, "name": "Boat keeper"}), rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.sketch.slots["name"] == "Paper sorter"
    events = list(designer.answer("will it touch old files?"))
    assert designer.sketch.slots["name"] == "Paper sorter" and not has(events, AgentCard)  # the card is up: its own new idea is not taken
    events = list(designer.answer("call it Boat keeper"))
    assert designer.sketch.slots["name"] == "Boat keeper"
    assert one(events, AgentCard).name == "Boat keeper"
    assert not has(events, Result) and rehearsal.calls == 1  # a new name alone is the same helper: not tried again


def test_a_name_said_for_a_folder_is_not_the_helpers_name(home):
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "Boat"}), rows=[ROWS])
    list(designer.start(REQUEST + ", and can you call the folder Boat"))
    assert designer.sketch.slots["name"] == "Downloads helper"  # code's own, from the folder
    # Also when the word is in no setting of the card: the model put it only in the name.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "Keepers"}), rows=[ROWS])
    events = list(designer.start(REQUEST + ", and can you call the folder Keepers"))
    assert designer.sketch.slots["name"] == "Downloads helper" and one(events, AgentCard).name == "Downloads helper"
    # Or put it where it was refused: a new folder with no place to make it in.
    unplaced = form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "Keepers", "into": ("", "Keepers")})
    designer, _, _ = designing(unplaced, dict(unplaced))
    list(designer.start("my downloads are a mess, put the folders in Keepers"))
    assert "into" not in designer.sketch.slots and "name" not in designer.sketch.slots
    # Named so by the user, it is.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "Boat"}), rows=[ROWS])
    list(designer.start(REQUEST + ", and name the helper Boat"))
    assert designer.sketch.slots["name"] == "Boat"
    # The model's own name may be made of words they used, when they named nothing with them.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    list(designer.start("I'd like a paper sorter for my downloads"))
    assert designer.sketch.slots["name"] == "Paper sorter"


def test_with_no_name_from_the_model_code_makes_a_plain_one(home, monkeypatch):
    fixer = dict(rule="Correct the grammar and spelling of the text. Keep its meaning.")
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=ANSWER, **fixer))
    list(designer.start("fix my grammar when I ask"))
    assert designer.sketch.slots["name"] == "Chat helper"
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=WHILE_ON, then=SHOW, **fixer))
    list(designer.start("fix the grammar of what I highlight"))
    assert designer.sketch.slots["name"] == "Highlight helper"


def test_a_name_that_is_taken_is_made_another(home):
    store.save(store.Agent("Paper sorter", "custom", {"when": IN_CHAT, "instruction": "Say hello.", "name": "Paper sorter"}))
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": '"Paper sorter:"'}), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert designer.sketch.slots["name"] == "Paper sorter 2" and one(events, AgentCard).name == "Paper sorter 2"
    assert f"- A helper they already have: Paper sorter: {IN_CHAT} — Say hello." in script.notes[0]
    list(designer.choose(CARD, CREATE_IT))
    assert sorted(a.name for a in store.list_agents()) == ["Paper sorter", "Paper sorter 2"]  # the one they had is untouched
    # With no helper being changed, no name is let through as that helper's own.
    store.save(store.Agent("Agent", "custom", {"when": IN_CHAT, "instruction": "Say hello.", "name": "Agent"}))
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "agent"}), rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.sketch.slots["name"] == "Agent 2"


# ------------------------------------------------------ one they already have


def test_a_helper_that_repeats_one_they_have_is_asked_about_first(home):
    card_they_have(home)
    # Use it: nothing is made, and the conversation is over.
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "File tidier"}),
                                            rows=[ROWS])
    events = list(designer.start(REQUEST))
    question = one(events, Question)
    assert question.id == DUPLICATE and question.choices == ["Use Paper sorter", "Change Paper sorter", MAKE_ANOTHER]
    assert question.text == ("You already have Paper sorter, which works on the new files in Downloads in the same "
                             "way. What would you like to do?")
    assert "Here it is" not in said(events) and not has(events, AgentCard) and rehearsal.calls == 0
    assert designer.sketch.waiting == DUPLICATE
    # A click on a card that isn't up asks it again, with its buttons.
    again = one(list(designer.choose(CARD, CREATE_IT)), Question)
    assert (again.id, again.text, again.choices) == (question.id, question.text, question.choices)
    events = list(designer.choose(DUPLICATE, "Use Paper sorter"))
    assert not designer.active and script.released and [a.name for a in store.list_agents()] == ["Paper sorter"]
    assert said(events) == "Okay, keep using Paper sorter. It works while it's switched on in your helpers list."
    assert "already been answered" in said(list(designer.choose(DUPLICATE, "Use Paper sorter")))

    # Change it: the conversation carries on about the one they have, from what they first asked for.
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(NOTHING_MISSING, "It goes by names now.", looks_at=NAME_ONLY), rows=[ROWS])
    list(designer.start(REQUEST + ", going by the names"))
    events = list(designer.answer("change paper sorter"))  # typed word for word instead of clicked
    assert designer.active and designer.sketch.editing and designer.sketch.replaces == "Paper sorter"
    assert script.turns[1] == [{"role": "user", "content": REQUEST + ", going by the names"}]
    assert EDITING in script.notes[1] and one(events, AgentCard).actions[0] == SAVE_CHANGES

    # Make another one: said to the model like anything typed, and not asked about again.
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                            form(NOTHING_MISSING, "Here is another one.", **MOVER),
                                            form(say="Only new ones.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.sketch.slots["name"] == "Paper sorter 2"  # what the form said was taken before it was asked
    events = list(designer.choose(DUPLICATE, MAKE_ANOTHER))
    assert script.turns[1][-2:] == [{"role": "assistant", "content": question.text},
                                    {"role": "user", "content": MAKE_ANOTHER}]
    assert one(events, AgentCard).name == "Paper sorter 2" and rehearsal.calls == 1
    events = list(designer.answer("will it move my old files?"))
    assert not has(events, Question) and "Only new ones." in said(events)


def test_what_counts_as_the_same_helper(home):
    hello = store.Agent("Greeter", "custom", {"when": WHILE_ON, "instruction": "Say hello  to them.", "name": "Greeter"})
    store.save(hello)
    manuals = home / "Documents" / "Manuals"
    manuals.mkdir()
    (manuals / "washer.txt").write_text("To start the washer, press the green button twice.", encoding="utf-8")
    store.save(store.Agent("Manuals helper", "documents_qa", {"folder": str(manuals), "name": "Manuals helper"}))
    # A helper that works on text: the same rule, word for word, whenever it works.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=ANSWER, rule="say hello to them."))
    question = one(list(designer.start("greet people for me")), Question)
    assert question.text == "You already have Greeter, which does the same. What would you like to do?"
    events = list(designer.choose(DUPLICATE, "Use Greeter"))
    assert said(events) == "Okay, keep using Greeter. It works while it's switched on in your helpers list."
    # One that answers from documents: the same folder. Only a card can be changed by talking.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=DOCUMENTS,
                                    folder=("Documents", "manuals")))
    question = one(list(designer.start("I want to ask questions about my manuals")), Question)
    assert question.id == DUPLICATE and question.choices == ["Use Manuals helper", MAKE_ANOTHER]
    assert f"which answers from the documents in {Path('Documents') / 'Manuals'}" in question.text
    events = list(designer.choose(DUPLICATE, "Use Manuals helper"))
    assert said(events) == 'Okay, keep using Manuals helper. To ask it something, start your message with "Manuals helper:".'
    # Not the same: another folder, another THEN in the same folder, another rule, or the one being changed.
    card_they_have(home)
    (home / "Desktop" / "Papers").mkdir()
    for other in (dict(MOVER, folder=("Desktop", "Papers")),
                  dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""), rule="Say in one line what this file is."),
                  dict(when=IN_CHAT, then=ANSWER, rule="Say goodbye to them.")):
        designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **other), rows=[ROWS])
        events = list(designer.start(REQUEST))
        assert has(events, AgentCard) and not any(isinstance(e, Question) and e.id == DUPLICATE for e in events)
    designer, _, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), rows=[ROWS])
    events = list(designer.edit(store.find_agent("Paper sorter"), "go by the file names only"))
    assert has(events, AgentCard) and not has(events, Question)


# ------------------------------------------------------------ ending it, or not


def test_never_mind_drops_it_and_something_else_hands_the_message_back_and_keeps_the_helper(home):
    designer, script, _ = designing(form(say="What bothers you about them?"), form(CALLED_OFF, "No problem, I'll leave it."))
    list(designer.start(REQUEST))
    events = list(designer.answer("hmm actually i don't need it"))
    assert not designer.active and "No problem" in said(events) and script.released
    assert store.list_agents() == [] and designer.handoff is None and designer.aside is None

    designer, script, _ = designing(form(say="What bothers you about them?"), form(MOVED_ON, "Paris!"))
    list(designer.start(REQUEST))
    events = list(designer.answer("what's the capital of France?"))
    assert not designer.active and designer.handoff == "what's the capital of France?" and script.released
    # Nothing is said in words on the way out: the engine answers it, as it answers any
    # message, and that answer is the first thing they read.
    assert said(events) == "" and [type(e) for e in events] == [Thinking]
    assert designer.aside is not None  # the helper is kept: an aside used to throw it away


def test_called_off_with_no_way_chosen_yet_is_called_off_and_keeps_no_idea(home):
    """ "hm its not worth it. forget about it", said before a WHEN and a THEN were chosen,
    came back as "cancel" with "None of these" for both. Read as a helper that cannot be
    made, it was answered "Nothing was created, and I've kept the idea in your list"."""
    designer, script, _ = designing(form(say="How would you tell which ones belong together?"),
                                    form(CALLED_OFF, "No problem at all.", when=NONE_FIT, then=NONE_FIT))
    list(designer.start("i can never find the photos from one trip"))
    events = list(designer.answer("hm its not worth it. forget about it"))
    assert not designer.active and said(events) == "No problem at all." and planner.list_ideas() == []
    assert designer.aside is None and designer.handoff is None and script.released


def test_called_off_without_a_word_code_says_so(home):
    designer, _, _ = designing(form(say="What bothers you about them?"), form(CALLED_OFF))
    list(designer.start(REQUEST))
    events = list(designer.answer("oh, I changed my mind about all this"))
    assert not designer.active and said(events) == "Okay, I won't create it."


def test_the_first_message_cannot_be_something_else(home):
    designer, _, _ = designing(form(MOVED_ON, "What would you like it to do?"))
    list(designer.start(REQUEST))
    assert designer.active and designer.handoff is None


def test_cancel_and_a_typed_never_mind_end_it_without_asking_the_model(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.choose(CARD, "Cancel"))
    assert not designer.active and "Okay, I won't create it." in said(events)
    assert store.list_agents() == [] and script.released and len(script.notes) == 1

    # Alone, before a comma or a full stop, or at the start of more: a turn of the model
    # costs as much as any answer through a plan, and it might not choose to end it.
    for words in ("Never mind.", "cancel", "stop!", "forget it", "never mind, I'll do it myself", "cancel this",
                  "Stop, forget it", "no thanks I'm fine", "그만"):
        designer, script, _ = designing(form(say="What bothers you about them?"))
        list(designer.start(REQUEST))
        events = list(designer.answer(words))
        assert not designer.active and "Okay, I won't create it." in said(events) and len(script.notes) == 1, words

    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("no"))  # a plain no to the card on screen
    assert not designer.active and store.list_agents() == []


def test_a_longer_message_that_begins_like_a_cancel_is_a_change(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(NOTHING_MISSING, "Pictures stay now.", **{**MOVER, "rule": RULE + " Never move a picture."}),
                                    rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("stop moving the pictures"))
    assert designer.active and designer.sketch.slots["instruction"].endswith("Never move a picture.")
    assert script.turns[1][-1] == {"role": "user", "content": "stop moving the pictures"}
    # Nor is a word that only begins like one of them.
    script.forms.append(form(say="It makes none.", **{**MOVER, "rule": RULE + " Never move a picture."}))
    list(designer.answer("cancellations of what?"))
    assert designer.active and len(script.notes) == 3


def test_a_design_model_that_fails_ends_the_conversation_plainly_with_nothing_made(home):
    designer, script, _ = designing(DesignerError("no answer"))
    events = list(designer.start(REQUEST))
    assert not designer.active and store.list_agents() == [] and script.released
    assert any(isinstance(e, Thinking) and "couldn't carry on (no answer)" in e.text for e in events)
    assert "I couldn't carry on working this helper out just now. Nothing was created." in said(events)
    assert designer.handoff is None and designer.take_created() is None
    # With the card already up, the same: the card is gone and nothing was made of it.
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), DesignerError("signed out"), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("also leave the pictures"))
    assert not designer.active and store.list_agents() == [] and "Nothing was created." in said(events)


def test_what_cannot_be_made_ends_honestly_and_is_kept_as_an_idea(home):
    designer, script, _ = designing(form(CANT_BE_MADE, "I can't press keys in other programs for you; that would take "
                                         "a part that isn't built.", when=NONE_FIT, then=NONE_FIT,
                                         wants="Press a key every ten minutes"))
    events = list(designer.start("press F5 for me every ten minutes"))
    assert not designer.active and store.list_agents() == [] and script.released
    words = said(events)
    assert "I can't press keys in other programs for you" in words
    assert 'Nothing was created, and I\'ve kept the idea in your list. Say "my ideas" to see it.' in words
    idea = planner.list_ideas()[0]
    assert (idea["request"], idea["title"]) == ("press F5 for me every ten minutes", "Press a key every ten minutes")
    assert idea["steps"] == [{"block": "other", "detail": "Press a key every ten minutes"}]
    # "None of these" on the form says the same, whatever the status says.
    designer, _, _ = designing(form(say="That can't be done here.", when=NONE_FIT))
    events = list(designer.start("press F5 for me every ten minutes"))
    assert not designer.active and "Nothing was created" in said(events) and len(planner.list_ideas()) == 2


def test_with_a_card_worked_out_none_of_these_alone_does_not_lose_it(home):
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(say="It can't send email, but the rest stays as it is.", when=NONE_FIT, then=NONE_FIT),
                               form(CANT_BE_MADE, "Then this can't be made.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("can it also email me a list?"))
    assert designer.active and designer.sketch.slots["then"] == MOVE and "can't send email" in said(events)
    list(designer.choose(CARD, "Change something"))
    events = list(designer.answer("no, emailing is the whole point"))
    assert not designer.active and store.list_agents() == []  # the status ends it


# ------------------------------------------------------------ the card and what creates


def test_a_click_on_a_button_is_taken_in_code_and_said_to_the_model(home):
    designer, script, _ = designing(
        form(say="Should it go by what's inside each file, or only by its name?", asks="looks_at", when=NEW_FILE,
             then=MOVE, folder=("Downloads", "")),
        form(say="And which folders should they go into?"))
    events = list(designer.start(REQUEST))
    question = one(events, Question)
    assert question.id == "looks_at" and question.choices == [INSIDE_FILE, NAME_ONLY]
    list(designer.choose("looks_at", NAME_ONLY))
    assert designer.sketch.slots["looks_at"] == NAME_ONLY
    assert script.turns[1][-1] == {"role": "user", "content": NAME_ONLY}
    assert f"- What it looks at: {NAME_ONLY}" in script.notes[1]  # the card it reads is code's


def test_a_questions_buttons_are_for_what_its_words_ask(home):
    """ "Should the explanation stay on the screen until you unhighlight the word, or should
    it disappear after a few seconds?" went out with the buttons for where the result is
    shown (a bubble, the clipboard, both): the form had named the wrong setting, and a
    click on any of them answered a question nobody had asked."""
    explainer = dict(when=WHILE_ON, then=SHOW)
    stays = "Should the explanation stay on the screen until you unhighlight the word, or should it disappear after a few seconds?"
    designer, _, _ = designing(form(say=stays, asks="show", **explainer), form(say="And what should it explain?", **explainer))
    question = one(designer.start("explain a word i highlight"), Question)
    assert question.id == "keep" and question.choices == [UNTIL_UNHIGHLIGHT, designer_mod.parts.THENS[SHOW].settings[1].choices[1]]
    list(designer.choose("keep", UNTIL_UNHIGHLIGHT))
    assert designer.sketch.slots["keep"] == UNTIL_UNHIGHLIGHT and "show" not in designer.sketch.slots
    # The same with one word of the setting the form named in it: most of its words are the other's.
    bubble = "Would you like that bubble to stay there until you unhighlight the text, or should it disappear after a few seconds?"
    designer, _, _ = designing(form(say=bubble, asks="show", **explainer))
    assert one(designer.start("explain a word i highlight"), Question).id == "keep"
    # Words that are about the setting the form named keep its buttons, and so do words
    # that share none with any choice: a question in another language is not second-guessed.
    for words in ("Should it show a bubble above the text, or copy the result?", "결과를 어떻게 보여 드릴까요?"):
        designer, _, _ = designing(form(say=words, asks="show", **explainer))
        question = one(designer.start("explain a word i highlight"), Question)
        assert question.id == "show" and question.choices == [BUBBLE, "Copy it to the clipboard", BOTH], words


def test_a_plain_yes_at_the_card_creates_but_ok_but_is_a_change(home):
    designer, _, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                       form(NOTHING_MISSING, "In Documents, then.", into=("Documents", "Sorted"), **MOVER),
                                       rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("ok but put them in documents"))
    assert store.list_agents() == [] and designer.sketch.slots["into"] == str(home / "Documents" / "Sorted")
    card = one(events, AgentCard)  # the card again, with the change
    assert f"Keep those folders in {Path('Documents') / 'Sorted'}" in card.can_do
    assert rehearsal.calls == 1  # where the folders are kept changes nothing a try-out would show: not tried again
    list(designer.answer("ok sounds good"))
    assert [a.slots["into"] for a in store.list_agents()] == [str(home / "Documents" / "Sorted")]


def test_a_question_at_the_card_is_answered_without_the_card_again(home):
    designer, _, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                       form(say="No, only files that land from now on.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("will it move my old files?"))
    assert "only files that land from now on" in said(events)
    assert not has(events, AgentCard) and not has(events, Result) and designer.sketch.waiting == CARD
    assert rehearsal.calls == 1
    list(designer.answer("Yes!"))
    assert len(store.list_agents()) == 1


def test_a_question_about_a_setting_with_a_usual_value_is_told_once_and_never_holds_the_card_back(home):
    """With everything known a model asked whether a bubble should stay up or go away by
    itself: such a setting gets its usual value, so the model is told once, and when it asks
    all the same the question comes off and the card comes. Left on, "Is it okay if I call
    this helper ...?" stood over a card with another name, and a yes to it created nothing."""
    asks = form(say="It sorts by what is inside. Would you like me to go only by the files' names instead?",
                asks="looks_at", **MOVER)
    designer, script, _ = designing(asks, dict(asks), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert len(script.notes) == 2 and "PROBLEMS WITH YOUR LAST FORM" not in script.notes[0]
    assert "Your question asks for `looks_at` (What it looks at), which has a usual value" in script.notes[1]
    assert said(events) == "It sorts by what is inside." and has(events, AgentCard)
    assert designer.sketch.slots["looks_at"] == INSIDE_FILE and designer.sketch.waiting == CARD
    # Nothing was asked, so a plain yes is a yes to the card.
    list(designer.answer("yes"))
    assert len(store.list_agents()) == 1


def test_a_question_about_a_place_that_has_a_usual_value_is_told_once_and_its_guess_is_not_taken(home):
    """With the rule not written yet, a model asked "Would you like that notes file to be
    named something specific, or should I just name it after the helper?", twice, and had
    filled in the Documents folder for it, which nobody had named: the notes file was taken
    out of the folder it belongs in."""
    writer = dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""))
    asks = form(say="Would you like that notes file to be named something specific?", asks="notes",
                notes=("Documents", ""), **writer)
    proposes = form(say="It would write two lines about each new file in Downloads. Is that right?",
                    rule="Write two lines about what the file is.", **writer)
    designer, script, _ = designing(asks, proposes)
    events = list(designer.start("write a couple of lines about each new file in my downloads"))
    assert len(script.notes) == 2
    assert ("Your question asks for `notes` (Notes file it writes in), which has a usual value, so it is not worth a "
            "question: leave it empty. What is still not known is: The rule. The rule is yours to write") in script.notes[1]
    # (Their one message said all of it, so the card comes without "Is that right?".)
    assert said(events) == "It would write two lines about each new file in Downloads." and has(events, AgentCard)
    assert designer.sketch.slots["notes"] == ""  # the place its question asked for was a guess: the usual one it is
    # Asked all the same, its question stands (something needed is still missing), and the guess is still not taken.
    designer, script, _ = designing(asks, dict(asks))
    events = list(designer.start("write a couple of lines about each new file in my downloads"))
    assert said(events) == asks["say"] and "notes" not in designer.sketch.slots
    # A place they named themselves is taken like any other, asked about or not.
    named = form(say="It would write two lines about each new file. Is that right?", notes=("Documents", "Reading log"),
                 rule="Write two lines about what the file is.", **writer)
    designer, script, _ = designing(named)
    list(designer.start("write a couple of lines about each new file in my downloads, in Reading log in my documents"))
    assert designer.sketch.slots["notes"] == str(home / "Documents" / "Reading log")


def test_a_place_nobody_said_is_not_taken_before_there_is_a_card(home):
    """A form gave the notes file the Documents folder, with nothing asked about it and
    not a word of it in what was said: the first card came with the notes outside the
    folder they are about."""
    writer = dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""), rule="Write two lines about what the file is.")
    request = "write a couple of lines about each new file in my downloads"
    silent = form(NOTHING_MISSING, "It writes two lines about each new file.", notes=("Documents", ""), **writer)
    designer, _, _ = designing(silent)
    events = list(designer.start(request))
    assert has(events, AgentCard) and designer.sketch.slots["notes"] == ""  # the usual place: inside the watched folder
    # Said in the form's own words, it is taken: they read it above the card.
    spoken = form(NOTHING_MISSING, "It writes two lines about each new file, in a notes file in your Documents folder.",
                  notes=("Documents", ""), **writer)
    designer, _, _ = designing(spoken)
    list(designer.start(request))
    assert designer.sketch.slots["notes"] == str(home / "Documents")
    # Said by them, it is taken with nothing more said; and a place with a name of its own
    # is a proposal that stands on the card to be seen, as before.
    for typed, given, where in ((request + " and keep the notes on my desktop", ("Desktop", ""), home / "Desktop"),
                                (request, ("Documents", "Reading log"), home / "Documents" / "Reading log")):
        designer, _, _ = designing(form(NOTHING_MISSING, "It writes two lines about each new file.", notes=given, **writer))
        list(designer.start(typed))
        assert designer.sketch.slots["notes"] == str(where), typed
    # Once a card is up, a place is changed like anything else on it.
    designer, _, _ = designing(silent, form(NOTHING_MISSING, "I moved the notes file.", notes=("Pictures", ""),
                                            changes="Keep the notes somewhere else.", **writer))
    list(designer.start(request))
    list(designer.answer("put the notes file with my photos instead"))
    assert designer.sketch.slots["notes"] == str(home / "Pictures")


def test_a_question_that_offers_a_result_is_told_once_which_results_can_be_made(home):
    """Of someone who wanted rough notes written out properly a model asked "Would you like
    it to just reply with the tidy version, or should it also save that entry into a
    specific notes file for you?", three plays out of three: no helper asked in the chat
    keeps anything in a file."""
    asks = form(say="Should it reply in the chat, or save the entry into a notes file for you?", asks="then",
                when=IN_CHAT, then=ANSWER)
    proposes = form(say="You would write its name and your notes, and it replies with the tidy entry. Is that right?",
                    when=IN_CHAT, then=ANSWER, rule="Write the notes out as a tidy entry.", name="Entry writer")
    designer, script, _ = designing(asks, proposes, form(say="And then?", asks="then", when=IN_CHAT, then=ANSWER))
    events = list(designer.start("turn my rough notes into a tidy entry"))
    assert len(script.notes) == 2 and said(events) == proposes["say"]
    told = script.notes[1].split("PROBLEMS WITH YOUR LAST FORM", 1)[1]
    # Only the result that follows a rule is offered; the one that follows none is named
    # apart, as another kind of helper. Offered side by side, the documents were asked about
    # as an extra to a helper that tidies notes, in two plays of three.
    assert ('Your question asks them what the helper should do THEN. With "When you ask in the chat" a helper that '
            'follows a rule can only be "Answers in the chat": nothing else can be made') in told
    assert ('("Answers from the documents in a folder" is a helper of another kind. It answers questions from the '
            "documents in one folder, and says which file each answer came from. It follows no rule. Offer it only when "
            "that is all they want, never beside another result.)") in told
    assert '"Answers in the chat" or "Answers from the documents in a folder"' not in told
    # Where every result follows a rule, the line is as it was measured.
    files = form(say="Should it move them, or write about them?", asks="then", when=NEW_FILE, folder=("Downloads", ""))
    other, files_script, _ = designing(files, form(say="It would move them. Is that right?", when=NEW_FILE, then=MOVE,
                                                   folder=("Downloads", "")))
    list(other.start("do something with each new file in my downloads"))
    assert ('Your question asks them what the helper should do THEN. With "When a new file lands in a folder" that can '
            'only be "Moves the file into a folder" or "Writes about the file in a notes file": nothing else can be '
            "made, and a question that offers anything else offers what cannot be done. If one of those is plainly "
            "what they described, take it and say how the helper would work; ask only when more than one of those "
            "would do, and offer nothing but those.") in files_script.notes[1]
    # Once: the next question about it goes out as it is.
    list(designer.answer("hm, what else could it do with them?"))
    assert len(script.notes) == 3 and designer.sketch.told_thens


def test_words_that_were_only_such_a_question_leave_codes_own_line(home):
    asks = form(say="Should the helper be called something else?", asks="name", **MOVER)
    designer, _, _ = designing(asks, dict(asks), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert said(events) == "Here is Paper sorter. Create it if it looks right." and has(events, AgentCard)


def test_a_model_told_once_that_its_question_is_not_needed_shows_the_card(home):
    designer, script, _ = designing(form(say="Should it go by the files' names instead?", asks="looks_at", **MOVER),
                                    form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert said(events) == "Here it is." and has(events, AgentCard) and designer.sketch.waiting == CARD


def test_the_button_works_while_a_question_is_open_at_the_card(home):
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(say="Only new ones. Which of the old ones matter to you?", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("will it move my old files?"))
    assert designer.sketch.waiting != CARD  # Noir has just asked something: a yes would answer that
    list(designer.choose(CARD, CREATE_IT))
    assert len(store.list_agents()) == 1


def test_a_yes_under_a_question_asked_at_the_card_answers_the_question_and_makes_nothing(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(say="Only new ones. Which of the old ones matter to you?", **MOVER),
                                    form(say="Then they stay where they are.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("will it move my old files?"))
    events = list(designer.answer("yes"))
    assert store.list_agents() == [] and designer.active  # the card is up, but the yes was to what Noir just asked
    assert script.turns[2][-1] == {"role": "user", "content": "yes"} and "Then they stay" in said(events)
    list(designer.answer("yes"))  # nothing is open now: this one is a yes to the card
    assert len(store.list_agents()) == 1


def test_the_button_of_a_card_that_is_not_up_asks_the_open_question_again(home):
    designer, script, _ = designing(form(say="What bothers you about them?"))
    list(designer.start(REQUEST))
    events = list(designer.choose(CARD, CREATE_IT))
    assert [(e.id, e.text) for e in events if isinstance(e, Question)] == [(DESIGN, "What bothers you about them?")]
    assert store.list_agents() == [] and len(script.notes) == 1 and designer.active
    # Nor does a yes typed before there is a card make anything: it is said to the model.
    script.forms.append(form(say="Which folder do they land in?"))
    list(designer.answer("yes"))
    assert store.list_agents() == [] and script.turns[1][-1] == {"role": "user", "content": "yes"}


def test_a_card_that_changed_since_it_was_shown_is_not_created_from_its_old_button(home):
    wrong = {**MOVER, "rule": RULE + " Leave the pictures.", "folder": ("", "Papres")}
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(say="Okay.", **wrong),
                               form(say="Okay.", **wrong), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.answer("leave the pictures, and watch Papres instead"))
    assert not has(events, AgentCard)  # the folder was refused, so the card waits, though the rule changed
    events = list(designer.choose(CARD, CREATE_IT))
    assert store.list_agents() == [] and has(events, Question)


def test_change_something_is_said_in_words(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(NOTHING_MISSING, "By name now.", looks_at=NAME_ONLY, **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    events = list(designer.choose(CARD, "Change something"))
    assert [e.id for e in events if isinstance(e, Question)] == [DESIGN]
    list(designer.answer("go by the file names instead"))
    assert designer.sketch.slots["looks_at"] == NAME_ONLY
    assert script.turns[1][-2:] == [{"role": "assistant", "content": "What should I change?"},
                                    {"role": "user", "content": "go by the file names instead"}]


def test_the_model_reads_places_by_name_never_the_whole_path(home):
    (home / "Projects" / "Papers").mkdir(parents=True)  # in the home folder, in none of the places people name
    base = dict(when=NEW_FILE, then=MOVE)
    designer, script, _ = designing(form(say="Which folders should they go into?", folder=("", "Papers"), **base),
                                    form(say="And what stays?", into=("Desktop", "Sorted"), choices="Boat", **base),
                                    form(say="Anything else that stays?", **base))
    events = list(designer.start(REQUEST))
    list(designer.answer("desktop, in Sorted, only Boat"))
    list(designer.answer("everything else stays"))
    assert all(str(home) not in note for note in script.notes)  # the user's name is in that path
    assert f"- Folder it watches: {Path('Projects') / 'Papers'}" in script.notes[1]
    assert f"- Where those folders are kept: {Path('Desktop') / 'Sorted'}" in script.notes[2]
    assert "- Downloads has 2 files in it right now" in script.notes[0]
    assert f"- {Path('Projects') / 'Papers'} has no files in it right now." in script.notes[1]
    assert "report.pdf" not in "".join(script.notes)  # how many and which endings, never their names
    assert "- They have no other helper yet." in script.notes[0]
    assert "- What it looks at: not known yet (usually: What's inside the file)" in script.notes[1]
    assert f"- Where those folders are kept: not known yet (usually: {INSIDE})" in script.notes[1]
    assert "- The rule: not known yet" in script.notes[1] and "- Name: not known yet (given one if you leave it empty)" in script.notes[1]
    assert all(str(home) not in e.text for e in events if isinstance(e, (Thinking, Question)))


# ----------------------------------------------------------------- the try-out


def test_the_try_out_runs_once_and_again_only_when_the_card_changed(home):
    stays = "the rule leaves it: a planting plan"
    changed = [ROWS[0], {**ROWS[1], "choice": "", "why": stays}, ROWS[2]]
    designer, _, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(say="Only new files, from then on.", **MOVER),
        form(NOTHING_MISSING, "Garden things stay now.", **{**MOVER, "rule": RULE + " Leave anything about tulips."}),
        form(NOTHING_MISSING, "Roses too.", **{**MOVER, "rule": RULE + " Leave anything about tulips or roses."}),
        rows=[ROWS, changed, changed])
    events = list(designer.start(REQUEST))
    result = one(events, Result)
    assert result.agent == "Try-out" and result.text == (
        "Tried on the 3 newest files in Downloads. Nothing was moved.\n"
        "boat_insurance.pdf → Boat (read as an insurance letter for a boat)\n"
        "tulips.docx → Garden (read as a planting plan)\nsetup.exe: stays (nothing inside it could be read)")
    assert any(isinstance(e, Thinking) and e.text == "Trying it on what's in Downloads now. Nothing moves." for e in events)
    # The dry run is given the card as an agent that was never saved.
    tried = rehearsal.agents[0]
    assert (tried.name, tried.blueprint, tried.slots) == ("Paper sorter", "custom", designer.sketch.slots)
    assert store.list_agents() == []

    events = list(designer.answer("will it touch what's already there?"))
    assert rehearsal.calls == 1 and not has(events, Result)  # nothing changed: not tried again

    events = list(designer.answer("leave the tulip things where they are"))
    assert rehearsal.calls == 2 and one(events, Result).text == (
        "Tried again on the same 3 files in Downloads. Nothing was moved.\n"
        "boat_insurance.pdf → Boat (read as an insurance letter for a boat)\n"
        "tulips.docx: stays now (was Garden; the rule leaves it: a planting plan)\n"
        "setup.exe: stays (nothing inside it could be read)")
    assert has(events, AgentCard)

    events = list(designer.answer("and roses"))
    assert rehearsal.calls == 3 and one(events, Result).text == (
        "Tried again on the same 3 files in Downloads. Nothing was moved.\nIt came out the same as before.")


def test_other_files_than_last_time_are_listed_as_a_first_try(home):
    other = [{"name": "sails.pdf", "ending": ".pdf", "choice": "Boat", "new": False, "why": ""}]
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(NOTHING_MISSING, "By name now.", looks_at=NAME_ONLY, **MOVER), rows=[ROWS, other])
    list(designer.start(REQUEST))
    events = list(designer.answer("go by the names"))
    assert one(events, Result).text == "Tried on the 1 newest file in Downloads. Nothing was moved.\nsails.pdf → Boat"


def test_a_try_out_is_only_held_against_one_of_the_same_kind(home):
    # The same files, but the helper now writes about them instead of moving them: what
    # came out before is no measure of this.
    wrote = [{**row, "choice": "", "note": "A line about it." if row["choice"] else ""} for row in ROWS]
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(NOTHING_MISSING, "It writes about them now.", when=NEW_FILE, then=NOTE,
                                    rule="Say in one line what this file is."), rows=[ROWS, wrote])
    list(designer.start(REQUEST))
    events = list(designer.answer("don't move them, just write me a line about each"))
    assert one(events, Result).text == (
        "Tried on the 3 newest files in Downloads. Nothing was written.\n"
        "boat_insurance.pdf: A line about it.\ntulips.docx: A line about it.\n"
        "setup.exe: nothing to write (nothing inside it could be read)")


def test_an_empty_folder_has_nothing_to_try_it_on(home):
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(say="Yes.", **MOVER), rows=[[]])
    events = list(designer.start(REQUEST))
    assert one(events, Result).text == ("There is nothing in Downloads to try it on yet. It starts with the next file "
                                        "that lands.")
    assert has(events, AgentCard) and rehearsal.calls == 1
    list(designer.answer("is that all?"))
    assert "- The folder had nothing in it to try it on." in script.notes[1] and rehearsal.calls == 1


def test_a_helper_that_writes_notes_is_tried_without_writing(home):
    noter = dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""), name="What came in",
                 rule="Say in two lines what this file is and who sent it. Write nothing about programs.")
    rows = [{"name": "letter.pdf", "ending": ".pdf", "what": "a letter", "choice": "", "new": False, "why": "",
             "note": "A letter from the harbour office.\nIt asks for the mooring fee."},
            {"name": "setup.exe", "ending": ".exe", "what": "", "choice": "", "new": False,
             "why": "nothing inside it could be read", "note": ""}]
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **noter), form(say="Yes.", **noter), rows=[rows],
                                    here=False)
    events = list(designer.start("tell me what lands in my downloads"))
    assert one(events, Result).text == (
        "Tried on the 2 newest files in Downloads. Nothing was written.\n"
        "letter.pdf: A letter from the harbour office. It asks for the mooring fee.\n"
        "setup.exe: nothing to write (nothing inside it could be read)")
    assert any(isinstance(e, Thinking) and e.text.endswith("Nothing is written.") for e in events)
    assert "Add what the rule asks for about each file to What came in.md, in Downloads" in one(events, AgentCard).can_do
    list(designer.answer("is that all?"))
    assert "- A note would be written: 1 file (1 .pdf)" in script.notes[1]
    assert "- Nothing would be written: 1 file (1 .exe)" in script.notes[1] and "harbour" not in script.notes[1]


def test_a_model_off_this_computer_never_reads_a_files_name_and_one_on_it_does(home):
    rows = [*ROWS, {"name": "mooring_2026.pdf", "ending": ".pdf", "what": "a bill for a mooring", "choice": "Harbour fees",
                    "new": True, "why": ""}]
    free = {**MOVER, "open": OPEN_YES}
    for here in (True, False):
        designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **free), form(say="Only new ones.", **free),
                                        rows=[rows], here=here)
        events = list(designer.start(REQUEST))
        list(designer.answer("will it move my old files?"))
        note = script.notes[1]
        opening = events[0].text
        if here:
            assert "- boat_insurance.pdf → Boat (read as an insurance letter for a boat)" in note
            assert "- mooring_2026.pdf → Harbour fees (a new folder; read as a bill for a mooring)" in note
            assert "- setup.exe: stays (nothing inside it could be read)" in note
            assert "never your files' names" not in opening  # nothing leaves the computer: nothing to say
        else:
            for row in rows:
                assert row["name"] not in note and (not row["what"] or row["what"] not in note)
            # Nor the name of a folder that was made up from what a file says.
            assert "Harbour fees" not in note and "could be read" not in note
            assert "- Into Boat: 1 file (1 .pdf)" in note and "- Into Garden: 1 file (1 .docx)" in note
            assert "- Left where it is: 1 file (1 .exe)" in note and "- Into a new folder: 1 file (1 .pdf)" in note
            assert "never a file's name or what it says" in note
            assert "never your files' names or what's in them" in opening
        # The user sees every file by name, whoever designs.
        assert "mooring_2026.pdf → Harbour fees (a new folder; read as a bill for a mooring)" in one(events, Result).text


def test_a_model_off_this_computer_is_told_of_the_other_helpers_but_not_their_rules(home):
    """A rule is the user's own words about their own things, and one worked out with a model
    on this computer was never said to a model elsewhere. What such a model is sent is said
    before it is sent: the line once named only what they type and their folders' names."""
    kept = "Put letters from the harbour office about my mooring in Kept."
    store.save(store.Agent("Letters", "custom", {"when": NEW_FILE, "then": MOVE, "folder": str(home / "Downloads"),
                                                 "choices": "Kept", "instruction": kept, "name": "Letters"}))
    fixer = dict(when=IN_CHAT, then=ANSWER, rule="Correct the grammar and spelling of the text. Keep its meaning.")
    for here in (True, False):
        designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **fixer), here=here)
        events = list(designer.start("fix my grammar when I ask"))
        note = script.notes[0]
        if here:
            assert f"- A helper they already have: Letters: {NEW_FILE} (Downloads) — {kept}" in note
            assert events[0].text == "Working a helper out is a conversation, so Test model talks it through with you."
        else:
            assert f"- A helper they already have: Letters: {NEW_FILE} (Downloads)\n" in note
            assert "harbour" not in note and "mooring" not in note
            assert "- Downloads has 2 files in it right now (" in note  # which the line says too
            assert events[0].text.endswith(
                "It sees what you type, the names of your folders and helpers, and how many files of each kind are "
                "in those folders, never your files' names or what's in them.")
    # Changing a helper, such a model reads how that helper is set up, its rule too, and the line says so.
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), rows=[ROWS], here=False)
    events = list(designer.edit(store.find_agent("Letters"), "go by the file names only"))
    assert f"- The rule: {kept}" in script.notes[0]
    assert "It sees what you type, how Letters is set up, the names of your folders and other helpers, and" in events[0].text


def test_the_try_out_frees_a_design_model_on_this_computer_first(home):
    log = []
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS], log=log)
    list(designer.start(REQUEST))
    assert log == ["release", "rehearse"]  # the built-in model and it don't both fit on the graphics card
    # One off this computer holds no room here.
    log = []
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS], here=False, log=log)
    list(designer.start(REQUEST))
    assert log == ["rehearse"] and script.released == 0


def test_a_try_out_that_cannot_run_does_not_hold_the_card_back(home):
    def broken(agent):
        raise OllamaError("Ollama stopped")

    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(say="Yes.", **MOVER))
    designer.rehearse = broken
    events = list(designer.start(REQUEST))
    assert has(events, AgentCard) and not has(events, Result)
    assert any(isinstance(e, Thinking) and "couldn't try it out" in e.text for e in events)
    list(designer.answer("is that all?"))
    assert "\nTHE TRY-OUT (" not in script.notes[1]


def test_a_helper_that_works_on_text_is_tried_on_a_sample(home):
    fixer = dict(when=IN_CHAT, then=ANSWER, name="Grammar fixer",
                 rule="Correct the grammar and spelling of the text. Keep its meaning.")
    log = []
    built_in = BuiltIn(log)
    designer, script, rehearsal = designing(form(NOTHING_MISSING, 'Write "Grammar fixer:" and your text.',
                                                 try_on="me and him goes", **fixer),
                                            form(say="Yes, it keeps your meaning.", try_on="their going home", **fixer),
                                            form(NOTHING_MISSING, "Tried on yours.", try_on="she dont know", **fixer),
                                            ollama=built_in, log=log)
    events = list(designer.start("fix my grammar when I ask, like me and him goes"))
    result = one(events, Result)
    assert (result.agent, result.text) == ("Try-out", 'On "me and him goes" it gives:\nME AND HIM GOES')
    assert built_in.asked[0][0]["content"].startswith(fixer["rule"]) and rehearsal.calls == 0
    assert log == ["release", "built-in"]  # the design model makes room for the built-in one here too
    card = one(events, AgentCard)
    assert card.kind == IN_CHAT and 'starting with its name ("Grammar fixer: ...")' in card.reads[0]
    # Another sample the model made up does not run it again.
    events = list(designer.answer("does it keep my meaning?"))
    assert not has(events, Result) and len(built_in.asked) == 1
    assert "THE TRY-OUT (code tried the helper, as the card has it, on one short text; nothing was changed)" in script.notes[1]
    assert '- On their own text, "me and him goes", it gave: ME AND HIM GOES' in script.notes[1]
    # A text of their own does, on the card as it is.
    events = list(designer.answer("try it on: she dont know"))
    assert one(events, Result).text == 'On "she dont know" it gives:\nSHE DONT KNOW'
    assert not has(events, AgentCard) and designer.sketch.waiting == CARD

    list(designer.choose(CARD, CREATE_IT))
    agent = store.list_agents()[0]
    assert agent.slots == {"when": IN_CHAT, "then": ANSWER, "instruction": fixer["rule"], "name": "Grammar fixer"}


def test_a_highlight_helper_gets_its_usual_values_and_the_usual_sample(home):
    built_in = BuiltIn()
    plain = dict(when=WHILE_ON, then=SHOW, name="Plain words",
                 rule="Say what the text means in plain words, in one or two sentences.")
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **plain),
                                    form(say="Yes, in any program.", try_on="A sample it thought of later.", **plain),
                                    ollama=built_in)
    events = list(designer.start("explain what I highlight in plain words"))
    slots = designer.sketch.slots
    assert (slots["show"], slots["keep"]) == (BUBBLE, UNTIL_UNHIGHLIGHT)
    # A text that isn't theirs is called a sample, on the screen and to the model, so
    # nobody takes a made-up sentence for something of the user's.
    assert one(events, Result).text.startswith(f'On a sample, "{parts.SAMPLE_TEXT}", it gives:\n')
    assert one(events, AgentCard).kind == WHILE_ON
    # Once it has been tried, a sample the model makes up later does not try it again.
    events = list(designer.answer("does it work in my browser?"))
    assert not has(events, Result) and len(built_in.asked) == 1
    assert f'- On a sample that was made up, not a text of theirs, "{parts.SAMPLE_TEXT}", it gave: ' in script.notes[1]
    assert "on their own things" not in script.notes[1]


def test_a_text_helper_whose_try_out_fails_still_gets_its_card(home):
    class Down(BuiltIn):
        def chat(self, model, messages, **more):
            raise OllamaError("Ollama stopped")
            yield ""

    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=ANSWER, rule="Say it shorter."),
                               ollama=Down())
    events = list(designer.start("make my texts shorter when I ask"))
    assert has(events, AgentCard) and not has(events, Result)


def test_a_helper_that_answers_from_documents_counts_what_it_can_read(home):
    manuals = home / "Documents" / "Manuals"
    manuals.mkdir()
    (manuals / "washer.txt").write_text("To start the washer, press the green button twice.", encoding="utf-8")
    (manuals / "oven.md").write_text("The oven needs ten minutes to warm up.", encoding="utf-8")
    (manuals / "photo.png").write_bytes(b"not text")
    reader = dict(when=IN_CHAT, then=DOCUMENTS, folder=("Documents", "Manuals"), name="Manuals helper",
                  rule="Answer from the manuals.")
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **reader))
    events = list(designer.start("I want to ask questions about my manuals"))
    where = Path("Documents") / "Manuals"
    assert one(events, Result).text == f"Found 2 files it can read in {where}."
    card = one(events, AgentCard)
    assert card.reads == [f"The PDF, Word and text files in {where} (2 right now)"] and card.kind == IN_CHAT
    assert rehearsal.calls == 0 and "instruction" not in designer.sketch.slots  # it follows no rule
    assert script.released == 0  # nothing here asks the built-in model: the design model stays
    # The model is told what was done: the files were counted, nothing was tried.
    script.forms.append(form(say="Yes, both of them.", **reader))
    list(designer.answer("is that all of them?"))
    assert "THE TRY-OUT (nothing was tried: code counted the files in the folder that it can read)" in script.notes[1]
    assert "- 2 files it can read were found in the folder." in script.notes[1]

    events = list(designer.choose(CARD, CREATE_IT))
    agent = store.list_agents()[0]
    assert (agent.name, agent.blueprint) == ("Manuals helper", "documents_qa")  # saved as it always was
    assert agent.slots == {"folder": str(manuals), "name": "Manuals helper"}
    assert sorted(agent.contents) == ["oven.md", "washer.txt"] and store.load_index(agent)
    assert one(events, Result).text.startswith("Test question: How do I start the washer?\n")
    assert 'Manuals helper is ready. To use it, start your message with its name' in said(events)
    assert one(events, AgentList).agents == ["Manuals helper"]
    assert designer.take_created() is None and script.released  # finished where it was made


def test_a_folder_with_nothing_to_read_cannot_be_answered_from(home):
    (home / "Pictures" / "boat.png").write_bytes(b"not text")
    empty = form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=DOCUMENTS, folder=("Pictures", ""))
    designer, script, _ = designing(empty, dict(empty))
    events = list(designer.start("I want to ask questions about my pictures"))
    assert "folder" not in designer.sketch.slots and not has(events, AgentCard) and not has(events, Result)
    assert "nothing there to answer from" in script.notes[1]
    assert "Pictures has no files I can read. I can read PDF, Word and text files." in said(events)
    assert "Which folder are the documents in?" in said(events)
    # Refused twice, it is passed over while they talk of something else.
    script.forms += [dict(empty), dict(empty)]
    events = list(designer.answer("what kinds of files can it read?"))
    assert "folder" not in designer.sketch.slots and "no files I can read" not in said(events)
    # Named again, by its place since it has no other name, it is looked at again, and the
    # file they have put there since is found: the count from before is not kept.
    (home / "Pictures" / "manual.txt").write_text("To start the washer, press the green button twice.", encoding="utf-8")
    script.forms.append(dict(empty))
    events = list(designer.answer("ok I put a text file in Pictures now, use Pictures"))
    assert designer.sketch.slots["folder"] == str(home / "Pictures") and has(events, AgentCard)
    assert one(events, Result).text == "Found 1 file it can read in Pictures."


# ---------------------------------------------------------- changing one they have


def card_they_have(home) -> store.Agent:
    agent = store.Agent("Paper sorter", "custom",
                        {"when": NEW_FILE, "then": MOVE, "folder": str(home / "Downloads"), "looks_at": INSIDE_FILE,
                         "choices": "Boat, Garden", "open": OPEN_NO, "into": "", "instruction": RULE,
                         "name": "Paper sorter", "examples": [{"name": "sails.pdf", "choice": "Boat"}]},
                        created="2026-11-01T10:00:00")
    store.save(agent)
    return agent


def test_changing_a_helper_shows_save_changes_and_saves_over_it(home):
    old = card_they_have(home)
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "It goes by names now.", when=NEW_FILE, then=MOVE,
                                                 looks_at=NAME_ONLY, name="Name sorter"), rows=[ROWS])
    events = list(designer.edit(old, "make Paper sorter go by the file names only"))
    card = one(events, AgentCard)
    assert card.actions == [SAVE_CHANGES, "Change something", "Cancel"]
    assert card.name == "Paper sorter"  # its name is theirs: the model's own idea for one is not taken
    assert "The name of each new file in Downloads, never what's inside it" in card.reads
    assert EDITING in script.notes[0] and CARD_SAVES in script.notes[0]
    assert "- Folder it watches: Downloads" in script.notes[0] and f"- The rule: {RULE}" in script.notes[0]
    assert "- They have no other helper yet." in script.notes[0]  # the one being changed is the card itself
    assert script.turns[0] == [{"role": "user", "content": "make Paper sorter go by the file names only"}]
    assert rehearsal.calls == 1  # the change is tried on their files before it is saved
    assert store.find_agent("Paper sorter").slots["looks_at"] == INSIDE_FILE  # nothing is saved until they say so

    events = list(designer.choose(CARD, SAVE_CHANGES))
    saved = store.find_agent("Paper sorter")
    assert saved.slots["looks_at"] == NAME_ONLY and saved.slots["instruction"] == RULE
    assert saved.slots["examples"] == [{"name": "sails.pdf", "choice": "Boat"}]  # what they taught it stays
    assert saved.created == "2026-11-01T10:00:00" and len(store.list_agents()) == 1
    assert "Saved the changes to Paper sorter." in said(events) and has(events, AgentList)
    assert designer.edited and designer.replaced is None and designer.take_created().name == "Paper sorter"


def test_a_helper_renamed_while_changing_it_replaces_the_old_one(home):
    old = card_they_have(home)
    designer, _, _ = designing(form(NOTHING_MISSING, "Renamed.", name="Boat keeper"), rows=[ROWS])
    events = list(designer.edit(old, "call it Boat keeper"))
    assert one(events, AgentCard).name == "Boat keeper"
    list(designer.answer("save it"))  # a plain yes to a card that saves
    assert [a.name for a in store.list_agents()] == ["Boat keeper"] and designer.replaced == "Paper sorter"
    assert store.list_agents()[0].slots["name"] == "Boat keeper"


def test_changing_can_be_called_off_and_the_helper_stays_as_it_was(home):
    old = card_they_have(home)
    designer, _, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), rows=[ROWS])
    list(designer.edit(old, "go by names"))
    events = list(designer.choose(CARD, "Cancel"))
    assert "Okay, I left Paper sorter as it was." in said(events) and not designer.active
    assert store.find_agent("Paper sorter").slots["looks_at"] == INSIDE_FILE

    designer, _, _ = designing(form(CANT_BE_MADE, "It can't send email."))
    events = list(designer.edit(old, "email me each file instead"))
    assert "It can't send email. I left Paper sorter as it was." in said(events)
    assert planner.list_ideas() == [] and len(store.list_agents()) == 1

    designer, _, _ = designing(DesignerError("signed out"))
    events = list(designer.edit(old, "go by names"))
    assert "Paper sorter is as it was." in said(events) and len(store.list_agents()) == 1


def test_a_change_only_the_routers_model_saw_may_be_handed_back_on_its_first_turn(home):
    """A message the router's model took for a change to a helper, because it shared a word
    with the helper's rule, could not be handed back: the first form of any conversation
    had no "something else" on it. Now one that code did not decide can be, and nothing is
    kept to carry on with, since nothing was worked out."""
    old = card_they_have(home)
    designer, script, _ = designing(form(MOVED_ON, "That is about something else."))
    events = list(designer.edit(old, "what should I plant in spring?", unsure=True))
    ends = script.schemas[0]["properties"]["status"]["enum"]
    assert MOVED_ON in ends and CALLED_OFF in ends
    assert designer.handoff == "what should I plant in spring?"
    assert not designer.active and designer.aside is None and script.released == 1
    assert not has(events, NoirText) and not has(events, Question)  # the engine answers it
    assert store.find_agent("Paper sorter").slots == old.slots

    designer, script, _ = designing(form(CALLED_OFF, ""))
    events = list(designer.edit(old, "never mind the boat", unsure=True))
    assert "Okay, I left Paper sorter as it was." in said(events) and not designer.active
    assert designer.handoff is None

    # One code took for a change (the helper was named) has neither, as before.
    designer, script, _ = designing(form(STILL_ASKING, "Which files?"))
    list(designer.edit(old, "change Paper sorter"))
    ends = script.schemas[0]["properties"]["status"]["enum"]
    assert MOVED_ON not in ends and CALLED_OFF not in ends


def test_changes_to_a_helper_deleted_meanwhile_are_not_saved_and_it_does_not_come_back(home):
    old = card_they_have(home)
    designer, _, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), rows=[ROWS])
    list(designer.edit(old, "go by names"))
    store.delete(old)
    events = list(designer.choose(CARD, SAVE_CHANGES))
    assert "Paper sorter was deleted, so there is nothing to save the changes to." in said(events)
    assert store.list_agents() == [] and designer.take_created() is None and not designer.active


def test_an_older_card_is_changed_with_the_then_its_when_always_meant(home):
    old = store.Agent("Explainer", "custom", {"instruction": "Explain it.", "name": "Explainer"})
    store.save(old)
    designer, script, _ = designing(form(NOTHING_MISSING, "Shorter now.", rule="Explain it in one short sentence."))
    list(designer.edit(old, "make Explainer shorter"))
    slots = designer.sketch.slots
    assert (slots["when"], slots["then"], slots["instruction"]) == (WHILE_ON, SHOW, "Explain it in one short sentence.")
    assert f"- When it works: {WHILE_ON}" in script.notes[0] and f"- What it does then: {SHOW}" in script.notes[0]


def test_a_card_changed_into_one_that_answers_from_documents_goes_only_once_the_new_one_is_made(home, monkeypatch):
    """The old helper was deleted first, and when the folder then couldn't be read they were
    told nothing was created and had neither."""
    manuals = home / "Documents" / "Manuals"
    manuals.mkdir()
    (manuals / "washer.txt").write_text("To start the washer, press the green button twice.", encoding="utf-8")
    fixer = {"when": IN_CHAT, "then": ANSWER, "instruction": "Correct the grammar of the text.", "name": "Grammar fixer"}
    reader = dict(when=IN_CHAT, then=DOCUMENTS, folder=("Documents", "Manuals"))

    def changing(filled, request="answer from my manuals instead"):
        store.save(store.Agent("Grammar fixer", "custom", dict(fixer)))
        designer, _, _ = designing(filled)
        events = list(designer.edit(store.find_agent("Grammar fixer"), request))
        return designer, events

    def unreadable(agent):
        raise PermissionError(13, "Permission denied")
        yield

    # The folder can't be read: nothing is made, and the helper they had is as it was.
    designer, events = changing(form(NOTHING_MISSING, "It answers from your manuals now.", **reader))
    assert one(events, AgentCard).actions[0] == SAVE_CHANGES and one(events, AgentCard).name == "Grammar fixer"
    with monkeypatch.context() as patched:
        patched.setattr(builder_mod.runner, "refresh_index", unreadable)
        events = list(designer.choose(CARD, SAVE_CHANGES))
    assert "I couldn't read that folder (Permission denied). Nothing was created." in said(events)
    assert "Grammar fixer is as it was." in said(events) and not has(events, AgentList)
    kept = store.list_agents()
    assert [(a.name, a.blueprint, a.slots) for a in kept] == [("Grammar fixer", "custom", fixer)]
    assert designer.replaced is None and designer.take_created() is None

    # Made under the same name, it is saved over the card, and nothing else goes.
    designer, events = changing(form(NOTHING_MISSING, "It answers from your manuals now.", **reader))
    events = list(designer.choose(CARD, SAVE_CHANGES))
    assert [(a.name, a.blueprint) for a in store.list_agents()] == [("Grammar fixer", "documents_qa")]
    assert [e.agents for e in events if isinstance(e, AgentList)] == [["Grammar fixer"]] and designer.replaced is None

    # Made under a new name, the card goes once the new one is there, and the list is sent after that.
    designer, events = changing(form(NOTHING_MISSING, "Renamed too.", name="Manuals helper", **reader),
                                "answer from my manuals instead, and call it Manuals helper")
    assert one(events, AgentCard).name == "Manuals helper"
    events = list(designer.choose(CARD, SAVE_CHANGES))
    assert [(a.name, a.blueprint) for a in store.list_agents()] == [("Manuals helper", "documents_qa")]
    assert [e.agents for e in events if isinstance(e, AgentList)] == [["Manuals helper"]]
    assert designer.replaced == "Grammar fixer" and designer.edited


def test_only_cards_are_changed_by_talking(home):
    documents = store.Agent("Manuals helper", "documents_qa", {"folder": str(home / "Documents"), "name": "Manuals helper"})
    designer, script, _ = designing(form(say="What should change?"))
    events = list(designer.edit(documents, "make it read another folder"))
    assert not designer.active and script.notes == [] and "Manuals helper" in said(events)


# ------------------------------------------------------------- who designs


def test_the_designer_is_handed_what_it_needs_and_knows_neither_the_engine_nor_the_watcher():
    """The design model, the dry run and the built-in model's name come in through its
    constructor: taking them from the engine or the folder watcher itself, each would wait
    for the other to be loaded, and a designer could not be tried without both."""
    tree = ast.parse(Path(designer_mod.__file__).read_text(encoding="utf-8"))
    names = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    for word in ("engine", "folderwatch", "organizer", "conductor", "talk"):
        assert word not in names and not any(module.split(".")[-1] == word for module in modules), word


def test_without_a_design_model_nothing_is_started(home):
    designer = Designer(BuiltIn(), "noir", None, Rehearsal(), lambda: None, lambda: "Small model")
    assert not designer.available()
    events = list(designer.start(REQUEST))
    assert not designer.active and NO_DESIGNER in said(events)
    events = list(designer.edit(card_they_have(home), "go by names"))
    assert not designer.active and NO_DESIGNER in said(events)
    assert designing(form())[0].available()


def test_a_model_that_still_has_to_load_is_said_first(home):
    script = Script(form(say="What bothers you about them?"))
    designer = Designer(BuiltIn(), "noir", None, Rehearsal(),
                        lambda: DesignModel(script.fill, "Test model", here=True, loaded=lambda: False), lambda: "")
    events = list(designer.start(REQUEST))
    assert [e.text for e in events if isinstance(e, Thinking)][1] == "Loading Test model first, which takes a few seconds."


def test_a_form_with_things_that_are_not_on_it_is_read_without_harm(home):
    odd = {"wants": 3, "when": ["x"], "then": None, "folder": "Downloads", "choices": ["Boat", "Garden"], "open": True,
           "instruction": {"text": "x"}, "name": 7, "try_on": None, "status": "done", "asks": "the folder", "say": None}
    designer, script, _ = designing(odd, dict(odd))
    events = list(designer.start(REQUEST))
    assert designer.active and designer.sketch.slots == {} and one(events, Question).text == WHEN.ask


# ----------------------------------------------------------------- the opening
# What follows guards what the conversations with real models changed (20 Nov 2026): each
# test is one thing a model did there, played back by a script of forms.


def test_a_first_message_that_only_names_a_trouble_gets_one_question_and_nothing_is_worked_out(home):
    """Told in the long note to ask about their situation, a model answered "my downloads
    are a mess" with a helper that moves files and a question about its rules, four times
    out of four. So the first message is read on its own, with a short note and two fields."""
    designer, script, _ = designing(form(say="I could put boat things in Boat. Does that suit you?",
                                         when=NEW_FILE, then=MOVE, folder=("Downloads", ""), choices="Boat", rule=RULE))
    script.opening = {"heard": NOT_TOLD,
                      "question": "What kind of files pile up in there, and what would you like to happen to them?"}
    events = list(designer.start(REQUEST))
    # One question, and of two joined by "and" the first: people answer the second half.
    assert [(e.id, e.text, e.choices) for e in events if isinstance(e, Question)] == [
        (DESIGN, "What kind of files pile up in there?", None)]
    assert script.notes == [] and designer.sketch.slots == {} and designer.sketch.waiting == DESIGN
    # The short note: how to talk, the one decision, what the computer holds. Not the parts.
    opening = script.openings[0]
    assert opening.startswith(VOICE) and designer_mod.OPENING in opening
    assert "ABOUT THIS COMPUTER" in opening and "Downloads has 2 files" in opening
    assert "WHAT A HELPER CAN BE MADE OF" not in opening and "FORM NOTE" not in opening
    # Their answer is the first whole turn, and the model reads its own question in the conversation.
    events = list(designer.answer("boat papers mostly"))
    assert len(script.notes) == 1 and len(script.openings) == 1
    assert script.turns[0] == [{"role": "user", "content": REQUEST},
                               {"role": "assistant", "content": "What kind of files pile up in there?"},
                               {"role": "user", "content": "boat papers mostly"}]
    # That answer is not the message that started it: it can be called off or be about something else.
    assert CALLED_OFF in script.schemas[0]["properties"]["status"]["enum"]


def test_a_first_message_that_says_what_they_want_goes_on_to_the_whole_form(home):
    designer, script, _ = designing(form(say="Which folder?"))
    events = list(designer.start(REQUEST))
    assert len(script.openings) == 1 and len(script.notes) == 1 and one(events, Question).text == "Which folder?"
    assert designer_mod.OPENING_SCHEMA["properties"]["heard"]["enum"] == [TOLD, NOT_TOLD]


@pytest.mark.parametrize("opening", [{"heard": NOT_TOLD, "question": ""}, {"heard": NOT_TOLD, "question": "Tell me more."},
                                     {"heard": TOLD, "question": "What is in there?"}, {}, DesignerError("stopped")])
def test_an_opening_that_asks_nothing_or_cannot_be_had_goes_on_to_the_whole_form(home, opening):
    designer, script, _ = designing(form(say="Which folder?"))

    def fill(note, turns, schema, real=script.fill):
        if "heard" in schema["properties"] and isinstance(opening, Exception):
            raise opening
        return real(note, turns, schema)

    script.opening = opening if isinstance(opening, dict) else {}
    designer.design_model = lambda: DesignModel(fill, "Test model", here=True)
    events = list(designer.start(REQUEST))
    assert len(script.notes) == 1 and one(events, Question).text == "Which folder?"


def test_a_change_to_a_helper_they_have_has_no_opening(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), rows=[ROWS])
    list(designer.edit(card_they_have(home), "go by names"))
    assert script.openings == [] and len(script.notes) == 1


def test_the_first_of_two_questions_is_the_one_asked():
    one_question = designer_mod._one_question
    assert one_question("What is in there, and how would you like it sorted?") == "What is in there?"
    assert one_question("What is in there? And what bothers you?") == "What is in there?"
    assert one_question("Is it the papers or the photos that pile up?") == "Is it the papers or the photos that pile up?"
    assert one_question("어떤 파일이 가장 많이 쌓여 있나요？") == "어떤 파일이 가장 많이 쌓여 있나요?"
    assert one_question("Tell me about your files.") == ""


# ----------------------------------------------------------------- a proposal waits for their answer


def test_a_helper_described_to_them_waits_for_their_answer_and_then_the_card_comes(home):
    """A card once came under "Which folder should it watch?", for a folder the model had
    guessed. So while the model says it is still asking, its question stands and no card
    comes; once, since after their answer the try-out and the card are what they see next."""
    proposal = form(say="It would put boat things in Boat and garden things in Garden. Is that right?", **MOVER)
    again = form(say="So boat things go in Boat and garden things in Garden. Does that sound right?", **MOVER)
    designer, _, rehearsal = designing(proposal, again, rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert one(events, Question).text.endswith("Is that right?") and not has(events, AgentCard) and rehearsal.calls == 0
    assert designer.sketch.proposed and designer.sketch.waiting == DESIGN
    # The button of a card that is not up asks the open question again.
    assert one(list(designer.choose(CARD, CREATE_IT)), Question).text.endswith("Is that right?")
    assert store.list_agents() == []
    events = list(designer.answer("yes, but leave the letters"))
    # The card comes whatever the model asks now, and a question that only asks the same again comes off.
    assert has(events, AgentCard) and said(events) == "So boat things go in Boat and garden things in Garden."
    assert designer.sketch.waiting == CARD


def test_a_first_message_that_said_all_of_it_gets_its_card_at_once(home):
    """Such a message was said back to them with "Is that how you want it to work?", four
    times out of four: the try-out and the card answer that better. Only when the folder it
    works in and the folders it moves things into were all named in the message."""
    echo = form(say="It watches Downloads and sorts into Boat and Garden. Is that how you want it to work?", **MOVER)
    designer, _, _ = designing(echo, rows=[ROWS])
    events = list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    assert has(events, AgentCard) and said(events) == "It watches Downloads and sorts into Boat and Garden."
    # A folder they did not name is a guess, and a guess is asked about.
    designer, _, _ = designing(echo, rows=[ROWS])
    events = list(designer.start("sort my papers into Boat and Garden"))
    assert not has(events, AgentCard) and one(events, Question).text.endswith("Is that how you want it to work?")
    designer, _, _ = designing(echo, rows=[ROWS])
    events = list(designer.start("watch my downloads and sort the papers"))
    assert not has(events, AgentCard)
    # A real question holds the card back even then.
    asks = form(say="It sorts into Boat and Garden. Do the letters from the harbour go with the boat?", **MOVER)
    designer, _, _ = designing(asks, rows=[ROWS])
    events = list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    assert not has(events, AgentCard) and designer.sketch.waiting == DESIGN


def test_a_helper_for_text_always_waits_for_their_answer_first(home):
    """Asked for something that turns rough notes into a letter, a model chose for them
    that it would be asked in the chat, and with nothing in the message to check, the card
    came at once. How they want to use it is theirs to say."""
    fixer = dict(when=IN_CHAT, then=ANSWER, name="Grammar fixer", rule="Correct the grammar of the text.")
    designer, _, _ = designing(form(say='You would write "Grammar fixer:" and your text. Is that right?', **fixer),
                               form(say='You write "Grammar fixer:" and your text. Is that how you want it?', **fixer))
    events = list(designer.start("fix the grammar of what I write"))
    assert not has(events, AgentCard) and one(events, Question).id == DESIGN
    events = list(designer.answer("ok sure"))
    assert has(events, AgentCard) and has(events, Result)


def test_after_a_plain_yes_a_question_that_only_asks_the_same_again_does_not_hold_the_card(home):
    """Asked "Should I set it up so you type its name and then your notes?", they said "ok
    sure" and were asked "Is that how you would like to use it?": the third such question
    in a row."""
    first = form(say="Shall it go by what is inside each file?", when=NEW_FILE, then=MOVE, folder=("Downloads", ""),
                 choices="Boat, Garden")
    whole = form(say="It sorts into Boat and Garden by what is inside. Is that how you would like it?", **MOVER)
    for answer, comes in (("ok sure", True), ("네 좋아요", True), ("yes and the letters too", False)):
        designer, _, _ = designing(first, whole, rows=[ROWS])
        list(designer.start(REQUEST))
        events = list(designer.answer(answer))
        assert has(events, AgentCard) == comes, answer


def test_a_plain_yes_changes_no_choice_that_was_already_made(home):
    """Asked "Is it okay if I create these two folders inside your Downloads folder?", they
    said yes, and the form that followed let the helper make new folders of its own, which
    nobody had spoken of: the try-out came out differently under a card they had only
    agreed to."""
    proposed = form(say="Is it okay if I keep those two folders inside Downloads?", open=OPEN_NO, looks_at=INSIDE_FILE,
                    **MOVER)
    flipped = form(NOTHING_MISSING, "Here it is.", open=OPEN_YES, looks_at=NAME_ONLY, **MOVER)
    designer, _, _ = designing(proposed, flipped, rows=[ROWS])
    list(designer.start(REQUEST))
    assert designer.sketch.slots["open"] == OPEN_NO
    events = list(designer.answer("yes"))
    assert has(events, AgentCard) and (designer.sketch.slots["open"], designer.sketch.slots["looks_at"]) == (OPEN_NO, INSIDE_FILE)
    # Said in words, it is a change like any other.
    designer, _, _ = designing(proposed, flipped, rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("yes, and it may make new folders when something fits neither"))
    assert designer.sketch.slots["open"] == OPEN_YES
    # A yes to the question that asked for that very choice, with its buttons, is an answer to it.
    asks = form(say="May it make new folders when the rule calls for one?", asks="open", open=OPEN_NO, looks_at=INSIDE_FILE,
                when=NEW_FILE, then=MOVE, folder=("Downloads", ""))
    designer, _, _ = designing(asks, flipped, rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert one(events, Question).id == "open" and designer.sketch.slots["open"] == OPEN_NO
    list(designer.answer("yes"))
    assert designer.sketch.slots["open"] == OPEN_YES and designer.sketch.slots["looks_at"] == INSIDE_FILE
    # A choice made and put right in one and the same turn is not held to its first value.
    first = form(say="Is that right?", when=WHILE_ON, then=SHOW, rule="Say what the text means.", name="Meaning")
    wrong = form(NOTHING_MISSING, "Here it is.", when=WHILE_ON, then=SHOW, rule="Say what the text means.", name="Meaning",
                 show=BOTH)
    designer, script, _ = designing(first, wrong)
    list(designer.start("tell me what a text i highlight means"))
    list(designer.answer("yes"))
    assert designer.sketch.slots["show"] == BOTH  # not known when they said yes: taken


def test_at_the_card_a_choice_nobody_spoke_of_stays_as_it_was(home):
    """The model fills every setting in again each turn. Told "also leave the pictures
    alone" at the card, it also let the helper make new folders, and said only that the
    pictures would stay: the card gained "or into a new folder when the rule calls for one",
    and the helper was made that way."""
    shut = {**MOVER, "open": OPEN_NO}
    pictures = {**MOVER, "open": OPEN_YES, "rule": RULE + " Pictures stay where they are."}
    designer, _, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **shut),
        form(NOTHING_MISSING, "I have updated the rule so your pictures stay exactly where they are.",
             changes="Pictures are never moved.", **pictures),
        rows=[ROWS, ROWS])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    events = list(designer.answer("also leave the pictures alone"))
    assert designer.sketch.slots["open"] == OPEN_NO
    assert designer.sketch.slots["instruction"] == pictures["rule"]  # what was asked for is taken
    assert not any("new folder" in line for line in one(events, AgentCard).can_do)
    list(designer.choose(CARD, CREATE_IT))
    assert store.find_agent("Paper sorter").slots["open"] == OPEN_NO
    store.delete(store.find_agent("Paper sorter"))  # or the next ones would first be asked about it
    # Spoken of, by them or in the words they read, it is a change like any other: also in
    # another language, where the form's change and the model's words say it.
    for typed, changes, say in (("it may make new folders for anything else", "", "Okay."),
                                ("다른 건 새 폴더를 만들어도 돼요", "It may make new folders.", "새 폴더도 만들 수 있어요."),
                                ("other things can go somewhere new", "", "It may now make a folder of its own.")):
        designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **shut),
                                   form(NOTHING_MISSING, say, changes=changes, **{**shut, "open": OPEN_YES}),
                                   rows=[ROWS, ROWS])
        assert has(list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden")),
                   AgentCard)
        list(designer.answer(typed))
        assert designer.sketch.slots["open"] == OPEN_YES, typed


def test_a_change_to_a_helper_they_have_changes_no_choice_it_does_not_speak_of(home):
    """Asked for a shorter explanation, a model also had the result copied to the clipboard
    instead of shown, and gone after a few seconds: saved that way, without a word of it."""
    rule = "Explain the highlighted word in simple everyday words, in two sentences."
    shorter = "Explain the highlighted word in simple everyday words, in one short sentence."
    agent = store.Agent("Word explainer", parts.CUSTOM, {"when": WHILE_ON, "then": SHOW, "instruction": rule,
                                                         "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT, "skip_language": "",
                                                         "name": "Word explainer"})
    store.save(agent)
    flips = dict(when=WHILE_ON, then=SHOW, rule=shorter, show=CLIPBOARD, keep=FEW_SECONDS, name="Word explainer")
    designer, _, _ = designing(form(NOTHING_MISSING, "It now explains in one short sentence.",
                                    changes="Make the explanation shorter.", **flips))
    events = list(designer.edit(agent, "make the explanation shorter"))
    assert (designer.sketch.slots["show"], designer.sketch.slots["keep"]) == (BUBBLE, UNTIL_UNHIGHLIGHT)
    assert f"Rule: {shorter}" in one(events, AgentCard).can_do
    list(designer.choose(CARD, SAVE_CHANGES))
    saved = store.find_agent("Word explainer").slots
    assert (saved["instruction"], saved["show"], saved["keep"]) == (shorter, BUBBLE, UNTIL_UNHIGHLIGHT)
    # What they ask for is changed, and only that.
    designer, _, _ = designing(form(NOTHING_MISSING, "It copies the explanation now.", **flips))
    list(designer.edit(agent, "copy it to the clipboard instead of the bubble"))
    assert (designer.sketch.slots["show"], designer.sketch.slots["keep"]) == (CLIPBOARD, UNTIL_UNHIGHLIGHT)
    designer, _, _ = designing(form(NOTHING_MISSING, "It goes away by itself after a few seconds now.", **flips))
    list(designer.edit(agent, "make the bubble go away by itself"))
    # (A word of another of its choices, "bubble", is no word about how the result is shown.)
    assert (designer.sketch.slots["show"], designer.sketch.slots["keep"]) == (BUBBLE, FEW_SECONDS)


def test_a_plain_yes_to_a_question_that_offers_more_than_one_choice_asks_which_one(home):
    """Asked "a bubble above the text, copied to your clipboard, or both?", they typed "yes".
    The model picked "Both" for them, and once made the helper copied every highlight over
    what was on their clipboard."""
    asks = form(say="Would you like it in a bubble above the text, copied to your clipboard, or both?", asks="show",
                when=WHILE_ON, then=SHOW)
    picked = form(NOTHING_MISSING, "Here it is.", when=WHILE_ON, then=SHOW, rule="Say what the text means in English.",
                  name="Meaning", show=BOTH)
    designer, script, _ = designing(asks, {**picked, "show": BUBBLE})
    list(designer.start("when i highlight a sentence i want to see what it means in english"))
    events = list(designer.answer("yes"))
    question = one(events, Question)
    assert (question.id, question.text) == ("show", "Which one would you like?")
    assert question.choices == [BUBBLE, CLIPBOARD, BOTH]
    assert len(script.notes) == 1 and "show" not in designer.sketch.slots  # nothing asked of the model, nothing filled in
    assert designer.sketch.turns[-1]["content"] == asks["say"]  # the yes answered nothing, and is not kept
    # A click answers it, as any click does.
    events = list(designer.choose("show", BUBBLE))
    assert designer.sketch.slots["show"] == BUBBLE and len(script.notes) == 2 and has(events, AgentCard)
    # It is asked once. A play that typed "yes", "yes thats right" and "ok" was asked "Which
    # one?" three times and never got its helper: the second yes goes on to the model.
    designer, script, _ = designing(asks, {**picked, "show": BUBBLE})
    list(designer.start("when i highlight a sentence i want to see what it means in english"))
    assert one(list(designer.answer("yes")), Question).text == "Which one would you like?"
    events = list(designer.answer("yes thats right"))
    assert len(script.notes) == 2 and has(events, AgentCard) and designer.sketch.slots["show"] == BUBBLE
    assert {"role": "user", "content": "yes thats right"} in designer.sketch.turns
    # A yes to a question about one of them is an answer, and goes to the model.
    one_of = form(say="Is it okay if it shows in a bubble above the text?", asks="show", when=WHILE_ON, then=SHOW)
    designer, script, _ = designing(one_of, {**picked, "show": BUBBLE})
    list(designer.start("when i highlight a sentence i want to see what it means in english"))
    list(designer.answer("yes"))
    assert len(script.notes) == 2 and designer.sketch.slots["show"] == BUBBLE
    # Asked in Korean, the same.
    korean = form(say="버블로 보여 드릴까요, 아니면 클립보드에 복사할까요?", asks="show", when=WHILE_ON, then=SHOW)
    designer, script, _ = designing(korean, picked)
    list(designer.start("내가 하이라이트한 문장의 뜻을 영어로 보여 줘"))
    assert one(list(designer.answer("네")), Question).text == "Which one would you like?" and len(script.notes) == 1


def test_only_a_question_that_asks_whether_it_is_right_comes_off():
    without = designer_mod._without_confirming
    assert without("It sorts by what is inside. Does that sound like the right plan?") == "It sorts by what is inside."
    assert without("It sorts them. Is this correct?") == "It sorts them."
    assert without("It sorts them. Is that how you would like to use it?") == "It sorts them."
    assert without("I have updated the name. Does this setup look correct to you?") == "I have updated the name."
    assert without("It sorts them. Does that plan sound right?") == "It sorts them."
    # ("Does that cover everything you need?" stood in the middle of an answer at the card,
    # with what the try-out had done said after it.)
    assert without("Only bills go to Bills now. Does that cover everything you need?") == "Only bills go to Bills now."
    kept = "It sorts them. Is it okay if we start with just the new ones?"
    assert without(kept) == kept  # one with an "if" in it asks about something
    assert without("Is that right?") == "Is that right?"  # all there is: it stays


def test_a_value_for_what_its_question_asks_for_is_a_guess_and_is_not_taken(home):
    """A model asked "Which folder should it watch?" with a folder of its own choosing
    filled in; with nothing left missing, the card came for that folder."""
    guess = form(say="Which folder should it watch for new files?", asks="folder", **MOVER)
    designer, _, _ = designing(guess, rows=[ROWS])
    events = list(designer.start(REQUEST))
    assert "folder" not in designer.sketch.slots and not has(events, AgentCard)
    assert one(events, Question).text == "Which folder should it watch for new files?"
    # One that is known already stays; the question may be about changing it.
    designer, _, _ = designing(form(say="Which folders?", when=NEW_FILE, then=MOVE, folder=("Downloads", "")),
                               form(say="Is Downloads the right folder to watch?", asks="folder", when=NEW_FILE, then=MOVE))
    list(designer.start(REQUEST))
    list(designer.answer("boat things"))
    assert designer.sketch.slots["folder"] == str(home / "Downloads")


# ----------------------------------------------------------------- what the model is told once


def test_a_question_that_hands_them_the_rule_goes_back_once(home):
    """With the folders named and what to leave alone said, a model asked whether the
    helper should go by "the content of the document ... or should it look for specific
    keywords?": the designing, handed to the person who came because they did not know."""
    known = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""), choices="Boat, Garden")
    hands = form(say="Should it go by the words in a file or by its name?", asks="instruction", **known)
    designer, script, _ = designing(hands, form(say="Boat things in Boat, garden things in Garden. Is that right?", **MOVER))
    events = list(designer.start(REQUEST))
    assert "Everything but the rule is known, and your question asks them how the helper should decide" in script.notes[1]
    # (The line that sent a model's one honest sentence away with its question: it now says to keep it.)
    assert "If your words said that something they want cannot be done, keep saying that." in script.notes[1]
    assert one(events, Question).text.endswith("Is that right?") and designer.sketch.slots["instruction"] == RULE


def test_a_question_that_asks_them_for_the_folders_goes_back_once(home):
    """Told what was in the folder, a model answered "What specific folder names would you
    like it to use for these categories?", and in Korean the same."""
    known = dict(when=NEW_FILE, then=MOVE, folder=("Downloads", ""))
    asks = form(say="Which folder names would you like it to use?", asks="choices", **known)
    designer, script, _ = designing(asks, form(say="I would use Boat and Garden. Does that suit you?", **MOVER),
                                    form(say="Which other folders would you like?", asks="choices", **known))
    events = list(designer.start(REQUEST))
    assert len(script.notes) == 2 and "Your question asks them which folders they want. That is yours to propose" in script.notes[1]
    assert one(events, Question).text == "I would use Boat and Garden. Does that suit you?"
    assert designer.sketch.told_folders
    # Told once: after that its question stands.
    designer, script, _ = designing(asks, dict(asks), dict(asks))
    events = list(designer.start(REQUEST))
    assert len(script.notes) == 2 and one(events, Question).text == "Which folder names would you like it to use?"
    list(designer.answer("no idea"))
    assert len(script.notes) == 3


def test_a_helper_asked_in_the_chat_is_proposed_with_how_it_is_asked(home):
    """"How do I give it my notes?" was answered "whenever you paste your messy notes into
    the chat, it will automatically rewrite them": a message without its name is not for it."""
    fixer = dict(when=IN_CHAT, then=ANSWER, name="Grammar fixer", rule="Correct the grammar of the text.")
    vague = form(say="Whenever you paste text into the chat it fixes it. Is that right?", **fixer)
    named = form(say='You write "Grammar fixer:" and then your text. Is that right?', **fixer)
    designer, script, _ = designing(vague, named, dict(vague), dict(vague))
    events = list(designer.start("fix the grammar of what I write"))
    assert len(script.notes) == 2 and 'by writing its name, a colon and then the text ("Grammar fixer: ...")' in script.notes[1]
    assert one(events, Question).text.startswith('You write "Grammar fixer:"')
    list(designer.answer("hmm, and commas?"))  # told once: not again, whatever the words now say
    assert len(script.notes) == 3
    # Words that name it are not sent back at all, and neither is a helper that is not asked in the chat.
    designer, script, _ = designing(named)
    list(designer.start("fix the grammar of what I write"))
    assert len(script.notes) == 1
    designer, script, _ = designing(form(say="It explains what you highlight. Is that right?", when=WHILE_ON, then=SHOW,
                                         name="Plain words", rule="Say what the text means in plain words."))
    list(designer.start("explain what I highlight"))
    assert len(script.notes) == 1


def test_the_note_says_what_no_helper_can_do_and_who_answers_other_things(monkeypatch):
    """With only the parts listed, a wish for something that reads the person's mail was
    answered "I can help with that" and worked into a helper for "the emails provided"."""
    monkeypatch.setattr(sys, "platform", "win32")
    note = note_for(["nothing yet"], [])
    limits = designer_mod.NO_HELPER_CAN
    assert note.index("WHAT A HELPER CAN BE MADE OF") < note.index(limits) < note.index("HOW THESE WORK (you may tell")
    assert "no helper can read their mail, their messages, their calendar or a website" in limits
    assert "never work around it in silence" in limits and f'the status is "{CANT_BE_MADE}"' in limits
    # A message about something else is the app's to answer: asked about tomorrow's rain, a
    # model that had just read those limits said it was not allowed to look at the internet.
    assert f'"{MOVED_ON}" when their message is about something else than this helper' in note
    assert "what a helper cannot do says nothing about it. The app answers it" in note
    assert "If they ask you something about the helper, answer it from HOW THESE WORK" in HOW_TO_DESIGN


# ----------------------------------------------------------------- the writer


def test_a_rule_from_the_form_is_written_out_once_before_it_goes_on_a_card(home):
    """In the whole form a model put "Do not include ... the date" into a rule for someone
    who wanted the dates. From a short note of its own, with only the conversation and the
    draft, it left that out."""
    designer, script, _ = designing(form(say="Boat things in Boat. Is that right?", **MOVER),
                                    form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(say="Only new files.", **MOVER), rows=[ROWS])
    script.rewrites = ["Boat papers go in Boat and garden plans in Garden. The rest stays."]
    list(designer.start(REQUEST))
    written = "Boat papers go in Boat and garden plans in Garden. The rest stays."
    assert designer.sketch.slots["instruction"] == written and len(script.rules) == 1
    note, content = script.rules[0]
    assert note == designer_mod.WRITE.format(limit=parts.MAX_RULE)
    assert content == ("WHAT THE HELPER DOES\n" + parts.WHENS[NEW_FILE].about + " " + parts.THENS[MOVE].about
                       + "\n\nITS FOLDERS\nBoat, Garden"
                       + f"\n\nWHAT WAS SAID\nThem: {REQUEST}"
                       + f"\n\nTHE DRAFT\n{RULE}")
    # The model fills the rule in again every turn, as it first wrote it or as it reads it
    # now: neither is a new draft, and neither puts its own wording back.
    events = list(designer.answer("yes"))
    assert len(script.rules) == 1 and designer.sketch.slots["instruction"] == written
    assert f"Rule: {written}" in one(events, AgentCard).can_do
    # Also once the card is up: its first wording, filled in again, does not come back onto the card.
    script.forms.append(form(say="And only while it is on.", **{**MOVER, "rule": written}))
    for asked in ("will it move my old files?", "and when it is off?"):
        events = list(designer.answer(asked))
        assert len(script.rules) == 1 and designer.sketch.slots["instruction"] == written
        assert not has(events, AgentCard) and not has(events, Result)


def test_once_the_card_is_up_a_change_to_the_rule_is_not_written_out_again(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                    form(NOTHING_MISSING, "Letters stay now.", changes="Leave letters.",
                                         **{**MOVER, "rule": RULE + " Letters stay where they are."}), rows=[ROWS])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    assert len(script.rules) == 1
    list(designer.answer("leave my letters alone"))
    assert len(script.rules) == 1 and designer.sketch.slots["instruction"] == RULE + " Letters stay where they are."


def test_the_writer_is_not_asked_for_a_helper_they_have_nor_through_a_plan_and_may_fail(home):
    # A model off this computer: each such note would be one more whole answer from their plan.
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS], here=False)
    list(designer.start(REQUEST))
    assert script.rules == [] and designer.sketch.slots["instruction"] == RULE
    # A writer that can't take its turn, or gives nothing back, leaves the draft standing.
    for answer in (DesignerError("stopped"), "", "   "):
        designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
        script.rewrites = [answer]
        events = list(designer.start(REQUEST))
        assert designer.sketch.slots["instruction"] == RULE and has(events, AgentCard)
    # A helper they already have: its rule was agreed in a conversation this one knows nothing of.
    designer, script, _ = designing(form(NOTHING_MISSING, "Letters stay now.",
                                         **{**MOVER, "rule": RULE + " Letters stay where they are."}), rows=[ROWS])
    list(designer.edit(card_they_have(home), "leave my letters alone"))
    assert script.rules == [] and designer.sketch.slots["instruction"].endswith("Letters stay where they are.")


def test_what_the_writer_gives_is_held_to_what_a_rule_may_be(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    script.rewrites = ['"' + "Boat papers go in Boat. " * 40 + '"']
    list(designer.start(REQUEST))
    rule = designer.sketch.slots["instruction"]
    assert len(rule) <= parts.MAX_RULE and rule.endswith("Boat papers go in Boat.") and not rule.startswith('"')


# ----------------------------------------------------------------- a change that was said and not made


def test_a_change_said_and_not_made_goes_back_once_and_then_code_says_so(home):
    """Told that two files had gone to the wrong folder, a model answered "I have updated
    the rules to ensure..." over a rule that was word for word what it had been."""
    same = form(NOTHING_MISSING, "I have updated the rule so letters stay.", changes="Letters should stay.", **MOVER)
    for last, line in ((dict(same), designer_mod.ALREADY_SO),
                       (form(say="I have fixed the rule.", changes="Letters should stay.", **MOVER),
                        designer_mod.NOT_CHANGED)):
        designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), same, last, rows=[ROWS])
        list(designer.start(REQUEST))
        events = list(designer.answer("make it leave my letters alone"))
        assert len(script.notes) == 3
        assert 'You wrote that their message asks for this change: "Letters should stay."' in script.notes[2]
        assert "nothing would change" in script.notes[2]
        assert said(events) == line and not has(events, AgentCard) and rehearsal.calls == 1
    assert "it already does that" in designer_mod.ALREADY_SO and "it is still as it was" in designer_mod.NOT_CHANGED


def test_a_word_for_empty_in_the_changes_is_no_change(home):
    for empty in ("None", "n/a", "No changes.", "nothing", " - "):
        designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                                        form(say="Only files that land from now on.", changes=empty, **MOVER), rows=[ROWS])
        list(designer.start(REQUEST))
        events = list(designer.answer("will it move my old files?"))
        assert len(script.notes) == 2 and said(events) == "Only files that land from now on."


def test_a_change_made_a_turn_ago_written_down_again_is_not_a_change_asked_for_now(home):
    """Asked at the card "will it touch what is already in there?", a model wrote its last
    two corrections down again as what was asked for now, and answered the question well in
    its words. Code's "Nothing changed on the card" was all the person heard."""
    changed = {**MOVER, "rule": RULE + " Letters stay where they are."}
    designer, script, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Letters stay now.", changes="Letters should stay where they are.", **changed),
        form(NOTHING_MISSING, "Only files that land after it is switched on.",
             changes="I made sure letters stay where they are.", **changed),
        form(NOTHING_MISSING, "I have updated the rule so the letters stay.",
             changes="The letters should stay where they are.", **changed),
        rows=[ROWS, ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("leave my letters alone"))
    assert designer.sketch.changes_made == ["Letters should stay where they are."]
    events = list(designer.answer("will it touch what is already in there?"))
    assert len(script.notes) == 3  # no second form for it
    assert said(events) == "Only files that land after it is switched on." and designer.sketch.waiting == CARD
    # Words that say a change was made, over a card that did not change, are still not said.
    events = list(designer.answer("and the old ones?"))
    assert said(events) == designer_mod.ALREADY_SO


def test_an_earlier_change_said_again_in_other_words_about_a_question_is_no_change_asked_for(home):
    """The wording of a real play: three of the seven telling words were the earlier
    change's, the rest padding, and none was a word of the question it was written under."""
    changed = {**MOVER, "rule": RULE + " Electricity bills go in Boat too."}
    again = "The rule was updated to ensure electricity bills are specifically included in the Boat folder."
    designer, script, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Electricity bills go there too now.", changes="Move electricity bills into the Boat folder.", **changed),
        form(NOTHING_MISSING, "It only works on files that land after it is switched on.", changes=again, **changed),
        # The same words under a message that is about that very thing are a change asked for:
        # it goes back once, and when nothing changes, code says so.
        form(NOTHING_MISSING, "Electricity bills go there.", changes=again, **changed),
        form(NOTHING_MISSING, "Electricity bills go there.", changes=again, **changed),
        rows=[ROWS, ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("the electricity one goes in boat too"))
    events = list(designer.answer("will it touch the stuff thats already in there?"))
    assert len(script.notes) == 3  # no second form for it
    assert said(events) == "It only works on files that land after it is switched on." and designer.sketch.waiting == CARD
    events = list(designer.answer("are electricity bills really included?"))
    assert len(script.notes) == 5 and said(events) == designer_mod.ALREADY_SO


def test_a_question_at_the_card_does_not_change_the_rule_it_was_tried_with(home):
    """Asked "will it touch the stuff thats already in there?", a model answered that well
    and, in the same form, wrote the rule out in other words, with the change of the turn
    before written down again as the one asked for: the helper was tried again under its
    answer, and three files came out otherwise on a card nobody had asked to change."""
    changed = {**MOVER, "rule": RULE + " Electricity bills go in Boat too."}
    reworded = {**MOVER, "rule": "Boat things and electricity bills go in Boat, garden things in Garden. Leave the rest."}
    again = "I updated the rule to include electricity bills in the Boat folder."
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Electricity bills go there too now.", changes="Move electricity bills into the Boat folder.", **changed),
        form(NOTHING_MISSING, "It only works on files that land after it is switched on.", changes=again, **reworded),
        form(NOTHING_MISSING, "Phone bills go there as well now.", changes="Move phone bills into the Boat folder too.",
             **{**MOVER, "rule": changed["rule"] + " Phone bills too."}),
        rows=[ROWS, ROWS, ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("the electricity one goes in boat too"))
    stood, tried = dict(designer.sketch.slots), rehearsal.calls
    events = list(designer.answer("will it touch the stuff thats already in there?"))
    assert designer.sketch.slots == stood and rehearsal.calls == tried  # the card as it was, and not tried again
    assert said(events) == "It only works on files that land after it is switched on." and not has(events, AgentCard)
    assert designer.sketch.waiting == CARD
    # A question that asks for a change is a change: its words are in what the model wrote down.
    events = list(designer.answer("can the phone bills go in boat too?"))
    assert designer.sketch.slots["instruction"].endswith("Phone bills too.") and has(events, AgentCard)


def test_a_plain_yes_to_a_question_at_the_card_that_changes_nothing_is_pointed_at_the_button(home):
    """"Should I proceed?" was asked at the card; "ok make it" then went to the model, which
    said "I have everything I need to set this up for you" and nothing more."""
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(say="Only new ones. Which of the old ones matter to you?", **MOVER),
                               form(NOTHING_MISSING, "I have everything I need.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("will it move my old files?"))
    events = list(designer.answer("ok make it"))
    assert said(events) == "I have everything I need. The button on the card creates it."
    assert store.list_agents() == [] and designer.sketch.waiting == CARD
    list(designer.answer("yes"))
    assert len(store.list_agents()) == 1


def test_a_nudge_to_begin_comes_off_so_a_yes_is_a_yes_to_the_card():
    assert tidy_say("It only works on new files. Should I proceed with setting this up?") == "It only works on new files."
    assert tidy_say("Here it is. Shall I create it now?") == "Here it is."
    assert tidy_say("Here it is. Should we go ahead?") == "Here it is."
    kept = "Here it is. Should the letters stay too?"
    assert tidy_say(kept) == kept


@pytest.mark.parametrize("yes", ["ok good", "great thanks", "that looks right", "yes thats good", "Perfect!", "ok make it",
                                 "sounds good, go ahead", "좋아요", "네 좋아요", "만들어 주세요"])
def test_a_whole_message_that_only_agrees_is_a_yes_to_the_card(home, yes):
    """"ok good" under a card went to the model, which took it for a change to make,
    changed nothing, and the person was told "I couldn't work that into the card"."""
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer(yes))
    assert len(store.list_agents()) == 1 and len(script.notes) == 1


@pytest.mark.parametrize("more", ["ok but leave the letters", "good, and the photos?", "is that right?", "thanks",
                                  "make it stricter", "it is not good"])
def test_a_message_that_says_more_than_yes_goes_to_the_model(home, more):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(say="Tell me more.", **MOVER),
                                    rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer(more))
    assert store.list_agents() == [] and len(script.notes) == 2


# ----------------------------------------------------------------- the mender


def test_a_correction_the_form_left_out_of_the_rule_is_made_by_the_mender(home):
    """In the whole form a model that read its own rule as saying the right thing wrote it
    out unchanged, twice, with the try-out that said otherwise in the same note. Given only
    the rule, what the try-out did with the files they spoke of and what they said, it
    writes a new rule every time."""
    stays = {**ROWS[1], "choice": "", "why": "the rule leaves it: a planting plan"}
    mended = RULE + " A planting plan is not a garden paper: it stays where it is."
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Planting plans stay now.", changes="The tulips file should stay.", **MOVER),
        rows=[ROWS, [ROWS[0], stays, ROWS[2]]])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    script.rewrites = [mended]
    events = list(designer.answer("the tulips one should stay where it is"))
    assert len(script.notes) == 2  # no second whole form: the short note did it
    note, content = script.rules[-1]
    assert note == designer_mod.MEND.format(limit=parts.MAX_RULE)
    assert content == (f"THE RULE AS IT STANDS\n{RULE}\n\nITS FOLDERS\nBoat, Garden\n\n"
                       "WHAT IT DID WITH THE FILES THEY SPEAK OF (in brackets: what the small model took the file for)\n"
                       "- tulips.docx → Garden (read as a planting plan)\n\n"
                       "WHAT IT DID WITH THE OTHER FILES, WHICH THEY DID NOT SPEAK OF\n"
                       "- boat_insurance.pdf → Boat (read as an insurance letter for a boat)\n"
                       "- setup.exe: stays (nothing inside it could be read)\n\n"
                       "WHAT THEY SAID\nthe tulips one should stay where it is")
    assert designer.sketch.slots["instruction"] == mended and rehearsal.calls == 2
    assert "tulips.docx: stays now (was Garden; the rule leaves it: a planting plan)" in one(events, Result).text
    assert f"Rule: {mended}" in one(events, AgentCard).can_do and said(events) == "Planting plans stay now."


def test_a_rule_that_was_changed_and_still_does_the_same_is_mended_once_and_code_says_how_it_stands(home):
    """A model wrote the correction down, left the rule saying nothing new about the files,
    and said "I have updated the plan"; the try-out under those words put both where they
    had been. So code looks at what came of the change."""
    changed = {**MOVER, "rule": RULE + " Be careful with plans."}
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "I have changed the rule for planting plans.", changes="The tulips file should stay.",
             **changed),
        rows=[ROWS, ROWS, ROWS])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    script.rewrites = [RULE + " A planting plan stays where it is."]
    events = list(designer.answer("the tulips one should stay where it is"))
    steps = [e.text for e in events if isinstance(e, Thinking)]
    assert "tulips.docx still comes out as before, so I'm putting the rule another way." in steps
    assert rehearsal.calls == 3 and script.rules[-1][0] == designer_mod.MEND.format(limit=parts.MAX_RULE)
    assert designer.sketch.slots["instruction"] == RULE + " A planting plan stays where it is."
    # Still the same after that: said by code, since the model's words say what it changed, not what came of it.
    assert said(events) == ("I have changed the rule for planting plans. In the try-out below, tulips.docx still comes "
                            "out as before.")
    # A change was asked for, so every file is shown, the one they meant among them.
    assert one(events, Result).text == (
        "Tried again on the same 3 files in Downloads. Nothing was moved. Every file came out as before.\n"
        "boat_insurance.pdf → Boat (read as an insurance letter for a boat)\n"
        "tulips.docx → Garden (read as a planting plan)\nsetup.exe: stays (nothing inside it could be read)")


def test_another_file_that_now_comes_out_differently_is_pointed_at(home):
    """Asked to leave one file where it was, a model added a line to the rule, and with it
    the built-in model put another file into a different folder than before."""
    after = [{**ROWS[0], "choice": "Garden"}, {**ROWS[1], "choice": "", "why": "the rule leaves it: a planting plan"},
             ROWS[2]]
    designer, _, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Planting plans stay now.", changes="The tulips file should stay.",
             **{**MOVER, "rule": RULE + " Planting plans stay."}),
        rows=[ROWS, after])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    events = list(designer.answer("the tulips one should stay where it is"))
    assert said(events) == ("Planting plans stay now. In the try-out below, boat_insurance.pdf also comes out "
                            "differently than before.")
    assert "boat_insurance.pdf → Garden now (was Boat; read as an insurance letter for a boat)" in one(events, Result).text


def test_only_the_files_a_message_names_most_closely_are_the_ones_it_speaks_of(home):
    """"Put the ... one back" about one of two files named alike was taken to speak of
    both, and the other, which had come out right, was reported as still coming out wrong."""
    rows = [{"name": "invoice_harbour_cafe.pdf", "ending": ".pdf", "what": "an invoice", "choice": "Boat", "why": ""},
            {"name": "invoice_garden_centre.pdf", "ending": ".pdf", "what": "an invoice", "choice": "Garden", "why": ""},
            {"name": "notes.txt", "ending": ".txt", "what": "notes", "choice": "", "why": "the rule leaves it: notes"}]
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[rows])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    spoken = lambda text: [row["name"] for row in (designer.sketch.turns.append({"role": "user", "content": text})
                                                   or designer._spoken_of())]  # noqa: E731
    assert spoken("the harbour invoice is wrong") == ["invoice_harbour_cafe.pdf"]
    assert spoken("the invoices are wrong") == ["invoice_harbour_cafe.pdf", "invoice_garden_centre.pdf"]
    assert spoken("will it move my old files?") == []
    assert spoken("that 2026 one is wrong") == []  # numbers and short words name nothing


def test_through_a_plan_the_mender_reads_how_many_came_out_which_way_never_a_name(home):
    designer, script, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "Planting plans stay now.", changes="The tulips file should stay.", **MOVER),
        rows=[ROWS, ROWS], here=False)
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    script.rewrites = [RULE + " A planting plan stays where it is."]
    list(designer.answer("the tulips one should stay where it is"))
    content = script.rules[-1][1]
    assert "- 1 of them: into garden" in content and "- 1 of them: into boat" in content
    assert "tulips.docx" not in content and "planting plan" not in content and "insurance" not in content
    assert "WHAT THEY SAID\nthe tulips one should stay where it is" in content  # their own words, which they typed to it


def test_through_a_plan_codes_sentences_about_the_try_out_go_into_the_conversation_without_names(home):
    """After a change at the card, code says under the model's words which file still comes
    out as before, or which other file now comes out otherwise. Those words went into the
    conversation as they were said, and with the next message to a plan's model, the names
    of files the user had never typed: the opening had promised "never your files' names"."""
    after = [{**ROWS[0], "choice": "Garden"}, {**ROWS[1], "choice": "", "why": "the rule leaves it: a planting plan"},
             ROWS[2]]
    changed = {**MOVER, "rule": RULE + " Planting plans stay."}
    for here in (False, True):
        designer, script, _ = designing(
            form(NOTHING_MISSING, "Here it is.", **MOVER),
            form(NOTHING_MISSING, "Planting plans stay now.", changes="The tulips file should stay.", **changed),
            form(NOTHING_MISSING, "Only new ones.", **changed),
            rows=[ROWS, after, after], here=here)
        list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
        events = list(designer.answer("the tulips one should stay where it is"))
        # They read the file by name, whoever designs.
        assert said(events) == ("Planting plans stay now. In the try-out below, boat_insurance.pdf also comes out "
                                "differently than before.")
        list(designer.answer("and what about the old ones?"))
        sent = [turn["content"] for turn in script.turns[-1]]
        if here:
            assert said(events) in sent  # nothing leaves the computer: kept as it was said
        else:
            assert ("Planting plans stay now. In the try-out below, 1 other file also comes out differently than "
                    "before.") in sent
            for row in ROWS:
                assert all(row["name"] not in turn for turn in sent), row["name"]
    # The same for the files they spoke of that still come out as before.
    still = {**MOVER, "rule": RULE + " Be careful with plans."}
    designer, script, _ = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "I have changed the rule for planting plans.", changes="The tulips file should stay.",
             **still),
        form(NOTHING_MISSING, "Okay.", **still),
        rows=[ROWS, ROWS, ROWS], here=False)
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    events = list(designer.answer("the tulips one should stay where it is"))
    assert said(events).endswith("In the try-out below, tulips.docx still comes out as before.")
    list(designer.answer("ok and the rest?"))
    sent = [turn["content"] for turn in script.turns[-1]]
    assert ("I have changed the rule for planting plans. In the try-out below, 1 file you spoke of still comes out as "
            "before.") in sent
    assert all(row["name"] not in turn for row in ROWS for turn in sent)


def test_a_change_about_a_kind_of_file_that_changed_nothing_is_said_and_every_file_is_shown(home):
    """Told "also leave the pictures alone", a model said it had changed the rule to make
    sure of that. No file was named, so the files they meant were not looked for, and the
    try-out said only "It came out the same as before.", while the one picture in the folder
    went on going into a folder."""
    rows = [*ROWS, {"name": "harbour_view.png", "ending": ".png", "what": "a photo of a boat", "choice": "Boat",
                    "new": False, "why": "", "note": ""}]
    claims = {**MOVER, "rule": RULE + " Pictures stay where they are."}
    designer, script, rehearsal = designing(
        form(NOTHING_MISSING, "Here it is.", **MOVER),
        form(NOTHING_MISSING, "I have updated the rule so your pictures stay where they are.",
             changes="Pictures are never moved.", **claims),
        rows=[rows, rows])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    events = list(designer.answer("also leave the pictures alone"))
    # No file was spoken of by name, so the mender is not asked (only the writer was, for the first card).
    mend = designer_mod.MEND.format(limit=parts.MAX_RULE)
    assert rehearsal.calls == 2 and all(note != mend for note, _ in script.rules)
    assert said(events) == ("I have updated the rule so your pictures stay where they are. In the try-out below, every "
                            "file still comes out as it did before.")
    assert one(events, Result).text == (
        "Tried again on the same 4 files in Downloads. Nothing was moved. Every file came out as before.\n"
        "boat_insurance.pdf → Boat (read as an insurance letter for a boat)\n"
        "tulips.docx → Garden (read as a planting plan)\nsetup.exe: stays (nothing inside it could be read)\n"
        "harbour_view.png → Boat (read as a photo of a boat)")
    assert has(events, AgentCard) and designer.sketch.waiting == CARD
    # A rule the model wrote again with no change asked for, that changed nothing, is still one line.
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(NOTHING_MISSING, "Here it is again.", **claims), rows=[rows, rows])
    list(designer.start("watch my downloads and put boat papers in Boat and garden plans in Garden"))
    events = list(designer.answer("looks fine, does it work with pdfs?"))
    assert one(events, Result).text == ("Tried again on the same 4 files in Downloads. Nothing was moved.\n"
                                        "It came out the same as before.")
    assert said(events) == "Here it is again."


# ----------------------------------------------------------------- their own text, and a rule that says how it is shown


def test_asked_only_to_try_it_on_a_text_of_theirs_the_card_stays_as_it_was(home):
    """Asked "what would it say for ...?", a model wrote that very word into the rule, with
    what the answer for it should be, and described the answer itself."""
    fixer = dict(when=IN_CHAT, then=ANSWER, name="Grammar fixer", rule="Correct the grammar of the text.")
    worse = {**fixer, "rule": fixer["rule"] + ' For "she dont know" the answer is "she does not know".'}
    designer, _, _ = designing(form(say='Write "Grammar fixer:" and your text. Is that right?', **fixer),
                               form(NOTHING_MISSING, 'Write "Grammar fixer:" and your text.', **fixer),
                               form(say='It would say "she does not know".', try_on="she dont know", **worse),
                               form(NOTHING_MISSING, "Shorter answers now.", changes="Keep answers short.",
                                    try_on="she dont know", **{**fixer, "rule": fixer["rule"] + " Keep it short."}))
    list(designer.start("fix the grammar of what I write"))
    list(designer.answer("yes"))
    events = list(designer.answer("what would it give for: she dont know"))
    assert designer.sketch.slots["instruction"] == fixer["rule"]  # by its own word no change was asked for
    assert said(events) == "Here is what it gives on your own text." and not has(events, AgentCard)
    assert one(events, Result).text == 'On "she dont know" it gives:\nSHE DONT KNOW'
    # A change they did ask for is made, on the same text of theirs.
    events = list(designer.answer("keep it short"))
    assert designer.sketch.slots["instruction"].endswith("Keep it short.") and has(events, AgentCard)


def test_a_rule_that_says_how_the_result_is_shown_goes_back_and_then_loses_that_sentence(home):
    """The built-in model reads the rule as its whole job, and one that ended "The result
    should be shown in a bubble above the text" came back with its answer between two
    round emoji."""
    shows = dict(when=WHILE_ON, then=SHOW, name="Plain words",
                 rule="Say what the text means in plain words. Show the result in a bubble above the text.")
    designer, script, _ = designing(form(say="It explains what you highlight. Is that right?", **shows),
                                    form(say="It explains what you highlight. Is that right?", **shows))
    list(designer.start("explain what I highlight"))
    assert 'The rule says how the result is shown ("bubble"). Take that out' in script.notes[1]
    assert designer.sketch.slots["instruction"] == "Say what the text means in plain words."
    # A helper that is asked in the chat may speak of anything in its rule.
    designer, script, _ = designing(form(say='Write "Bubble tea:" and ask. Is that right?', when=IN_CHAT, then=ANSWER,
                                         name="Bubble tea", rule="Say how to make bubble tea with what they have."))
    list(designer.start("tell me how to make bubble tea"))
    assert len(script.notes) == 1 and "bubble tea" in designer.sketch.slots["instruction"]


# ----------------------------------------------------------------- a folder that is nearly there, and a change to one they have


def test_a_folder_one_letter_off_is_asked_about_by_name_never_taken(home):
    """"Could you tell me the exact name of the folder?" was all someone heard who had typed
    one letter wrong."""
    (home / "Documents" / "Appliance manuals").mkdir()
    (home / "Documents" / "Photos 2026").mkdir()
    reader = dict(when=IN_CHAT, then=DOCUMENTS)
    wrong = form(say="I will answer from them.", folder=("Documents", "applience manuals"), **reader)
    designer, script, _ = designing(wrong, dict(wrong))
    events = list(designer.start("can I ask you about my manuals"))
    shown = str(Path("Documents") / "Appliance manuals")
    assert f'One has nearly that name: "Appliance manuals" ({shown}). Ask whether they mean that one' in script.notes[1]
    assert "folder" not in designer.sketch.slots
    assert one(events, Question).text == f'I can\'t find a folder called "applience manuals". Did you mean {shown}?'
    # A folder for another year is not a slip for this one, and two that are near are not guessed between.
    assert designer_mod._near_folders("Photos 2025") == []
    (home / "Desktop" / "Appliance manual").mkdir()
    near = designer_mod._near_folders("applience manuals")
    assert [path.name for path in near] == ["Appliance manuals", "Appliance manual"]
    designer, script, _ = designing(wrong, dict(wrong))
    events = list(designer.start("can I ask you about my manuals"))
    assert said(events) == 'I can\'t find a folder called "applience manuals". Which folder are the documents in?'


def test_a_folder_of_nearly_that_name_is_not_taken_in_the_turn_that_asks_about_it(home):
    """Told to ask whether they meant the folder that is there, a model filled that folder
    in and marked its question as being about the helper's name: the folder was taken
    unasked, and the question, about a setting with a usual value, was cut off its words."""
    (home / "Documents" / "Appliance manuals").mkdir()
    reader = dict(when=IN_CHAT, then=DOCUMENTS)
    (home / "Documents" / "Appliance manuals" / "oven.txt").write_text("Press bake.", encoding="utf-8")
    wrong = form(say="I will answer from them.", folder=("", "applience manuals"), **reader)
    asks = form(say="I noticed a folder called Appliance manuals in your Documents. Is that the one you mean?",
                asks="name", folder=("Documents", "Appliance manuals"), **reader)
    taken = form(NOTHING_MISSING, "It answers from your manuals.", folder=("Documents", "Appliance manuals"), **reader)
    designer, script, _ = designing(wrong, asks, taken)
    events = list(designer.start("can I ask you about my manuals"))
    assert "folder" not in designer.sketch.slots and not has(events, AgentCard)
    assert said(events) == "I noticed a folder called Appliance manuals in your Documents. Is that the one you mean?"
    # Once they have said so, it is taken like any folder.
    events = list(designer.answer("yes that one"))
    assert designer.sketch.slots["folder"] == str(home / "Documents" / "Appliance manuals") and has(events, AgentCard)
    # A second form that neither asks nor puts it right: code asks, by the folder's name.
    designer, script, _ = designing(wrong, form(say="I will use your manuals folder.", **reader))
    events = list(designer.start("can I ask you about my manuals"))
    shown = str(Path("Documents") / "Appliance manuals")
    assert said(events) == f'I can\'t find a folder called "applience manuals". Did you mean {shown}?'
    # A second form that asks about something else, with not a word of the folder: "theyre
    # in my applience manuals folder" was answered "I will call this helper House Manuals.
    # Is that a good name for it?". Code asks about the folder, and the folder still waits.
    other = form(say="I will call this helper House Manuals. Is that a good name for it?", asks="name",
                 folder=("Documents", "Appliance manuals"), name="House Manuals", **reader)
    designer, script, _ = designing(wrong, other)
    events = list(designer.start("can I ask you about my manuals"))
    assert said(events) == f'I can\'t find a folder called "applience manuals". Did you mean {shown}?'
    assert "folder" not in designer.sketch.slots and one(events, Question).id == DESIGN and not has(events, AgentCard)


def test_a_folder_written_as_the_folders_it_is_reached_through_is_that_folder(home):
    """Asked "Did you mean Documents\\Household\\Appliance manuals?", they said yes, and the
    model filled the folder in as it had read it, the place and "Household/Appliance
    manuals". No folder has that for a name, so the yes was answered "I can't find a folder
    called "Household/Appliance manuals"", three turns running."""
    manuals = home / "Documents" / "Household" / "Appliance manuals"
    manuals.mkdir(parents=True)
    (manuals / "oven.txt").write_text("Press bake.", encoding="utf-8")
    reader = dict(when=IN_CHAT, then=DOCUMENTS)
    for given in (("Documents", "Household/Appliance manuals"), ("Documents", "household\\appliance manuals"),
                  ("", "Documents\\Household\\Appliance manuals"), ("Desktop", "Household/Appliance manuals"),
                  ("", "Documents/Household/Appliance manuals/")):
        designer, script, _ = designing(form(NOTHING_MISSING, "It answers from your manuals.", folder=given, **reader))
        events = list(designer.start("can I ask you about my manuals in Appliance manuals"))
        assert designer.sketch.slots.get("folder") == str(manuals), given
        assert has(events, AgentCard), given
    # A way that leads nowhere is looked for by the folder's own name, like any other.
    designer, script, _ = designing(form(NOTHING_MISSING, "It answers from your manuals.",
                                         folder=("Documents", "Papers/Appliance manuals"), **reader))
    list(designer.start("can I ask you about my manuals in Appliance manuals"))
    assert designer.sketch.slots.get("folder") == str(manuals)
    # And one that is nowhere at all is still refused, by its own name and not by the way to it.
    designer, script, _ = designing(*[form(say="I will answer from them.", folder=("Documents", "Household/Boat papers"), **reader)] * 2)
    events = list(designer.start("can I ask you about my boat papers"))
    assert said(events) == 'I can\'t find a folder called "Boat papers". Which folder are the documents in?'


def test_a_folder_they_name_is_known_by_its_name_and_never_asked_for_by_where_it_is(home):
    """ "Whenever I save something into my ... folder" was answered "Where is that folder
    located on your computer?", at every turn, with the folder's name in the request."""
    for name in ("House papers", "Appliance manuals", ".hidden"):
        (home / "Documents" / name).mkdir()
    for number in range(designer_mod.MAX_FOLDERS_TOLD + 3):
        (home / "Pictures" / f"Trip {number:02d}").mkdir()
    designer, script, _ = designing(form(say="What should it write?", when=NEW_FILE, then=NOTE, folder=("", "House papers")))
    list(designer.start("write a line about each new file in my House papers folder"))
    assert designer.sketch.slots["folder"] == str(home / "Documents" / "House papers")  # found by its name alone
    note = script.notes[0]
    assert "- Folders in Documents: Appliance manuals, House papers." in note  # by name, hidden ones left out
    assert "- Folders in Pictures: Trip 00, Trip 01," in note and "Trip 11 and 3 more." in note and "Trip 12" not in note
    assert "Folders in Downloads" not in note  # none there: nothing is said
    assert str(home) not in note
    assert "never ask them where it is: give its name" in parts.WHENS[NEW_FILE].settings[0].how
    assert "never ask them where it is: give its name" in parts.THENS[DOCUMENTS].settings[0].how


def test_a_helper_they_have_keeps_its_name_and_they_are_told_once_how_to_give_it_another(home):
    """Changed to give its result in another language, a helper kept the name the model had
    once given it, which said the old language, with not a word on how to rename it."""
    old = card_they_have(home)
    renamed = dict(MOVER, name="Garden and boat sorter", rule=RULE + " Letters stay where they are.")
    designer, script, _ = designing(form(NOTHING_MISSING, "Letters stay now.", changes="Letters stay.", **renamed),
                                    form(NOTHING_MISSING, "Bills stay too now.", changes="Bills stay.",
                                         **{**renamed, "name": "Another name", "rule": RULE + " Letters and bills stay."}),
                                    rows=[ROWS, ROWS])
    events = list(designer.edit(old, "leave my letters alone"))
    assert designer.sketch.slots["name"] == old.name and one(events, AgentCard).name == old.name
    assert said(events).endswith('To give it another name, say "call it ...".')
    events = list(designer.answer("and my bills"))  # said once, however often the model offers a name
    assert "call it" not in said(events) and designer.sketch.slots["name"] == old.name
    # The name it has, filled in again, is no other name: nothing is said.
    designer, script, _ = designing(form(NOTHING_MISSING, "Letters stay now.", changes="Letters stay.",
                                         **dict(MOVER, name=old.name.upper(), rule=RULE + " Letters stay where they are.")),
                                    rows=[ROWS])
    assert "call it" not in said(list(designer.edit(old, "leave my letters alone")))
    assert 'Never "the user" in it' in parts.RULE.how and 'Never "the user" in it' in designer_mod.WRITE


def test_a_change_to_a_helper_they_have_shows_its_card_and_says_nothing_is_saved_yet(home):
    """Asked to have a helper take one more kind of thing, a model answered "I have updated
    the helper to include ... Is this how you want it to work?", with nothing saved and no
    card shown."""
    designer, script, _ = designing(form(say="I will have it leave letters. Is this how you want it to work?",
                                         changes="Leave letters.",
                                         **{**MOVER, "name": "", "rule": RULE + " Letters stay where they are."}),
                                    rows=[ROWS])
    events = list(designer.edit(card_they_have(home), "leave my letters alone"))
    assert has(events, AgentCard) and one(events, AgentCard).actions[0] == SAVE_CHANGES
    assert said(events) == ("I will have it leave letters. Paper sorter stays as it is until you press Save changes on "
                            "the card.")
    assert "Their helper stays exactly as it was until they press the button on the card that saves the changes" in EDITING
    assert store.find_agent("Paper sorter").slots["instruction"] == RULE
    # Words that already point at the card are left as they are.
    designer, _, _ = designing(form(NOTHING_MISSING, "Letters stay. The card below has the button to save it.",
                                    **{**MOVER, "name": "", "rule": RULE + " Letters stay where they are."}), rows=[ROWS])
    events = list(designer.edit(store.find_agent("Paper sorter"), "leave my letters alone"))
    assert said(events) == "Letters stay. The card below has the button to save it."


def test_a_change_that_cannot_change_what_a_try_out_shows_does_not_run_it_again(home):
    """Asked only to give the notes file another name, a helper was tried on the same five
    files again, to write the same about each."""
    noter = dict(when=NEW_FILE, then=NOTE, folder=("Downloads", ""), name="What came in",
                 rule="Say in two lines what this file is.")
    rows = [{"name": "letter.pdf", "ending": ".pdf", "what": "a letter", "choice": "", "new": False, "why": "",
             "note": "A letter from the harbour office."}]
    designer, _, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **noter),
                                       form(NOTHING_MISSING, "It writes in Log now.", changes="Name the notes file Log.",
                                            notes=("Documents", "Log"), **noter),
                                       form(NOTHING_MISSING, "One line now.", changes="One line.",
                                            notes=("Documents", "Log"), **{**noter, "rule": "Say in one line what it is."}),
                                       rows=[rows, rows])
    list(designer.start("watch my downloads and write two lines about each new file"))
    events = list(designer.answer("call the notes file Log, in documents"))
    assert rehearsal.calls == 1 and not has(events, Result)
    assert "Add what the rule asks for about each file to Log.md, in Documents" in one(events, AgentCard).can_do
    list(designer.answer("one line is enough"))
    assert rehearsal.calls == 2  # the rule is what a try-out shows
    assert designer_mod.SAME_OUTCOME == ("name", "into", "notes", "show", "keep")


# ----------------------------------------------------------------- the language a card leaves out
# One setting any helper for highlighted text can have. Nothing knows a kind of helper by
# it: the model fills it in like any other setting, and code keeps it, shows it and tries
# the helper out by it.

PLAIN = dict(when=WHILE_ON, then=SHOW, name="Plain words", rule="Say what the text means in plain words.")


def leaving(language="", status=NOTHING_MISSING, say="Here it is.", **more) -> dict:
    """The form of a whole helper for highlighted text, with the language it leaves out as a model fills it in."""
    return {**form(status, say, **{**PLAIN, **more}), "skip_language": language}


def steps(events) -> str:
    return " ".join(e.text for e in events if isinstance(e, Thinking))


def test_the_form_can_say_which_language_a_helper_leaves_out_and_take_it_off_again(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    setting = parts.WHENS[WHILE_ON].settings[0]
    fields = schema_for()["properties"]
    # Its languages, a word for none, and "" for "not mine to fill". Left empty a setting
    # stays as it is, so without the word one that was set could never be taken off again.
    assert fields["skip_language"] == {"enum": [*setting.choices, parts.NONE, ""]}
    # Only a choice whose usual value is none of its choices has the word.
    for key in ("looks_at", "show", "keep", "open"):
        assert parts.NONE not in fields[key]["enum"], key
    note = note_for(["nothing yet"], [], first=True)
    assert f"  - Leaves out text already in (`skip_language`, has a usual value): {setting.how}" in note
    assert "`skip_language`" in note.split("FORM NOTE")[1]


def test_a_helper_for_highlights_is_made_with_the_language_it_leaves_out(home):
    designer, script, _ = designing(leaving("Korean"), leaving("", STILL_ASKING, "Yes, in any program."))
    events = list(designer.start("show me in plain Korean words what I highlight"))
    assert designer.sketch.slots["skip_language"] == "Korean"
    assert "leaves out text already in: Korean" in steps(events)
    assert one(events, AgentCard).can_do[-1] == "Leaves out text that is already in Korean"
    # Left empty in a later form, it stays: an empty value never erases a known one.
    events = list(designer.answer("does it work in my browser?"))
    assert designer.sketch.slots["skip_language"] == "Korean" and not has(events, AgentCard)
    assert "- Leaves out text already in: Korean" in script.notes[1]
    list(designer.choose(CARD, CREATE_IT))
    assert store.find_agent("Plain words").slots["skip_language"] == "Korean"


def test_with_no_language_said_a_helper_leaves_nothing_out_and_saying_so_again_changes_nothing(home):
    built_in = BuiltIn()
    designer, script, _ = designing(leaving(parts.NONE), leaving(parts.NONE, STILL_ASKING, "Yes, in any program."),
                                    leaving("Spanish", STILL_ASKING, "It works on all of it."), ollama=built_in)
    events = list(designer.start("say what I highlight in plain words"))
    assert designer.sketch.slots["skip_language"] == ""  # its usual value, written on the card
    assert not any("Leaves out" in line for line in one(events, AgentCard).can_do)
    # "None" from the model only takes a known language off: on a card that had none it is
    # nothing learned, so nothing about it is said to the user.
    assert "leaves out" not in steps(events)
    # The model reads it as the form says it, and fills it in again that way each turn:
    # nothing is taken for a change, no card comes again and nothing is tried again.
    events = list(designer.answer("does it work in my browser?"))
    assert "- Leaves out text already in: None" in script.notes[1]
    assert not has(events, AgentCard) and not has(events, Result) and len(built_in.asked) == 1
    assert designer.sketch.slots["skip_language"] == "" and designer.sketch.waiting == CARD
    # A language that is not on the form's list is not taken, whoever says it.
    list(designer.answer("and Spanish text?"))
    assert designer.sketch.slots["skip_language"] == ""


def test_the_language_a_helper_they_have_leaves_out_is_changed_and_taken_off_by_talking(home):
    old = store.Agent("Plain words", "custom", {"when": WHILE_ON, "then": SHOW, "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT,
                                                "instruction": PLAIN["rule"], "skip_language": "Korean",
                                                "name": "Plain words"})
    store.save(old)
    designer, script, _ = designing(leaving("Japanese", say="It leaves Japanese text alone now.",
                                            changes="Leave out Japanese text, not Korean."),
                                    leaving(parts.NONE, say="It works on every text now.", changes="Leave nothing out."))
    events = list(designer.edit(old, "it should leave Japanese alone, not Korean"))
    assert "- Leaves out text already in: Korean" in script.notes[0]  # the card as it is saved, for the model to read
    assert designer.sketch.slots["skip_language"] == "Japanese"
    assert one(events, AgentCard).can_do[-1] == "Leaves out text that is already in Japanese"
    events = list(designer.answer("actually it should work on everything"))
    assert designer.sketch.slots["skip_language"] == ""
    assert "leaves out text already in: None" in steps(events)
    card = one(events, AgentCard)
    assert not any("Leaves out" in line for line in card.can_do) and card.actions[0] == SAVE_CHANGES
    assert store.find_agent("Plain words").slots["skip_language"] == "Korean"  # nothing is saved before the button
    list(designer.choose(CARD, SAVE_CHANGES))
    assert store.find_agent("Plain words").slots["skip_language"] == ""


def test_a_helper_changed_to_be_asked_in_the_chat_leaves_nothing_out_any_more(home):
    designer, _, _ = designing(leaving("Korean"),
                               form(NOTHING_MISSING, "You ask it in the chat now.", changes="Ask it in the chat.",
                                    **{**PLAIN, "when": IN_CHAT, "then": ANSWER}))
    list(designer.start("show me in plain Korean words what I highlight"))
    events = list(designer.answer("I'd rather ask it in the chat"))
    assert "skip_language" not in designer.sketch.slots  # a setting of the WHEN it had
    assert one(events, AgentCard).kind == IN_CHAT


def test_the_try_out_passes_over_a_text_the_helper_itself_would_pass_over(home):
    """The helper does nothing with a highlight that is already in the language its card
    leaves out. Shown a result for such a text in the try-out, they would wait for one
    that never comes."""
    built_in = BuiltIn()
    designer, script, _ = designing(leaving("Korean", try_on="안녕하세요 반가워요"),
                                    leaving("Korean", STILL_ASKING, "Yes.", try_on="안녕하세요 반가워요"),
                                    leaving("Korean", say="Tried on yours.", try_on="good morning to you"),
                                    ollama=built_in)
    events = list(designer.start("show me in plain Korean words what I highlight, like 안녕하세요 반가워요"))
    assert one(events, Result).text == ('On "안녕하세요 반가워요" it does nothing: the text is already in Korean, and it '
                                        "leaves such text out.")
    assert built_in.asked == []  # as when it runs: the built-in model is never asked about such a text
    assert has(events, AgentCard)
    list(designer.answer("is that right?"))
    assert ('- On their own text, "안녕하세요 반가워요", it did nothing: the text is already in Korean, and the card '
            "leaves such text out") in script.notes[1]
    # A text it does work on is tried as ever.
    events = list(designer.answer("try it on: good morning to you"))
    assert one(events, Result).text == 'On "good morning to you" it gives:\nGOOD MORNING TO YOU'


def test_a_helper_that_would_pass_over_the_sample_made_up_for_it_is_told_once_then_leaves_nothing_out(home):
    """A helper that was to show what Japanese sentences mean in English came with Japanese
    as the language it leaves out: the language of the text it reads. Its try-out said "it
    does nothing: the text is already in Japanese", and its card that it leaves Japanese out."""
    sample = "こんにちは、元気ですか？"
    wrong = leaving("Japanese", try_on=sample)
    # Put right in the second form: the language the result comes out in.
    built_in = BuiltIn()
    designer, script, _ = designing(wrong, leaving("English", try_on=sample), ollama=built_in)
    events = list(designer.start("show me what the Japanese I highlight means in English"))
    assert len(script.notes) == 2
    assert ("`skip_language` is Japanese, and the text you gave to try the helper on is already in Japanese" in script.notes[1]
            and "never the language of the text it is given" in script.notes[1])
    assert designer.sketch.slots["skip_language"] == "English"
    assert one(events, Result).text == f'On a sample, "{sample}", it gives:\n{sample}' and len(built_in.asked) == 1
    # Said the same again: it is taken off, and the helper works on every text.
    designer, script, _ = designing(wrong, dict(wrong), ollama=BuiltIn())
    events = list(designer.start("show me what the Japanese I highlight means in English"))
    assert designer.sketch.slots["skip_language"] == ""
    assert not any("Leaves out" in line for line in one(events, AgentCard).can_do) and "it gives" in one(events, Result).text
    # The other way to put it right: the helper was right, and another sample is given.
    designer, script, _ = designing(leaving("Korean", try_on="안녕하세요 반가워요"), leaving("Korean", try_on="good morning"),
                                    ollama=BuiltIn())
    events = list(designer.start("show me in Korean what I highlight"))
    assert designer.sketch.slots["skip_language"] == "Korean" and one(events, Result).text.startswith('On a sample, "good morning"')
    # A text of their own that the helper passes over is no mistake: the try-out says so.
    designer, script, _ = designing(leaving("Korean", try_on="안녕하세요 반가워요"), ollama=BuiltIn())
    events = list(designer.start("show me in plain Korean words what I highlight, like 안녕하세요 반가워요"))
    assert len(script.notes) == 1 and designer.sketch.slots["skip_language"] == "Korean"
    assert "it does nothing: the text is already in Korean" in one(events, Result).text
    assert "the language its result comes out in" in parts.WHENS[WHILE_ON].settings[0].how


class Gives(BuiltIn):
    """The built-in model, when what a helper for text gives has to be in a language of its own."""

    def __init__(self, words: str):
        super().__init__()
        self.words = words

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.asked.append(messages)
        yield self.words


def test_the_language_a_card_leaves_out_is_put_right_by_what_its_try_out_gave(home):
    """A helper that was to show what Japanese sentences mean in English came with Japanese
    as the language it leaves out, again: the sample the model made up had too many Chinese
    characters in it to be told for Japanese, so nothing caught it, and once it was made an
    English sentence was turned into Japanese. And one changed by talking to give Korean
    kept English as the language it leaves out."""
    sample = "私は今日、公園へ行きました。"  # Japanese that code can't tell for Japanese
    wrong = leaving("Japanese", try_on=sample)
    designer, script, _ = designing(wrong, {**wrong, "name": "Meaning", "say": "It is called Meaning now."},
                                    ollama=Gives("I went to the park today."))
    events = list(designer.start("show me what the Japanese I highlight means in English"))
    assert len(script.notes) == 1 and designer.sketch.slots["skip_language"] == "English"
    assert "What it gives is in English, so that is the language it leaves out, not Japanese." in steps(events)
    assert "Leaves out text that is already in English" in one(events, AgentCard).can_do
    # Filled in the old way again the next turn, it stays as it was put right, and is not tried again for it.
    events = list(designer.answer("call it Meaning"))
    assert designer.sketch.slots["skip_language"] == "English" and designer.sketch.slots["name"] == "Meaning"
    assert not has(events, Result) and "- Leaves out text already in: English" in script.notes[1]
    # A change to another language whose setting did not follow: the result says which it is.
    stale = leaving("English", try_on="こんにちは、元気ですか？")
    designer, _, _ = designing(stale, ollama=Gives("안녕하세요, 잘 지내세요?"))
    list(designer.start("show me in Korean what the Japanese I highlight means"))
    assert designer.sketch.slots["skip_language"] == "Korean"
    # A result code can't tell the language of changes nothing; nor does one in the
    # language of the text it came from (the helper did not turn it into anything).
    for language, text, gives in (("English", "こんにちは", "Hello"), ("English", "こんにちは、元気ですか？", "こんにちは、元気ですか？"),
                                  ("Korean", "good morning to you", "GOOD MORNING TO YOU")):
        designer, _, _ = designing(leaving(language, try_on=text), ollama=Gives(gives))
        events = list(designer.start("show me what it means"))
        assert designer.sketch.slots["skip_language"] == language and "so that is the language" not in steps(events)
    # Found wrong in a turn in which they only said yes, it can still be put right in that
    # turn: a choice that was known is otherwise held through a plain yes, and held to
    # "Japanese" there, the model's own correction was not taken and the setting was taken off.
    kana = "こんにちは、元気ですか？"
    designer, script, _ = designing(leaving("Japanese", STILL_ASKING, "Should it show the meaning above the text?", rule=""),
                                    leaving("Japanese", try_on=kana), leaving("English", try_on=kana), ollama=BuiltIn())
    list(designer.start("show me what the Japanese I highlight means in English"))
    assert designer.sketch.slots["skip_language"] == "Japanese"
    list(designer.answer("yes"))
    assert len(script.notes) == 3 and designer.sketch.slots["skip_language"] == "English"
    # And a card that leaves nothing out is never given a language by its result.
    designer, _, _ = designing(leaving("", try_on="こんにちは、元気ですか？"), ollama=Gives("Hello, how are you? It is nice to see you."))
    list(designer.start("show me what it means"))
    assert designer.sketch.slots["skip_language"] == ""
    assert "Never the language of the text it is given" in parts.WHENS[WHILE_ON].settings[0].how


def test_a_click_on_a_question_about_it_sets_it_like_any_choice(home):
    designer, _, _ = designing(leaving("", STILL_ASKING, "Which language should it leave alone?", asks="skip_language",
                                       rule=""),
                               leaving("", STILL_ASKING, "And what should it do with the text?", rule=""),
                               leaving("", STILL_ASKING, "And what should it do with the text?", rule=""))
    question = one(designer.start("something for what I highlight"), Question)
    # Asked while something needed is still missing, it has its buttons: the languages, and one for none.
    assert question.id == "skip_language" and question.choices == [*parts.WHENS[WHILE_ON].settings[0].choices, parts.NONE]
    list(designer.choose("skip_language", "Thai"))
    assert designer.sketch.slots["skip_language"] == "Thai"
    list(designer.choose("skip_language", parts.NONE))
    assert designer.sketch.slots["skip_language"] == ""


# ------------------------------------------------ set aside, and taken up again

ELSE = "what's the capital of France?"  # a message about something else, as the model in these tests takes it


def test_whether_a_message_is_about_something_else_is_decided_on_its_own_before_the_whole_form(home):
    """Left to the status of the whole form, a model handed back one such message of three:
    asked at the card how many legs a spider has, it answered that itself, and the person
    read "Nothing changed on the card: as far as I can tell it already does that"."""
    asks = form(say="What kind of files pile up in there?", wants="A tidier Downloads folder")
    designer, script, _ = designing(asks, form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    script.elsewhere = {"how many legs does a spider have"}
    list(designer.start(REQUEST))
    assert script.asides == []  # the message that starts it is what the conversation is about
    events = list(designer.answer("how many legs does a spider have"))
    # Handed back to the app before anything is worked out with it: no whole form was filled.
    assert [type(e) for e in events] == [Thinking] and designer.handoff == "how many legs does a spider have"
    assert not designer.active and designer.aside is not None and len(script.notes) == 1 and script.released == 1
    assert designer.aside.turns == [{"role": "user", "content": REQUEST}, {"role": "assistant", "content": asks["say"]}]
    note, asked = script.asides[0]
    assert note == designer_mod.ASIDE and "anything about the helper" in note and '"Part of this"' in note
    assert asked == ("THE HELPER\nA tidier Downloads folder\n\nYOUR LAST WORDS TO THEM\nWhat kind of files pile up in "
                     "there?\n\nTHEY HAVE JUST WRITTEN\nhow many legs does a spider have")
    # A message that is part of it goes on to the whole form, and is asked about once.
    designer.handoff = None
    list(designer.carry_on())
    events = list(designer.answer("boat papers and garden plans, mostly"))
    assert designer.active and has(events, AgentCard) and len(script.asides) == 2 and designer.handoff is None
    # At the card too; and what code takes itself (a plain yes, a never mind) is never asked about.
    script.elsewhere.add("who wrote war and peace")
    events = list(designer.answer("who wrote war and peace"))
    assert not designer.active and designer.aside.shown == designer.aside.slots and len(script.notes) == 2
    list(designer.carry_on())
    asked = len(script.asides)
    list(designer.answer("yes"))
    assert len(store.list_agents()) == 1 and len(script.asides) == asked
    # A change to a helper they have is said to be one, with its name.
    designer, script, _ = designing(form(say="Shall I leave the rest as it is?"), form(say="Then nothing changes."))
    list(designer.edit(store.list_agents()[0], "put the boat papers somewhere else"))
    list(designer.answer("yes leave it"))
    assert script.asides[0][1].startswith("THE HELPER\nA change to their helper Paper sorter: put the boat papers somewhere else\n")


def test_a_model_off_this_computer_is_not_asked_first_and_one_that_cannot_answer_is_taken_for_part_of_it(home):
    # Through a plan every form is a whole answer: its model says "something else" in the whole form, or not at all.
    designer, script, _ = designing(form(say="What kind of files pile up in there?"), form(MOVED_ON, "Not mine."), here=False)
    script.elsewhere = {ELSE}
    list(designer.start(REQUEST))
    list(designer.answer(ELSE))
    assert script.asides == [] and len(script.notes) == 2 and designer.aside is not None and designer.handoff == ELSE

    class Stumbles(Script):
        def fill(self, note, turns, schema):
            if "about" in schema["properties"]:
                raise DesignerError("it didn't fill in the form")
            return super().fill(note, turns, schema)

    script = Stumbles(form(say="What kind of files pile up in there?"), form(say="And where should they go?"))
    designer = Designer(BuiltIn(), "noir", None, Rehearsal(),
                        lambda: DesignModel(script.fill, "Test model", here=True, release=script.release), lambda: "Small model")
    list(designer.start(REQUEST))
    events = list(designer.answer(ELSE))
    assert designer.active and designer.aside is None and said(events) == "And where should they go?"


def test_a_helper_set_aside_stands_as_it_stood_and_carrying_on_asks_the_open_question_again(home):
    asks = form(say="Should it go by what's inside each file, or only by its name?", asks="looks_at", when=NEW_FILE,
                then=MOVE, folder=("Downloads", ""), wants="A tidier Downloads folder")
    designer, script, _ = designing(asks, form(MOVED_ON, "That is not mine to answer.", wants="To know a capital"),
                                    form(say="And which folders should they go into?"))
    list(designer.start(REQUEST))
    before = dict(designer.sketch.slots)
    list(designer.answer(ELSE))
    kept = designer.aside
    assert not designer.active and kept.slots == before
    assert kept.wants == "A tidier Downloads folder"  # what that message was about is not what the helper is for
    # Its conversation is as it was before the aside: the message is taken out of it again.
    assert kept.turns == [{"role": "user", "content": REQUEST}, {"role": "assistant", "content": asks["say"]}]
    assert script.released == 1 and len(script.notes) == 2  # a model on this computer leaves memory meanwhile

    events = list(designer.carry_on())
    assert designer.active and designer.aside is None and designer.sketch is kept
    # One line that says where things stood: the question that was open, with its buttons again.
    assert len(events) == 1 and len(script.notes) == 2  # and nobody was asked anything for it
    question = events[0]
    assert (question.id, question.choices) == ("looks_at", [INSIDE_FILE, NAME_ONLY])
    assert question.text == f"Back to the helper we were working out. {asks['say']}"
    # It goes on as if nothing had come between, with the model it was begun with.
    list(designer.choose("looks_at", NAME_ONLY))
    assert designer.sketch.slots["looks_at"] == NAME_ONLY and script.released == 1
    assert script.turns[2] == [{"role": "user", "content": REQUEST}, {"role": "assistant", "content": asks["say"]},
                               {"role": "user", "content": NAME_ONLY}]
    assert "- What they want: A tidier Downloads folder" in script.notes[2]


def test_carrying_on_at_the_card_shows_the_card_and_the_try_out_it_had_and_asks_nobody(home):
    log = []
    designer, script, rehearsal = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), form(MOVED_ON),
                                            rows=[ROWS], log=log)
    first = list(designer.start(REQUEST))
    card, tried = one(first, AgentCard), one(first, Result)
    list(designer.answer(ELSE))
    assert designer.aside.shown == designer.aside.slots and store.list_agents() == []
    del log[:]
    events = list(designer.carry_on())
    assert said(events) == ("Back to the helper we were working out. Here is Paper sorter as we left it: create it if "
                            "it looks right, or tell me what to change.")
    again = one(events, Result)
    words = next(e for e in events if isinstance(e, NoirText))
    assert events.index(words) < events.index(again) < events.index(one(events, AgentCard))
    # The try-out is the one it had, said as what came out then: it is not run again for this.
    assert again.agent == "Try-out"
    assert again.text.splitlines()[0] == "The try-out from before, on 3 files in Downloads. Nothing was moved."
    assert again.text.splitlines()[1:] == tried.text.splitlines()[1:]
    assert one(events, AgentCard) == card
    assert log == [] and rehearsal.calls == 1 and len(script.notes) == 2  # no model was asked, nothing was tried
    # Nothing is asked in those words, so a plain yes is a yes to the card.
    assert designer.sketch.waiting == CARD
    list(designer.answer("yes"))
    assert [a.name for a in store.list_agents()] == ["Paper sorter"]


def test_a_question_that_was_open_at_the_card_does_not_hold_a_yes_once_the_card_is_shown_again(home):
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER),
                               form(say="Only new ones. Which of the old ones matter to you?", **MOVER),
                               form(MOVED_ON), rows=[ROWS])
    list(designer.start(REQUEST))
    list(designer.answer("will it move my old files?"))
    assert designer.sketch.waiting == DESIGN  # Noir has just asked something: a yes would answer that
    list(designer.answer(ELSE))
    events = list(designer.carry_on())
    # The words the card comes back under ask nothing, and invite the yes.
    assert has(events, AgentCard) and "?" not in said(events) and designer.sketch.waiting == CARD
    list(designer.answer("yes"))
    assert len(store.list_agents()) == 1


def test_the_try_out_of_a_helper_for_text_or_for_documents_comes_back_as_it_was(home):
    fixer = dict(when=IN_CHAT, then=ANSWER, name="Grammar fixer",
                 rule="Correct the grammar and spelling of the text. Keep its meaning.")
    built_in = BuiltIn()
    designer, _, _ = designing(form(NOTHING_MISSING, 'Write "Grammar fixer:" and your text.', try_on="me and him goes",
                                    **fixer), form(MOVED_ON), ollama=built_in)
    list(designer.start("fix my grammar when I ask, like me and him goes"))
    list(designer.answer(ELSE))
    events = list(designer.carry_on())
    assert one(events, Result).text == 'The try-out from before: on "me and him goes" it gave:\nME AND HIM GOES'
    assert len(built_in.asked) == 1 and has(events, AgentCard)  # the built-in model was not asked again

    manuals = home / "Documents" / "Manuals"
    manuals.mkdir()
    (manuals / "washer.txt").write_text("To start the washer, press the green button twice.", encoding="utf-8")
    reader = dict(when=IN_CHAT, then=DOCUMENTS, folder=("Documents", "Manuals"), name="Manuals helper")
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **reader), form(MOVED_ON))
    list(designer.start("I want to ask questions about my manuals"))
    list(designer.answer(ELSE))
    events = list(designer.carry_on())
    assert one(events, Result).text == f"Found 1 file it can read in {Path('Documents') / 'Manuals'}."
    assert one(events, AgentCard).reads == [f"The PDF, Word and text files in {Path('Documents') / 'Manuals'} (1 right now)"]

    # A try-out that could not run is not made up afterwards: the card comes back without one.
    class Down(BuiltIn):
        def chat(self, model, messages, **more):
            raise OllamaError("Ollama stopped")
            yield ""

    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", when=IN_CHAT, then=ANSWER, rule="Say it shorter."),
                               form(MOVED_ON), ollama=Down())
    list(designer.start("make my texts shorter when I ask"))
    list(designer.answer(ELSE))
    events = list(designer.carry_on())
    assert has(events, AgentCard) and not has(events, Result)


def test_a_change_that_was_set_aside_is_taken_up_or_dropped_with_the_helper_as_it_was(home):
    old = card_they_have(home)
    designer, script, _ = designing(form(NOTHING_MISSING, "It goes by names now.", when=NEW_FILE, then=MOVE,
                                         looks_at=NAME_ONLY), form(MOVED_ON), rows=[ROWS])
    list(designer.edit(old, "make Paper sorter go by the file names only"))
    list(designer.answer(ELSE))
    assert designer.aside.editing and store.find_agent("Paper sorter").slots["looks_at"] == INSIDE_FILE
    events = list(designer.carry_on())
    assert said(events) == ("Back to the changes to Paper sorter. Here is Paper sorter as we left it: save the changes "
                            "if it looks right, or tell me what to change.")
    assert one(events, AgentCard).actions[0] == SAVE_CHANGES and designer.sketch.slots["looks_at"] == NAME_ONLY
    script.forms.append(form(MOVED_ON))
    list(designer.answer("and of Spain?"))
    events = list(designer.drop())
    assert said(events) == "Okay, I left Paper sorter as it was." and designer.aside is None and not designer.active
    assert store.find_agent("Paper sorter").slots["looks_at"] == INSIDE_FILE
    # With nothing set aside, both say so.
    assert "already been answered" in said(list(designer.drop()))
    assert "already been answered" in said(list(designer.carry_on())) and not designer.active


def test_beginning_or_changing_another_helper_leaves_the_one_set_aside(home):
    old = card_they_have(home)
    designer, script, _ = designing(form(say="What bothers you about them?"), form(MOVED_ON),
                                    form(say="Which words should it explain?"), rows=[ROWS])
    list(designer.start(REQUEST))
    first = designer.sketch
    list(designer.answer(ELSE))
    events = list(designer.start("explain the words I highlight"))
    assert designer.aside is None and designer.active and designer.sketch is not first
    assert designer.sketch.request == "explain the words I highlight"
    assert events[0].text == ("This begins another one, so I've left the helper we were working out before: nothing "
                              "was created.")
    assert "already been answered" in said(list(designer.carry_on())) and designer.sketch is not first
    # The same when it is a change to one they have that is begun, and a change that waited says what was kept.
    script.forms += [form(MOVED_ON), form(NOTHING_MISSING, "By names now.", looks_at=NAME_ONLY), form(MOVED_ON),
                     form(say="Which folders?")]
    list(designer.answer(ELSE))
    events = list(designer.edit(old, "go by names"))
    assert designer.aside is None and designer.sketch.editing
    assert any(isinstance(e, Thinking) and "left the helper we were working out before" in e.text for e in events)
    list(designer.answer(ELSE))
    events = list(designer.start(REQUEST))
    assert events[0].text == ("This begins another one, so I've left the helper we were working out before: Paper "
                              "sorter is as it was.")
    # With nobody to work one out with, nothing is begun, and the one that waits goes on waiting.
    script.forms.append(form(MOVED_ON))
    list(designer.answer(ELSE))
    waiting = designer.aside
    designer.design_model = lambda: None
    assert said(list(designer.start("and another one"))) == NO_DESIGNER and designer.aside is waiting


def test_the_question_about_a_helper_they_have_comes_back_with_its_buttons(home):
    card_they_have(home)
    designer, _, _ = designing(form(NOTHING_MISSING, "Here it is.", **{**MOVER, "name": "File tidier"}), form(MOVED_ON),
                               rows=[ROWS])
    asked = one(list(designer.start(REQUEST)), Question)
    list(designer.answer(ELSE))
    again = one(list(designer.carry_on()), Question)
    assert (again.id, again.choices) == (DUPLICATE, asked.choices)
    assert again.text == f"Back to the helper we were working out. {asked.text}"
    list(designer.choose(DUPLICATE, "Use Paper sorter"))
    assert not designer.active and [a.name for a in store.list_agents()] == ["Paper sorter"]


def test_set_aside_by_code_nothing_is_asked_of_the_model_and_an_answer_without_a_question_is_said_again(home):
    designer, script, _ = designing(form(NOTHING_MISSING, "Here it is.", **MOVER), rows=[ROWS])
    list(designer.start(REQUEST))
    designer.set_aside()  # as the engine does for a message no helper's conversation should read
    assert not designer.active and designer.aside is not None and designer.handoff is None
    assert len(script.notes) == 1 and script.released == 2  # once for the try-out, once now
    designer.set_aside()  # with nothing being worked out, nothing changes
    assert designer.aside is not None
    list(designer.drop())

    # Where things stood was words that asked nothing, with no card yet (a folder that could
    # not be used): they are said again, as where we left it.
    guessed = dict(when=NEW_FILE, then=MOVE, choices="Boat", rule=RULE)
    designer, _, _ = designing(
        form(NOTHING_MISSING, "Watching Papres.", folder=("", "Papres"), **guessed),
        form(NOTHING_MISSING, "I couldn't find Papres, so it will watch Downloads.", folder=("Downloads", ""), **guessed),
        form(MOVED_ON), rows=[ROWS])
    assert not has(list(designer.start(REQUEST)), Question)
    list(designer.answer(ELSE))
    events = list(designer.carry_on())
    assert said(events) == ("Back to the helper we were working out. Where we left it: I couldn't find Papres, so it "
                            "will watch Downloads.")
    assert not has(events, Question) and not has(events, AgentCard) and designer.sketch.waiting == DESIGN
