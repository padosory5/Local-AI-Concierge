"""What an agent can be made of: the catalog of parts.

An agent is a card: WHEN it works, what it LOOKS AT, the RULE in the user's own words,
and what it does THEN. The rule is the only thing about an agent that says what it is
for, and it is data: plain sentences worked out while the user and Noir talk
(agents/designer.py), read later by the built-in model for every single item
(agents/worker.py). Everything else is picked from the parts in this file, and a part is
mechanics only: watch a folder, move a file so the move can be undone, show a bubble.

Until now every kind of agent was written by hand, with its own scripted questions and
its own judge, so Noir could only make the kinds somebody had already built, and each of
them knew one subject. Nothing here knows what any particular agent is for, and nothing
here may: no subject, no kind of document, no question that only one agent would ask.

Code owns the catalog. A model proposes a WHEN, a THEN and their settings; code checks
them against what is here (fits, settings_for, missing) and writes every line of the
card from the slots (card, describe, how), so what the user reads on a card is never a
model's wording.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .. import noir
from ..places import known_folder
from ..quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT
from ..quick.selection import MAX_CHARS as _MAX_HIGHLIGHT
from ..quick.translate import TELLABLE, language_in, looks_like
from . import store

# The id every card is saved under, and the two WHENs there were before there were cards.
# They are spelled out here, and this file takes nothing from recipe.py or builder.py:
# both of those are to get what they need from the catalog, and two files that each wait
# for the other can't be loaded at all.
CUSTOM = "custom"
WHILE_ON, IN_CHAT = "While it's switched on", "When you ask in the chat"
# What an agent that works on text, and one that answers from documents, can be tried
# with on its page.
SAMPLE_TEXT = "The committee reached a quorum, so the motion carried."
SAMPLE_QUESTION = "What are these files about?"
# These texts are what is saved in an agent's slots and what the user reads, like the
# older ones (WHILE_ON, IN_CHAT, BUBBLE...): changing one orphans the agents saved with it.
NEW_FILE = "When a new file lands in a folder"
SHOW = "Shows the result where you are"
ANSWER = "Answers in the chat"
MOVE = "Moves the file into a folder"
NOTE = "Writes about the file in a notes file"
DOCUMENTS = "Answers from the documents in a folder"
INSIDE_FILE, NAME_ONLY = "What's inside the file", "Only the file's name"
OPEN_NO, OPEN_YES = "No, only the folders named", "Yes, when the rule calls for one"
# What the built-in model does for each item: writes text, picks where a file goes, or
# answers from a search of a folder's documents (agents/runner.py).
WRITE, CHOOSE, SEARCH = "write", "choose", "search"
MAX_RULE = 600
MAX_CHOICES = 12
MAX_EXAMPLES = 8
MAX_FOLDER_NAME = 40
# The one agent that is not saved as a card: its runtime is a search index, so it keeps
# the blueprint id it always had (see DOCUMENTS).
DOCUMENTS_QA = "documents_qa"
# The places a form can name. A place is an enum, never free text, so a model can't
# misspell one or invent a path; only a new folder's own name is free.
PLACE_NAMES = ["Desktop", "Documents", "Downloads", "Pictures"]
INSIDE = "inside the watched folder"
# What a form says for a setting that may be none of its choices, to take off one that is
# known. Left empty, a setting stays as it is, so without a word for it such a setting,
# once set, could never be taken off again by talking.
NONE = "None"
# What a card that works on files can be tried with on its page: sent to it in the chat,
# it goes through what has landed.
SAMPLE_FILES = "go through the new files"
# Words that tell nothing about a folder whatever it is for: the small words of a
# sentence, and the words for the things every such card handles. A model asked for a
# folder's name sometimes says "the Boat folder" for Boat. No word here may belong to a
# subject: the list this one replaced was one agent's vocabulary, and folders named in
# those words were matched differently from everybody else's. The list is short on
# purpose, since every word on it makes two names more alike: "a" is not here ("Plan A"
# and "Plan B" are two folders), nor "to", "in" or "on" ("To do", "On hold").
STOPWORDS = {"the", "and", "for", "with", "from", "of", "my", "file", "files", "folder", "folders"}
# What no folder's name can hold on Windows, the strictest of the systems Noir runs on,
# and the longest a name can be there and on a Mac.
_NOT_IN_A_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_LONGEST_NAME = 255
# The endings a notes file can have: plain text, which a note can be added to the end of.
# Any other name gets ".md" after it, so a note is never written into a Word file or a
# spreadsheet that happens to be named.
_NOTES_ENDINGS = (".md", ".markdown", ".txt")
# A word of a folder's name: letters or digits, with any + or # that follows them, which
# are part of some names ("C++" and "C#" are not "C").
_WORD = re.compile(r"[^\W_]+[+#]*")


@dataclass(frozen=True)
class Setting:
    key: str  # the slot it is saved in
    label: str  # what the user sees ("Folder it watches")
    # "folder" (must exist) | "place" (a folder or file that may be new) | "choice" | "list" | "text" | "rule"
    type: str
    ask: str | None  # the plain question when it has to be known; None when it has a usual value
    how: str  # for the designer model: how to fill it
    choices: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True)
class Part:
    key: str  # the stored text
    kind: str  # "when" | "then"
    about: str  # one line for the designer: what it does, mechanics only
    settings: tuple[Setting, ...]
    facts: tuple[str, ...]  # true statements about how it works; each must stay true to the code
    mode: str = ""  # then-parts: WRITE, CHOOSE or SEARCH
    windows_only: bool = False


# ------------------------------------------------------------------ the settings

_PLACES = ", ".join(PLACE_NAMES)
# No example of a folder's name in any of these: given one ("like ..."), a model offered it
# to the user as if it were theirs, and a smaller one filled it in as the answer.
_AN_EXISTING_FOLDER = (f"It must be a folder that already exists. `place` when they name one of {_PLACES}; `name` for "
                       "any other existing folder, as they wrote it (its name or its full path). "
                       # Asked for something to happen in a folder they named, a model asked where on
                       # the computer that folder was, at every turn, with its name in front of it.
                       "You need not know where such a folder is, and never ask them where it is: give its name, and "
                       "the app looks for it on this computer. Both empty if they have not said.")

_WATCHED = Setting(
    "folder", "Folder it watches", "folder", "Which folder should it watch for new files?",
    "The folder whose new files it works on. " + _AN_EXISTING_FOLDER)
# The languages are the ones code can tell a text is in (quick/translate.py), and no
# others: for any other language nothing would ever be left out, and the card would say
# something untrue. They are listed in the line a model reads, because a model on this
# computer is held to the form's choices without being shown them, and one that wanted a
# language that isn't there would be made to pick another. The line names no helper: it
# is a setting any card that works on highlights can have.
_SKIP_LANGUAGE = Setting(
    "skip_language", "Leaves out text already in", "choice", None,
    "Only for a helper whose rule turns text into one language, and only when that language is one of "
    f"{', '.join(TELLABLE)}: the language its result comes out in, so text that is already in that language, which "
    "needs nothing done to it, is left alone and nothing is shown for it. "
    # A helper that was to show what sentences in one language mean in another was given
    # the language of the sentences here. Its try-out then said it does nothing with such a
    # sentence, and its card that it leaves that language out.
    "Never the language of the text it is given: set to that, it would pass over every text it is for. "
    f'When the rule is changed to give another language, this changes with it. "{NONE}" for every other helper, '
    "for any other language, and when they want such text worked on too.",
    TELLABLE, "")
_LOOKS_AT = Setting(
    "looks_at", "What it looks at", "choice", None,
    f'"{INSIDE_FILE}" is the usual one: the beginning of each file is read on this computer, so the rule can go by '
    f'what a file is. "{NAME_ONLY}" only when they say the names are enough, or that what is inside their files must '
    "not be read.",
    (INSIDE_FILE, NAME_ONLY), INSIDE_FILE)
_SHOW = Setting(
    "show", "How it shows the result", "choice", None,
    f'"{BUBBLE}" is the usual one. "{CLIPBOARD}" when they want the result ready to paste and nothing shown; '
    f'"{BOTH}" when they want it shown and ready to paste.',
    (BUBBLE, CLIPBOARD, BOTH), BUBBLE)
_KEEP = Setting(
    "keep", "How long the result stays", "choice", None,
    f'How long the bubble stays up. "{UNTIL_UNHIGHLIGHT}" is the usual one; "{FEW_SECONDS}" when they want it to go '
    "away by itself.",
    (UNTIL_UNHIGHLIGHT, FEW_SECONDS), UNTIL_UNHIGHLIGHT)
_CHOICES = Setting(
    "choices", "Folders it moves files into", "list",
    "Which folders should the files go into? Name them, or tell me it may make folders as it goes.",
    "The names of the folders a file may be moved into, separated by commas, as they said them. Names only, never a "
    "path: where those folders are kept is `into`. Empty if they have not named any; it may stay empty only when "
    f'`open` is "{OPEN_YES}".')
_OPEN = Setting(
    "open", "May it make new folders", "choice", None,
    f'"{OPEN_NO}" is the usual one: a file then goes into one of the folders they named, or stays where it is. '
    f'"{OPEN_YES}" when they want folders made as files come; the rule must then say how a new folder is named.',
    (OPEN_NO, OPEN_YES), OPEN_NO)
_INTO = Setting(
    "into", "Where those folders are kept", "place", None,
    "Where the folders it moves files into are kept. It may be a new folder, which is made for them. `place` is "
    f'"{INSIDE}" or one of {_PLACES}; `name` is a new folder to make there, or empty for none. Both empty if they '
    "have not said: the folders are then made inside the watched folder.",
    default="")
_NOTES = Setting(
    "notes", "Notes file it writes in", "place", None,
    f'Where its notes file is. `place` is "{INSIDE}" or one of {_PLACES}; `name` is the notes file\'s name when they '
    "gave one, as they said it (a name with no ending gets .md), or empty: the notes file is then named after the "
    "helper. Both empty if they have not said: it then keeps one notes file, named after the helper, inside the "
    "watched folder.",
    default="")
_READ = Setting(
    "folder", "Folder it reads", "folder", "Which folder are the documents in?",
    "The folder whose documents it answers from. " + _AN_EXISTING_FOLDER)

RULE = Setting(
    "instruction", "The rule", "rule", "What should it do, and what should it leave alone?",
    "The rule, written out for the built-in model, which reads it for every single item and knows nothing of this "
    "conversation: plain, complete sentences that stand on their own, saying what should happen to which things in "
    "the person's own terms, and what must be left alone. "
    # A rule that began "... to help the user remember what it was" gave notes that read
    # "The user must return the signed slip by Friday".
    'Never "the user" in it: what is written from a rule that says "the user" speaks of "the user" too. Where the '
    'rule has to speak of the person at all, they are "I" and "my". For a helper that works on text, say exactly what '
    'to do '
    "with the text and what to reply with, and name a language for the result only if they named one. For a helper "
    "that moves files, say which things go into which of its folders and which stay where they are. Only what is "
    # Not "where a result goes": for a helper that moves files that is the whole rule, and
    # read as a ban on naming folders in it, the rule could not say what goes where.
    "done with the item, never when it works, which folder it watches, where its folders are kept, where its notes "
    f"file is or how a result is shown: those are the other settings. At most {MAX_RULE} characters.")
NAME = Setting(
    "name", "Name", "text", None,
    "A short name for the helper, two to four words, that says what it does. The name they gave it, when they gave "
    "one.")


# ------------------------------------------------------------------ the parts
# Every fact below is told to the user by the designer, so each one must stay true to the
# code that runs the part (quick/agents.py and quick/selection.py for highlights, the
# engine for the chat, folderwatch.py and quick/tidy.py for files, agents/runner.py for
# documents). When that code changes, the fact changes with it.

WHENS: dict[str, Part] = {
    WHILE_ON: Part(
        WHILE_ON, "when",
        "It works on any text the person highlights with the mouse, in any program, for as long as it is switched on.",
        (_SKIP_LANGUAGE,),
        ("It works on Windows only, for now.",
         "While it is switched on, text highlighted with the mouse in any program goes through it. Switched off, "
         "nothing is read.",
         # The watcher drops a longer highlight without a word (quick/selection.py), so the
         # number is taken from there, never typed again here.
         f"It works on a highlight of up to {_MAX_HIGHLIGHT:,} characters. A longer one is ignored: nothing happens.",
         "In a terminal or a code editor a highlight often can't be read, and then nothing happens.",
         # (quick/agents.py, handle: looks_like says yes to a highlight with no letters in it,
         # whatever the language.)
         f"It can be set to leave out text that is already in one language, one of {', '.join(TELLABLE)}: such a "
         "highlight, and one with no letters in it, is passed over, and nothing is shown for it. Set to none, every "
         "highlight is worked on.",
         "The text is read by the built-in model on this computer. Nothing leaves the computer.",
         "It works only while Noir is running, minimized or not."),
        windows_only=True),
    IN_CHAT: Part(
        IN_CHAT, "when",
        # How it is asked is said here, where a model reads what this WHEN is: with that
        # only among the facts further down, a helper for rough notes was described as
        # working "whenever you paste your notes into the chat", twice, the second time in
        # answer to "how do I give it my notes?".
        "It works only when the person asks it: in the chat they write its name, a colon and their text, and a "
        "message that does not begin with its name is not for it. It does nothing by itself.",
        (),
        ("It does nothing until the person asks it.",)),
    NEW_FILE: Part(
        NEW_FILE, "when",
        "It works by itself on each new file that lands in one folder, for as long as it is switched on.",
        (_WATCHED, _LOOKS_AT),
        # How the files already there get their turn is said, because left at "unless the
        # person asks", a model asked about them answered that it could be set up to leave
        # them alone, and nothing more.
        ("Only files that land in the folder after it is switched on are handled by themselves. The files already "
         "there are left alone unless the person asks: right after the helper is created the app asks once "
         "whether to go through them, and they can ask for that in the chat later.",
         "A file is looked at a few seconds after it has finished arriving. A download still on its way is waited "
         "for.",
         "It reads the beginning of documents, code and other text, spreadsheets and slides, the names of the files "
         "inside a zip, and a picture or a scanned page when a model that can see is installed. A program or a "
         "recording has nothing in it that can be read.",
         # Not "it never opens a file": every new file is opened for a moment to see that no
         # program is still writing it, whatever the card looks at (folderwatch.py, _ready).
         f'With "{NAME_ONLY}" what is inside a file is never looked at: the rule is followed from the file\'s name '
         "alone.",
         # Not "by the built-in model" alone: when it can't see, a picture or a scanned page is
         # read through another model that is installed here (folderwatch.py, seer).
         "Every file is read and judged on this computer, by the built-in model (a picture or a scanned page by a "
         "model on this computer that can see, which may be another one). Nothing leaves the computer.",
         "It works while Noir is running, minimized or not, and only while it is switched on.",
         "Everything it does shows in the chores list.")),
}

THENS: dict[str, Part] = {
    SHOW: Part(
        SHOW, "then",
        "The built-in model does what the rule says with the highlighted text, and the result is shown right there: "
        "in a bubble above the text, on the clipboard, or both.",
        (_SHOW, _KEEP),
        ("The result shows in a small bubble above the highlighted text, is copied to the clipboard ready to paste, "
         "or both.",
         "A bubble stays until the text is no longer highlighted, or goes away by itself after a few seconds, "
         "whichever was chosen.",
         "It never changes the text that was highlighted."),
        mode=WRITE),
    ANSWER: Part(
        ANSWER, "then",
        "What the rule says is done with the text the person sends it, and the result is an answer in the chat.",
        (),
        ("The person asks it by writing its name, a colon and the text in the chat. The answer comes in the chat.",
         "Its answer is written by the model that answers the chat: the built-in one, unless the person picked "
         "another.",
         # The Spot offers the first few chat cards that have a rule (engine._helpers,
         # spot.MAX_HELPERS), so "may": not every one is a button there.
         "On Windows, the small card that opens when Ctrl is tapped twice may offer it as a button too. There it "
         "works on the highlighted text, always with the built-in model."),
        mode=WRITE),
    MOVE: Part(
        MOVE, "then",
        "For each file, the built-in model follows the rule and says which folder the file goes into, or that it "
        "stays where it is. Code moves the file.",
        (_CHOICES, _OPEN, _INTO),
        ("It never deletes or overwrites a file: where a name is taken, the file gets a number after its name.",
         "Every move can be undone for a week, from the chores list.",
         "A file it isn't sure about stays where it is, and the list says why.",
         "A folder is made the first time a file goes into it.",
         f'With "{OPEN_NO}" a file can only go into one of the folders named, or stay. With "{OPEN_YES}" it may also '
         "make a folder, named the way the rule says.",
         "Telling it in the chat to put a file in a folder moves the file there, and it remembers that as an "
         "example for later files."),
        mode=CHOOSE),
    NOTE: Part(
        NOTE, "then",
        "For each file, the built-in model writes what the rule asks for about it, and that is added to one notes "
        "file. The file itself is not touched.",
        (_NOTES,),
        ("It adds to the end of one notes file, under the file's name and the time.",
         "It never moves, changes or deletes the file it read.",
         "It writes nothing about a file when the rule says so.",
         # (worker._language: said to the built-in model by name, whatever the file is in.)
         "What it writes is in the language the rule is written in, whatever language a file is in, unless the "
         "rule asks for another language by name."),
        mode=WRITE),
    DOCUMENTS: Part(
        DOCUMENTS, "then",
        "It answers questions from the documents in one folder, and says which file each answer came from. It "
        "follows no rule.",
        (_READ,),
        ("It reads the PDF, Word and text files in one folder and in the folders inside it.",
         "Each answer names the file it came from and quotes the passage.",
         "It never changes, moves or deletes those files.",
         "It reads the files when it is created, and again whenever they have changed.",
         "It answers on this computer, with the built-in model."),
        mode=SEARCH),
}

# Which THEN goes with which WHEN.
FITS: dict[str, tuple[str, ...]] = {WHILE_ON: (SHOW,), IN_CHAT: (ANSWER, DOCUMENTS), NEW_FILE: (MOVE, NOTE)}


def whens(platform: str | None = None) -> list[Part]:
    """The WHENs this computer can run: highlights are read on Windows only, for now."""
    platform = platform or sys.platform
    return [part for part in WHENS.values() if platform == "win32" or not part.windows_only]


def then_of(slots: dict) -> str:
    """What a card does with its result. Cards saved before there were THENs have none: one
    that works while switched on shows its result, any other answers in the chat. (A card
    with no WHEN at all counts as switched on, as it always has.)"""
    return slots.get("then") or (SHOW if _when(slots) == WHILE_ON else ANSWER)


def fits(when: str, then: str) -> bool:
    return then in FITS.get(when, ())


def settings_for(when: str, then: str) -> list[Setting]:
    """Everything a card of this WHEN and THEN is made of: the WHEN's settings, the THEN's,
    the rule (a documents card follows none) and the name."""
    found = [*(WHENS[when].settings if when in WHENS else ()), *(THENS[then].settings if then in THENS else ())]
    return [*found, *([] if then == DOCUMENTS else [RULE]), NAME]


def all_settings() -> list[Setting]:
    """Every setting once, by its key, always in the same order: the designer's form has one
    field for each. (Two parts share the key `folder`, the folder watched and the folder
    read; both are a folder that must exist, and no card has both.)"""
    found: dict[str, Setting] = {}
    for part in [*WHENS.values(), *THENS.values()]:
        for setting in part.settings:
            found.setdefault(setting.key, setting)
    return [*found.values(), RULE, NAME]


def needed(setting: Setting) -> bool:
    """A setting the agent can't be made without: it has a question and no usual value."""
    return bool(setting.ask) and setting.default is None


