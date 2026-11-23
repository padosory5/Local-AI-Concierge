"""The one step the built-in model takes for a file (agents/worker.py): the form it is
handed, the note it reads, and what code makes of whatever comes back."""

from __future__ import annotations

import pytest

from concierge.agents import parts, worker
from concierge.agents.worker import FILE_IT, LEAVE, READ_CHARS, UNSURE, Item, Outcome, choose, content_for, write_note

RULE = "Anything about the boat goes in Boat, plant lists go in Garden. Leave bills where they are."
FILE = Item("engine-service.pdf", "Service record for the outboard engine, 40 hours.")


class Model:
    """A pretend model: fills the form it is handed from the answers it was made with, and
    keeps what it was asked."""

    def __init__(self, **answers):
        self.answers = answers
        self.asked: list[tuple[str, str, dict]] = []

    def __call__(self, note: str, content: str, schema: dict) -> dict:
        self.asked.append((note, content, schema))
        return {key: self.answers.get(key, "") for key in schema["properties"]}

    @property
    def note(self) -> str:
        return self.asked[-1][0]

    @property
    def schema(self) -> dict:
        return self.asked[-1][2]


def says(reply):
    """A model that answers with this, whatever it is asked."""
    return lambda note, content, schema: reply


# ------------------------------------------------------------------ choosing among named folders


def test_the_form_for_named_folders():
    model = Model(what="a service record", choice="Boat")
    assert choose(model, RULE, ["Boat", "Garden"], FILE) == Outcome(choice="Boat", what="a service record")
    assert model.schema == {"type": "object",
                            "properties": {"what": {"type": "string"}, "choice": {"enum": ["Boat", "Garden", LEAVE, UNSURE]}},
                            "required": ["what", "choice"]}
    # What it is comes first, so the choice follows from it rather than the other way round.
    assert list(model.schema["properties"]) == ["what", "choice"]
    assert model.asked[0][1] == content_for(FILE)


def test_the_note_for_named_folders_is_the_one_that_was_measured():
    model = Model(what="a service record", choice="Boat")
    choose(model, f"  {RULE}\n", ["Boat", "Garden"], FILE)
    assert model.note == (
        "One file has arrived on the user's computer. Decide what happens to it by following the user's rule, and "
        "nothing else.\n"
        "\n"
        "THE USER'S RULE\n"
        f"{RULE}\n"
        "\n"
        "WHERE IT CAN GO\n"
        "- Boat\n"
        "- Garden\n"
        "- Leave it where it is: the rule says a file like this stays, or it belongs in none of the places above.\n"
        "- Not sure: what you were given does not tell you.\n"
        "\n"
        'Fill in the form in order. First "what": what this file is, in a few plain words (the kind of thing it is, '
        'and what it is for). Then "choice".\n'
        "Go by what the file is as a whole, never by a word that happens to appear in it: a file that only mentions "
        "a thing is not a file of that thing.")
    # Nothing in it knows a subject or a kind of document: the sentence it used to end with did.
    for word in ("bill", "form or a list", "subject", "material"):
        assert word not in worker.CHOOSE_NOTE, word
    assert (LEAVE, UNSURE, FILE_IT) == ("Leave it where it is", "Not sure", "Put it in a folder")


def test_it_may_leave_a_file_or_not_be_sure():
    assert choose(Model(what="a phone bill", choice=LEAVE), RULE, ["Boat"], FILE) == Outcome(choice=LEAVE, what="a phone bill")
    assert choose(Model(what="can't tell", choice=UNSURE), RULE, ["Boat"], FILE) == Outcome(choice=UNSURE, what="can't tell")


@pytest.mark.parametrize("answer", ["Shed", "boat", "A new folder", "", None, 7, ["Boat"], FILE_IT])
def test_a_choice_that_is_not_on_the_form_is_not_sure(answer):
    assert choose(Model(what="a thing", choice=answer), RULE, ["Boat", "Garden"], FILE) == Outcome(choice=UNSURE, what="a thing")


def test_a_choice_with_spaces_around_it_is_still_that_choice():
    assert choose(says({"what": "a list of plants", "choice": " Garden \n"}), RULE, ["Boat", "Garden"], FILE).choice == "Garden"


def test_a_model_that_cannot_be_reached_is_said_so_not_guessed():
    assert choose(says(None), RULE, ["Boat"], FILE) is None
    assert choose(says(None), RULE, ["Boat"], FILE, open=True) is None
    assert write_note(says(None), RULE, FILE) is None


