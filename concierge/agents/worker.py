"""The one step the built-in model takes for an item of a card.

Every card that works on files is run the same way: for each file the small built-in
model reads the user's rule and what could be read of the file, and fills one small form.
Which folder the file goes into (CHOOSE), or what to write about it (WRITE). It knows
nothing else: not the conversation the rule came from, not what the agent is called.
Code does everything around it (folderwatch.py: reading the file, moving it, the record),
and decides what the form may say: a choice that isn't on the form's list is "not sure",
and whether a folder's name is one that exists or a new one is worked out here, never
asked of the model.

These are pure functions. They read no file and know no model: the caller hands in `ask`,
which puts a note, the item and a schema to a model and returns the filled form. The note
for choosing among named folders is kept word for word as it was measured (see the
numbers above it); a change to it is a change to measure again.

Text that is highlighted or sent in the chat is not done here: that stays
recipe.run_instruction.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..quick.translate import LANGUAGES, language_in, looks_like
from . import parts

# What a file's form can say besides a folder's name. They are the form's own words, so the
# note and the choice the model is given always agree.
LEAVE, UNSURE, FILE_IT = "Leave it where it is", "Not sure", "Put it in a folder"
READ_CHARS = 3000  # how much of a file the model reads to tell what it is
MAX_WHAT = 120  # "what this file is, in a few plain words": a line of the record, not a paragraph
MAX_NOTE = 2000  # what one file may add to a notes file

# Measured with Noir's own 4B model on 24 made-up files of many kinds and two rules, one
# terse and one that spells out what stays, each run twice (about 0.3 s a file on a quiet
# graphics card). On 13 Nov 2026 this note got 22 and 21 of 24 right. Its last sentence then
# read "... a bill, a form or a list that only mentions a subject is not material about
# that subject": the one agent there used to be, speaking. On 20 Nov 2026 five endings were
# run the same day, the files read by FolderWatch and judged through choose():
#   that sentence as it was                                              21, 21 | 21, 21
#   "... a file that only mentions something the rule names is not that thing"  23, 23 | 20, 20
#   only its first half ("... never by a word that happens to appear in it.")  23, 23 | 20, 20
#   the sentence below                                                   23, 23 | 21, 21
#   no last sentence at all                                              22, 22 | 20, 20
# So the sentence below, which knows no subject and no kind of document, does better with
# the terse rule and as well with the full one. Every miss in every run was a file moved
# that should have stayed (a paper that lists what the rule names; a script and a data
# file taken for material of the same kind).
CHOOSE_NOTE = (
    "One file has arrived on the user's computer. Decide what happens to it by following the user's rule, and "
    "nothing else.\n"
    "\n"
    "THE USER'S RULE\n"
    "{rule}\n"
    "\n"
    "WHERE IT CAN GO\n"
    "{places}\n"
    f"- {LEAVE}: the rule says a file like this stays, or it belongs in none of the places above.\n"
    f"- {UNSURE}: what you were given does not tell you.\n"
    "{examples}\n"
    'Fill in the form in order. First "what": what this file is, in a few plain words (the kind of thing it is, '
    'and what it is for). Then "choice".{folder}\n'
    "Go by what the file is as a whole, never by a word that happens to appear in it: a file that only mentions a "
    "thing is not a file of that thing."
)
# A card that goes by names alone gets this same note, with the file's name as all it is
# given. A last line of its own was tried for it on 19 Nov 2026 ("Only the file's name is
# given, on purpose ... Go by what the name says"), since the line above could be read as
# arguing against the name. On 24 made-up names, with two rules and each run twice with
# Noir's own model, the note as it then was got 24 and 23 right, and its one miss left a
# file where it was. With the line for names it got 24 and 23 too, but its one miss moved a
# water bill into a folder. So there is one note. When its last sentence was changed (20
# Nov 2026) the two were held against each other by names alone as well, on the names of the
# 24 files above, most of which say little: with the terse rule neither moved a file it
# should not have (the old one left 6 it could have placed, the new one 7); with the full
# rule the old one moved 4 it should not have, the new one 3.

# When it may make folders, the form asks only for a folder's name. Asked to pick between
# the folders there were and "a new folder", a small model took an existing one every time.
# And with the folders listed under "Use one of them when the file belongs there", it did
# much the same. Measured on 25 made-up files with Noir's own model (20 Nov 2026), rule:
# "a folder named after the client it is for; a file that is not for a client stays". The
# first folder it made was for a hotel booking, which is no client's, and the four other
# files it moved all went into that folder: 5 moved, 5 wrong, and three files of one
# client stayed where they were. With no list at all, 12 files went into 10 folders, the
# same client under two names and six files moved that were nobody's. With the wording
# below, 5 moved: both files of one client together under the client's name, one of the
# other's under its name, and one moved that should have stayed. Two other rules (by
# kind of paper, by month) came out much the same all three ways, with the wording below
# no longer filing a photo that has no date in it under a month.
OPEN_PLACES = (
    "In a folder, named the way the rule says. Work out from the file alone which name the rule gives its folder. "
    "The folders made so far are listed only so that the same name is spelled the same way:\n"
    "{folders}\n"
    "A file goes into one of them only when that is the very name the rule gives it; otherwise give the new name."
)
NONE_YET = "(none yet)"
OPEN_FOLDER = f' Then "folder": the folder\'s name when the choice is "{FILE_IT}", and nothing otherwise.'
TOLD_BEFORE = "WHAT THE USER TOLD YOU BEFORE"
# Writing about a file is two small forms: first whether the rule asks for anything about
# this file, then the note. One form could not hold both. Measured with Noir's own 4B
# model, through FolderWatch, on six made-up files of six kinds with five rules and on
# five contracts with one (20 Nov 2026; 35 notes in all, each wording the same day):
#   one form, "in the file's own language unless the rule names another" (as it was):
#     with an English rule 3 of 6 notes about English files came out in Russian; with a
#     rule that says "write nothing about any other file", 3 of 5 such files were written
#     about; with a rule in Korean, 3 notes in English and the rule itself copied out once
#   one form with a field for the decision before the note, the language said by name:
#     the decision held (1 wrong of 6), but with the language named it chose "nothing" for
#     files the rule did ask about: 5 of 6 with the Korean rule
#   one form, no decision, the language by name, "the whole text the rule asks for":
#     lines copied out of the file in place of a note (5 of 6 with a rule that asked for
#     the main points), and the rule handed back where nothing was to be written (3 of 5)
#   one form, no decision, the language by name, "in your own words, never lines copied
#     out of the file" (the note below): 29 of 29 notes real notes in the right language,
#     but under the rule that says to write nothing about other files, all 5 written about
#   the two forms below: 32 of 35 as the rule says. The three: a contract under which she
#     is paid taken for something that asks her to pay, and a script twice given nothing.
# Which language to write in is worked out in code and said by name (_language): told "in
# the language the rule is written in", the model wrote English under a Korean rule.
ASK_FIRST = (
    "One file has arrived on the user's computer. The user's rule says what is to be written about their files. "
    "Decide whether the rule asks for anything to be written about this file.\n"
    "\n"
    "THE USER'S RULE\n"
    "{rule}\n"
    "\n"
    'Fill in the form in order. First "what": what this file is, in a few plain words. Then "write": "{write}" when '
    'the rule asks for something to be written about a file like this; "{nothing}" only when the rule itself says '
    "that nothing is to be written about a file like this. A rule that does not speak of leaving any file out asks "
    "for every file to be written about."
)
WRITE_IT, NOTHING = "Write about it", "Nothing to write"
ASK_SCHEMA = {"type": "object", "properties": {"what": {"type": "string"}, "write": {"enum": [WRITE_IT, NOTHING]}},
              "required": ["what", "write"]}
WRITE_NOTE = (
    "One file has arrived on the user's computer. Write what the user's rule asks for about this file, and nothing "
    "else.\n"
    "\n"
    "THE USER'S RULE\n"
    "{rule}\n"
    "\n"
    'Fill in the form in order. First "what": what this file is, in a few plain words. That is for the record '
    'only: it is not part of what you write. Then "note": what the rule asks for about this file, in your own '
    "words, never lines copied out of the file, with no heading and no bullet marks. Write it {language}, whatever "
    "language the file itself is in. Leave it empty only when the rule itself says that nothing is to be written "
    "about a file like this."
)
WRITE_SCHEMA = {"type": "object", "properties": {"what": {"type": "string"}, "note": {"type": "string"}},
                "required": ["what", "note"]}
# What the note says of the language when code can't tell which one the rule is in.
THE_RULES_OWN = "in the language the rule is written in"
# How much of a note's words must be the rule's own words for it to be the rule said again,
# and how many words a note must have before that is asked of it.
RULE_AGAIN, RULE_AGAIN_WORDS = 0.8, 5
# Words of the form's own note, which a small model sometimes hands back in place of one.
OWN_WORDS = "fill in the form"
# A field that was to be left empty sometimes comes back holding a word for empty. That is
# no note: written into the notes file, the user would read "None" under the file's name.
NO_NOTE = re.compile(r"^\W*(n/?a|none|nothing|empty|null|no note)\W*$", re.IGNORECASE)
HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)


@dataclass(frozen=True)
class Item:
    name: str  # the file's name
    text: str  # what could be read of it ("" when nothing)
    how: str = ""  # how it was read, for the record: "", "a picture: read through <model>", "its name only"
    # The card goes by names alone, so nothing inside was looked at. It is a field of its
    # own, never worked out from `how`, whose words are for people to read.
    name_only: bool = False


@dataclass(frozen=True)
class Outcome:
    choice: str = ""  # CHOOSE: a folder name, LEAVE or UNSURE
    what: str = ""  # what the model said the item is, a few words
    new: bool = False  # CHOOSE, open: the folder does not exist yet
    text: str = ""  # WRITE on a file: what to add to the notes ("" = nothing)


# (the note, the item, the form's schema) -> the filled form, None when the model can't be reached
Ask = Callable[[str, str, dict], dict | None]


def choose(ask: Ask, rule: str, choices: Iterable[str], item: Item, open: bool = False,
           examples: Iterable[dict] = ()) -> Outcome | None:
    """Where one file goes by the user's rule: one of the folders, LEAVE or UNSURE. None
    when the model couldn't be reached. `choices`: the folders there are, by name. `open`:
    it may also make a folder, and then code, never the model, says whether the name it
    gave is a folder there is or a new one. `examples`: what the user told it before, as
    {"name", "choice"}, newest last."""
    folders = _folders(choices)
    what = {"type": "string"}
    if open:
        places = OPEN_PLACES.format(folders="\n".join(f"- {name}" for name in folders) or NONE_YET)
        schema = {"type": "object",
                  "properties": {"what": what, "choice": {"enum": [FILE_IT, LEAVE, UNSURE]}, "folder": {"type": "string"}},
                  "required": ["what", "choice", "folder"]}
    else:
        # The folders by name only: a few file names already in each, tried as a hint, made
        # the 4B model get a file wrong that it had right from the bare names.
        places = "\n".join(f"- {name}" for name in folders)
        schema = {"type": "object", "properties": {"what": what, "choice": {"enum": [*folders, LEAVE, UNSURE]}},
                  "required": ["what", "choice"]}
    note = CHOOSE_NOTE.format(rule=rule.strip(), places=places, folder=OPEN_FOLDER if open else "",
                              examples=_told(examples, None if open else folders))
    filled = ask(note, content_for(item), schema)
    if filled is None:
        return None
    if not isinstance(filled, dict):
        return Outcome(choice=UNSURE)  # not a form at all: nothing is done on the strength of it
    said = _what(filled.get("what"))
    choice = filled.get("choice")
    choice = choice.strip() if isinstance(choice, str) else ""
    if choice == LEAVE:
        return Outcome(choice=LEAVE, what=said)
    if not open:
        return Outcome(choice=choice if choice in folders else UNSURE, what=said)
    if choice != FILE_IT:
        return Outcome(choice=UNSURE, what=said)
    wanted = filled.get("folder")
    wanted = wanted if isinstance(wanted, str) else ""
    new = parts.folder_name(wanted)
    # As the model wrote it, then as it would be made: a name that only becomes a folder
    # there is once it is made safe is that folder, not a second one of the same name.
    known = parts.same_folder(wanted, folders) or parts.same_folder(new, folders)
    if known:
        return Outcome(choice=known, what=said)
    if not new or _bare(new) in {_bare(words) for words in (LEAVE, UNSURE, FILE_IT, NONE_YET)}:
        # No name, or the form's or the note's own words put where a name goes. "(none
        # yet)" is what the note says where no folder is listed: echoed back, it once
        # became a real folder of that name, with the file in it.
        return Outcome(choice=UNSURE, what=said)
    if _bare(new) in (_bare(item.name), _bare(item.name.rpartition(".")[0])):
        # The file's own name given as its folder: asked for the folder of the client a
        # file was for, the small model answered a spreadsheet that was nobody's with the
        # spreadsheet's name, and a folder of that name would have been made for it.
        return Outcome(choice=UNSURE, what=said)
    if len(new) == 1 and new.isascii() and new.isalpha():
        # A single letter is no folder's name. Only a letter of the alphabet: in Korean one
        # syllable is a whole word, and a rule may call for a folder named by a number.
        return Outcome(choice=UNSURE, what=said)
    return Outcome(choice=new, what=said, new=True)


def write_note(ask: Ask, rule: str, item: Item) -> Outcome | None:
    """What the user's rule asks to have written about one file, as `text` ("" when the
    rule asks for nothing about a file like this). None when the model couldn't be reached.
    Two small forms: whether the rule asks for anything about this file, and then the note."""
    content = content_for(item)
    first = ask(ASK_FIRST.format(rule=rule.strip(), write=WRITE_IT, nothing=NOTHING), content, ASK_SCHEMA)
    if first is None:
        return None
    if not isinstance(first, dict):
        return Outcome()
    if first.get("write") == NOTHING:
        return Outcome(what=_what(first.get("what")))
    filled = ask(WRITE_NOTE.format(rule=rule.strip(), language=_language(rule)), content, WRITE_SCHEMA)
    if filled is None:
        return None
    if not isinstance(filled, dict):
        return Outcome()
    text = _note(filled.get("note"))
    if _says_the_rule(text, rule) or OWN_WORDS in text.casefold():
        text = ""
    return Outcome(what=_what(filled.get("what")) or _what(first.get("what")), text=text)


def content_for(item: Item) -> str:
    """One file as the model is given it: its name, and the beginning of what is inside.
    For a card that goes by names alone it is the name and nothing more, as going by name
    always was. The line about nothing being readable is only for a file that was tried
    and gave nothing: it is there to make the model hold back, and said of every file of a
    card that never looks inside, it was untrue and pushed each one toward "Not sure"."""
    if item.name_only:
        return f"File name: {item.name}"
    text = item.text.strip()[:READ_CHARS]
    if text:
        return f"File name: {item.name}\n\nWhat is inside (the beginning):\n{text}"
    return f"File name: {item.name}\n\n(Nothing inside it could be read. Only its name is known.)"


def _folders(choices: Iterable[str]) -> list[str]:
    """The folders as the form lists them: each once, and none that is one of the form's own words."""
    found: dict[str, str] = {}
    for name in choices:
        name = name.strip() if isinstance(name, str) else ""
        if name and name not in (LEAVE, UNSURE, FILE_IT):
            found.setdefault(name, name)
    return list(found)