def missing(slots: dict) -> list[Setting]:
    """The settings of the chosen WHEN and THEN that must be known and aren't yet. The
    folders to move files into may stay unnamed when it may make folders itself. (Whether a
    WHEN and a THEN are chosen at all is the caller's to check: see fits.)"""
    when, then = _pair(slots)
    lacking = []
    for setting in settings_for(when, then):
        if not needed(setting) or _filled(slots, setting):
            continue
        if setting.key == "choices" and slots.get("open") == OPEN_YES:
            continue
        lacking.append(setting)
    return lacking


def defaults(slots: dict) -> dict:
    """The usual values for the settings of the chosen WHEN and THEN that are still empty:
    what a card is given once nothing needed is missing."""
    when, then = _pair(slots)
    usual = {setting.key: setting.default for setting in settings_for(when, then)
             if setting.default is not None and slots.get(setting.key) in (None, "")
             and slots.get(setting.key) != setting.default}
    if then == MOVE and slots.get("open") == OPEN_YES and slots.get("choices") is None:
        usual["choices"] = ""  # no folders named, and none needed: it makes them as it goes
    return usual


def mode(slots: dict) -> str:
    """What the built-in model does for each item of this card: WRITE, CHOOSE or SEARCH."""
    then = THENS.get(then_of(slots))
    return then.mode if then else ""