@pytest.mark.parametrize("junk", ["Boat", ["Boat"], 3, {}, {"choice": {"folder": "Boat"}}, {"what": ["a", "b"]}])
def test_junk_instead_of_a_form_moves_nothing(junk):
    for open in (False, True):
        outcome = choose(says(junk), RULE, ["Boat"], FILE, open=open)
        assert outcome.choice == UNSURE and outcome.what == "" and not outcome.new


def test_what_it_said_the_file_is_becomes_a_few_words_on_one_line():
    outcome = choose(says({"what": '  "A service record\n for an engine."  ', "choice": "Boat"}), RULE, ["Boat"], FILE)
    # It is read in the middle of a line ("the rule leaves it: a service record ..."), so an
    # article it began with a capital begins small.
    assert outcome.what == "a service record for an engine"
    for began, reads in (("An engine's record.", "an engine's record"), ("The harbour's letter", "the harbour's letter")):
        assert choose(says({"what": began, "choice": "Boat"}), RULE, ["Boat"], FILE).what == reads
    # Any other first word may be a name, and is left as it came.
    for name in ("Anna's mooring bill", "Aland ferry timetable", "Theatre tickets"):
        assert choose(says({"what": name, "choice": "Boat"}), RULE, ["Boat"], FILE).what == name
    long = choose(says({"what": "word " * 200, "choice": "Boat"}), RULE, ["Boat"], FILE)
    assert len(long.what) <= worker.MAX_WHAT and not long.what.endswith(" ")
    assert choose(says({"what": 12, "choice": "Boat"}), RULE, ["Boat"], FILE) == Outcome(choice="Boat")


def test_folders_are_listed_once_and_never_under_the_forms_own_words():
    model = Model(what="x", choice=LEAVE)
    choose(model, RULE, ["Boat", " Boat ", "", LEAVE, UNSURE, FILE_IT, "Garden", None], FILE)
    assert model.schema["properties"]["choice"]["enum"] == ["Boat", "Garden", LEAVE, UNSURE]
    assert model.note.count("- Boat\n") == 1


def test_with_no_folder_named_it_can_only_leave_the_file():
    model = Model(what="x", choice=UNSURE)
    assert choose(model, RULE, [], FILE).choice == UNSURE
    assert model.schema["properties"]["choice"]["enum"] == [LEAVE, UNSURE]


def test_a_rule_with_braces_in_it_is_read_as_written():
    model = Model(what="x", choice="Boat")
    choose(model, "Files named {year}-{month} go in Boat.", ["Boat"], FILE, open=True)
    assert "Files named {year}-{month} go in Boat." in model.note
    write_note(model, "Write {nothing} odd.", FILE)
    assert "Write {nothing} odd." in model.note


# ------------------------------------------------------------------ when it may make folders


def test_the_form_when_it_may_make_folders():
    model = Model(what="a service record", choice=FILE_IT, folder="Boat")
    assert choose(model, RULE, ["Boat", "Garden"], FILE, open=True) == Outcome(choice="Boat", what="a service record")
    assert model.schema == {"type": "object",
                            "properties": {"what": {"type": "string"}, "choice": {"enum": [FILE_IT, LEAVE, UNSURE]},
                                           "folder": {"type": "string"}},
                            "required": ["what", "choice", "folder"]}
    assert list(model.schema["properties"]) == ["what", "choice", "folder"]
    # The folders are in the note, never on the form: asked to pick between the folders
    # there were and "a new folder", a small model took an existing one every time.
    assert "Boat" not in str(model.schema)
    assert model.note.startswith("One file has arrived on the user's computer. Decide what happens to it by following "
                                 "the user's rule, and nothing else.\n\nTHE USER'S RULE\n" + RULE + "\n\n")
    # The folders there are stand in the note for their spelling only: listed as places to
    # choose among, the first folder that was made became the home of every file moved.
    assert ("WHERE IT CAN GO\n"
            "In a folder, named the way the rule says. Work out from the file alone which name the rule gives its "
            "folder. The folders made so far are listed only so that the same name is spelled the same way:\n"
            "- Boat\n"
            "- Garden\n"
            "A file goes into one of them only when that is the very name the rule gives it; otherwise give the new "
            "name.\n"
            "- Leave it where it is: the rule says a file like this stays, or it belongs in none of the places above.\n"
            "- Not sure: what you were given does not tell you.\n") in model.note
    assert 'Then "choice". Then "folder": the folder\'s name when the choice is "Put it in a folder", and nothing otherwise.\n' in model.note
    assert model.note.endswith("a file that only mentions a thing is not a file of that thing.")