def _bare(words: str) -> str:
    """Words with case, spaces and marks aside: "(None yet.)" is "noneyet"."""
    return re.sub(r"[\W_]+", "", words).casefold()


def _told(examples: Iterable[dict], folders: list[str] | None) -> str:
    """What the user told it before, for the note: the newest few, and (with a fixed list
    of folders) only the ones whose folder is still on the list."""
    lines = []
    for example in examples or ():
        if not isinstance(example, dict):
            continue
        name, choice = example.get("name"), example.get("choice")
        if not (isinstance(name, str) and isinstance(choice, str)):
            continue
        name, choice = name.strip(), choice.strip()
        if not name or not choice or (folders is not None and choice != LEAVE and choice not in folders):
            continue
        lines.append(f"- {name}: {choice}")
    lines = lines[-parts.MAX_EXAMPLES:]
    return f"\n{TOLD_BEFORE}\n" + "\n".join(lines) + "\n" if lines else ""


def _language(rule: str) -> str:
    """The language a note is written in, as the note for the model says it: the one the
    rule asks for by name ("in Korean"), else the one the rule itself is written in, when
    its letters tell (quick/translate.py). Said by name, because "the language the rule is
    written in" was not followed: a small model wrote English under a Korean rule."""
    named = language_in(rule, target_only=True)
    if not named and any(letter.isalpha() for letter in rule):
        named = next((name for name in LANGUAGES if looks_like(rule, name)), None)
    return f"in {named}" if named else THE_RULES_OWN


