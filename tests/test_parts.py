"""The catalog an agent is made from (agents/parts.py): which parts there are, which go
together, what a card says from its slots alone, and what becomes of the agents that were
written by hand before there were cards."""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from concierge import noir
from concierge.agents import parts, store, worker
from concierge.agents.parts import (ANSWER, CHOOSE, CUSTOM, DOCUMENTS, DOCUMENTS_QA, IN_CHAT, INSIDE, INSIDE_FILE, MOVE,
                                    NAME, NAME_ONLY, NEW_FILE, NOTE, OPEN_NO, OPEN_YES, RULE, SAMPLE_QUESTION,
                                    SAMPLE_TEXT, SEARCH, SHOW, WHILE_ON, WRITE)
from concierge.agents.store import Agent
from concierge.quick import selection, translate
from concierge.quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT

PAIRS = [(WHILE_ON, SHOW), (IN_CHAT, ANSWER), (IN_CHAT, DOCUMENTS), (NEW_FILE, MOVE), (NEW_FILE, NOTE)]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A made-up home: the places people name, a data folder, and nothing of the real computer."""
    for place in parts.PLACE_NAMES:
        (tmp_path / place).mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(parts, "known_folder", lambda name, home=None: tmp_path / name)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "data" / "agents")
    monkeypatch.setattr(noir, "data_dir", lambda: tmp_path / "data")
    return tmp_path


def slots_for(home: Path, when: str, then: str, **more) -> dict:
    """A whole card of this WHEN and THEN, made up."""
    slots = {"when": when, "then": then, "name": "Paper sorter"}
    if then != DOCUMENTS:
        slots["instruction"] = "Put anything about the boat in Boat. Leave the rest."
    if when == NEW_FILE:
        slots.update(folder=str(home / "Downloads"), looks_at=INSIDE_FILE)
    if when == WHILE_ON:
        slots["skip_language"] = ""
    if then == MOVE:
        slots.update(choices="Boat, Garden", open=OPEN_NO, into=str(home / "Desktop" / "Sorted"))
    if then == NOTE:
        slots["notes"] = ""
    if then == SHOW:
        slots.update(show=BUBBLE, keep=UNTIL_UNHIGHLIGHT)
    if then == DOCUMENTS:
        slots["folder"] = str(home / "Documents" / "Manuals")
    return {**slots, **more}


def lines_of(card: tuple) -> list[str]:
    kind, reads, can_do, cannot_do, runs_on = card
    return [kind, *reads, *can_do, *cannot_do, runs_on]


# ------------------------------------------------------------------ the catalog


def test_the_texts_saved_with_agents_stay_as_they_are():
    # They are stored in agent.yaml files: a changed text orphans every agent saved with it.
    assert WHILE_ON == "While it's switched on" and IN_CHAT == "When you ask in the chat"
    assert NEW_FILE == "When a new file lands in a folder"
    assert (SHOW, ANSWER) == ("Shows the result where you are", "Answers in the chat")
    assert (MOVE, NOTE) == ("Moves the file into a folder", "Writes about the file in a notes file")
    assert DOCUMENTS == "Answers from the documents in a folder"
    assert (INSIDE_FILE, NAME_ONLY) == ("What's inside the file", "Only the file's name")
    assert (OPEN_NO, OPEN_YES) == ("No, only the folders named", "Yes, when the rule calls for one")
    assert (WRITE, CHOOSE, SEARCH) == ("write", "choose", "search")
    assert (parts.MAX_RULE, parts.MAX_CHOICES, parts.MAX_EXAMPLES, parts.MAX_FOLDER_NAME) == (600, 12, 8, 40)
    assert RULE.key == "instruction" and RULE.type == "rule"  # the key highlight agents and shared recipes use
    assert NAME.key == "name" and NAME.type == "text" and NAME.ask is None
    assert CUSTOM == "custom"
    assert SAMPLE_TEXT == "The committee reached a quorum, so the motion carried."
    assert SAMPLE_QUESTION == "What are these files about?"


def test_the_older_texts_are_the_same_wherever_they_are_spelled_out():
    # recipe.py had them first, and agents, starters and shared recipes are saved with them.
    from concierge.agents import recipe

    assert (recipe.CUSTOM, recipe.WHILE_ON, recipe.IN_CHAT) == (CUSTOM, WHILE_ON, IN_CHAT)
    assert (recipe.SAMPLE_TEXT, recipe.SAMPLE_QUESTION) == (SAMPLE_TEXT, SAMPLE_QUESTION)


def test_the_catalog_waits_for_neither_the_recipes_nor_the_builder():
    """recipe.py and builder.py are to take what they need from the catalog. If the catalog
    took anything from them in turn, whichever was loaded first would find the other half
    made, and the app would not start."""
    loaded = subprocess.run(
        [sys.executable, "-c",
         "import sys, concierge.agents.parts\n"
         "print(sorted(name for name in sys.modules if name.startswith('concierge.agents.')))"],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], check=True).stdout
    assert "concierge.agents.parts" in loaded and "concierge.agents.store" in loaded
    assert "concierge.agents.recipe" not in loaded and "concierge.agents.builder" not in loaded


def test_every_part_is_filed_under_its_own_text():
    assert list(parts.WHENS) == [WHILE_ON, IN_CHAT, NEW_FILE]
    assert list(parts.THENS) == [SHOW, ANSWER, MOVE, NOTE, DOCUMENTS]
    for kind, catalog in (("when", parts.WHENS), ("then", parts.THENS)):
        for key, part in catalog.items():
            assert part.key == key and part.kind == kind
            assert part.about and part.facts
    assert {then: part.mode for then, part in parts.THENS.items()} == {
        SHOW: WRITE, ANSWER: WRITE, MOVE: CHOOSE, NOTE: WRITE, DOCUMENTS: SEARCH}
    assert [key for key, part in parts.WHENS.items() if part.windows_only] == [WHILE_ON]


def test_which_then_goes_with_which_when():
    assert parts.FITS == {WHILE_ON: (SHOW,), IN_CHAT: (ANSWER, DOCUMENTS), NEW_FILE: (MOVE, NOTE)}
    for when in parts.WHENS:
        for then in parts.THENS:
            assert parts.fits(when, then) == ((when, then) in PAIRS), (when, then)
    assert not parts.fits("", "") and not parts.fits("Whenever", MOVE) and not parts.fits(NEW_FILE, "")
    # Every THEN can be reached, each from one WHEN.
    assert sorted(then for thens in parts.FITS.values() for then in thens) == sorted(parts.THENS)


def test_highlights_are_only_offered_on_windows(monkeypatch):
    assert [part.key for part in parts.whens("win32")] == [WHILE_ON, IN_CHAT, NEW_FILE]
    assert [part.key for part in parts.whens("darwin")] == [IN_CHAT, NEW_FILE]
    monkeypatch.setattr(sys, "platform", "darwin")
    assert WHILE_ON not in [part.key for part in parts.whens()]


def test_a_card_saved_before_there_were_thens_has_the_one_its_when_meant():
    assert parts.then_of({"when": WHILE_ON, "instruction": "Explain it."}) == SHOW
    assert parts.then_of({"when": IN_CHAT, "instruction": "Fix it."}) == ANSWER
    assert parts.then_of({"instruction": "Translate the text into Korean."}) == SHOW  # no WHEN at all: switched on, as ever
    assert parts.then_of({"when": NEW_FILE, "then": NOTE}) == NOTE
    assert parts.then_of({"when": IN_CHAT, "then": DOCUMENTS}) == DOCUMENTS


def test_the_settings_of_each_pair():
    keys = lambda when, then: [setting.key for setting in parts.settings_for(when, then)]
    assert keys(WHILE_ON, SHOW) == ["skip_language", "show", "keep", "instruction", "name"]
    assert keys(IN_CHAT, ANSWER) == ["instruction", "name"]
    assert keys(IN_CHAT, DOCUMENTS) == ["folder", "name"]  # it follows no rule
    assert keys(NEW_FILE, MOVE) == ["folder", "looks_at", "choices", "open", "into", "instruction", "name"]
    assert keys(NEW_FILE, NOTE) == ["folder", "looks_at", "notes", "instruction", "name"]
    assert keys("", "") == ["instruction", "name"]  # nothing chosen yet
    watched, read = parts.settings_for(NEW_FILE, NOTE)[0], parts.settings_for(IN_CHAT, DOCUMENTS)[0]
    assert (watched.label, read.label) == ("Folder it watches", "Folder it reads")
    assert watched.type == read.type == "folder"


def test_every_setting_once_for_the_designers_form():
    keys = [setting.key for setting in parts.all_settings()]
    assert keys == ["skip_language", "folder", "looks_at", "show", "keep", "choices", "open", "into", "notes",
                    "instruction", "name"]
    assert keys == [setting.key for setting in parts.all_settings()]  # the same order every time
    types = {setting.key: setting.type for setting in parts.all_settings()}
    assert types == {"skip_language": "choice", "folder": "folder", "looks_at": "choice", "show": "choice",
                     "keep": "choice", "choices": "list", "open": "choice", "into": "place", "notes": "place",
                     "instruction": "rule", "name": "text"}
    for when, then in PAIRS:  # and nothing a pair needs is missing from it
        assert {setting.key for setting in parts.settings_for(when, then)} <= set(keys)


def test_what_must_be_asked_and_what_has_a_usual_value():
    by_key = {setting.key: setting for setting in parts.all_settings()}
    assert [key for key, setting in by_key.items() if parts.needed(setting)] == ["folder", "choices", "instruction"]
    assert parts.needed(parts.settings_for(IN_CHAT, DOCUMENTS)[0])  # the folder it reads
    assert by_key["looks_at"].default == INSIDE_FILE and by_key["open"].default == OPEN_NO
    assert by_key["show"].default == BUBBLE and by_key["show"].choices == (BUBBLE, CLIPBOARD, BOTH)
    assert by_key["keep"].default == UNTIL_UNHIGHLIGHT and by_key["keep"].choices == (UNTIL_UNHIGHLIGHT, FEW_SECONDS)
    assert by_key["into"].default == "" and by_key["notes"].default == ""  # inside the watched folder
    for setting in [*by_key.values(), parts.settings_for(IN_CHAT, DOCUMENTS)[0]]:
        assert setting.label and setting.how
        assert (setting.ask is None) == (setting.default is not None or setting.key == "name"), setting.key
        if setting.type == "choice":
            # (A choice whose usual value is none of its choices has "" for it.)
            assert setting.default in setting.choices or setting.default == ""


def test_any_card_that_works_on_highlights_can_leave_out_text_in_one_language():
    """What was once known of one kind of helper, by reading its rule for a word, is a
    setting any card of this WHEN can have. It is never asked for, it is none unless said,
    and only a language code can really tell a text is in can be picked: for any other,
    nothing would ever be left out and the card would say something untrue."""
    setting = parts.WHENS[WHILE_ON].settings[0]
    assert (setting.key, setting.label, setting.type) == ("skip_language", "Leaves out text already in", "choice")
    assert setting.ask is None and setting.default == "" and not parts.needed(setting)
    assert setting.choices == translate.TELLABLE
    assert set(setting.choices) < set(translate.LANGUAGES)  # a language the app knows, and not every one of them
    for language in translate.LANGUAGES:
        # The ones it can't tell: no text with letters in it ever looks like one of them.
        assert (language in setting.choices) == any(translate.looks_like(text, language) for text in (
            "The cat is on the table and it is asleep.", "안녕하세요 반가워요", "おはようございます", "早上好朋友们",
            "Доброе утро всем", "สวัสดีตอนเช้า", "صباح الخير", "सुप्रभात दोस्तों"))
    # Its line for the design model names no helper. It lists the languages that can be
    # picked, those and no others: a model on this computer is held to the form's choices
    # without being shown them. And it says how one is taken off again.
    assert not re.search(r"translat|helper for|such as|like ", setting.how, re.IGNORECASE)
    assert f"one of {', '.join(setting.choices)}:" in setting.how
    assert not any(language in setting.how for language in translate.LANGUAGES if language not in setting.choices)
    assert f'"{parts.NONE}" for every other helper, for any other language' in setting.how
    assert parts.NONE not in setting.choices
    # No other WHEN has it: nothing is highlighted for a card asked in the chat or one that works on files.
    assert all(s.key != "skip_language" for when in (IN_CHAT, NEW_FILE) for s in parts.WHENS[when].settings)


def test_which_text_a_card_leaves_out():
    card = {"when": WHILE_ON, "instruction": "Say it more simply.", "skip_language": "Korean"}
    assert parts.skip_language(card) == "Korean"
    assert parts.leaves_out(card, "안녕하세요, 반가워요") == "Korean"
    assert parts.leaves_out(card, "Good morning") == ""
    assert parts.leaves_out(card, "12:30 - 14:00") == "Korean"  # no letters: nothing in any language to work on
    # None set, which is the usual: every highlight is worked on, numbers too.
    for none in ({"when": WHILE_ON}, {"when": WHILE_ON, "skip_language": ""}, {"skip_language": None}):
        assert parts.skip_language(none) == "" and parts.leaves_out(none, "안녕하세요") == ""
        assert parts.leaves_out(none, "12:30") == ""
    # What the rule says makes no difference either way: only the setting counts.
    says_so = {"when": WHILE_ON, "instruction": "Translate the text into Korean."}
    assert parts.leaves_out(says_so, "안녕하세요") == ""
    assert parts.leaves_out({**card, "instruction": "Count the words."}, "안녕하세요") == "Korean"
    # A card with no WHEN works while switched on, as ever; one that works another way leaves nothing out.
    assert parts.skip_language({"skip_language": "English"}) == "English"
    assert parts.skip_language({"when": IN_CHAT, "skip_language": "Korean"}) == ""
    assert parts.skip_language({"when": NEW_FILE, "skip_language": "Korean"}) == ""
    # Something saved that is no language code can tell counts as none, never as a promise.
    assert parts.skip_language({"when": WHILE_ON, "skip_language": "Spanish"}) == ""
    assert parts.leaves_out({"when": WHILE_ON, "skip_language": "Klingon"}, "12:30") == ""


def test_nothing_in_the_catalog_knows_what_an_agent_is_for():
    """No subject, no kind of document, no example of somebody's folder: given one, a model
    offered it to the user as if it were theirs."""
    texts = []
    for part in [*parts.WHENS.values(), *parts.THENS.values()]:
        texts += [part.about, *part.facts]
        texts += [text for setting in part.settings for text in (setting.label, setting.ask or "", setting.how)]
    texts += [RULE.label, RULE.ask, RULE.how, NAME.label, NAME.how]
    # The words that count for nothing in a folder's name decide which folders are the same
    # one, so they are the catalog's too: the list this one replaced was one agent's subject.
    texts += sorted(parts.STOPWORDS)
    banned = re.compile(r"\b(course|school|college|class|lecture|homework|exam|bank|tax|bill|invoice|receipt|"
                        r"organi[sz]er|summar\w*|translat\w*|physics|math\w*)\b|\blike \"|\bsuch as\b|\be\.g\.", re.IGNORECASE)
    for text in texts:
        assert not banned.search(text), text
    subject = re.compile(r"\b(course|school|college|lecture|homework|exam|quiz|midterm|lab|labs|handout|physics|"
                         r"phys ?\d+)\b", re.IGNORECASE)
    assert not [word for word in parts.STOPWORDS if subject.search(word)]
    # What a function says of itself is read by whoever builds on it: no example there is
    # the old agent's either. (Only the part that turns old agents into cards names them.)
    for name, function in inspect.getmembers(parts, inspect.isfunction):
        if function.__module__ == parts.__name__ and not name.startswith("_old") and name != "migrate":
            assert not subject.search(function.__doc__ or ""), name


def test_every_fact_is_true_to_the_code_that_runs_the_part():
    """The designer may tell the user any of these, and nothing else."""
    watching = " ".join(parts.WHENS[NEW_FILE].facts)
    # Every new file is opened for a moment to see that nothing is still writing it, so
    # "it never opens a file" was not true. What is true is that nothing inside is looked at.
    assert "opens a file" not in watching and "opened" not in parts.WHENS[NEW_FILE].settings[1].how
    assert f'With "{NAME_ONLY}" what is inside a file is never looked at' in watching
    # A highlight past the watcher's own limit is dropped without a word, and the fact takes
    # the number from the watcher, so the two can't come to differ.
    assert (f"It works on a highlight of up to {selection.MAX_CHARS:,} characters. A longer one is ignored: nothing "
            "happens.") in parts.WHENS[WHILE_ON].facts
    # Which languages it can leave out is said from the list code goes by, and so is that a
    # highlight with no letters in it is passed over along with them.
    leaving = next(fact for fact in parts.WHENS[WHILE_ON].facts if "leave out" in fact)
    assert ", ".join(translate.TELLABLE) in leaving and "one with no letters in it" in leaving
    assert all(language in leaving or language not in translate.TELLABLE for language in translate.LANGUAGES)
    assert not any(language in leaving for language in translate.LANGUAGES if language not in translate.TELLABLE)
    # A chat helper with a rule is also offered by the Spot, so "only in the chat" was not the whole of it.
    assert "only in the chat" not in parts.WHENS[IN_CHAT].about + " ".join(parts.WHENS[IN_CHAT].facts)
    # How it is asked is part of what this WHEN is: left to the facts further down, a model
    # told someone their helper would work "whenever you paste your notes into the chat".
    assert "in the chat they write its name, a colon and their text" in parts.WHENS[IN_CHAT].about
    assert "a message that does not begin with its name is not for it" in parts.WHENS[IN_CHAT].about
    assert any("Ctrl is tapped twice" in fact and "always with the built-in model" in fact for fact in parts.THENS[ANSWER].facts)
    assert not any("Ctrl" in fact for fact in parts.THENS[DOCUMENTS].facts)  # it follows no rule, so the Spot has no button for it
    # Which language a note is written in is worked out in code from the rule, and said as it is.
    assert any("in the language the rule is written in, whatever language a file is in" in fact
               for fact in parts.THENS[NOTE].facts)
    assert worker._language("Say what each file is.") == "in English"
    assert worker._language("각 파일이 무엇인지 적어 주세요.") == worker._language("Say in Korean what it is.") == "in Korean"


# ------------------------------------------------------------------ missing and usual values


def test_what_is_still_missing_from_a_card(home):
    keys = lambda slots: [setting.key for setting in parts.missing(slots)]
    assert keys({}) == ["instruction"]  # nothing chosen: only the rule is known to be needed
    assert keys({"when": NEW_FILE, "then": MOVE}) == ["folder", "choices", "instruction"]
    assert keys({"when": NEW_FILE, "then": NOTE}) == ["folder", "instruction"]
    assert keys({"when": IN_CHAT, "then": DOCUMENTS}) == ["folder"]
    assert keys({"when": WHILE_ON, "then": SHOW}) == ["instruction"]
    assert keys({"when": NEW_FILE}) == ["folder", "instruction"]  # the THEN is the caller's to notice
    for when, then in PAIRS:
        assert parts.missing(slots_for(home, when, then)) == []


def test_folders_need_not_be_named_when_it_may_make_them(home):
    card = slots_for(home, NEW_FILE, MOVE, choices="")
    assert [setting.key for setting in parts.missing(card)] == ["choices"]
    assert parts.missing({**card, "open": OPEN_YES}) == []
    assert [setting.key for setting in parts.missing({**card, "choices": " , ;"})] == ["choices"]  # no name in it
    assert parts.missing({**card, "choices": "Boat"}) == []


def test_a_card_from_before_thens_misses_nothing_it_has():
    assert parts.missing({"when": IN_CHAT, "instruction": "Fix the grammar.", "name": "Grammar Fixer"}) == []
    assert parts.missing({"when": WHILE_ON, "instruction": "Explain it.", "name": "Explainer"}) == []
    assert [s.key for s in parts.missing({"when": WHILE_ON, "instruction": "  "})] == ["instruction"]


def test_the_usual_values_fill_only_what_is_empty(home):
    assert parts.defaults({"when": NEW_FILE, "then": MOVE}) == {"looks_at": INSIDE_FILE, "open": OPEN_NO, "into": ""}
    assert parts.defaults({"when": NEW_FILE, "then": NOTE}) == {"looks_at": INSIDE_FILE, "notes": ""}
    assert parts.defaults({"when": WHILE_ON, "then": SHOW}) == {"skip_language": "", "show": BUBBLE,
                                                                "keep": UNTIL_UNHIGHLIGHT}
    assert parts.defaults({"when": WHILE_ON, "then": SHOW, "skip_language": "Korean", "show": BOTH}) == {
        "keep": UNTIL_UNHIGHLIGHT}  # a language that is set stays
    assert parts.defaults({"when": IN_CHAT, "then": ANSWER}) == {}
    assert parts.defaults({"when": IN_CHAT, "then": DOCUMENTS}) == {}
    assert parts.defaults({}) == {}
    chosen = {"when": NEW_FILE, "then": MOVE, "looks_at": NAME_ONLY, "open": OPEN_YES, "into": str(home / "Desktop")}
    assert parts.defaults(chosen) == {"choices": ""}  # none named and none needed: it makes them as it goes
    assert parts.defaults({**chosen, "choices": "Boat"}) == {}
    assert parts.defaults({"when": NEW_FILE, "then": MOVE, "looks_at": "", "into": ""}) == {"looks_at": INSIDE_FILE,
                                                                                         "open": OPEN_NO}
    assert parts.defaults({"when": WHILE_ON, "show": CLIPBOARD}) == {"skip_language": "",
                                                                     "keep": UNTIL_UNHIGHLIGHT}  # an older card
    for when, then in PAIRS:
        assert parts.defaults(slots_for(home, when, then)) == {}


# ------------------------------------------------------------------ small questions about a card


def test_what_the_small_model_does_for_each_card():
    assert parts.mode({"when": NEW_FILE, "then": MOVE}) == CHOOSE
    assert parts.mode({"when": NEW_FILE, "then": NOTE}) == WRITE
    assert parts.mode({"when": IN_CHAT, "then": DOCUMENTS}) == SEARCH
    assert parts.mode({"when": WHILE_ON}) == WRITE and parts.mode({"when": IN_CHAT}) == WRITE
    assert parts.mode({"when": NEW_FILE, "then": "Something else"}) == ""


def test_which_agents_watch_and_which_can_be_switched_on():
    mover = Agent("Mover", CUSTOM, {"when": NEW_FILE, "then": MOVE})
    noter = Agent("Noter", CUSTOM, {"when": NEW_FILE, "then": NOTE})
    highlight = Agent("Explainer", CUSTOM, {"when": WHILE_ON, "instruction": "Explain it."})
    older = Agent("Translator", CUSTOM, {"instruction": "Translate it."})  # saved with no WHEN
    chat = Agent("Fixer", CUSTOM, {"when": IN_CHAT, "instruction": "Fix it."})
    documents = Agent("Manuals", DOCUMENTS_QA, {"folder": "C:/x/Manuals"})
    assert [parts.watches(a) for a in (mover, noter, highlight, older, chat, documents)] == [True, True, False, False, False, False]
    assert [parts.is_switchable(a) for a in (mover, noter, highlight, older, chat, documents)] == [True, True, True, True, False, False]
    assert not parts.watches(Agent("Odd", "something_else", {"when": NEW_FILE}))


def test_folder_names_are_cleaned():
    assert parts.choices_of({"choices": " Boat ,garden;  Tax: 2026/returns?\nBoat"}) == ["Boat", "garden", "Tax 2026 returns"]
    assert parts.choices_of({"choices": "PHYS 122, phys-122, Phys122"}) == ["PHYS 122"]  # one folder, said three ways
    assert parts.choices_of({"choices": ["Boat", "", "Garden"]}) == ["Boat", "Garden"]  # a list is taken too
    assert parts.choices_of({"choices": ""}) == [] and parts.choices_of({}) == [] and parts.choices_of({"choices": None}) == []
    assert parts.choices_of({"choices": "..., &, ??"}) == []
    assert parts.choices_of({"choices": "Boat and garden"}) == ["Boat and garden"]  # "and" may be in a name


def test_the_users_own_folder_names_are_kept_as_given():
    # Cleaned the way a model's made-up name is, "C++" and "C#" both became "C" and "Mom's
    # recipes" became "Mom s recipes": a new folder beside the one the user has.
    assert parts.choices_of({"choices": "C, C++, C#, Mom's recipes"}) == ["C", "C++", "C#", "Mom's recipes"]
    assert parts.choices_of({"choices": "Bills + receipts; 100% done\n[old] @home, 세금 2026"}) == [
        "Bills + receipts", "100% done", "[old] @home", "세금 2026"]
    assert parts.choices_of({"choices": "Reports. , .config,  two   spaces "}) == ["Reports", ".config", "two spaces"]
    # Only what no folder's name can hold is taken out, and a name is never a way out of its folder.
    assert parts.choices_of({"choices": 'a<b>c|d"e*f'}) == ["a b c d e f"]
    assert parts.choices_of({"choices": "..\\..\\Windows, .., ."}) == [".. .. Windows"]
    assert parts.choices_of({"choices": "tab\there"}) == ["tab here"]
    long = "A name that is longer than the forty characters a made-up name may have"
    assert parts.choices_of({"choices": long}) == [long]
    assert len(parts.choices_of({"choices": "x" * 400})[0]) == 255  # the longest a folder's name can be


def test_every_folder_a_card_has_comes_back_however_many():
    # At most MAX_CHOICES is for whoever takes a new list from the user to check. Cut here, a
    # card's thirteenth folder was never shown to the model again, so nothing could go in it.
    many = [f"Folder {n}" for n in range(30)]
    assert parts.choices_of({"choices": ", ".join(many)}) == many
    assert len(many) > parts.MAX_CHOICES


def test_a_folder_name_is_safe_to_make():
    assert parts.folder_name("Tax: 2026/returns?") == "Tax 2026 returns"
    assert parts.folder_name("  R&D (old) - v1.2  ") == "R&D (old) - v1.2"
    assert parts.folder_name("..\\..\\Windows") == "Windows"
    assert parts.folder_name("...") == "" and parts.folder_name("") == ""
    assert parts.folder_name("여행 사진") == "여행 사진"
    assert len(parts.folder_name("x" * 100)) == parts.MAX_FOLDER_NAME


def test_the_telling_words_of_a_name():
    assert parts.words_of("Plans for the Garden") == {"plans", "garden"}
    assert parts.words_of("The folder of my files") == set()
    assert parts.words_of("Plan B") == {"plan", "b"} and parts.words_of("Box 1") == {"box", "1"}  # one letter or digit counts
    assert parts.words_of("세금 2026") == {"세금", "2026"}  # in any language
    assert parts.words_of("C++ and C#") == {"c++", "c#"}
    assert parts.words_of("old_tax-papers (2026)") == {"old", "tax", "papers", "2026"}
    # No subject's words count for less than any other's.
    assert parts.words_of("Homework and exam practice for the course") == {"homework", "exam", "practice", "course"}
    assert not hasattr(parts, "closest")  # the folder with the most shared words: one shared word was enough


def test_which_folder_a_name_means():
    known = ["PHYS122", "Garden plans", "Boat"]
    assert parts.same_folder("PHYS 122", known) == "PHYS122"  # case, spaces and marks aside
    assert parts.same_folder("phys-122", known) == "PHYS122"
    assert parts.same_folder("  boat ", known) == "Boat"
    assert parts.same_folder("Plans for the garden", known) == "Garden plans"  # the same words, another order
    assert parts.same_folder("the Boat folder", known) == "Boat"
    assert parts.same_folder("Garden", known) == "Garden plans"  # some of the words of one folder only
    assert parts.same_folder("Job applications", known) is None  # nothing in common: a folder of its own
    assert parts.same_folder("PHYS 121", known) is None
    assert parts.same_folder("The folder", ["My files"]) is None  # only words that tell nothing
    assert parts.same_folder("", known) is None and parts.same_folder("?!", known) is None
    assert parts.same_folder("Boat", []) is None
    assert parts.same_folder("Boat", ["Boat trip", "Boat"]) == "Boat"  # the same name wins
    assert parts.same_folder("C++", ["C", "C#"]) is None and parts.same_folder("c#", ["C", "C#"]) == "C#"


@pytest.mark.parametrize("name, known", [
    ("PHYS 121", ["PHYS 122"]), ("Physics 121", ["Physics 122"]), ("Tax 2025", ["Tax 2026"]),
    ("Taxes 2026", ["Taxes 2025"]), ("Travel 2026", ["Tax 2026"]), ("Garden 2026", ["Boat 2026"]),
    ("Invoices 2026", ["Receipts 2026"]), ("Client Jones", ["Client Smith"]), ("Lab Jones", ["Lab Smith"]),
    ("My taxes", ["My photos"]), ("세금 2026", ["여행 2026"]), ("Plan B", ["Plan A"]),
    ("Bank statements", ["Bank of America job application"]),
    ("Folder 13", [f"Folder {n}" for n in range(1, 13)]),
    ("Boat trip", ["Boat trips"]), ("Exam papers", ["Exam paper"]),  # whatever the subject, the same answer
])
def test_one_shared_word_does_not_make_two_names_one_folder(name, known):
    """A new folder the rule called for was quietly turned into a different one that was
    there already, and the file moved into it."""
    assert parts.same_folder(name, known) is None


def test_a_name_that_says_more_or_other_than_a_folder_is_a_folder_of_its_own():
    assert parts.same_folder("Client Jones", ["Client"]) is None  # or the short name becomes the home of everything
    assert parts.same_folder("Tax 2026", ["Tax"]) is None and parts.same_folder("Tax", ["Tax 2026"]) is None
    assert parts.same_folder("Boat", ["Boat trips", "Boat repairs"]) is None  # which of the two, nobody can say
    assert parts.same_folder("Boat", ["Boat trips", "Garden"]) == "Boat trips"
    assert parts.same_folder("2026 invoices", ["Invoices 2026"]) == "Invoices 2026"
    assert parts.same_folder("Bills receipts", ["Bills + receipts"]) == "Bills + receipts"


def test_where_a_cards_folders_and_notes_are(home):
    downloads = home / "Downloads"
    assert parts.destination({"folder": str(downloads), "into": ""}) == downloads
    assert parts.destination({"folder": str(downloads)}) == downloads
    assert parts.destination({"folder": str(downloads), "into": str(home / "Desktop" / "Sorted")}) == home / "Desktop" / "Sorted"
    card = {"folder": str(downloads), "name": "What came in"}
    assert parts.notes_path(card) == downloads / "What came in.md"  # named after the agent, in the folder it watches
    assert parts.notes_path({**card, "notes": ""}) == downloads / "What came in.md"
    assert parts.notes_path({**card, "name": "Bills: 2026?"}) == downloads / "Bills 2026.md"
    assert parts.notes_path({"folder": str(downloads)}) == downloads / "Notes.md"
    assert parts.notes_path({**card, "notes": str(home / "Documents" / "log.txt")}) == home / "Documents" / "log.txt"
    # A place that is a folder already: the notes file goes inside it.
    assert parts.notes_path({**card, "notes": str(home / "Desktop")}) == home / "Desktop" / "What came in.md"


def test_a_notes_file_named_without_an_ending_is_still_a_file(home):
    """People say "call the notes file Reading log" and rarely an ending. Read as a folder,
    that made a new folder with a file named after the agent inside it."""
    card = {"folder": str(home / "Downloads"), "name": "What came in"}
    desktop = home / "Desktop"
    assert parts.notes_path({**card, "notes": str(desktop / "Reading log")}) == desktop / "Reading log.md"
    assert parts.notes_path({**card, "notes": str(desktop / "Reading log.md")}) == desktop / "Reading log.md"
    assert parts.notes_path({**card, "notes": str(desktop / "LOG.TXT")}) == desktop / "LOG.TXT"
    # A dot in the name is not an ending.
    assert parts.notes_path({**card, "notes": str(desktop / "Notes v1.2")}) == desktop / "Notes v1.2.md"
    assert parts.notes_path({**card, "notes": str(desktop / "From Mr. Lee")}) == desktop / "From Mr. Lee.md"
    # A note is plain text added to the end of a file, so it never goes into a file of another kind.
    assert parts.notes_path({**card, "notes": str(desktop / "notes.docx")}) == desktop / "notes.docx.md"
    (desktop / "Reading").mkdir()  # a folder of that name is there: the notes file goes inside it
    assert parts.notes_path({**card, "notes": str(desktop / "Reading")}) == desktop / "Reading" / "What came in.md"
    kind, _reads, can_do, _never, _runs = parts.card(
        {"when": NEW_FILE, "then": NOTE, "instruction": "Say what it is.", **card, "notes": str(desktop / "Reading log")}, "")
    assert "Add what the rule asks for about each file to Reading log.md, in Desktop" in can_do


def test_a_place_is_said_by_name_never_as_a_whole_path(home):
    assert parts.short_place(home / "Downloads") == "Downloads"
    assert parts.short_place(home / "Desktop" / "College") == str(Path("Desktop") / "College")
    outside = home / "Elsewhere"
    assert parts.short_place(outside) == str(outside)  # a folder outside those places is shown as it is
    assert parts.INSIDE == "inside the watched folder" and parts.PLACE_NAMES == ["Desktop", "Documents", "Downloads", "Pictures"]


# ------------------------------------------------------------------ the card


@pytest.mark.parametrize("when, then", PAIRS)
def test_every_pair_has_a_whole_card_with_no_whole_path(home, when, then):
    kind, reads, can_do, cannot_do, runs_on = card = parts.card(slots_for(home, when, then), "Qwen 3.5 4B", count=4)
    assert kind and reads and can_do and cannot_do
    assert all(isinstance(line, str) and line.strip() for line in lines_of(card))
    assert all(str(home) not in line for line in lines_of(card))  # the user's name is in that path
    assert runs_on.startswith("Qwen 3.5 4B (the built-in model)") and "on this computer" in runs_on
    if then == DOCUMENTS:
        assert not any(line.startswith("Rule:") for line in can_do)
    else:
        assert can_do[0] == "Rule: Put anything about the boat in Boat. Leave the rest."


def test_a_card_that_moves_files(home):
    kind, reads, can_do, cannot_do, runs_on = parts.card(slots_for(home, NEW_FILE, MOVE), "Qwen 3.5 4B", count=3)
    assert kind == "When a new file lands in Downloads"
    assert reads[0] == "Each new file in Downloads: the beginning of what's inside it, read on this computer"
    assert reads[-1] == "The 3 files already there are left alone, unless you ask"
    assert "Move each file the rule covers into one of: Boat, Garden" in can_do
    assert f"Keep those folders in {Path('Desktop') / 'Sorted'}" in can_do
    assert "Show every move in your chores, with Undo for a week" in can_do
    assert cannot_do[:3] == ["Delete or overwrite a file",
                             "Touch files that were there before it was switched on, unless you ask",
                             "Send anything over the internet"]
    assert runs_on == "Qwen 3.5 4B (the built-in model), reading each file on this computer"


def test_a_card_that_moves_files_other_ways(home):
    inside = parts.card(slots_for(home, NEW_FILE, MOVE, into=""), "Qwen 3.5 4B")
    assert "Keep those folders inside Downloads" in inside[2]
    assert not any("already there" in line for line in inside[1])  # nobody counted
    one = parts.card(slots_for(home, NEW_FILE, MOVE), "Qwen 3.5 4B", count=1)
    assert one[1][-1] == "The 1 file already there is left alone, unless you ask"
    more = parts.card(slots_for(home, NEW_FILE, MOVE, open=OPEN_YES), "Qwen 3.5 4B")
    assert "Move each file the rule covers into one of: Boat, Garden, or into a new folder when the rule calls for one" in more[2]
    free = parts.card(slots_for(home, NEW_FILE, MOVE, open=OPEN_YES, choices=""), "Qwen 3.5 4B")
    assert "Move each file the rule covers into a folder, made when the rule calls for one" in free[2]
    by_name = parts.card(slots_for(home, NEW_FILE, MOVE, looks_at=NAME_ONLY), "Qwen 3.5 4B")
    assert by_name[1] == ["The name of each new file in Downloads, never what's inside it"]
    assert by_name[4] == "Qwen 3.5 4B (the built-in model), on this computer"


def test_a_card_that_writes_notes(home):
    kind, reads, can_do, cannot_do, _runs_on = parts.card(slots_for(home, NEW_FILE, NOTE), "Qwen 3.5 4B")
    assert kind == "When a new file lands in Downloads"
    assert "Add what the rule asks for about each file to Paper sorter.md, in Downloads" in can_do
    assert cannot_do[0] == "Move, change or delete the files it reads"
    named = parts.card(slots_for(home, NEW_FILE, NOTE, notes=str(home / "Documents" / "Reading" / "log.md")), "Qwen 3.5 4B")
    assert f"Add what the rule asks for about each file to log.md, in {Path('Documents') / 'Reading'}" in named[2]


def test_cards_that_work_on_text(home):
    kind, reads, can_do, cannot_do, runs_on = parts.card(slots_for(home, WHILE_ON, SHOW), "Qwen 3.5 4B")
    assert kind == WHILE_ON
    assert reads == ["Text you highlight with the mouse in any program, while it's switched on"]
    assert can_do[1:] == [f"Shows the result: {BUBBLE}", f"The result stays: {UNTIL_UNHIGHLIGHT}"]
    assert "Send anything over the internet" in cannot_do
    assert runs_on == "Qwen 3.5 4B (the built-in model), on this computer"
    copied = parts.card(slots_for(home, WHILE_ON, SHOW, show=CLIPBOARD), "Qwen 3.5 4B")
    assert copied[2][1:] == [f"Shows the result: {CLIPBOARD}"]  # nothing stays up
    older = parts.card({"when": WHILE_ON, "instruction": "Explain it.", "name": "Explainer"}, "Qwen 3.5 4B")
    assert older[2] == ["Rule: Explain it.", f"Shows the result: {BUBBLE}", f"The result stays: {UNTIL_UNHIGHLIGHT}"]
    # The language it leaves out is on the card when one is set, in plain words, and only then.
    leaves = parts.card(slots_for(home, WHILE_ON, SHOW, skip_language="Korean"), "Qwen 3.5 4B")
    assert leaves[2][1:] == [f"Shows the result: {BUBBLE}", f"The result stays: {UNTIL_UNHIGHLIGHT}",
                             "Leaves out text that is already in Korean"]
    assert parts.card(slots_for(home, WHILE_ON, SHOW, show=CLIPBOARD, skip_language="English"), "Qwen 3.5 4B")[2][1:] == [
        f"Shows the result: {CLIPBOARD}", "Leaves out text that is already in English"]
    for none in ("", "Spanish"):  # none set, or something saved that code can't tell: no line, so no promise
        assert not any("Leaves out" in line
                       for line in lines_of(parts.card(slots_for(home, WHILE_ON, SHOW, skip_language=none), "Qwen 3.5 4B")))

    kind, reads, can_do, cannot_do, runs_on = parts.card(slots_for(home, IN_CHAT, ANSWER), "Qwen 3.5 4B")
    assert kind == IN_CHAT
    assert reads == ['What you send it in the chat, starting with its name ("Paper sorter: ...")']
    assert can_do[1:] == ["Answers in the chat"]
    # Its answer is written by whichever model answers the chat, so the card promises nothing about the internet.
    assert not any("internet" in line for line in cannot_do)
    assert runs_on == "Qwen 3.5 4B (the built-in model), on this computer, unless you picked another model for the chat"
    # Nothing is highlighted for a card asked in the chat, so it leaves nothing out, whatever was saved with it.
    assert not any("Leaves out" in line
                   for line in lines_of(parts.card(slots_for(home, IN_CHAT, ANSWER, skip_language="Korean"), "Qwen 3.5 4B")))


def test_a_card_that_answers_from_documents(home):
    kind, reads, can_do, cannot_do, runs_on = parts.card(slots_for(home, IN_CHAT, DOCUMENTS), "", count=12)
    assert kind == IN_CHAT
    assert reads == [f"The PDF, Word and text files in {Path('Documents') / 'Manuals'} (12 right now)"]
    assert can_do == ["Find and quote passages from those files",
                      "Answer questions about them, with the file each answer came from"]
    assert cannot_do == ["Change, move or delete files", "Read anything outside that folder", "Use the internet"]
    assert runs_on == "The built-in model, on this computer"  # no name known for it
    assert parts.card(slots_for(home, IN_CHAT, DOCUMENTS), "the built-in model")[4] == "The built-in model, on this computer"
    assert parts.card(slots_for(home, IN_CHAT, DOCUMENTS), "Qwen 3.5 4B")[1] == [
        f"The PDF, Word and text files in {Path('Documents') / 'Manuals'}"]


def test_a_folder_somewhere_else_is_named_without_its_path(home):
    elsewhere = home / "Projects" / "Papers"  # in the home folder, in none of the places people name
    far = Path(home.anchor) / "vault-of-things" / "Sorted"  # not in the home folder at all
    card = parts.card(slots_for(home, NEW_FILE, MOVE, folder=str(elsewhere), into=str(far)), "Qwen 3.5 4B")
    assert card[0] == f"When a new file lands in {Path('Projects') / 'Papers'}"
    assert "Keep those folders in Sorted" in card[2]
    assert all(str(home) not in line and "vault-of-things" not in line for line in lines_of(card))


def test_a_place_is_shown_to_others_the_way_a_card_shows_it(home):
    # The designer's note for its model, which may be off this computer, says places this way.
    assert parts.shown_place(home / "Downloads") == "Downloads"
    assert parts.shown_place(home / "Desktop" / "Sorted") == str(Path("Desktop") / "Sorted")
    assert parts.shown_place(home / "Projects" / "Papers") == str(Path("Projects") / "Papers")
    assert parts.shown_place(Path(home.anchor) / "vault-of-things" / "Sorted") == "Sorted"
    assert parts.shown_place(home) == "your home folder"


def test_a_card_still_in_the_making_does_not_break(home):
    assert parts.card({}, "Qwen 3.5 4B")[2][0] == "Rule: "
    kind, reads, can_do, _cannot, _runs = parts.card({"when": NEW_FILE}, "Qwen 3.5 4B")
    assert kind == "When a new file lands in a folder" and reads and can_do == ["Rule: "]
    rule = parts.card({"when": IN_CHAT, "then": ANSWER, "instruction": "Fix\n the   grammar."}, "Qwen 3.5 4B")[2][0]
    assert rule == "Rule: Fix the grammar."  # one line on the card
    noter = parts.card({"when": NEW_FILE, "then": NOTE, "name": "Log"}, "Qwen 3.5 4B")
    assert "Add what the rule asks for about each file to Log.md, in a folder" in noter[2]  # no folder chosen yet
    assert parts.card({"then": DOCUMENTS}, "Qwen 3.5 4B")[0] == IN_CHAT  # the only WHEN it goes with
    assert parts.how(Agent("Half", CUSTOM, {"when": NEW_FILE})) == "Watches a folder and handles each new file by your rule."
    assert parts.describe(Agent("Half", CUSTOM, {"when": NEW_FILE}))["sample"] == parts.SAMPLE_FILES


# ------------------------------------------------------------------ the agent's page and the chores list


def test_an_agent_is_described_in_the_users_words():
    chat = parts.describe(Agent("Grammar Fixer", CUSTOM, {"instruction": "Fix it.", "when": IN_CHAT}))
    assert chat["does"] == "Fix it." and chat["sample"] == SAMPLE_TEXT
    assert dict(chat["facts"])["How it answers"] == "In the chat"
    assert "How long it stays" not in dict(chat["facts"])

    on = parts.describe(Agent("Explainer", CUSTOM, {"instruction": "Explain it.", "when": WHILE_ON, "show": "Both"}))
    assert dict(on["facts"])["How it answers"] == "Both"
    assert dict(on["facts"])["How long it stays"] == UNTIL_UNHIGHLIGHT
    assert on["sample"] == SAMPLE_TEXT

    older = parts.describe(Agent("Translator", CUSTOM, {"instruction": "Translate the text into Korean."}))
    assert older["does"] == "Translate the text into Korean."
    assert dict(older["facts"])["When it works"] == WHILE_ON and dict(older["facts"])["How it answers"] == BUBBLE
    # Its page says which language it leaves out when one is set, and nothing about that otherwise:
    # what the rule says is never read for it.
    assert "Leaves out" not in dict(older["facts"]) and "Leaves out" not in dict(on["facts"]) | dict(chat["facts"])
    leaves = parts.describe(Agent("Explainer", CUSTOM, {"instruction": "Explain it.", "when": WHILE_ON,
                                                        "skip_language": "Korean"}))
    assert dict(leaves["facts"])["Leaves out"] == "Text that is already in Korean"
    assert [label for label, _ in leaves["facts"]][-2:] == ["Leaves out", "Runs on"]

    files = parts.describe(Agent("Files", DOCUMENTS_QA, {"folder": "C:/Users/me/Papers"}, contents=["a.pdf"]))
    assert files["does"] == "Answers questions about your files, and shows which file each answer came from."
    assert dict(files["facts"])["Reads"] == "Papers" and dict(files["facts"])["Knows"] == "1 file"
    assert files["sample"] == SAMPLE_QUESTION
    assert dict(parts.describe(Agent("Files", DOCUMENTS_QA, {"folder": "C:/x/Papers"}, contents=["a", "b"]))["facts"])["Knows"] == "2 files"


def test_cards_that_work_on_files_are_described_from_their_slots(home):
    mover = parts.describe(Agent("Paper sorter", CUSTOM, slots_for(home, NEW_FILE, MOVE)))
    assert mover["does"] == "Put anything about the boat in Boat. Leave the rest."
    assert mover["facts"] == [["When it works", "When a new file lands in Downloads"],
                              ["What it looks at", INSIDE_FILE],
                              ["Folders", "Boat, Garden"],
                              ["May make new folders", OPEN_NO],
                              ["Keeps the folders in", str(Path("Desktop") / "Sorted")],
                              ["Runs on", "This computer"]]
    assert mover["sample"] == parts.SAMPLE_FILES == "go through the new files"
    free = parts.describe(Agent("Paper sorter", CUSTOM, slots_for(home, NEW_FILE, MOVE, choices="", open=OPEN_YES, into="")))
    assert dict(free["facts"])["Folders"] == "Made when the rule calls for one"
    assert dict(free["facts"])["Keeps the folders in"] == "Downloads"

    noter = parts.describe(Agent("Paper sorter", CUSTOM, slots_for(home, NEW_FILE, NOTE, looks_at=NAME_ONLY)))
    assert dict(noter["facts"]) == {"When it works": "When a new file lands in Downloads", "What it looks at": NAME_ONLY,
                                    "Writes in": "Paper sorter.md, in Downloads", "Runs on": "This computer"}
    for described in (mover, free, noter):
        assert all(str(home) not in value for _label, value in described["facts"])


def test_one_sentence_for_the_chores_list(home):
    line = lambda when, then, **more: parts.how(Agent("Paper sorter", CUSTOM, slots_for(home, when, then, **more)))
    assert line(NEW_FILE, MOVE) == (f"Watches Downloads and moves each new file your rule covers into Boat, Garden, "
                                    f"kept in {Path('Desktop') / 'Sorted'}.")
    assert line(NEW_FILE, MOVE, into="", open=OPEN_YES) == (
        "Watches Downloads and moves each new file your rule covers into Boat, Garden or a new folder.")
    assert line(NEW_FILE, MOVE, into="", open=OPEN_YES, choices="", looks_at=NAME_ONLY) == (
        "Watches Downloads and moves each new file your rule covers into folders it makes when the rule calls for "
        "one, going by its name alone.")
    assert line(NEW_FILE, NOTE) == ("Watches Downloads and writes what your rule asks for about each new file into "
                                    "Paper sorter.md.")
    assert line(WHILE_ON, SHOW) == ("While it's on, what you highlight in any program goes through it, and the answer "
                                    "shows above the text.")
    assert line(WHILE_ON, SHOW, show=CLIPBOARD).endswith("and the answer is copied, ready to paste.")
    assert line(WHILE_ON, SHOW, show=BOTH).endswith("and the answer shows above the text and is copied.")
    assert line(IN_CHAT, ANSWER) == 'Answers in the chat when you write "Paper sorter:" and your text.'
    documents = Agent("Manuals", DOCUMENTS_QA, {"folder": str(home / "Documents" / "Manuals"), "name": "Manuals"})
    assert parts.how(documents) == (f"Answers your questions from the files in {Path('Documents') / 'Manuals'}, when "
                                    "you ask in the chat.")
    for when, then in PAIRS:
        if then != DOCUMENTS:
            assert str(home) not in line(when, then)


# ------------------------------------------------------------------ the agents of the last version


def old_mover(home: Path, **slots) -> Agent:
    return Agent("File organizer", "organizer", {"folder": str(home / "Downloads"), "into": str(home / "Desktop" / "College"),
                                                 "groups": "PHYS122, CSE163", "by": "What's inside each file",
                                                 "name": "File organizer", **slots})


def state(home: Path, name: str = "organizer_state.json") -> dict:
    return json.loads((home / "data" / name).read_text(encoding="utf-8"))


def test_an_agent_that_sorted_into_named_folders_becomes_a_card(home):
    store.save(old_mover(home))
    assert parts.migrate() == ["File organizer"]
    [agent] = store.list_agents()
    assert agent.blueprint == CUSTOM and agent.name == "File organizer"
    assert agent.slots == {
        "when": NEW_FILE, "then": MOVE,
        "instruction": "Put each file into the folder that fits what it is about. If none fits, or it isn't clear, "
                       "leave it where it is.",
        "folder": str(home / "Downloads"), "looks_at": INSIDE_FILE, "choices": "PHYS122, CSE163", "open": OPEN_NO,
        "into": str(home / "Desktop" / "College"), "name": "File organizer"}
    assert parts.watches(agent) and parts.is_switchable(agent) and parts.mode(agent.slots) == CHOOSE
    assert parts.missing(agent.slots) == [] and parts.fits(agent.slots["when"], agent.slots["then"])
    assert parts.migrate() == []  # once is enough


def test_one_that_decided_as_it_went_keeps_the_folders_it_made_and_may_make_more(home):
    store.save(old_mover(home, groups="Decide as you go", by="The file's name", into=""))
    (home / "data" / "organizer_state.json").write_text(json.dumps(
        {"on": ["File organizer"], "made": {"File organizer": ["Physics 122", "Tax 2026"], "Another": ["X"]},
         "kinds": {"File organizer": {".xlsx": "yes"}}}), encoding="utf-8")
    assert parts.migrate() == ["File organizer"]
    slots = store.find_agent("File organizer").slots
    assert slots["choices"] == "Physics 122, Tax 2026" and slots["open"] == OPEN_YES
    assert slots["looks_at"] == NAME_ONLY and slots["into"] == ""
    assert parts.missing(slots) == []
    # Its card says it may make folders, so its rule says when and how. With the rule of one
    # that had its folders named ("if none fits, leave it") the setting did nothing.
    assert slots["instruction"] == ("Put each file into the folder that fits what it is about. If no folder fits, "
                                    "make a new one, named for what the file is about in two to four plain words. "
                                    "If it isn't clear what a file is about, leave it where it is.")
    assert len(slots["instruction"]) <= parts.MAX_RULE


def test_every_folder_an_old_agent_had_is_kept(home):
    """Twelve is the most a new list may name, not the most an agent may have: an old agent's
    thirteenth folder was dropped without a word, and nothing could be moved into it again."""
    groups = [f"G{n}" for n in range(14)] + ["C++", "Mom's recipes"]
    store.save(old_mover(home, groups=", ".join(groups)))
    made = [f"Made {n}" for n in range(15)]
    store.save(Agent("As it goes", "organizer", {"folder": str(home / "Downloads"), "groups": "Decide as you go",
                                                 "name": "As it goes"}))
    (home / "data" / "organizer_state.json").write_text(json.dumps({"made": {"As it goes": made}}), encoding="utf-8")
    assert sorted(parts.migrate()) == ["As it goes", "File organizer"]
    named = store.find_agent("File organizer").slots
    assert parts.choices_of(named) == groups and named["open"] == OPEN_NO  # and each name as the user gave it
    assert parts.choices_of(store.find_agent("As it goes").slots) == made


def test_one_that_had_made_no_folder_yet_starts_with_none(home):
    store.save(old_mover(home, groups="Decide as you go", into=str(home / "Downloads")))
    assert parts.migrate() == ["File organizer"]
    slots = store.find_agent("File organizer").slots
    assert slots["choices"] == "" and slots["open"] == OPEN_YES and parts.missing(slots) == []
    assert slots["into"] == ""  # the folder it watches, said as a place, only means inside it


def test_an_agent_that_wrote_summaries_becomes_a_card_that_writes_in_the_same_file(home):
    downloads = home / "Downloads"
    store.save(Agent("Summary writer", "summarizer", {"folder": str(downloads), "length": "Three short lines",
                                                      "name": "Summary writer"}))
    store.save(Agent("Long notes", "summarizer", {"folder": str(downloads), "length": "One short paragraph",
                                                  "notes": str(home / "Documents" / "arrivals.md"), "name": "Long notes"}))
    assert sorted(parts.migrate()) == ["Long notes", "Summary writer"]
    short = store.find_agent("Summary writer")
    assert short.blueprint == CUSTOM
    assert short.slots == {"when": NEW_FILE, "then": NOTE,
                           "instruction": "Say what this document is and what it says, in three short lines.",
                           "folder": str(downloads), "looks_at": INSIDE_FILE,
                           "notes": str(downloads / "Summaries.md"), "name": "Summary writer"}
    assert parts.notes_path(short.slots) == downloads / "Summaries.md"  # where its notes already are
    long = store.find_agent("Long notes").slots
    assert long["instruction"] == "Say what this document is and what it says, in one short paragraph."
    assert parts.notes_path(long) == home / "Documents" / "arrivals.md"
    assert parts.mode(long) == WRITE and parts.missing(long) == []


def test_they_come_back_switched_off_and_the_rest_is_left_as_it_was(home):
    store.save(old_mover(home))
    store.save(Agent("Summary writer", "summarizer", {"folder": str(home / "Downloads"), "name": "Summary writer"}))
    highlight = {"when": WHILE_ON, "instruction": "Explain it.", "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT,
                 "skip_language": "", "name": "Explainer"}
    store.save(Agent("Explainer", CUSTOM, dict(highlight)))
    store.save(Agent("Manuals", DOCUMENTS_QA, {"folder": str(home / "Documents"), "name": "Manuals"}, contents=["a.pdf"]))
    store.save(Agent("Newer card", CUSTOM, slots_for(home, NEW_FILE, MOVE, name="Newer card")))
    for name in ("organizer_state.json", "folderwatch_state.json"):
        (home / "data" / name).write_text(json.dumps(
            {"on": ["File organizer", "Newer card", "Summary writer"], "made": {}, "since": {"Newer card": 12.5},
             "seen": {"File organizer": ["x"]}}), encoding="utf-8")

    assert sorted(parts.migrate()) == ["File organizer", "Summary writer"]
    for name in ("organizer_state.json", "folderwatch_state.json"):
        assert state(home, name)["on"] == ["Newer card"]  # a card made by talking stays on
        assert state(home, name)["since"] == {"Newer card": 12.5} and state(home, name)["seen"] == {"File organizer": ["x"]}
    assert store.find_agent("Explainer").slots == highlight
    assert store.find_agent("Manuals").blueprint == DOCUMENTS_QA and store.find_agent("Manuals").contents == ["a.pdf"]
    assert store.find_agent("Newer card").slots == slots_for(home, NEW_FILE, MOVE, name="Newer card")
    assert {agent.blueprint for agent in store.list_agents()} == {CUSTOM, DOCUMENTS_QA}


def test_the_folders_it_made_are_found_in_the_newer_state_file_too(home):
    store.save(old_mover(home, groups="Decide as you go"))
    (home / "data" / "folderwatch_state.json").write_text(json.dumps(
        {"on": ["File organizer"], "made": {"File organizer": ["Boat"]}}), encoding="utf-8")
    assert parts.migrate() == ["File organizer"]
    assert store.find_agent("File organizer").slots["choices"] == "Boat"
    assert state(home, "folderwatch_state.json")["on"] == []


def test_a_state_file_that_cannot_be_read_stops_nothing(home):
    store.save(old_mover(home, groups="Decide as you go"))
    (home / "data" / "organizer_state.json").write_text("{not json", encoding="utf-8")
    (home / "data" / "folderwatch_state.json").write_text(json.dumps(["a", "list"]), encoding="utf-8")
    assert parts.migrate() == ["File organizer"]
    assert store.find_agent("File organizer").slots["choices"] == ""
    assert parts.migrate() == [] and [a.name for a in store.list_agents()] == ["File organizer"]


# ------------------------------------------------------------------ cards from before they could say what they leave out


def old_card(name: str, rule: str, **slots) -> Agent:
    return Agent(name, CUSTOM, {"instruction": rule, "when": WHILE_ON, "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT,
                                "name": name, **slots})


def test_a_card_saved_before_the_setting_is_given_it_once_from_what_its_rule_said(home):
    """Code used to work out from a card's rule alone that text already in one language was
    to be left out. That is a setting now, and the cards people already have get it here,
    once, so they go on working as they did. The first is the user's own kind of card."""
    store.save(old_card("Korean Translator", "Translate the text into Korean."))
    store.save(old_card("English one", "Translate what is highlighted to English, briefly."))
    store.save(old_card("한국어", "하이라이트한 문장을 한국어로 번역해줘"))
    no_when = Agent("Oldest", CUSTOM, {"instruction": "Translate the text into Japanese."})  # no WHEN: switched on, as ever
    store.save(no_when)
    store.save(old_card("Word explainer", "Explain this English word in simple Korean."))  # names a language, translates nothing
    store.save(old_card("Spanish Translator", "Translate the text into Spanish."))  # no text can be told to be in it
    store.save(old_card("Which one", "Translate the text."))  # says no language
    created = store.find_agent("Korean Translator").created

    assert parts.migrate() == []  # nothing became a card, nothing is switched off, nothing to tell the user
    left_out = {agent.name: agent.slots["skip_language"] for agent in store.list_agents()}
    assert left_out == {"Korean Translator": "Korean", "English one": "English", "한국어": "Korean", "Oldest": "Japanese",
                        "Word explainer": "", "Spanish Translator": "", "Which one": ""}
    mine = store.find_agent("Korean Translator")
    assert mine.blueprint == CUSTOM and mine.created == created
    assert mine.slots == {"instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE,
                          "keep": UNTIL_UNHIGHLIGHT, "name": "Korean Translator", "skip_language": "Korean"}
    assert parts.leaves_out(mine.slots, "안녕하세요") and not parts.leaves_out(mine.slots, "Good morning")
    assert "Leaves out text that is already in Korean" in parts.card(mine.slots, "")[2]
    assert "when" not in store.find_agent("Oldest").slots  # the rest of a card is left as it was