def watches(agent: store.Agent) -> bool:
    """A card that works on the new files of a folder (folderwatch.py runs it)."""
    return agent.blueprint == CUSTOM and agent.slots.get("when") == NEW_FILE


def is_switchable(agent: store.Agent) -> bool:
    """Works outside the chat while switched on (rather than being asked in it)."""
    return agent.blueprint == CUSTOM and _when(agent.slots) in (WHILE_ON, NEW_FILE)


def choices_of(slots: dict) -> list[str]:
    """The folders a card may move files into, by name: none empty, none twice (case,
    spaces and marks aside). The names are the user's own, so each is kept as it was given,
    less only what no folder's name can hold: cleaned the way a model's made-up name is
    (folder_name), "C++" and "C#" both became "C", and files went into a new folder beside
    the user's real one. Every folder there is comes back, however many: at most
    MAX_CHOICES is for whoever takes a new list from the user to check, never a cut made
    here, or a card's thirteenth folder could not be chosen any more."""
    raw = slots.get("choices") or ""
    pieces = raw if isinstance(raw, (list, tuple)) else re.split(r"[,;\n]", str(raw))
    found: dict[str, str] = {}
    for piece in pieces:
        name = as_given(str(piece))
        if name and _key(name):
            found.setdefault(_key(name), name)
    return list(found.values())