def test_with_no_folders_yet_the_note_says_so():
    model = Model(what="a plant list", choice=FILE_IT, folder="Garden")
    assert choose(model, RULE, [], FILE, open=True) == Outcome(choice="Garden", what="a plant list", new=True)
    assert "spelled the same way:\n(none yet)\nA file goes into one of them only when" in model.note


def test_the_files_own_name_is_no_folder_for_it():
    """Asked for the folder of the client a file was for, the small model answered a
    spreadsheet that was nobody's with the spreadsheet's own name."""
    budget = Item("budget_2026.xlsx", "Household budget 2026")
    for name in ("budget_2026.xlsx", "budget 2026", "Budget_2026"):
        outcome = choose(Model(what="a budget", choice=FILE_IT, folder=name), RULE, ["Boat"], budget, open=True)
        assert outcome == Outcome(choice=UNSURE, what="a budget")
    kept = choose(Model(what="a budget", choice=FILE_IT, folder="Budgets"), RULE, ["Boat"], budget, open=True)
    assert kept == Outcome(choice="Budgets", what="a budget", new=True)


def test_code_decides_whether_the_folder_is_one_there_is_or_a_new_one():
    known = ["PHYS122", "Garden plans"]
    pick = lambda folder: choose(Model(what="x", choice=FILE_IT, folder=folder), RULE, known, FILE, open=True)
    assert pick("PHYS122") == Outcome(choice="PHYS122", what="x")
    assert pick("phys 122") == Outcome(choice="PHYS122", what="x")  # the same folder, said another way
    assert pick("Plans for the garden") == Outcome(choice="Garden plans", what="x")  # shares its telling words
    assert pick("Job applications") == Outcome(choice="Job applications", what="x", new=True)
    assert pick("PHYS 121") == Outcome(choice="PHYS 121", what="x", new=True)  # not the folder it resembles
    assert pick("  Tax: 2026/returns?  ") == Outcome(choice="Tax 2026 returns", what="x", new=True)  # safe to make


@pytest.mark.parametrize("folder, known", [
    ("PHYS 121", ["PHYS 122"]), ("Physics 121", ["Physics 122"]), ("Taxes 2026", ["Taxes 2025"]),
    ("Travel 2026", ["Tax 2026"]), ("Invoices 2026", ["Receipts 2026"]), ("Client Jones", ["Client Smith"]),
    ("Client Jones", ["Client"]), ("Folder 13", [f"Folder {n}" for n in range(1, 13)]),
])
def test_a_new_folder_the_rule_calls_for_is_made_not_swapped_for_one_that_resembles_it(folder, known):
    """One shared word once made a new name "mean" a folder there was: the file went into a
    different folder, and the one the rule asked for was never made."""
    model = Model(what="x", choice=FILE_IT, folder=folder)
    assert choose(model, RULE, known, FILE, open=True) == Outcome(choice=folder, what="x", new=True)


def test_a_name_that_is_a_folder_there_is_once_made_safe_is_that_folder():
    # "C++" is made as "C": with a folder C there, that is the folder, not a new one of the same name.
    pick = lambda folder, known: choose(Model(what="x", choice=FILE_IT, folder=folder), RULE, known, FILE, open=True)
    assert pick("C++", ["C"]) == Outcome(choice="C", what="x")
    assert pick("C++", ["C", "C++"]) == Outcome(choice="C++", what="x")  # the user's own folder of that name
    assert pick("Tax: 2026?", ["Tax 2026"]) == Outcome(choice="Tax 2026", what="x")


@pytest.mark.parametrize("folder", ["", "   ", "?", "..", "x", "Q", None, 5, FILE_IT, LEAVE, "not sure"])
def test_no_folder_name_means_not_sure(folder):
    outcome = choose(Model(what="x", choice=FILE_IT, folder=folder), RULE, ["Boat"], FILE, open=True)
    assert outcome == Outcome(choice=UNSURE, what="x")