def test_the_setting_is_filled_once_and_is_the_cards_own_from_then_on(home):
    store.save(old_card("Korean Translator", "Translate the text into Korean."))
    store.save(old_card("Word explainer", "Explain this word."))
    parts.migrate()
    # Later the rules come to say something else. Nothing reads a rule for a language again.
    for name, rule in (("Korean Translator", "Count the words."), ("Word explainer", "Translate the text into Korean.")):
        agent = store.find_agent(name)
        agent.slots["instruction"] = rule
        store.save(agent)
    assert parts.migrate() == []
    assert store.find_agent("Korean Translator").slots["skip_language"] == "Korean"
    assert store.find_agent("Word explainer").slots["skip_language"] == ""
    # A card that says what it leaves out, also "nothing", was never one from before.
    store.save(old_card("Mine", "Translate the text into Korean.", skip_language=""))
    store.save(old_card("Theirs", "Translate the text into Korean.", skip_language="English"))
    parts.migrate()
    assert store.find_agent("Mine").slots["skip_language"] == ""
    assert store.find_agent("Theirs").slots["skip_language"] == "English"


def test_only_cards_that_work_on_highlights_are_given_it(home):
    chat = Agent("Chat one", CUSTOM, {"instruction": "Translate the text into Korean.", "when": IN_CHAT, "name": "Chat one"})
    store.save(chat)
    store.save(Agent("Newer card", CUSTOM, slots_for(home, NEW_FILE, NOTE, name="Newer card",
                                                     instruction="Translate each file's first line into Korean.")))
    store.save(Agent("Manuals", DOCUMENTS_QA, {"folder": str(home / "Documents"), "name": "Manuals"}))
    assert parts.migrate() == []
    assert store.find_agent("Chat one").slots == chat.slots
    assert not any("skip_language" in agent.slots for agent in store.list_agents())