def as_given(name: str) -> str:
    """A folder's name as the user gave it, less only what no folder's name can hold: the
    marks a path is written with, an end in dots or spaces, a length past what a name can
    have. An apostrophe, a plus, a hash or a bracket is part of the name. (For a name the
    built-in model makes up, see folder_name.)"""
    clean = re.sub(r"\s+", " ", _NOT_IN_A_NAME.sub(" ", name)).strip()
    return clean[:_LONGEST_NAME].rstrip(" .")


def same_name(one: str, other: str) -> bool:
    """Whether two names are one folder's name, with case, spaces and marks aside ("box-12"
    is "Box 12"). No more than that: for the folder a name may mean, see same_folder."""
    key = _key(one)
    return bool(key) and key == _key(other)


def folder_name(name: str) -> str:
    """A safe folder name from the model's words: letters, digits, spaces and a few marks."""
    clean = re.sub(r"[^\w \-&().]+", " ", name, flags=re.UNICODE).strip(" .")
    clean = re.sub(r"\s+", " ", clean)[:MAX_FOLDER_NAME].strip()
    return clean


def words_of(name: str) -> set[str]:
    """The telling words of a folder's name, in small letters: "Plans for the garden" is
    {plans, garden}. Every other word counts, in any language, and so does a single letter
    or digit: "Plan B" is not "Plan A", and "Box 1" is not "Box 13"."""
    return {word for word in _WORD.findall(name.casefold()) if word not in STOPWORDS}