@pytest.mark.parametrize("folder", ["책", "일", "7", "é", "AB"])
def test_a_short_name_that_is_a_word_or_a_number_is_a_folders_name(folder):
    # Only a single letter of the alphabet is refused. In Korean one syllable is a whole
    # word, and refused by its length, a folder so named could be used but never made.
    outcome = choose(Model(what="x", choice=FILE_IT, folder=folder), RULE, ["Boat"], FILE, open=True)
    assert outcome == Outcome(choice=folder, what="x", new=True)
    assert choose(Model(what="x", choice=FILE_IT, folder=folder), RULE, [folder], FILE, open=True) == Outcome(choice=folder, what="x")


def test_leaving_and_not_being_sure_ignore_any_folder_given():
    assert choose(Model(what="a bill", choice=LEAVE, folder="Boat"), RULE, ["Boat"], FILE, open=True) == Outcome(choice=LEAVE, what="a bill")
    assert choose(Model(what="?", choice=UNSURE, folder="Boat"), RULE, ["Boat"], FILE, open=True) == Outcome(choice=UNSURE, what="?")
    # A folder's name where the choice goes is not on the form either.
    assert choose(Model(what="x", choice="Boat", folder="Boat"), RULE, ["Boat"], FILE, open=True) == Outcome(choice=UNSURE, what="x")


# ------------------------------------------------------------------ what the user told it before


def test_what_the_user_told_it_before_is_in_the_note():
    model = Model(what="x", choice="Boat")
    told = [{"name": "winter-cover.pdf", "choice": "Boat"}, {"name": "phone-june.pdf", "choice": LEAVE}]
    choose(model, RULE, ["Boat", "Garden"], FILE, examples=told)
    assert ("- Not sure: what you were given does not tell you.\n"
            "\n"
            "WHAT THE USER TOLD YOU BEFORE\n"
            "- winter-cover.pdf: Boat\n"
            "- phone-june.pdf: Leave it where it is\n"
            "\n"
            "Fill in the form in order.") in model.note


def test_with_nothing_told_there_is_no_such_heading():
    model = Model(what="x", choice="Boat")
    for examples in ((), [], None, [{"name": "", "choice": "Boat"}], ["junk", {"name": "a.pdf"}, {"choice": "Boat"}]):
        choose(model, RULE, ["Boat"], FILE, examples=examples)
        assert worker.TOLD_BEFORE not in model.note
        assert "does not tell you.\n\nFill in the form in order." in model.note


def test_an_example_for_a_folder_that_is_no_longer_a_choice_is_left_out():
    model = Model(what="x", choice="Boat")
    told = [{"name": "old.pdf", "choice": "Shed"}, {"name": "new.pdf", "choice": "Boat"}]
    choose(model, RULE, ["Boat"], FILE, examples=told)
    assert "new.pdf: Boat" in model.note and "old.pdf" not in model.note
    choose(model, RULE, ["Boat"], FILE, open=True, examples=told)  # it may make folders: Shed could be made again
    assert "- old.pdf: Shed\n- new.pdf: Boat\n" in model.note


def test_only_the_newest_examples_are_told():
    model = Model(what="x", choice="Boat")
    told = [{"name": f"file{n}.pdf", "choice": "Boat"} for n in range(parts.MAX_EXAMPLES + 3)]
    choose(model, RULE, ["Boat"], FILE, examples=told)
    listed = [line for line in model.note.splitlines() if line.startswith("- file")]
    assert listed == [f"- file{n}.pdf: Boat" for n in range(3, parts.MAX_EXAMPLES + 3)]


# ------------------------------------------------------------------ writing about a file