def test_the_first_kind_of_helper_there_was_becomes_a_card_that_says_what_it_leaves_out(home):
    store.save(Agent("Korean translator", "translate_selection", {"language": "Korean", "show": CLIPBOARD,
                                                                  "name": "Korean translator"}))
    store.save(Agent("Spanish translator", "translate_selection", {"language": "Spanish", "name": "Spanish translator"}))
    store.save(Agent("Plain", "translate_selection", {"name": "Plain"}))
    (home / "data" / "folderwatch_state.json").write_text(json.dumps({"on": ["Somebody else"]}), encoding="utf-8")
    assert sorted(parts.migrate()) == ["Korean translator", "Plain", "Spanish translator"]
    korean = store.find_agent("Korean translator")
    assert korean.blueprint == CUSTOM
    assert korean.slots == {"instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": CLIPBOARD,
                            "keep": UNTIL_UNHIGHLIGHT, "skip_language": "Korean", "name": "Korean translator"}
    assert store.find_agent("Spanish translator").slots["skip_language"] == ""  # no text can be told to be in it
    assert store.find_agent("Spanish translator").slots["instruction"] == "Translate the text into Spanish."
    assert store.find_agent("Plain").slots["skip_language"] == "English"  # the language it had when it said none
    assert state(home, "folderwatch_state.json")["on"] == ["Somebody else"]
    assert parts.migrate() == []  # only once


def test_only_the_part_that_reads_old_cards_reads_a_rule_for_a_language():
    """The old convention lives in one private helper, and nothing else in the catalog may
    look into a rule to find out what kind of helper it is."""
    source = Path(parts.__file__).read_text(encoding="utf-8")
    old = source[source.index("# ------------------------------------------------------------------ old agents"):
                 source.index("# ------------------------------------------------------------------ small helpers")]
    rest = source.replace(old, "")
    assert "_old_skip" in old and "language_in(" in old
    for word in ("language_in(", "_OLD_SAID_SO", "_old_skip"):
        assert word not in rest, word
    # (The module that tells languages apart is called that; its name is no knowledge of a helper.)
    assert not re.search(r"translat|번역", re.sub(r"quick[./]translate", "", rest), re.IGNORECASE)
    assert parts._old_skip("Translate the text into Korean.") == "Korean"
    assert parts._old_skip("Explain this English word in simple Korean.") == ""
    assert parts._old_skip(None) == ""