def same_folder(name: str, known: list[str]) -> str | None:
    """The known folder a name means, or None when it is a folder of its own. Code decides
    this, never the model: asked to choose between a folder it had made and "a new
    folder", a small model took the existing folder every time.

    It is the folder equal to the name with case, spaces and marks aside ("box-12" means
    "Box 12"). Else the one with the same telling words in another order ("Plans for the
    garden" means "Garden plans"). Else, when the name is only some of the words of exactly
    one folder, that folder ("Garden" means "Garden plans" when no other folder is the
    garden's). Never more than that. One shared word used to be enough, and a new folder
    the rule had called for was quietly turned into a different one that was there
    already: two names with different numbers in them are two folders ("Box 12" is not
    "Box 13"), and a name that says more than a folder does is a folder of its own, or the
    one folder with a short name would become the home of everything."""
    wanted = _key(name)
    if not wanted:
        return None
    for folder in known:
        if _key(folder) == wanted:
            return folder
    mine = words_of(name)
    if not mine:
        return None
    wider = []
    for folder in known:
        theirs = words_of(folder)
        if _numbers(mine) != _numbers(theirs):
            continue
        if theirs == mine:
            return folder
        if mine < theirs:
            wider.append(folder)
    return wider[0] if len(wider) == 1 else None


def skip_language(slots: dict) -> str:
    """The language a card that works on highlights leaves out: text that is already in it
    is passed over (quick/agents.py). "" when none is set, when the card works another way,
    or when what is saved is no language code can tell a text is in."""
    language = slots.get("skip_language") or ""
    return language if _when(slots) == WHILE_ON and language in TELLABLE else ""


def leaves_out(slots: dict, text: str) -> str:
    """The language a card passes this text over for: the one it leaves out, when the text
    is already in it (or has no letters in it, so there is nothing in any language to work
    on). "" when the card works on the text. Decided here for both the code that runs a
    card on a highlight (quick/agents.py) and the try-out that shows what a card would do
    (designer.py), so the two can't come to differ."""
    language = skip_language(slots)
    return language if language and looks_like(text, language) else ""


def destination(slots: dict) -> Path:
    """Where a card's folders are kept: the place the user named, else inside the folder it
    watches."""
    return Path(slots.get("into") or slots.get("folder") or "")


def notes_path(slots: dict) -> Path:
    """The file a card's notes are added to: the one the user named, else one named after the
    agent in the folder it watches. A place that is a folder there already means a notes
    file inside it, named after the agent. Any other place is the notes file itself, and
    one named without a plain-text ending gets ".md": people say "call it Reading log" and
    rarely an ending, and taken for a folder, that name made a new folder with a file named
    after the agent inside it."""
    usual = f"{folder_name(str(slots.get('name') or '')) or 'Notes'}.md"
    given = slots.get("notes") or ""
    if not given:
        return Path(slots.get("folder") or "") / usual
    path = Path(given)
    if path.is_dir() or not path.name:
        return path / usual
    return path if path.suffix.lower() in _NOTES_ENDINGS else path.with_name(f"{path.name}.md")


def short_place(path: Path) -> str:
    """A folder the way people say it: "Downloads", "Desktop\\Sorted". The designer reads
    and says places like this, so a whole path with the user's name in it never goes to a
    model off this computer; a folder outside those places is shown as it is."""
    for place in PLACE_NAMES:
        base = known_folder(place)
        if path == base:
            return place
        if base in path.parents:
            return str(Path(place) / path.relative_to(base))
    return str(path)


def shown_place(path: Path) -> str:
    """A place as a card says it, for whoever else has to say it the same way (the designer's
    note for its model, its own lines to the user): by name when it is in one of the places
    people name, from the home folder when it is somewhere else in it, else only the
    folder's own name. Never the whole path, which has the user's name in it."""
    return _shown(path)