def test_the_form_and_the_note_for_writing_about_a_file():
    model = Model(what="a service record", note="The engine was serviced at 40 hours.")
    rule = "Say in one line what the file is. Write nothing about pictures."
    assert write_note(model, rule, FILE) == Outcome(what="a service record", text="The engine was serviced at 40 hours.")
    assert model.schema == {"type": "object", "properties": {"what": {"type": "string"}, "note": {"type": "string"}},
                            "required": ["what", "note"]}
    assert list(model.schema["properties"]) == ["what", "note"]
    assert model.note == (
        "One file has arrived on the user's computer. Write what the user's rule asks for about this file, and "
        "nothing else.\n\nTHE USER'S RULE\n" + rule + "\n\n"
        "Fill in the form in order. First \"what\": what this file is, in a few plain words. That is for the record "
        "only: it is not part of what you write. Then \"note\": what the rule asks for about this file, in your own "
        "words, never lines copied out of the file, with no heading and no bullet marks. Write it in English, whatever "
        "language the file itself is in. Leave it empty only when the rule itself says that nothing is to be written "
        "about a file like this.")
    assert model.asked[0][1] == model.asked[1][1] == content_for(FILE)
    # Before the note, a form of its own for whether the rule asks for anything about this file:
    # one form could not hold both (see the numbers above the notes in worker.py).
    first, schema = model.asked[0][0], model.asked[0][2]
    assert first == (
        "One file has arrived on the user's computer. The user's rule says what is to be written about their files. "
        "Decide whether the rule asks for anything to be written about this file.\n\nTHE USER'S RULE\n" + rule + "\n\n"
        "Fill in the form in order. First \"what\": what this file is, in a few plain words. Then \"write\": \"Write "
        "about it\" when the rule asks for something to be written about a file like this; \"Nothing to write\" only "
        "when the rule itself says that nothing is to be written about a file like this. A rule that does not speak "
        "of leaving any file out asks for every file to be written about.")
    assert schema == {"type": "object", "properties": {"what": {"type": "string"},
                                                       "write": {"enum": ["Write about it", "Nothing to write"]}},
                      "required": ["what", "write"]}


def test_a_file_the_rule_asks_nothing_about_is_never_put_to_the_second_form():
    model = Model(what="a picture", write=worker.NOTHING, note="A picture of a boat.")
    assert write_note(model, RULE, FILE) == Outcome(what="a picture", text="")
    assert len(model.asked) == 1
    # Anything else in that field is no "nothing": the note is asked for.
    for said in (worker.WRITE_IT, "", "maybe", None):
        model = Model(what="a letter", write=said, note="A letter about the mooring.")
        assert write_note(model, RULE, FILE) == Outcome(what="a letter", text="A letter about the mooring.")
        assert len(model.asked) == 2


def test_a_note_that_hands_the_forms_own_words_back_is_no_note():
    handed = 'Say what it is.\n\nFill in the form in order. First "what": what this file is, in a few plain words.'
    assert write_note(says({"what": "a trip plan", "note": handed}), RULE, FILE) == Outcome(what="a trip plan", text="")


@pytest.mark.parametrize("rule, said", [
    ("Say in one line what the file is.", "Write it in English, whatever"),
    ("각 파일이 무엇인지 한 줄로 적어 주세요.", "Write it in Korean, whatever"),
    ("Say in one line, in Korean, what the file is.", "Write it in Korean, whatever"),  # the one the rule asks for
    ("각 파일이 무엇인지 영어로 한 줄 적어 주세요.", "Write it in English, whatever"),
    ("Resume cada archivo en dos lineas.", "Write it in the language the rule is written in, whatever"),  # can't tell
    ("12 / 24", "Write it in the language the rule is written in, whatever"),
])
def test_the_language_of_a_note_is_worked_out_in_code_and_said_by_name(rule, said):
    """Told to write "in the file's own language unless the rule names another", the small
    model wrote Russian about English files under an English rule, three times in six."""
    model = Model(what="a service record", note="x")
    write_note(model, rule, FILE)
    assert said in model.note and "file's own language" not in model.note


def test_a_note_that_only_says_the_rule_again_is_no_note():
    """Asked to leave the note empty for a file the rule wants nothing written about, the
    small model handed the rule back instead, word for word."""
    rule = ("For anything that asks me to pay money, write who it is from, how much it is and by when it must be paid, "
            "in one line. Write nothing about any other file.")
    for again in (rule, rule.upper(), "Write nothing about any other file.",
                  "For anything that asks me to pay money, write who it is from and how much it is."):
        assert write_note(says({"what": "a recipe", "note": again}), rule, FILE) == Outcome(what="a recipe", text="")
    # What the rule asks for is not the rule, however many of its words it has.
    for real in ("From the water company, $149.95, to be paid by 20 November.", "It is from me.",
                 "Who it is from: the harbour office. How much it is: 40 euros. By when it must be paid: Friday."):
        assert write_note(says({"what": "a bill", "note": real}), rule, FILE).text == real


@pytest.mark.parametrize("empty", ["", "   \n ", "N/A", "none", "(nothing)", "Empty.", None, 4, ["a"]])
def test_nothing_to_write_is_nothing(empty):
    assert write_note(says({"what": "a picture", "note": empty}), RULE, FILE) == Outcome(what="a picture", text="")