def _says_the_rule(note: str, rule: str) -> bool:
    """Whether a note only says the rule again. Asked to leave the note empty for a file
    the rule wants nothing written about, the small model sometimes hands the rule back
    instead, word for word or nearly; in the notes file that would stand under the file's
    name as if it were about the file."""
    words = re.findall(r"[^\W_]+", note.casefold())
    if len(words) < RULE_AGAIN_WORDS:
        return False
    rules = set(re.findall(r"[^\W_]+", rule.casefold()))
    return sum(word in rules for word in words) >= RULE_AGAIN * len(words)


def _what(value: object) -> str:
    """What the model said the file is, as a few words on one line. It is read in the
    middle of a line ("the rule leaves it: a phone bill"), so an article it began with a
    capital begins small; any other word may be a name and is left as it came."""
    text = re.sub(r"\s+", " ", value if isinstance(value, str) else "").strip().strip("\"'“”")
    text = re.sub(r"^(An?|The) ", lambda found: found.group(0).lower(), text)
    return text[:MAX_WHAT].rstrip(" .")


def _note(value: object) -> str:
    """The note as it goes into the notes file: no heading marks (each note already sits
    under the file's name as its heading), no empty stretches, not endless."""
    text = value.replace("\r\n", "\n") if isinstance(value, str) else ""
    text = HEADING.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if NO_NOTE.match(text):
        return ""
    if len(text) > MAX_NOTE:
        # Cut back to the end of a sentence when one is near the end, else to the end of a
        # word, else where the room ends. Never further back than a third: cut at the last
        # sentence end wherever it was, a note whose only full stop came after its first
        # sentence lost everything but that sentence.
        cut = text[:MAX_NOTE]
        least = MAX_NOTE - MAX_NOTE // 3
        end = max(cut.rfind(". "), cut.rfind("\n")) + 1
        if end < least:
            end = cut.rfind(" ")
        text = (cut[:end] if end >= least else cut).rstrip()
    return text