# ------------------------------------------------------------------ what the user reads


def card(slots: dict, model_name: str, count: int | None = None) -> tuple[str, list[str], list[str], list[str], str]:
    """(kind, reads, can do, cannot do, runs on) for events.AgentCard, every line written
    here from the slots: the model's words never reach a card. Places are shown by name,
    never as a whole path. `count`: how many files are in the folder right now, when the
    caller has counted them (the ones a documents card can read; the ones already there for
    a card that watches)."""
    when, then = _when(slots), then_of(slots)
    folder = _folder(slots)
    built_in = _built_in(model_name)
    if then == DOCUMENTS:
        now = "" if count is None else f" ({count} right now)"
        return (IN_CHAT,
                [f"The PDF, Word and text files in {folder}{now}"],
                ["Find and quote passages from those files",
                 "Answer questions about them, with the file each answer came from"],
                ["Change, move or delete files", "Read anything outside that folder", "Use the internet"],
                f"{built_in}, on this computer")
    can_do = [f"Rule: {_one_line(slots.get('instruction'))}"]
    if when == NEW_FILE:
        inside = slots.get("looks_at", INSIDE_FILE) != NAME_ONLY
        kind = f"When a new file lands in {folder}"
        if inside:
            reads = [f"Each new file in {folder}: the beginning of what's inside it, read on this computer",
                     "Documents, code, spreadsheets and slides by their words, a zip by the names inside it, a "
                     "picture or a scanned page when a model that can see is installed"]
        else:
            reads = [f"The name of each new file in {folder}, never what's inside it"]
        if count:
            reads.append(f"The {count} file{' already there is' if count == 1 else 's already there are'} left alone, "
                         "unless you ask")
        never = ["Touch files that were there before it was switched on, unless you ask",
                 "Send anything over the internet", "Work while it's switched off or Noir isn't running"]
        if then == MOVE:
            names = choices_of(slots)
            more = slots.get("open") == OPEN_YES
            if names:
                can_do.append(f"Move each file the rule covers into one of: {', '.join(names)}"
                              + (", or into a new folder when the rule calls for one" if more else ""))
            else:
                can_do.append("Move each file the rule covers into a folder, made when the rule calls for one")
            into = slots.get("into") or ""
            can_do += [f"Keep those folders in {_shown(Path(into))}" if into else f"Keep those folders inside {folder}",
                       "Leave a file where it is when the rule says so, or when it isn't sure",
                       "Show every move in your chores, with Undo for a week"]
            never = ["Delete or overwrite a file", *never]
        elif then == NOTE:
            notes = notes_path(slots)
            can_do += [f"Add what the rule asks for about each file to {notes.name}, in {_shown(notes.parent)}",
                       "Show each note in your chores"]
            never = ["Move, change or delete the files it reads", *never]
        return kind, reads, can_do, never, f"{built_in}, {'reading each file ' if inside else ''}on this computer"
    if when == WHILE_ON:
        show = slots.get("show") or BUBBLE
        can_do.append(f"Shows the result: {show}")
        if show != CLIPBOARD:
            can_do.append(f"The result stays: {slots.get('keep') or UNTIL_UNHIGHLIGHT}")
        if skip_language(slots):
            can_do.append(f"Leaves out text that is already in {skip_language(slots)}")
        return (when,
                ["Text you highlight with the mouse in any program, while it's switched on"],
                can_do,
                ["Change your files or the text you highlight", "Send anything over the internet",
                 "Work while it's switched off or Noir isn't running"],
                f"{built_in}, on this computer")
    # Asked in the chat. Its answers are written by whichever model answers the chat, so
    # this card never promises that nothing leaves the computer.
    return (when,
            [f'What you send it in the chat, starting with its name ("{slots.get("name") or "its name"}: ...")'],
            [*can_do, "Answers in the chat"],
            ["Change your files", "Do anything until you ask it"],
            f"{built_in}, on this computer, unless you picked another model for the chat")


def describe(agent: store.Agent) -> dict:
    """What an agent's page shows, in the user's words: what it does, how it's
    set up, and something to try it with."""
    slots = agent.slots
    if agent.blueprint == DOCUMENTS_QA:
        files = len(agent.contents)
        return {"does": "Answers questions about your files, and shows which file each answer came from.",
                "facts": [["Reads", Path(slots.get("folder", "")).name or "Your files"],
                          ["Knows", f"{files} file{'' if files == 1 else 's'}"],
                          ["How it answers", "In the chat"], ["Runs on", "This computer"]],
                "sample": SAMPLE_QUESTION}
    when, then = _when(slots), then_of(slots)
    does = slots.get("instruction", "")
    if when == NEW_FILE:
        folder = _folder(slots)
        facts = [["When it works", f"When a new file lands in {folder}"],
                 ["What it looks at", slots.get("looks_at") or INSIDE_FILE]]
        if then == MOVE:
            into = slots.get("into") or ""
            facts += [["Folders", ", ".join(choices_of(slots)) or "Made when the rule calls for one"],
                      ["May make new folders", slots.get("open") or OPEN_NO],
                      ["Keeps the folders in", _shown(Path(into)) if into else folder]]
        elif then == NOTE:
            notes = notes_path(slots)
            facts.append(["Writes in", f"{notes.name}, in {_shown(notes.parent)}"])
        return {"does": does, "facts": [*facts, ["Runs on", "This computer"]], "sample": SAMPLE_FILES}
    facts = [["When it works", when]]
    if when == WHILE_ON:
        facts += [["How it answers", slots.get("show", BUBBLE)],
                  ["How long it stays", slots.get("keep", UNTIL_UNHIGHLIGHT)],
                  *([["Leaves out", f"Text that is already in {skip_language(slots)}"]] if skip_language(slots) else []),
                  ["Runs on", "This computer"]]
    else:
        facts += [["How it answers", "In the chat"],
                  ["Runs on", "This computer, unless you picked another model for the chat"]]
    return {"does": does, "facts": facts, "sample": SAMPLE_TEXT}