def test_junk_instead_of_a_form_writes_nothing():
    for junk in ("a note", ["a note"], 3, {}):
        assert write_note(says(junk), RULE, FILE) == Outcome()


def test_a_note_is_cleaned_before_it_goes_into_the_notes_file():
    note = "## Summary\r\nThe engine was serviced.   \n\n\n\n  # Next\nOil change in spring.\n#1 on the list stays.\n"
    written = write_note(says({"what": "x", "note": note}), RULE, FILE).text
    # Each note already sits under its file's name as the heading: one of its own would break the notes file up.
    assert written == "Summary\nThe engine was serviced.\n\nNext\nOil change in spring.\n#1 on the list stays."
    assert write_note(says({"what": "x", "note": "Nothing was decided, none of it."}), RULE, FILE).text == "Nothing was decided, none of it."


def test_a_note_is_not_endless():
    long = write_note(says({"what": "x", "note": "A sentence that goes on. " * 400}), RULE, FILE).text
    assert len(long) <= worker.MAX_NOTE and long.endswith("goes on.")
    assert len(write_note(says({"what": "x", "note": "x" * 5000}), RULE, FILE).text) == worker.MAX_NOTE


def test_a_long_note_keeps_most_of_its_room_wherever_its_sentences_end():
    """Cut back to the last sentence end wherever that was, a note whose only full stop came
    after its first sentence was left with that sentence and nothing else."""
    cut = lambda note: write_note(says({"what": "x", "note": note}), RULE, FILE).text
    least = worker.MAX_NOTE - worker.MAX_NOTE // 3
    clauses = "It is a rental contract. " + ", ".join(f"clause {n} covers item {n}" for n in range(200))
    kept = cut(clauses)
    assert least <= len(kept) <= worker.MAX_NOTE and clauses.startswith(kept)
    assert clauses[len(kept)] == " " and not kept.endswith(" ")  # it stops at the end of a word
    assert cut("첫 문장입니다.\n" + "가" * 5000) == ("첫 문장입니다.\n" + "가" * 5000)[:worker.MAX_NOTE]  # no later break at all
    late = "word " * 370 + "The end is near. " + "tail " * 100  # a sentence ends in the last third: it stops there
    assert cut(late).endswith("The end is near.") and len(cut(late)) >= least


# ------------------------------------------------------------------ the file as the model is given it


def test_a_file_is_given_by_its_name_and_the_beginning_of_what_is_inside():
    assert content_for(Item("list.txt", "  tomatoes\nbeans  ")) == (
        "File name: list.txt\n\nWhat is inside (the beginning):\ntomatoes\nbeans")
    assert content_for(Item("clip.mp4", "")) == (
        "File name: clip.mp4\n\n(Nothing inside it could be read. Only its name is known.)")
    # How it was read is for the record, in words for people: the model's text never turns on it.
    assert content_for(Item("blank.txt", " \n ", how="its name only")) == content_for(Item("blank.txt", ""))
    long = content_for(Item("book.txt", "a" * (READ_CHARS + 500)))
    assert long.endswith("a" * READ_CHARS) and len(long) == len("File name: book.txt\n\nWhat is inside (the beginning):\n") + READ_CHARS
    assert READ_CHARS == 3000


def test_a_card_that_goes_by_names_alone_gives_the_name_and_nothing_else():
    """Told "(Nothing inside it could be read...)" about every file, a card that never
    looks inside was told something untrue, in the words that are there to make the model
    hold back when a read has failed."""
    by_name = Item("acme-2026-03.pdf", "", how="its name only", name_only=True)
    assert content_for(by_name) == "File name: acme-2026-03.pdf"
    assert content_for(Item("acme-2026-03.pdf", "words that were read", name_only=True)) == "File name: acme-2026-03.pdf"
    model = Model(what="a March invoice", choice="Boat")
    assert choose(model, RULE, ["Boat"], by_name) == Outcome(choice="Boat", what="a March invoice")
    assert model.asked[0][1] == "File name: acme-2026-03.pdf"
    write_note(model, RULE, by_name)
    assert model.asked[1][1] == "File name: acme-2026-03.pdf"


def test_an_item_and_an_outcome_start_empty():
    assert Item("a.txt", "words").how == "" and Item("a.txt", "words").name_only is False
    assert Outcome() == Outcome(choice="", what="", new=False, text="")