def how(agent: store.Agent) -> str:
    """One sentence for the chores list, from the agent's own settings."""
    slots = agent.slots
    folder = _folder(slots)
    if agent.blueprint == DOCUMENTS_QA:
        return f"Answers your questions from the files in {folder}, when you ask in the chat."
    when, then = _when(slots), then_of(slots)
    if when == NEW_FILE and then == MOVE:
        names = choices_of(slots)
        if not names:
            where = "into folders it makes when the rule calls for one"
        else:
            where = f"into {', '.join(names)}" + (" or a new folder" if slots.get("open") == OPEN_YES else "")
        into = slots.get("into") or ""
        kept = f", kept in {_shown(Path(into))}" if into else ""
        by = ", going by its name alone" if slots.get("looks_at") == NAME_ONLY else ""
        return f"Watches {folder} and moves each new file your rule covers {where}{kept}{by}."
    if when == NEW_FILE and then == NOTE:
        return f"Watches {folder} and writes what your rule asks for about each new file into {notes_path(slots).name}."
    if when == NEW_FILE:
        return f"Watches {folder} and handles each new file by your rule."
    if when == WHILE_ON:
        shown = {CLIPBOARD: "the answer is copied, ready to paste",
                 BOTH: "the answer shows above the text and is copied"}.get(slots.get("show"),
                                                                             "the answer shows above the text")
        return f"While it's on, what you highlight in any program goes through it, and {shown}."
    return f'Answers in the chat when you write "{agent.name}:" and your text.'


# ------------------------------------------------------------------ old agents
# The one place that still knows the kinds of agent that were written by hand before there
# were cards, and only to turn the ones people already have into cards. Their ids and the
# texts their slots were saved with are spelled out here, because the code that owned them
# is gone.

_OLD_MOVER, _OLD_NOTER = "organizer", "summarizer"
# The first kind there ever was: it showed what was highlighted in one language, which was
# its only setting besides how the result was shown.
_OLD_HIGHLIGHTER = "translate_selection"
_OLD_HIGHLIGHTER_RULE = "Translate the text into {language}."
# How code used to know, from a card's rule alone, that text already in one language was
# to be left out: the rule said it translated. Nothing reads a rule for that any more: it
# is a setting of the card (skip_language). This is only for the cards saved before it was.
_OLD_SAID_SO = re.compile(r"translat|번역", re.IGNORECASE)
_OLD_BY_NAME = "The file's name"
_OLD_DECIDE = "Decide as you go"
_OLD_PARAGRAPH = "One short paragraph"
_OLD_NOTES = "Summaries.md"
# What each of them did, said as a rule. It is a guess at what the user wanted: the old
# agents never had a rule of the user's own.
_MOVER_RULE = ("Put each file into the folder that fits what it is about. If none fits, or it isn't clear, leave it "
               "where it is.")
# One that decided as it went named a folder for each file by what the file was about, in
# a few words, and used those folders again. Its card says it may make folders, so its
# rule has to say when and how: with the rule above, the setting did nothing, and an agent
# that had made no folder yet could never move a file.
_MOVER_RULE_OPEN = ("Put each file into the folder that fits what it is about. If no folder fits, make a new one, "
                    "named for what the file is about in two to four plain words. If it isn't clear what a file is "
                    "about, leave it where it is.")
_NOTER_RULE = "Say what this document is and what it says, in {length}."
# Where the agents that watch a folder keep what is switched on and the folders each has
# made: the new name first, then the one it had before.
_STATE_FILES = ("folderwatch_state.json", "organizer_state.json")


def migrate() -> list[str]:
    """Turn the agents of earlier versions into cards, keeping their folders and settings.
    The ones that worked on a folder's files come back switched off: the rule of each is
    now a guess at what the old agent did, and the user makes it theirs by talking before
    it touches a file again. Returns the names of the agents that became cards. (Called at
    startup, before the agents that were on are brought back.)

    A card that works on highlights and was saved before cards could say which language
    they leave out is given that setting here, once, from what its rule says (_old_skip);
    it stays as it was in every other way, switched on if it was, and is not among the
    names returned."""
    changed = []
    made = _old_made()
    for agent in store.list_agents():
        old = agent.slots
        folder = old.get("folder", "")
        if agent.blueprint == CUSTOM:
            if _when(old) == WHILE_ON and "skip_language" not in old:
                # Written down also when it is none, so this is asked of a card once only:
                # from here on the setting is the card's own, whatever its rule comes to say.
                old["skip_language"] = _old_skip(old.get("instruction"))
                store.save(agent)
            continue
        if agent.blueprint == _OLD_HIGHLIGHTER:
            language = str(old.get("language") or "English")
            agent.slots = {"instruction": _OLD_HIGHLIGHTER_RULE.format(language=language), "when": WHILE_ON,
                           "show": old.get("show", BUBBLE), "keep": old.get("keep", UNTIL_UNHIGHLIGHT),
                           "skip_language": language if language in TELLABLE else "", "name": agent.name}
        elif agent.blueprint == _OLD_MOVER:
            groups = old.get("groups") or _OLD_DECIDE
            decides = groups == _OLD_DECIDE
            # Deciding as it went, its folders were the ones it had made so far, and it could
            # always make another. Every folder it had is kept, however many: one left out
            # here could never be moved into again.
            names = choices_of({"choices": made.get(agent.name, []) if decides else groups})
            into = old.get("into") or ""
            agent.slots = {"when": NEW_FILE, "then": MOVE,
                           "instruction": _MOVER_RULE_OPEN if decides else _MOVER_RULE, "folder": folder,
                           "looks_at": NAME_ONLY if old.get("by") == _OLD_BY_NAME else INSIDE_FILE,
                           "choices": ", ".join(names), "open": OPEN_YES if decides else OPEN_NO,
                           "into": "" if into and folder and Path(into) == Path(folder) else into,
                           "name": agent.name}
        elif agent.blueprint == _OLD_NOTER:
            length = "one short paragraph" if old.get("length") == _OLD_PARAGRAPH else "three short lines"
            agent.slots = {"when": NEW_FILE, "then": NOTE, "instruction": _NOTER_RULE.format(length=length),
                           "folder": folder, "looks_at": INSIDE_FILE,
                           # Said in full, so its notes carry on in the file they are in: a card
                           # with no notes file named would start a new one, named after it.
                           "notes": old.get("notes") or str(Path(folder) / _OLD_NOTES),
                           "name": agent.name}
        else:
            continue
        agent.blueprint = CUSTOM
        store.save(agent)
        changed.append(agent.name)
    if changed:
        _switch_off(changed)
    return changed


def _old_skip(rule: object) -> str:
    """The language a card saved before the setting existed left out, as code then worked
    it out from the rule: one that said it translated, into a language named in it. "" for
    any other rule, and for a language no text can be told to be in. The only place a rule
    is ever read for a language."""
    text = str(rule or "")
    if not _OLD_SAID_SO.search(text):
        return ""
    language = language_in(text, target_only=True) or language_in(text)
    return language if language in TELLABLE else ""


def _old_state() -> list[tuple[Path, dict]]:
    """The state files there are, each with what it holds."""
    found = []
    for name in _STATE_FILES:
        path = noir.data_dir() / name
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(state, dict):
            found.append((path, state))
    return found


def _old_made() -> dict[str, list[str]]:
    """The folders each agent had made, by the agent's name."""
    made: dict[str, list[str]] = {}
    for _, state in _old_state():
        kept = state.get("made")
        for name, folders in (kept.items() if isinstance(kept, dict) else ()):
            if isinstance(folders, list):
                made.setdefault(name, [str(folder) for folder in folders])
    return made


def _switch_off(names: list[str]) -> None:
    """Take these agents off the list of what was switched on, so they stay off at this start."""
    for path, state in _old_state():
        on = state.get("on")
        if not isinstance(on, list) or not set(on) & set(names):
            continue
        state["on"] = [name for name in on if name not in names]
        try:
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # it can't be written: the agent is a card all the same, and can be switched off by hand


# ------------------------------------------------------------------ small helpers


def _when(slots: dict) -> str:
    """When a saved card works. One saved with no WHEN works while switched on, as it always has."""
    return slots.get("when") or WHILE_ON


def _pair(slots: dict) -> tuple[str, str]:
    """The WHEN and THEN of a card that may still be in the making: only what is chosen.
    A card from before there were THENs has the one its WHEN always meant."""
    when = slots.get("when") or ""
    then = slots.get("then") or ""
    if not then and when in (WHILE_ON, IN_CHAT):
        then = then_of(slots)
    return when, then


def _filled(slots: dict, setting: Setting) -> bool:
    if setting.type == "list":
        return bool(choices_of({"choices": slots.get(setting.key)}))
    return bool(str(slots.get(setting.key) or "").strip())


def _bare(name: str) -> str:
    """A name with case, spaces and marks aside: "Box 12" and "box-12" are both box12. A +
    and a # stay, since they tell names apart: "C++", "C#" and "C" are three folders."""
    return re.sub(r"[^\w+#]+|_+", "", name, flags=re.UNICODE).casefold()


def _key(name: str) -> str:
    """What two names are told apart by: the bare name. A name with no letter or digit in
    it that holds a sign or a small picture (a star, an emoji) is told apart by itself,
    less its spaces: such a name used to count for nothing, so a folder somebody had named
    that way was dropped from the list without a word and they were asked for their folders
    again. A name of nothing but punctuation is still no name."""
    bare = _bare(name)
    if bare or not any(unicodedata.category(letter).startswith("S") for letter in name):
        return bare
    return "".join(name.split()).casefold()


def _numbers(words: set[str]) -> set[str]:
    """The words of a name that carry a number: "2026", "12", "a3"."""
    return {word for word in words if any(letter.isdigit() for letter in word)}


def _one_line(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _shown(path: Path) -> str:
    """A place as a card says it: by name when it is in one of the places people name, from
    the home folder when it is somewhere else in it, else only the folder's own name. Never
    the whole path."""
    if str(path) in ("", "."):
        return "a folder"  # not chosen yet
    short = short_place(path)
    if short != str(path):
        return short
    try:
        inside = path.relative_to(Path.home())
    except ValueError:
        return path.name or str(path)
    return str(inside) if inside.parts else "your home folder"


def _folder(slots: dict) -> str:
    folder = slots.get("folder") or ""
    return _shown(Path(folder)) if folder else "a folder"


def _built_in(model_name: str) -> str:
    name = (model_name or "").strip()
    return "The built-in model" if not name or name.lower() == "the built-in model" else f"{name} (the built-in model)"
