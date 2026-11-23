"""The real engine, following the contract in events.py.

Every message goes one of a few ways: while a helper is being worked out or
set up it answers that; otherwise the router decides between chatting with
Noir, making a new helper, changing one, and running one. A helper is made in
a conversation with a model in it (agents/designer.py) whenever there is a
model fit to hold one; without one, the plain questions make the little they
can (agents/builder.py, agents/planner.py). A message about something else in
the middle of working one out is answered like any message; the helper waits,
set aside, and under the answer the user is asked whether to carry on with it.
Nothing here knows what any helper is for: what follows once one is made, and
every answer about one, goes by what its card is made of (agents/parts.py) and
by the records of what it did.
Every exchange is saved as part of a conversation (conversations.py). Noir
must already be set up (`python -m concierge setup`).
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path

from . import (activity, auto, chores, cloud, noir, hardware, history, pictures, portrait, research, researcher, safety, signs,
               sources, usage, voice)
from .accounts import APPS
from .agents import community, parts, runner, store
from .agents.blueprint import load_blueprints
from .agents.builder import CARD_YES, YES_WORDS, AgentBuilder, say
from .agents.designer import NO_DESIGNER, DesignModel, Designer, local_form, talker_form
from .agents.planner import IDEA, IDEA_CHANGE, MAKE_IT, IdeaPlanner, describe_ideas
from .agents.recipe import COPY_WORDS, HIGHLIGHT_WORDS, SHOW_WORDS, migrate, run_instruction
from .agents.router import WANTS_NEW as WANTS_NEW_AGENT, WATCHES, names_an_agent, refers_to, route, wants_change
from .agents.starters import Starter, asks_for, install
from .attachments import NOTHING_SAID, Attached, read_attachments
from .catalog import ModelEntry, find_model, helper_room, load_designers, recommend
from .conversations import ChatBook
from .events import (AgentCard, AgentList, NoirDone, NoirText, Error, Event, IdeaCard, Progress, Question, Result,
                     SystemInfo, Thinking)
from .folderwatch import FolderWatch
from .models import ModelMenu
from .ollama import Ollama, OllamaError
from .quick import spot
from .quick.agents import BOTH, BUBBLE, CLIPBOARD, LEFT_OUT, NO_MODEL, NOTHING_BACK, QuickAgents
from .quick.tidy import downloads_dir
from .setup import Setup

# "delete the Sample docs helper 2 agent", "remove my contracts helper"
WANTS_DELETE = re.compile(r"\b(delete|remove|get rid of|uninstall)\b|삭제|지워", re.IGNORECASE)
# A message that is about the user's helpers at all, by the words for one. With no helper
# named, "delete" or "remove" alone is a job on text: "remove the duplicates from this
# list" was asked "Delete Word fixer?".
HELPER_WORDS = re.compile(r"\b(agents?|helpers?|assistants?)\b|에이전트", re.IGNORECASE)
# Switching by words said in so many words: "turn off the explainer". A bare "stop" or
# "start" is no switch unless the helper is named: "stop explaining and just give me the
# answer" switched the Highlight Explainer off.
SWITCH_WORDS = re.compile(r"\b(turn|switch)\s+(on|off)\b|켜|꺼|끄", re.IGNORECASE)
# "show my ideas", "what ideas did I save?"
WANTS_IDEAS = re.compile(r"\b(my|saved)\s+ideas\b|\bideas\s+(list|i saved)\b|아이디어\s*(목록|보여)",
                         re.IGNORECASE)
# The words below are how people talk to a helper that works on the files of a folder,
# whatever it does with them. They only count when the user has such a helper, and each is
# answered from that helper's card and from the records of what it did, never from
# knowing what it is for.
# Where a file went, or where its folders are.
WANTS_WHERE = re.compile(r"(\bwhere(?:'s|s)?\b|\bwhich folder\b).*\b(files?|folders?|pdf|documents?|notes?|it|that|them|they|"
                         r"these|those|put|moved?|went|go|gone|end(ed)? up|created|made|saved|sorted|wrote|written)\b",
                         re.IGNORECASE)
WANTS_STATUS = re.compile(r"\b(what (did|have) you (do|done|moved?|sorted?|written?|wrote)|did you (move|sort|do|put|write|"
                          r"organi[sz]e) (anything|something|it|them|the|my)|what are you doing|what('s| is) (running|on|"
                          r"going on)|which folders? (do you have|did you make|are there|exist)|how many files)\b",
                          re.IGNORECASE)
# What may stand around those words when the message is that question and nothing else:
# "what are you doing?" is about the helpers, "what are you doing this weekend?" is not.
STATUS_ALONE = re.compile(r"[\s?.!,]*((right )?now|today|lately|so far|then|yet|anything|noir)?[\s?.!,]*", re.IGNORECASE)
# "Go through them now", "organize it", "I just downloaded a file": go through the folder now.
WANTS_PASS = re.compile(r"\borgani[sz]e\b|\bsort (it|this|that|them|these|my|the)\b|\bdownloaded\b|\bfile (it|this|that|them)\b|"
                        r"\bmove (the|my|these|those) (files|documents|pdfs)\b|\bgo through\b|"
                        r"\b(handle|do|run) (it|them|these|those) now\b", re.IGNORECASE)
# A question about how things are, or how to do something, is no order to go through a
# folder, even with those words in it: "how do I organize all my recipes?" and "I
# downloaded all my photos from the camera, how do I back them up?" each moved files that
# had been in the folder all along. ("Can you go through them?" is an order, asked kindly.)
ASKS_HOW = re.compile(r"^\s*(what|why|how|where|which|who|when|whose|does|do|did|is|are|was|were|should|shall|have|has)\b|"
                      r"\b(how|why|what) (do|does|did|can|could|should|would|to)\b", re.IGNORECASE)
# What an order to go through the folder is said about when it names no file: the files
# themselves, by a word for them ("it", "them", "everything") at the end of what is said.
# "Organize my week" names neither and is no order to a helper.
PRONOUN_OBJECT = re.compile(r"\b(it|them|these|those|this|that|everything|all of (it|them))\s*"
                            r"(now|please|for me|out|up|again|too|then)?\s*[.!?]*$", re.IGNORECASE)
# "Why didn't you move the letter?", "why is my statement still in downloads?": answered
# from the record of what was decided about each file, never by the chat model.
WANTS_WHY = re.compile(r"\bwhy\b.*\b(move|moved|sort|sorted|organi[sz]ed?|put|filed?|still|left|skip|skipped|touch|touched|"
                       r"ignore|ignored|stay|stayed|write|wrote|written)\b", re.IGNORECASE)
WHERE_WORDS = re.compile(r"\bwhere(?:'s|s)?\b|\bwhich folder\b", re.IGNORECASE)
# A message about that work itself, which its facts answer here, never the web.
ABOUT_CHORES = re.compile(r"\b(organi[sz]e[ds]?|organi[sz]ing|watch(es|ing|ed)?|sort(s|ed|ing)?|folders?|"
                          r"files?|pdfs?|documents?|chores?|move[ds]?|moving|downloads|lands?|arrives?|comes? in|"
                          r"something new|new (files?|things?|stuff))\b", re.IGNORECASE)
# A short question with a pronoun soon after such a helper did something ("where did they
# go?") is about that, not about the world, when it asks where something is or went or why.
# A pronoun alone was not enough: "is it going to rain in Seattle tomorrow?", a minute after
# "where did my files go?", was answered from the chores and never looked up.
FOLLOWS_A_CHORE = re.compile(r"\b(it|they|them|that|those|these)\b", re.IGNORECASE)
FOLLOW_UP_ASKS = re.compile(r"\bwhere(?:'s|s)?\b|\bwhich folder\b|\bwhy\b|\b(moved?|put|left|stay(ed|s)?|went|go|gone|"
                            r"end(ed)? up)\b", re.IGNORECASE)
CHORE_FRESH_SECONDS = 600
# Words that say a message is about files or folders at all. A question with none of them,
# that names no file on record and no helper and does not follow straight on from one, is
# no question about a helper's work: "where should I go on vacation this summer?" was
# answered with where the helper keeps its folders, and "why do people still use fax
# machines?" with what it had looked at.
FILE_WORDS = re.compile(r"\b(files?|folders?|documents?|pdfs?|downloads|scans?|notes? file)\b|\.[a-z][a-z0-9]{1,4}\b|"
                        r"파일|폴더", re.IGNORECASE)
# What the person asks about what was done with their things: "why didn't you move the
# letter?", "where did you put it?".
YOU_HANDLED = re.compile(r"\byou\b.{0,20}\b(move[ds]?|sort(ed)?|put|filed?|skip(ped)?|touch(ed)?|organi[sz]ed?|wrote|"
                         r"written)\b", re.IGNORECASE)
# A question about what the helper itself does: "is it still watching my downloads?", "can
# it also sort pictures?", "can you also take zips?". "How do I zip a folder on windows?"
# is none, and with a plan model picked it went off this computer with the record of every
# file the helper had handled.
HELPER_DOES = re.compile(r"\b(it|they|helpers?|agents?|chores?)\b(\s+\w+){0,2}?\s+(watch|sort|move|moving|handl|take|"
                         r"read|look|touch|organi[sz]|work|run|land|arriv)\w*\b|\byou (also|still)\b", re.IGNORECASE)
# The places people name, as people say them in a message. One that is no folder a helper
# watches or keeps its folders in means the message is about somewhere else: "can you
# organize all my desktop files too?" went through everything in Downloads.
PLACE_SAID = {"Desktop": r"\bdesktop\b|바탕 ?화면", "Downloads": r"\bdownloads\b|\bdownload folder\b|다운로드",
              "Documents": r"\b(in|from|on|to|into) (my |the )?documents\b|\bdocuments folder\b",
              "Pictures": r"\b(in|from|on|to|into) (my |the )?pictures\b|\bpictures folder\b"}
# A request for new work ("when a pdf lands, write me a note"), never a question about a chore.
ASKS_FOR_WORK = re.compile(r"\b(write me|make|create|set ?up|build|start|every time|whenever|from now on|automatically|"
                           r"when (a|an|any|new|each) \w+ (lands|arrives|comes|appears|downloads))\b", re.IGNORECASE)
# A message about the person's own things on this computer: their folders, their files,
# their photos. Whatever it asks, the answer is not on the web. A request to tidy the
# Downloads folder, typed in Korean with a question mark, and "I have hundreds of photos
# ... in my Pictures folder and can never find the ones from ..." were both answered
# "This can change from day to day, so I'd look it up on the web. Shall I?".
OWN_THINGS = re.compile(
    r"\b(my|our) (\w+ )?(downloads?|documents?|desktop|pictures?|photos?|images?|screenshots?|files?|folders?|papers?|notes)\b|"
    r"\b(photos?|pictures?|images?|screenshots?|files?|documents?|papers?|notes) (of|from|in|on) (my|our)\b|"
    r"\b(downloads|documents|desktop|pictures) folder\b|폴더|파일|다운로드|바탕 ?화면|내 (사진|문서)", re.IGNORECASE)
# A message that asks something rather than tells an agent to do it.
WANTS_ANSWER = re.compile(r"\?|^\s*(which|where|what|why|how|when|who|is|are|was|were|did|do|does|can|could|have|has|"
                          r"will|would|should)\b", re.IGNORECASE)
# A plain no, typed to a question that has a Yes and a No button (yes is the builder's CARD_YES).
NO_WORDS = ("no", "nope", "no thanks", "leave it", "not now", "don't", "dont", "아니", "아니요", "싫어")
# Words of a question that never name a file.
_ASKING_WORDS = {"why", "did", "didn", "didnt", "not", "you", "the", "file", "files", "pdf", "move", "moved", "sort", "sorted",
                 "still", "downloads", "download", "folder", "folders", "into", "that", "this", "them", "what", "about",
                 "organize", "organise", "left", "behind", "there", "here", "with", "from", "have", "haven", "were", "was",
                 "your", "put", "where", "wheres", "which", "inside", "created", "document", "documents", "and", "for",
                 "are", "its", "how", "all", "any", "one", "now", "yet", "too", "but", "can", "has", "had", "new"}
# Words that may stand around a helper's name in a message that only calls it to do
# something to it ("please delete my fixer").
_CALLING_WORDS = {"please", "my", "the", "that", "this", "a", "an", "agent", "helper", "assistant", "one", "now", "it",
                  "delete", "remove", "get", "rid", "of", "uninstall", "can", "you", "could", "삭제", "지워"}
# "put output.pdf in Letters", "move the scan to Taxes": a move the user orders, which the
# helper keeps as an example for later files.
WANTS_PLACE = re.compile(r"^\s*(?:please |can you |could you |just )?(?:put|move|file|place|drop) (.+?) (?:in|into|to|under) "
                         r"(?:the |my |a )?(?:folder (?:called |named )?)?(.+?)(?: folder)?(?:,? please)?\s*[.!]?$", re.IGNORECASE)
# What such an order names when it is about a file at all ("move the meeting to Friday" is
# not). A word like "this" or "it" says nothing of that: "put this word in a sentence:
# serendipity" was answered "I can't see a file like that in Downloads."
_NAMES_A_FILE = re.compile(r"\.\w{2,5}\b|\b(files?|documents?|pdfs?|pictures?|photos?|scans?|downloads?)\b", re.IGNORECASE)
# Every file in the folder, the ones that were there before the helper too, asked for in so
# many words with what to do to them: "go through everything", "sort all the files". "All
# my" on its own once did, and "how do I organize all my recipes?" moved what had been in
# Downloads for months. Even then it is asked first (ALL_NOW).
WANTS_EVERYTHING = re.compile(r"\b(go(ing)? through|organi[sz]e|sort|handle|file|move|tidy( up)?|clean up)\s+(everything|"
                              r"all (of )?(it|them|these|those)|all (the |my |of the )?(files|documents|pdfs|downloads)|"
                              r"the whole folder|every file)\b", re.IGNORECASE)
# "turn on the word explainer", "switch off my helper", "켜줘"
WANTS_ON = re.compile(r"\b(turn|switch)\s+on\b|\b(start|enable|activate)\b|켜", re.IGNORECASE)
WANTS_OFF = re.compile(r"\b(turn|switch)\s+off\b|\b(stop|disable|deactivate)\b|꺼|끄", re.IGNORECASE)
# "it's not showing anything", "my helper doesn't work", "안 나와". Only that something is
# wrong with a helper: what the helper is for is none of this rule's business.
TROUBLE = re.compile(
    r"\b(not|isn'?t|doesn'?t|don'?t|won'?t|never|no)\b.{0,30}\b(show\w*|work\w*|appear\w*|"
    r"happen\w*|pop\w*|display\w*|see)\b|nothing (happens|shows|appears)|broken|안 ?(돼|나와|보여)|작동",
    re.IGNORECASE,
)
DELETE_AGENT, PICK_AGENT_TO_DELETE = "delete_agent", "pick_agent_to_delete"
FIX_AGENT, FIX_IT, LEAVE_IT = "fix_agent", "Fix it", "Leave it"
SWITCH_IT_ON = "Switch it on"
DELETE_IT, KEEP_IT = "Delete it", "Keep it"
# What each Spot button counts as on Today.
SPOT_KINDS = {"polish": activity.POLISHED, "shorter": activity.POLISHED, "explain": activity.EXPLAINED,
              "error": activity.EXPLAINED, "code": activity.EXPLAINED, "problems": activity.EXPLAINED,
              "translate": activity.TRANSLATED, "summarize": activity.SUMMED_UP}
# The jobs timed in the first two minutes: real jobs it does every day, small enough to be quick.
MEASURED_JOBS = (
    ("to explain a word you highlight", "Explain this word in simple, everyday words, in one sentence.", "serendipity"),
    ("to polish a messy message", "Rewrite the text so it reads clearly and politely. Keep its meaning.",
     "hey can u send me that report asap, its late and the boss keeps asking"),
    ("to translate a paragraph", "Translate the text into {language}.",
     "The library opens at nine on weekdays and at ten on weekends. Books can be borrowed for three weeks, "
     "and you can renew them online if nobody else is waiting for them."),
)
# The two buttons under an answer, and what each says in the chat. Code knows what they
# mean, so they skip the router, where "shorter" could change one of the user's agents.
FOLLOW_UPS = {"shorter": "Shorter, please.", "more": "Tell me more."}
# After a helper that works on a folder's new files is made: a first pass over what is in
# the folder already, or not.
FIRST_PASS = "first_pass"
GO_THROUGH, ONLY_NEW = "Yes, go through them", "Only new files from now on"
# Asked for in words later: every file in the folder, the ones from before it too. They are
# counted and asked about first, never taken at once.
ALL_NOW = "all_now"
LEAVE_THEM = "No, leave them"
# A helper that was being worked out when they asked about something else waits, set aside
# (agents/designer.py). Under the answer to what they asked: carry on with it, or not.
CARRY_ON = "carry_on"
CARRY_ON_YES, DROP_IT = "Carry on", "Drop it"
# After they put a file somewhere by hand ("put X in Y"): whether files like it should
# always go there, which is a change to the helper's rule and is talked through.
RULE_FROM_MOVE = "rule_from_move"
CHANGE_THE_RULE, JUST_THIS_ONE = "Yes, change the rule", "No, just this one"
# The building blocks (agents/capabilities.yaml) that mean a helper works on the files of
# a folder. Such a helper is only ever worked out in a conversation: the plain questions
# know nothing to ask about one.
FILE_PARTS = {"new_file", "folder_files", "move_files", "save_file"}
# Where the names of helpers an update changed and switched off are kept (in the app's
# state file) until each one has been changed or switched on, and which of them the chat
# has told the user about, once.
CHANGED_HELPERS = "changed_helpers"
CHANGED_TOLD = "changed_helpers_told"
# Why such a helper is off, for its line in the chores list.
NEEDS_TALKING = "its rule needs talking through"


def _mentions(text: str, name: str) -> bool:
    """Whether a question names this file: a word of the question is in the file's name, so
    "the insurance pdf" finds BoatInsurance2026.pdf and "the invoice" march_invoice.pdf."""
    lowered = name.lower()
    return any(word in lowered for word in re.findall(r"[a-z0-9]{3,}", text.lower()) if word not in _ASKING_WORDS)


def _says_file(text: str, name: str) -> bool:
    """Whether a message names this file by one of the words of its name, said whole: "the
    phone bill" names phone_bill.pdf, "the bills" names it too. Stricter than _mentions,
    which picks among files once the message is known to be about one: a word only inside
    another ("get" in budget.xlsx) is no sign that it is."""
    stem = Path(name).stem
    parts_of = {word.lower() for word in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", stem) if len(word) >= 4}
    said = {word for word in re.findall(r"[a-z0-9]{4,}", text.lower()) if word not in _ASKING_WORDS}
    return any(word == part or word.startswith(part) or part.startswith(word) for word in said for part in parts_of)


def _answers_yes(text: str) -> bool | None:
    """A message typed under a question with Yes and No buttons that begins by answering
    it: True for a yes ("yes, go through them"), False for a no ("no, leave them"), None
    when it does neither. A yes with "but" in it is no plain yes."""
    whole = text.strip().lower().strip("!. ")
    if (plain := _plain_answer(whole)) is not None:
        return plain
    first = re.split(r"[\s,.!]+", whole, maxsplit=1)[0]
    if first in YES_WORDS and not re.search(r"\bbut\b", whole):
        return True
    if first in ("no", "nope", "nah", "아니", "아니요"):
        return False
    return None


def _words_shared(text: str, name: str) -> int:
    """How many words of a message are in a file's name: what tells the file it means from
    another that shares only some of them."""
    lowered = name.lower()
    return sum(word in lowered for word in set(re.findall(r"[a-z0-9]{3,}", text.lower())) - _ASKING_WORDS)


def _named(text: str, *records: list[dict]) -> list[list[dict]]:
    """Of the files on record (each list an own record: the ones moved, the ones left),
    the ones a question names: those whose names have the most of its words in them. Any
    shared word used to do, and "where did the velo invoice go?" was answered with every
    invoice there was and a delivery note from Velo as well."""
    most = max((_words_shared(text, item["name"]) for record in records for item in record), default=0)
    return [[item for item in record if most and _words_shared(text, item["name"]) == most] for record in records]


def _plain_answer(text: str) -> bool | None:
    """True for a plain yes, False for a plain no, None for anything more."""
    words = text.strip().lower().strip("!. ")
    if words in CARD_YES:
        return True
    if words in NO_WORDS:
        return False
    return None


def _carry_answer(text: str) -> bool | None:
    """What a message typed right under "Carry on with the helper?" says to it: True to
    carry on, False to drop it, None for anything more. Only a plain yes, a plain no, or
    a button's own words. "Not now" and "leave it", which answer other questions with a
    no, say neither here: the helper goes on waiting, and is not thrown away for them."""
    words = text.strip().lower().strip("!. ")
    if words in CARD_YES or words == CARRY_ON_YES.lower():
        return True
    if words in ("no", "nope", "no thanks", "아니", "아니요") or words == DROP_IT.lower():
        return False
    return None


def _names(kept: object) -> list[str]:
    """A list of names as it was kept in the app's state, whatever is there now."""
    return [name for name in kept if isinstance(name, str)] if isinstance(kept, list) else []


def _lower(line: str) -> str:
    """A sentence to go on after a colon or a name: its first letter small."""
    return f"{line[:1].lower()}{line[1:]}"


def _count(number: int, thing: str) -> str:
    """ "1 file", "3 files". """
    return f"{number} {thing}{'' if number == 1 else 's'}"


class NoirEngine:
    def __init__(self, ollama: Ollama | None = None):
        self.ollama = ollama or Ollama()
        self.chat: noir.NoirChat | None = None
        # The three ways a helper is made, all built at startup: the conversation with a
        # model in it, and the plain questions and the idea planner for when there is none.
        self.designer: Designer | None = None
        self.builder: AgentBuilder | None = None
        self.planner: IdeaPlanner | None = None
        self.quick: QuickAgents | None = None
        self.blueprints = load_blueprints()
        self.book = ChatBook(noir.data_dir() / "conversations",
                             history=lambda: self.chat.history if self.chat else [])
        self.deleting: str | None = None  # agent waiting for "Delete it" / "Keep it"
        # A diagnosis waiting for "Fix it": (agent name, settings to change, switch it on),
        # and the button a plain yes typed in the chat stands for.
        self.fixing: tuple[str, dict, bool] | None = None
        self.fix_yes = ""
        self.talker_name = ""  # the model writing its answers, if it isn't its own
        # Auto (auto.py): its own model answers, and this one gets the hard questions.
        self.auto_cloud = None
        self.auto_last = ""  # where the last chat answer came from, for "why?" and "go on"
        self.auto_kind = ""  # what the last one kept here was, counted if asked again
        # Looking things up on the web (research.py): the message waiting for the user's
        # first yes, and what the last lookup found, for the sources under the answer.
        self.pending_lookup: tuple[str, bool, str] | None = None
        self.found: research.Findings | None = None
        # Helpers that work on a folder's new files (folderwatch.py) run on every system, so
        # what runs them is made here, not at startup.
        self.folderwatch = FolderWatch(self.ollama, noir.NOIR_MODEL, noir.data_dir() / "folderwatch.json",
                                       noir.data_dir() / "folderwatch_done.json")
        self.going_through: str | None = None  # the helper just made, waiting for "go through them?"
        self.all_asked = False  # the question about it was "go through all of them?", asked when they said so later
        self.just_asked = False  # that question was the last thing said, so a plain yes or no typed now answers it
        self.chore_spoken_at = 0.0  # when such a helper last said or did something in this chat
        # "Carry on with the helper?" was the last thing said, so a plain yes or no typed now answers it.
        self.carry_asked = False
        # A file they put somewhere by hand, waiting for "should files like it always go
        # there?": (the helper, the file, the folder, what they typed). The question is
        # asked once for a file, and a no stands for that helper until the app closes.
        self.ruling: tuple[str, str, str, str] | None = None
        self.rule_asked: set[tuple[str, str]] = set()
        self.rule_refused: set[str] = set()
        # Helpers an update turned into cards, which came back switched off. `changed_off`:
        # the ones not changed or switched on since, whose line in the chores list says why
        # they are off. `changed_over`: the ones the chat has still to tell the user about,
        # once, at the first message. Both are kept in the app's state.
        self.changed_off: list[str] = []
        self.changed_over: list[str] = []
        self.menu = ModelMenu(self.ollama, self._hardware)
        self.menu.changed = self._use_chosen_model
        self.setup = Setup(self.ollama)  # the first run's one button (setup.py)
        # Whether a helper may be worked out in a conversation with a model
        # (agents/designer.py). Off, nobody designs and the plain questions are asked: what
        # an eval of something else wants to hold still.
        self.designs = True

    # ----------------------------------------------------------- contract

    def startup(self) -> Iterator[Event]:
        report = hardware.detect()
        rec = recommend(report)
        tag = noir.load_state().get("base_model")
        model = find_model(tag) if tag else None
        in_use = f"{model.name} ({tag})" if model else tag or "not set up"
        recommended = f"{rec.model.name} ({rec.model.tag})" if rec.model else None
        note = rec.reason if rec.model is None else ""
        if rec.model and tag and tag != rec.model.tag:
            note = f"Not the recommended {rec.model.name}. Run `python -m concierge setup` to switch."
        yield SystemInfo(hardware.describe(report), recommended, in_use, rec.device_name, note)

        try:
            self.ollama.ensure_running()
            if not self.ollama.has_model(noir.NOIR_MODEL):
                yield Error("Noir isn't set up on this computer yet.")
                return
            if model and self.ollama.has_model(model.tag) and noir.needs_configure(self.ollama, model, rec, report):
                # Its prompt changed with the program (how it talks is part of it), so
                # it is rebuilt from the same base model before the first message. It
                # takes a moment, and without it a fix to its words never reaches the app.
                noir.configure(self.ollama, model, rec, report)
            self.chat = noir.NoirChat(self.ollama)
            self.chat.about = portrait.about_you(portrait.load())
            self._use_chosen_model()
        except OllamaError as exc:
            yield Error(str(exc))
            return
        self.designer = Designer(self.ollama, noir.NOIR_MODEL, self.chat.think, self.folderwatch.rehearse,
                                 self._design_model, self._built_in_name)
        self.builder = AgentBuilder(self.ollama, noir.NOIR_MODEL, self.chat.think, self.blueprints)
        self.planner = IdeaPlanner(self.ollama, noir.NOIR_MODEL, self.chat.think, self._hardware,
                                   self.blueprints)
        # Switch-on agents read highlights through Windows; on a Mac there are none yet.
        self.quick = QuickAgents(self.ollama, noir.NOIR_MODEL, self.chat.think) if sys.platform == "win32" else None
        # Agents of older versions become cards (the ones that worked on a folder's files
        # through parts.migrate, which also takes them off the list of what was on), before
        # the ones that were on are brought back.
        self._keep_changed(migrate())
        self.folderwatch.refresh(store.list_agents())
        yield self._agent_list()
        yield self.book.chat_list()

    def send(self, text: str, think: bool = False) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        # After the fixed reply to someone in trouble (safety.py) is no moment to ask about a helper.
        answered = self._then_carry_on(self._handle(text, think), quiet=bool(safety.crisis(text)))
        yield from self._full_lists(self.book.record(text, answered))

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        yield from self._full_lists(self.book.record(choice, self._then_carry_on(self._handle_choice(id, choice))))

    # The book saves the open conversation (with Noir's memory of it) before
    # switching, so the per-conversation state is only cleared after that.

    def new_chat(self) -> Iterator[Event]:
        events = self.book.new()
        self._clear_conversation_state()
        yield from events

    def open_chat(self, id: str) -> Iterator[Event]:
        conversation = self.book.open(id)
        if conversation is None:
            yield Error("That conversation could not be found.")
            yield self.book.chat_list()
            return
        self._clear_conversation_state()
        if self.chat:
            self.chat.history = list(conversation.history)
        yield self.book.transcript()
        yield self.book.chat_list()

    def delete_chat(self, id: str) -> Iterator[Event]:
        was_open = self.book.current is not None and self.book.current.id == id
        events = self.book.delete(id)
        if was_open:
            self._clear_conversation_state()
        yield from events

    def delete_agent(self, name: str) -> Iterator[Event]:
        # No user line in the transcript: the click on the agent is the context.
        yield from self.book.record("", self._confirm_delete(name))

    def toggle_agent(self, name: str) -> Iterator[Event]:
        yield from self.book.record("", self._toggle(name))

    def reset(self) -> None:
        self.book.new()
        self._clear_conversation_state()

    # Outside the contract, like details(): the full window's model menu, + button
    # and reservations call these through ChatHub.

    def send_files(self, text: str, paths: list[str], think: bool = False) -> Iterator[Event]:
        """A message with things added to it. They are the point of the message,
        so it goes straight to Noir instead of through the router."""
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        attached = read_attachments(paths)
        said = "\n".join(filter(None, [text, f"Attached: {', '.join(attached.names)}"]))
        answered = self._then_carry_on(self._with_attachments(text, attached, think))
        yield from self._full_lists(self.book.record(said, answered))

    def follow_up(self, which: str, think: bool = False) -> Iterator[Event]:
        """Shorter or More detail, clicked under its last answer (FOLLOW_UPS)."""
        if self.chat is None:
            yield Error("Noir is not running. Restart the app after setting it up.")
            return
        if which not in FOLLOW_UPS:
            return
        self.deleting = None
        self.fixing = None
        self.ruling = None
        self.just_asked = self.carry_asked = False
        if which in voice.BUDGETS:
            self.chat.kind = which
        answered = self._then_carry_on(self._follow_up(which, think))
        yield from self._full_lists(self.book.record(self.follow_up_words(which), answered))

    def follow_up_words(self, which: str) -> str:
        """What a click on a button under an answer says in the chat."""
        return FOLLOW_UPS.get(which, "")

    def _follow_up(self, which: str, think: bool) -> Iterator[Event]:
        try:
            yield Thinking("You asked for it shorter, so I'll keep only what matters most." if which == "shorter"
                           else "You asked for more, so I'll go further without repeating myself.")
            yield from self._reply(FOLLOW_UPS[which], think)
        except OllamaError as exc:
            yield Error(str(exc))

    def after_answer(self, reply: str) -> dict:
        """What can go under a reply the page just showed. Only its answer in the chat
        gets Shorter and More detail, not a setup's message or a switch's note; and only
        a plan that names places gets the one-time question about photos."""
        if not self._is_her_answer(reply):
            return {"follow_ups": False, "places": False}
        return {"follow_ups": True, "places": pictures.worth_asking(self._question(), self.chat.history[-1]["content"])}

    def pictures(self, reply: str) -> list[dict]:
        """Photos of the places its answer names, for beside their lines (pictures.py).
        The page asks only once the user said yes to photos."""
        if not self._is_her_answer(reply):
            return []
        return pictures.for_answer(self._question(), self.chat.history[-1]["content"])

    def _is_her_answer(self, reply: str) -> bool:
        history = self.chat.history if self.chat else []
        return bool(reply.strip() and history and history[-1]["role"] == "assistant"
                    and reply.strip().startswith(history[-1]["content"]))

    def _question(self) -> str:
        return self.chat.history[-2]["content"] if len(self.chat.history) > 1 else ""

    def set_agent(self, name: str, on: bool) -> Iterator[Event]:
        yield from self.book.record("", self._toggle(name, on=on))

    def recipes(self) -> dict:
        """The agents to discover, and which of them the user already has."""
        have = {agent.name.lower() for agent in store.list_agents()}
        return {"categories": list(community.CATEGORIES),
                "recipes": [{**asdict(recipe), "added": recipe.name.lower() in have} for recipe in community.recipes()]}

    def add_recipe(self, id: str) -> Iterator[Event]:
        recipe = community.find(id)
        if recipe is None:
            yield Error("I can't find that agent any more.")
            return
        community.install(recipe)
        yield self._agent_list()

    def _helpers(self) -> list[tuple[str, str]]:
        """The user's own agents that work on text when asked, for the Spot's buttons."""
        return [(agent.name, agent.slots.get("instruction", "")) for agent in store.list_agents()
                if agent.blueprint == parts.CUSTOM and not parts.is_switchable(agent) and agent.slots.get("instruction")]

    def spot_actions(self, text: str, editable: bool) -> list[dict]:
        return spot.actions_for(text, editable, self._helpers())

    def spot_run(self, action: str, text: str, ask: str = "") -> dict:
        """One Spot job, always on its own model: the Spot reads from any program."""
        try:
            instruction, words = spot.job(action, ask, text, self._helpers())
        except ValueError:
            return {"error": "I don't know that one."}
        if not words:
            return {"error": "Highlight something first, or tell me what to write."}
        try:
            result = run_instruction(self.ollama, noir.NOIR_MODEL, instruction, words, self._quick_think())
        except OllamaError as exc:
            return {"error": str(exc)}
        activity.record(SPOT_KINDS.get(action.split(":")[0], activity.HELPED))
        return {"text": result}

    def switch_agent(self, name: str, on: bool) -> Iterator[Event]:
        """A switch on Help me: adds the ready-made agent if it isn't there yet and
        turns it on or off, with nothing said in the chat."""
        agent = store.find_agent(name)
        if agent is None and on and (recipe := community.find(store.slugify(name))):
            community.install(recipe)
            agent = store.find_agent(name)
        if agent and parts.watches(agent):
            self._switch_watcher(agent, on)
        elif agent and self.quick and parts.is_switchable(agent):
            self.quick.switch(agent, on)
        yield self._agent_list()

    def activity(self) -> dict[str, int]:
        """This week's jobs for Today, with the tokens Auto kept off the user's plans
        and keys (usage.py), so the week's sentence can say "and saved about 12,400 tokens"."""
        counts = activity.this_week()
        saved = sum(plan["week"]["saved"] for plan in usage.summary().values())
        if saved:
            counts["saved"] = saved
        return counts

    # ------------------------------------- getting to know the user (history.py)

    def bring_in_history(self, path: str) -> dict:
        """Read a ChatGPT or Claude download. Outside events.py, like measure: it's
        part of getting to know the user, not of a conversation."""
        try:
            return history.bring_in(Path(path))
        except history.HistoryError as exc:
            return {"error": str(exc)}
        except OSError:
            return {"error": "I couldn't open that file."}

    def understand_history(self, progress=None) -> dict:
        """Read everything brought in and work out what it can about the user.
        Always its own model: these chats never go to a cloud one."""
        chats = history.brought_in()
        if not chats:
            return {"error": "There's nothing brought in yet."}
        try:
            made = portrait.understand(self.ollama, noir.NOIR_MODEL, chats, self._quick_think(), progress)
        except OllamaError as exc:
            return {"error": str(exc)}
        self._use_portrait()
        return made

    def look_around(self) -> dict:
        """What this computer says about the user (signs.py): names and counts only,
        and only because they asked."""
        summary = signs.look_around()
        made = portrait.add_computer(summary, signs.facts_from(summary))
        self._use_portrait()
        return made

    def bring_in_downloads(self, since: float = 0) -> dict:
        """Every ChatGPT or Claude download in Downloads not read yet. {} when none."""
        read, sources = 0, set()
        for path in history.find_exports(downloads_dir(), since):
            result = self.bring_in_history(str(path))
            if "error" not in result:
                read += result["read"]
                sources.update(result["sources"])
        return {"read": read, "sources": sorted(sources)} if read else {}

    def what_i_know(self) -> dict:
        return portrait.load()

    def keep_fact(self, fact_id: str, kept: bool) -> dict:
        made = portrait.keep(fact_id, kept)
        self._use_portrait()
        return made

    def forget_history(self) -> None:
        """Everything brought in and everything it worked out from it, gone."""
        history.forget()
        portrait.forget()
        self._use_portrait()

    def _use_portrait(self) -> None:
        if self.chat:
            self.chat.about = portrait.about_you(portrait.load())

    # First-run setup from inside the window (setup.py): the page asks how far it is,
    # presses one button, and starts it again when done (ChatHub.restart).

    def setup_state(self) -> dict:
        return self.setup.state()

    def setup_begin(self, smallest: bool = False) -> dict:
        return self.setup.begin(bool(smallest))

    def measure(self) -> dict:
        """What this computer can do, timed on it just now, for the first two minutes.
        Every number is measured; nothing is guessed."""
        report = hardware.detect()
        gpu = report.best_gpu()
        device = f"{gpu.name} · {gpu.vram_total_gb:.0f} GB" if gpu and gpu.vram_total_gb else report.cpu_name
        home = spot.home_language()
        other = "English" if home != "English" else "Korean"
        try:
            think = self._quick_think()
            self.ollama.refresh(noir.NOIR_MODEL, noir.KEEP_ALIVE)  # loading its isn't part of a job
            results = []
            for what, instruction, sample in MEASURED_JOBS:
                began = time.monotonic()
                said = run_instruction(self.ollama, noir.NOIR_MODEL, instruction.format(language=other),
                                       sample, think)
                seconds = time.monotonic() - began
                results.append({"what": what, "seconds": round(seconds, 1), "words": len(said.split())})
        except OllamaError as exc:
            return {"device": device, "error": str(exc)}
        # All three jobs together, so one quick answer can't make the speed look odd.
        seconds = sum(job["seconds"] for job in results)
        return {"device": device, "results": results,
                "words_per_second": round(sum(job["words"] for job in results) / seconds) if seconds else None}

    def _quick_think(self) -> bool | None:
        """Thinking off for small jobs, the same as in the chat. Asked of the model itself when
        the page calls before startup has finished, because a thinking model left to its
        default thinks first, and a word took 13 seconds to explain instead of a fraction of one."""
        if self.chat:
            return self.chat.think
        return False if "thinking" in self.ollama.capabilities(noir.NOIR_MODEL) else None

    def post_agent(self, name: str, about: str, category: str, by: str = "") -> dict:
        """The page that posts an agent, for the window to open. Nothing is sent from here."""
        agent = store.find_agent(name)
        if agent is None:
            return {"error": "Please pick one of your agents."}
        try:
            address = community.post_address(agent, about, category, by)
        except community.PostError as exc:
            return {"error": str(exc)}
        if not community.can_post():
            return {"error": "Posting isn't open yet, because the shared place for agents hasn't been set up."}
        return {"address": address}

    def close(self) -> None:
        self.book.save()
        if self.quick:
            self.quick.stop()
        self.folderwatch.stop()
        self._drop_design()
        if self.chat:
            self.chat.close()

    # ------------------------------------------------------------ routing

    def _handle(self, text: str, think: bool = False) -> Iterator[Event]:
        self.deleting = None  # an unanswered "Delete X?" is dropped by moving on
        fixing, self.fixing = self.fixing, None
        ruling, self.ruling = self.ruling, None
        just_asked, self.just_asked = self.just_asked, False
        carry_asked, self.carry_asked = self.carry_asked, False
        if safety.crisis(text):
            # Before anything else, setups included: this is no moment for a form.
            if self.designer is not None and self.designer.active:
                # A helper being worked out is set aside, in code. Left active, whatever they
                # typed next would be read as part of that conversation, and a plain "ok"
                # under a card is a yes to it.
                self.designer.set_aside()
            # The plain questions and an idea being talked through are left for the same
            # reason: an "ok" typed after the reply, at the plain card, made the helper.
            if self.builder is not None:
                self.builder.draft = None
            if self.planner is not None:
                self.planner.draft = None
            self.going_through = None
            yield Thinking("This sounds serious, so I'm answering with care, not guessing.")
            yield from say(safety.crisis_reply(text))
            return
        # While a helper is worked out with a model on this computer, Noir's own model has
        # made room for it on purpose, so "loading my model" would be untrue there.
        designing = self.designer is not None and self.designer.active
        if not designing:
            yield from self._waking()
        try:
            yield from self._say_changed()
            if fixing and self.fix_yes and (yes := _plain_answer(text)) is not None:
                # A yes or no typed under "Switch it on?" answers it like its button: sent on,
                # it was a chat message about nothing.
                self.fixing = fixing
                yield from self._apply_fix(self.fix_yes if yes else LEAVE_IT)
                return
            if just_asked and self.going_through:
                # The same for "Go through them now?", and only right under it: a yes typed
                # later belongs to something else, and this one moves files. A message that
                # begins with a yes or a no answers it too, and so does an order to go
                # through them: "yes, go through them" was taken for a pass over what had
                # landed since, and answered "Nothing new has landed".
                yes = _answers_yes(text)
                if yes is None and WANTS_PASS.search(text) and not ASKS_HOW.search(text) \
                        and not self._names_another_place(text, [a for a in store.list_agents() if parts.watches(a)]):
                    yes = True
                if yes is not None:
                    if self.all_asked:
                        yield from self._handle_choice(ALL_NOW, GO_THROUGH if yes else LEAVE_THEM)
                    else:
                        yield from self._handle_choice(FIRST_PASS, GO_THROUGH if yes else ONLY_NEW)
                    return
            if carry_asked and self.designer is not None and self.designer.aside is not None \
                    and (yes := _carry_answer(text)) is not None:
                # And for "Carry on with the helper?", the last thing said under the answer before.
                yield from self._handle_choice(CARRY_ON, CARRY_ON_YES if yes else DROP_IT)
                return
            if ruling and (yes := _plain_answer(text)) is not None:
                # And for "Should files like it always go there?".
                self.ruling = ruling
                yield from self._handle_choice(RULE_FROM_MOVE, CHANGE_THE_RULE if yes else JUST_THIS_ONE)
                return
            # A helper being worked out, a setup or an idea in progress gets the message
            # first; if the user moved on, it hands the message back for normal routing.
            for flow in (self.designer, self.builder, self.planner):
                if flow is not None and flow.active:
                    flow.handoff = None
                    yield from (flow.answer(text) if flow is self.planner else self._made(flow.answer(text)))
                    if flow.handoff is None:
                        return
                    text, flow.handoff = flow.handoff, None
                    if designing:
                        yield from self._waking()
            agents = store.list_agents()
            switchable = [a for a in agents if parts.is_switchable(a)]
            # What code decides about a helper they have (switch it, change it) it decides only
            # for one the message names. A helper whose rule merely shares a word with the
            # message is left to the router's model, which knows each rule: by the words
            # alone, "start a helper for explaining code" switched the Highlight Explainer on,
            # and "explain why I should update my drivers" began changing it.
            named = names_an_agent(text, switchable) or (
                self._called(text, switchable) if SWITCH_WORDS.search(text) else None)
            if named and (WANTS_ON.search(text) or WANTS_OFF.search(text)) and len(text.split()) <= 8 \
                    and not WANTS_NEW_AGENT.search(text):
                yield Thinking(f"This switches {named.name} {'off' if WANTS_OFF.search(text) else 'on'}.")
                yield from self._toggle(named.name, on=not WANTS_OFF.search(text))
                return
            if starter := asks_for(text):
                yield from self._add_starter(starter, switch_on=bool(WANTS_ON.search(text)))
                return
            if WANTS_DELETE.search(text) and agents:
                named = names_an_agent(text, agents) or self._called(text, agents, only=True)
                if named or HELPER_WORDS.search(text):
                    yield from self._confirm_delete(named.name) if named else self._ask_which_to_delete(agents)
                    return
            about = refers_to(text, agents, self.blueprints)
            if TROUBLE.search(text) and (about or len(switchable) == 1):
                # "it's not showing anything": find out why, don't change things blindly. The
                # trouble has to be about a helper: one named, or words for what such a helper
                # does. "My wifi isn't working" is not its trouble, and neither is "explain
                # why my code doesn't work" because "explain" is in a helper's name.
                suspect = names_an_agent(text, agents) or about or switchable[0]
                if names_an_agent(text, agents) or self._called(text, [suspect]) or self._trouble_about(text, suspect):
                    yield from self._diagnose(suspect, text)
                    return
            if (about := names_an_agent(text, agents)) and wants_change(text, about):
                # A change to an agent the user already has, named, decided in code.
                yield Thinking(f"This is a change to your {about.name}, not a new agent.")
                yield from self._change(about, text)
                return
            if (watchers := [a for a in agents if parts.watches(a)]) and not WANTS_NEW_AGENT.search(text):
                # What people ask a helper that works on a folder's files, answered in code
                # from its card and its records. Left to the chat model, it once said it
                # "couldn't see or move files" right after a move.
                answered = yield from self._about_files(text, think, watchers)
                if answered:
                    return
            if WANTS_IDEAS.search(text):
                yield from say(describe_ideas(*self._hardware(), self.blueprints))
                return
            if researcher.wants_research(text):
                yield from self._with_lookup(text, think, researcher.RESEARCH)
                return
            if lookup := self._lookup_kind(text):
                # A question that needs the web is a chat: the router's model call
                # would only say so, a second or two later.
                yield from self._with_lookup(text, think, lookup)
                return
            evidence = {a.name: runner.matching_words(a, text) for a in agents}
            where = route(self.ollama, noir.NOIR_MODEL, text, self.blueprints, agents,
                          think=self.chat.think, evidence=evidence)
            for name, words in evidence.items():
                if words and where.kind != "chat":
                    yield Thinking(f"{name}'s files mention: {', '.join(words)}.")
            if where.kind in ("new_agent", "idea"):
                yield from self._new_helper(text, where.blueprint if where.kind == "new_agent" else None, where.request)
            elif where.kind == "change_agent" and (agent := store.find_agent(where.agent)):
                yield Thinking(f"This is a change to your {agent.name}.")
                yield from self._change(agent, text, unsure=True)
                if self.designer is not None and self.designer.handoff is not None:
                    # The design model read the message and found it was about something
                    # else than that helper: it is a chat after all.
                    self.designer.handoff = None
                    yield from self._reply(text, think)
            elif where.kind == "run_agent":
                yield Thinking(f"This is a job for {where.agent}.")
                yield from self._run_agent(where.agent, where.request, text, think)
            else:
                if not self.auto_cloud:  # with Auto, _reply says who answers and why
                    yield Thinking(f"This is just a chat, so I'll ask {self.talker_name}." if self.talker_name
                                   else "This is just a chat, so I'll answer it myself.")
                if think and not self.chat.can_think and not self.talker_name:
                    yield Thinking("This model can't show its thinking, so here is my answer.")
                yield from self._reply(text, think)
        except OllamaError as exc:
            yield Error(str(exc))

    def _about_files(self, text: str, think: bool, watchers: list[store.Agent]):
        """A message that is for the helpers that work on a folder's files, or about them:
        why a file stayed, where one went, what they did, a file to put somewhere, the
        folder to go through now, a question about the work. Each is answered from the
        card and the records. Returns whether the message was one of those (a generator:
        use `yield from`).

        Each word rule counts only when the message is about files or a helper at all
        (_about_the_files): the words alone took everyday questions ("where should I go on
        vacation this summer?") for questions about the folders."""
        if WATCHES.search(text) or self._names_another_place(text, watchers):
            # Standing work on new files ("put every new download in a folder by what it's
            # about"), or work somewhere none of these helpers works ("can you organize all
            # my desktop files too?"): a helper to make, for the router and the conversation.
            # Taken here, the one went through Downloads and the other was asked "which file?".
            return False
        text_about = self._follows_a_chore(text)  # "where did they go?" a moment after a move: the files, never the web
        about = self._about_the_files(text, watchers)
        movers = [a for a in watchers if parts.mode(a.slots) == parts.CHOOSE]
        if WANTS_WHY.search(text) and about:
            yield Thinking("This asks why a file stayed or moved: the reason was kept for each one.")
            yield from self._say_why(text, watchers)
            return True
        if (WANTS_WHERE.search(text) or WHERE_WORDS.search(text)) and about:
            self.chore_spoken_at = time.time()
            yield Thinking("This asks where a file or folder is, which the record of what was done answers.")
            yield from self._say_where(text, watchers)
            return True
        if (status := WANTS_STATUS.search(text)) and (about or STATUS_ALONE.fullmatch(text[:status.start()] + text[status.end():])):
            self.chore_spoken_at = time.time()
            yield Thinking("This asks what has been done with your files: the record answers, not a guess.")
            yield from self._say_status(watchers)
            return True
        if movers and (placed := WANTS_PLACE.match(text)):
            found = self._file_named(placed.group(1), movers)
            if found or _NAMES_A_FILE.search(placed.group(1)) or text_about:
                self.chore_spoken_at = time.time()
                yield from self._place(found, placed.group(2), movers, text)
                return True
        if WANTS_PASS.search(text) and len(text.split()) <= 20 and not ASKS_HOW.search(text) \
                and not ASKS_FOR_WORK.search(text) and (about or PRONOUN_OBJECT.search(text)):
            # The one whose folder the message names, else one that is on, else the first.
            named = [a for a in watchers if (folder := Path(a.slots.get("folder") or "").name.lower()) and folder in text.lower()]
            chosen = next(iter(named), None) or next((a for a in watchers if self.folderwatch.is_on(a.name)), watchers[0])
            self.chore_spoken_at = time.time()
            if WANTS_EVERYTHING.search(text):
                yield from self._ask_all(chosen)
                return True
            yield Thinking(f"This is a job for {chosen.name}: what has landed since it was switched on.")
            yield from self._go_through(chosen, text=text)
            return True
        if (ABOUT_CHORES.search(text) or text_about) and WANTS_ANSWER.search(text) and not ASKS_FOR_WORK.search(text) \
                and not any(wants_change(text, a) for a in watchers) and self._asks_about_helper(text, watchers):
            self.chore_spoken_at = time.time()
            # "can it also take pictures?": a question about the work. Sent on, the router
            # once took one for an idea and began a second helper.
            yield from self._answer_about_chores(text, think)
            return True
        return False

    def _about_the_files(self, text: str, watchers: list[store.Agent]) -> bool:
        """Whether a message is about files or these helpers at all: it names a file on
        record or one of the helpers, has a word for files or folders, asks what was done
        with something ("why didn't you move..."), or follows straight on from a word about
        them."""
        return bool(self._names_a_file(text) or names_an_agent(text, watchers) or FILE_WORDS.search(text)
                    or YOU_HANDLED.search(text) or self._follows_a_chore(text))

    def _asks_about_helper(self, text: str, watchers: list[store.Agent]) -> bool:
        """Whether a question is about the helpers' own work, which their record answers: it
        names one of them or a file on record, follows straight on from them, or asks what
        "it" does ("is it still watching my downloads?"). A question that only has a word
        for files in it ("how do I zip a folder on windows?") is answered the usual way."""
        return bool(names_an_agent(text, watchers) or self._names_a_file(text) or self._follows_a_chore(text)
                    or HELPER_DOES.search(text))

    def _names_another_place(self, text: str, watchers: list[store.Agent]) -> bool:
        """Whether the message names one of the places people name (Desktop, Downloads...)
        that is none of the places these helpers watch, keep their folders in or write in."""
        own = set()
        for agent in watchers:
            for path in (agent.slots.get("folder") or "", parts.destination(agent.slots), parts.notes_path(agent.slots)):
                if str(path):
                    own.add(Path(parts.short_place(Path(path))).parts[0].lower() if Path(path).parts else "")
        return any(re.search(said, text, re.IGNORECASE) and place.lower() not in own for place, said in PLACE_SAID.items())

    def _called(self, text: str, agents: list[store.Agent], only: bool = False) -> store.Agent | None:
        """The one helper the message calls by a word of its name said whole: "the explainer"
        for Highlight Explainer, "my fixer" for Word fixer. A word that only begins like one
        ("explain") is no name. `only`: the message says nothing but that, with what to do
        to it ("delete my fixer", not "remove the grammar mistakes")."""
        said = re.findall(r"[a-z가-힣']+", text.lower())
        found = []
        for agent in agents:
            names = {word for word in re.findall(r"[a-z가-힣]+", agent.name.lower()) if len(word) >= 4}
            names -= {"helper", "agent", "assistant", "text", "word", "words"}
            if not names & set(said):
                continue
            if only and [word for word in said if word not in names and word not in _CALLING_WORDS]:
                continue
            found.append(agent)
        return found[0] if len(found) == 1 else None

    def _trouble_about(self, text: str, suspect: store.Agent) -> bool:
        """Whether a report of trouble that names no helper is about what this one does: for
        one that works on a folder's files, the files; for any other, the highlight, the
        bubble or the result it shows, or a helper at all."""
        if parts.watches(suspect):
            return bool(ABOUT_CHORES.search(text) or self._follows_a_chore(text, asks=False))
        return bool(HIGHLIGHT_WORDS.search(text) or SHOW_WORDS.search(text) or COPY_WORDS.search(text)
                    or HELPER_WORDS.search(text))

    def _ask_all(self, agent: store.Agent) -> Iterator[Event]:
        """Every file in the folder, asked for in words: counted and asked about first. It
        takes the ones that were there before the helper too, which "only new files from
        now on" had left alone."""
        count = self.folderwatch.count_files(agent)
        folder = parts.shown_place(Path(agent.slots.get("folder") or ""))
        if not count:
            yield from say(f"There is nothing in {folder} to go through right now.")
            return
        self.going_through, self.just_asked, self.all_asked = agent.name, True, True
        yield Thinking(f"This asks {agent.name} to go through everything in {folder}, the files from before too, so "
                       "I'll ask first.")
        there = f"There {'is' if count == 1 else 'are'} {_count(count, 'file')} in {folder}"
        since = (f", the ones from before {agent.name} was switched on as well" if self.folderwatch.is_on(agent.name)
                 else f". {agent.name} is switched off, so it hasn't been watching")
        yield Question(ALL_NOW, f"{there}{since}. Go through all of them now?", [GO_THROUGH, LEAVE_THEM])

    def _reply(self, text: str, think: bool, attached_chars: int = 0, where: str = "") -> Iterator[Event]:
        """where: auto.CLOUD to skip Auto's decision ("Ask Claude instead")."""
        done = NoirDone()
        if self.auto_cloud is not None:
            done = yield from self._auto_choose(text, attached_chars, where)
        said = False
        here = self._writes_here()
        try:
            for event in self._answer(text, think):
                said = said or isinstance(event, NoirText)
                yield event
        except cloud.CloudError as exc:
            if said or self.chat.talker is self.ollama or not self.auto_cloud:
                raise
            # The plan said no (signed out, used up, no internet) before a word was
            # written: Auto exists to keep it talking, so it answers itself.
            yield Thinking(f"{self.talker_name} couldn't answer ({exc}), so I'll answer myself.")
            self.chat.talker = self.ollama
            self.auto_last = auto.HERE
            done, here = NoirDone(by=self._own_name()), True
            yield from self._answer(text, think)
        finally:
            if self.auto_cloud is not None:
                self.chat.talker = self.ollama  # agents and the router stay here with Auto
        if note := safety.caution(text):
            yield NoirText(f"\n\n{note}")
        activity.record(activity.ANSWERED)
        if getattr(self, "found", None) is not None:  # the sources and pictures go under this answer
            done = replace(done, sources=list(self.found.sources), images=list(self.found.images))
            self.found = None
        yield self._answered(done, here)

    def _writes_here(self) -> bool:
        """Whether the model about to answer is on this computer."""
        if self.chat.talker is self.ollama:
            return True
        if self.auto_cloud is not None:
            return False  # with Auto, anything but its own model is the plan
        chosen = self.menu.chosen()
        return not chosen or bool(chosen.get("here"))

    def _answered(self, done: NoirDone, here: bool) -> NoirDone:
        """The reply's NoirDone with where it was written, for the dot under it:
        the tokens an answer written here saved (Auto only, since only then was
        there a plan it would have gone to), or how full the plan is after one from it."""
        chosen = self.menu.chosen() or {}
        source = (chosen.get("cloud") or chosen).get("provider", "")
        if here:
            saved = 0
            if self.auto_cloud is not None and source:
                saved = usage.saved_estimate(source, *getattr(self.ollama, "last_tokens", (0, 0)))
                usage.record_saved(source, saved)
            return replace(done, where=auto.HERE, saved=saved)
        plan_used = self.menu.plan_used(source) if source in APPS else -1.0
        return replace(done, where=auto.CLOUD, plan_used=plan_used, by=done.by or self.talker_name)

    # ----------------------------------------------------------- the web

    def _lookup_kind(self, text: str) -> str | None:
        """Whether this message needs the web, and for what. Code decides from the
        words; only a question code can't place is put to its model, as one word."""
        if ASKS_FOR_WORK.search(text) or WATCHES.search(text):
            return None  # a request for new work ("when a pdf lands, write me a note about it") is never a lookup
        if OWN_THINGS.search(text):
            return None  # their own folders, files and photos are on this computer, not on the web
        if ABOUT_CHORES.search(text) and any(parts.watches(a) for a in store.list_agents()):
            # "is it still watching my downloads?", "can it also take pictures?": about a chore
            # of its own, answered here from its facts; "pictures" would otherwise send it to
            # an image search.
            return None
        kind = research.wants_lookup(text)
        if kind is None and research.allowed() is not False and research.unsure(text):
            kind = research.SEARCH if research.model_form(self.ollama, noir.NOIR_MODEL)(text) else None
        return kind

    def _with_lookup(self, text: str, think: bool, kind: str) -> Iterator[Event]:
        """Answer from the web: after the user's one-time yes, look it up, hand it what
        was found along with the question, and put the sources under its answer."""
        may = research.allowed()
        if may is None:
            self.pending_lookup = (text, think, kind)
            yield Thinking("This can change from day to day, so I'd rather look it up than guess.")
            yield Question(research.WEB, research.WEB_QUESTION, [research.YES_LOOK, research.NO_LOOK])
            return
        if not may:
            yield Thinking("This may have changed since I learned it, and you've asked me not to look things "
                           "up on the web, so this is from memory.")
            yield from self._reply(text, think)
            return
        if kind == researcher.RESEARCH:
            yield from self._research_job(text, think)
            return
        what = {research.WEATHER: "the weather", research.IMAGES: "pictures", research.PRICE: "the price"}.get(kind, "this")
        yield Thinking(f"This changes from day to day, so I'm looking {what} up on the web.")
        yield Progress("Looking it up on the web...")
        try:
            self.found = research.look_up(text, kind)
        except Exception as exc:  # the web, not Ollama: whatever failed, it still answers
            self.found = None
            yield Thinking(f"The web didn't answer ({type(exc).__name__}), so this is from memory and may be "
                           "out of date.")
            yield from self._reply(text, think)
            return
        self.chat.attach(research.note(self.found), [])
        # With Auto, pages worth of findings go to the plan, which reads long text far
        # better than its 4B model; the weather or a price is short and stays here.
        yield from self._reply(text, think, attached_chars=len(self.found.text))

    def _research_job(self, text: str, think: bool) -> Iterator[Event]:
        """"Research X" (researcher.py): the plan model plans the searches and at the end
        merges the summaries and checks them; its own model reads each page. Every step
        is said in its thinking with its tokens, and the end counts what the plan paid
        against what it would have paid doing every step itself."""
        chosen = self.menu.chosen() or {}
        target = chosen.get("cloud") or chosen
        talker = self.auto_cloud or (self.chat.talker if self.chat.talker is not self.ollama else None)
        model = target.get("model", "")
        boss = self.talker_name
        if talker is not None and self.auto_cloud is not None:
            # With Auto, the plan's fast model merges: care matters here, depth doesn't,
            # and the slow one took 15 of the first job's 37 seconds.
            try:
                system = self.ollama.show(noir.NOIR_MODEL).get("system", "")
            except OllamaError:
                system = ""
            if fast := self.menu.fast_talker(system):
                talker, found = fast
                model, boss = found["model"], found["name"]
        source = target.get("provider", "") if talker is not None else ""
        own = self._own_name()
        boss = boss if talker is not None else own
        account = researcher.Account(source=source)

        def talk(system: str, user: str) -> Iterator[str]:
            """One call to the reviewer, streamed, its tokens counted once it ends."""
            if talker is None:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                yield from self.ollama.chat(noir.NOIR_MODEL, messages, think=False, keep_alive=noir.KEEP_ALIVE)
                read, wrote = getattr(self.ollama, "last_tokens", (0, 0))
                account.local_calls, account.local_read, account.local_wrote = (
                    account.local_calls + 1, account.local_read + read, account.local_wrote + wrote)
                return
            # The plan's apps take one question at a time and drop system messages
            # (accounts.transcript), so the note goes in front of the question.
            before = researcher.last_plan_answer(source)
            yield from talker.chat(model, [{"role": "user", "content": f"{system}\n\n{user}"}])
            read, wrote = researcher.plan_tokens_after(source, before)
            account.plan_calls, account.plan_read, account.plan_wrote = (
                account.plan_calls + 1, account.plan_read + read, account.plan_wrote + wrote)

        def form(system: str, user: str, schema: dict) -> dict:
            """Its own model fills the plan: as good as the plan model's, six times faster, free."""
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            filled = self.ollama.chat_json(noir.NOIR_MODEL, messages, schema, think=False)
            read, wrote = getattr(self.ollama, "last_tokens", (0, 0))
            account.local_calls, account.local_read, account.local_wrote = (
                account.local_calls + 1, account.local_read + read, account.local_wrote + wrote)
            return filled

        try:
            if talker is None:
                yield Thinking(f"Research job with no plan connected, so {own} does every step: plan the searches, "
                               "read each page, then merge and check.")
            else:
                yield Thinking(f"Research job: {own} plans the searches and reads each page on this computer, "
                               f"then {boss} merges the summaries and checks them.")
            yield Progress("Planning the searches...")
            queries, goal = researcher.plan(form, text)
            yield Thinking(f"{own} asked for {len(queries)} search{'es' if len(queries) != 1 else ''}: "
                           f"{'; '.join(queries)}. Goal: {goal}")
            yield Progress(f"Running {len(queries)} search{'es' if len(queries) != 1 else ''} at once, picking the "
                           "pages worth reading...")
            pages, choices = researcher.gather(text, queries, judge=sources.judge_with(form))
            picked_line, dropped_line = sources.said(choices)
            if choices:
                yield Thinking(picked_line)
            if dropped_line:
                yield Thinking(dropped_line)
            if not pages:
                yield Thinking("The searches found no page I could read, so this is from memory.")
                yield from self._reply(text, think)
                return
            for number, page in enumerate(pages, 1):
                yield Progress(f"Worker {number} of {len(pages)} reads {page.site}...")
                researcher.summarise(self.ollama, noir.NOIR_MODEL, text, page)
                account.local_calls, account.local_read, account.local_wrote = (
                    account.local_calls + 1, account.local_read + page.read, account.local_wrote + page.wrote)
                first = page.summary.splitlines()[0][:120] if page.summary else ""
                yield Thinking(f"Worker {number} ({own}) read {page.site}: {page.read:,} tokens in, {page.wrote:,} out. "
                               f"{first if page.useful else 'Nothing relevant on that page.'}")
            useful = [page for page in pages if page.useful]
            if not useful:
                yield Thinking("None of the pages said anything about it, so this is from memory.")
                yield from self._reply(text, think)
                return
            yield Thinking(f"{boss} merges {len(useful)} summaries, checks them against each other and writes the brief.")
            yield Progress("Writing the brief...")
            said: list[str] = []
            for piece in researcher.merge(talk, text, goal, useful, researcher.when_now()):
                said.append(piece)
                yield NoirText(piece)
        except cloud.CloudError as exc:
            yield Error(f"{boss} couldn't finish the research ({exc}). Try again, or pick another model.")
            return
        brief = "".join(said).strip()
        if note := safety.caution(text):  # health and money, the same plain note as any answer
            yield NoirText(f"\n\n{note}")
        researcher.settle(account, text)
        for line in researcher.account_lines(account, boss, own):
            yield Thinking(line)
        self.chat.remember(text, brief)
        activity.record(activity.ANSWERED)
        activity.record(activity.READ, len(useful))
        if source and account.saved:
            usage.record_saved(source, account.saved)
        yield NoirDone(by=boss, where=auto.CLOUD if source else auto.HERE, saved=account.saved,
                         plan_used=self.menu.plan_used(source) if source in APPS else -1.0,
                         sources=researcher.sources_of(useful))

    def _waking(self) -> Iterator[Event]:
        """Its model isn't in memory yet (the first message after the app opens, or after
        a while away), so the first word takes a few seconds longer: say so, or the window
        sits silent and looks stuck."""
        try:
            loaded = {m["name"].split(":")[0] for m in self.ollama.loaded()}
        except Exception:
            return  # Ollama didn't answer; the message itself will say what's wrong
        if noir.NOIR_MODEL not in loaded:
            yield Thinking("Loading my model into memory first, which takes a few seconds.")

    def _answer(self, text: str, think: bool, about_chores: bool = False) -> Iterator[Event]:
        # What its chores are doing goes with every answer; how they work, only with a
        # question about them, since its model has little room to read in.
        self.chat.jobs = self._chores_note(full=about_chores)
        # Small talk gets no thinking: its model thought to its limit over "how are you",
        # then wrote the answer a second time, so a greeting took the longest of all.
        if think and self.chat.can_think and voice.kind_of(text) != "small_talk":
            for kind, piece in self.chat.think_through(text):
                yield Thinking(piece, "thought") if kind == "thought" else NoirText(piece)
        else:
            for chunk in self.chat.send(text):
                yield NoirText(chunk)

    def _auto_choose(self, text: str, attached_chars: int, where: str):
        """Auto: its own model or the plan, for this one message. Says which and why,
        and returns the NoirDone that names who answered."""
        chosen = self.menu.chosen() or {}
        target = chosen.get("cloud") or {}
        if where == auto.CLOUD:
            decision = auto.Decision(auto.CLOUD, "asked", "user")
        else:
            decision = auto.decide(text, base_model=noir.load_state().get("base_model", ""), after=self.auto_last,
                                   plan_used=self.menu.plan_used(target.get("provider", "")),
                                   attached_chars=attached_chars,
                                   ask_model=auto.model_form(self.ollama, noir.NOIR_MODEL))
            if getattr(self, "found", None) is not None and decision.where == auto.CLOUD:
                yield Thinking(f"Auto: there's a lot to read from the web, so {self.talker_name} reads it.")
            else:
                yield Thinking(auto.say(decision, self.talker_name, plan=target.get("provider") in APPS))
        self.auto_last = decision.where
        if decision.where == auto.CLOUD:
            self.chat.talker = self.auto_cloud
            return NoirDone(by=self.talker_name)
        self.chat.talker = self.ollama
        self.auto_kind = decision.kind
        auto.record(decision.kind)
        return NoirDone(by=self._own_name(), instead=self.talker_name)

    def _own_name(self) -> str:
        tag = noir.load_state().get("base_model", "")
        model = find_model(tag) if tag else None
        return model.name if model else "Noir"

    def ask_again(self) -> Iterator[Event]:
        """"Ask Claude instead" under an answer Auto kept on this computer: the same
        question again, from the plan, and counted so wrongly placed kinds show up."""
        history = self.chat.history if self.chat else []
        if not self.auto_cloud or len(history) < 2 or history[-1]["role"] != "assistant":
            yield Error("There's nothing to ask again right now.")
            return
        text = history[-2]["content"]
        del history[-2:]  # replaced by the new answer, so it doesn't remember both
        auto.record(self.auto_kind or "unclear", asked_again=True)

        def again() -> Iterator[Event]:
            yield Thinking(f"Asking {self.talker_name} instead.")
            try:
                yield from self._reply(text, False, where=auto.CLOUD)
            except OllamaError as exc:
                yield Error(str(exc))

        self.carry_asked = False
        yield from self._full_lists(self.book.record(f"Ask {self.talker_name} instead", self._then_carry_on(again())))

    def _with_attachments(self, text: str, attached: Attached, think: bool) -> Iterator[Event]:
        self.deleting = None
        self.fixing = None
        self.ruling = None
        self.just_asked = self.carry_asked = False
        yield from self._waking()
        try:
            for name in attached.unread:
                yield Thinking(f"I couldn't read {name}.")
            if attached.folders:
                # One helper is made at a time. A folder added while another was being worked
                # out started the plain questions beside it, and the card those showed went
                # to the other conversation when clicked: nothing was made, and both stayed.
                left = self.designer and (self.designer.sketch or self.designer.aside)
                if left:
                    kept = f"{left.replaces} is as it was" if left.editing else "nothing was created"
                    yield Thinking(f"This begins another one, so I've left the helper we were working out: {kept}.")
                    self._drop_design()
                if self.planner is not None:
                    self.planner.draft = None
                yield Thinking("A folder is what a documents agent is for, so I'll set one up.")
                yield from self._made(self.builder.start_for_folder(parts.DOCUMENTS_QA, Path(attached.folders[0]), text))
                return
            images = attached.images
            if images and not self.chat.can_see:
                images = []
                yield Thinking("The model I'm using can't look at pictures.")
                if not attached.context:
                    yield from say("The model I'm using can't look at pictures. Pick one that can from the model "
                                   "menu, then send it again.")
                    return
            if not attached.context and not images:
                yield from say("I couldn't read that. I can read PDF, Word and text files, and pictures.")
                return
            read = [name for name in attached.names if name not in attached.unread]
            yield Thinking(f"Read {', '.join(read)}.")
            self.chat.attach(attached.context, images)
            yield from self._reply(text or NOTHING_SAID, think, attached_chars=len(attached.context))
        except OllamaError as exc:
            yield Error(str(exc))

    def _use_chosen_model(self) -> None:
        """Only its answers move to the model picked in the menu. Deciding what a
        message is for stays with its own small model, and so do agents that read
        every highlight: those see whatever the user selects, in any program, so
        that must never leave the computer without them asking each time."""
        chosen = self.menu.chosen()
        is_auto = bool(chosen and chosen.get("auto"))
        self.talker_name = (chosen["cloud"]["name"] if is_auto else chosen["name"]) if chosen else ""
        self.auto_last = ""
        if self.chat is None:
            return
        try:
            system = self.ollama.show(noir.NOIR_MODEL).get("system", "") if chosen else ""
        except OllamaError:
            system = ""
        talker = self.menu.talker(system) or self.ollama
        # With Auto its own model is the one in use; the plan only answers what
        # _auto_choose sends it, one message at a time.
        self.auto_cloud = talker if is_auto else None
        self.chat.talker = self.ollama if is_auto else talker
        # A plan or key model draws well enough to add a drawing unasked; its own 4B
        # model only draws when asked to (voice.DRAW_WORDS).
        self.chat.draws = talker is not self.ollama and not is_auto

    def _handle_choice(self, id: str, choice: str) -> Iterator[Event]:
        # Whatever is asked after this click, a yes typed then is not for "go through them?",
        # nor for a question about a helper set aside or a file put somewhere by hand.
        self.just_asked = self.carry_asked = False
        if id != RULE_FROM_MOVE:
            self.ruling = None
        if id == research.WEB:
            research.allow(choice == research.YES_LOOK)
            pending, self.pending_lookup = self.pending_lookup, None
            if pending:
                try:
                    yield from self._with_lookup(*pending)
                except OllamaError as exc:
                    yield Error(str(exc))
            else:
                yield from say("Okay." if choice == research.YES_LOOK else "Okay, I'll answer from what I know.")
        elif id == PICK_AGENT_TO_DELETE:
            yield from self._confirm_delete(choice) if store.find_agent(choice) else say("Okay, nothing deleted.")
        elif id == DELETE_AGENT:
            yield from self._finish_delete(choice)
        elif id == FIX_AGENT:
            yield from self._apply_fix(choice)
        elif id in (IDEA, IDEA_CHANGE) and self.planner and self.planner.active:
            taken = self.planner.take_plan() if choice == MAKE_IT else None
            try:
                if taken:  # every block is ready: make it
                    yield from self._make(*taken)
                elif choice == MAKE_IT:
                    yield from say("That one can't be made yet.")
                else:
                    yield from self.planner.choose(id, choice)
            except OllamaError as exc:
                yield Error(str(exc))
        elif id == FIRST_PASS:
            name, self.going_through = self.going_through, None
            self.all_asked = False
            agent = store.find_agent(name) if name else None
            if choice == GO_THROUGH and agent:
                yield from self._go_through(agent, everything=True)
            else:
                yield from say("Okay, only new files from now on.")
        elif id == ALL_NOW:
            name, self.going_through = self.going_through, None
            self.all_asked = False
            agent = store.find_agent(name) if name else None
            if agent is None:
                yield from say("That question has already been answered.")
            elif choice == GO_THROUGH:
                yield from self._go_through(agent, everything=True)
            else:
                yield from say("Okay, I left them where they are.")
        elif id == CARRY_ON:
            yield from self._carry_on(choice)
        elif id == RULE_FROM_MOVE:
            try:
                yield from self._rule_from_move(choice)
            except OllamaError as exc:
                yield Error(str(exc))
        elif self.designer is not None and self.designer.active:
            # The designing conversation's own questions: one in words, a choice among a few,
            # a helper they already have, and the card.
            try:
                yield from self._made(self.designer.choose(id, choice))
            except OllamaError as exc:
                yield Error(str(exc))
            self.designer.handoff = None  # a click is never a message to answer as a chat
        elif self.builder and self.builder.active:
            try:
                yield from self._made(self.builder.choose(id, choice))
            except OllamaError as exc:
                yield Error(str(exc))
        else:
            yield Error("Nothing is waiting for an answer right now.")

    def _clear_conversation_state(self) -> None:
        """Unfinished setups, questions and Noir's memory belong to the
        conversation being left. Call only after the book has saved it."""
        self.deleting = None
        self.going_through = None
        self.all_asked = False
        self.ruling = None
        self.carry_asked = False
        # A question asked in the conversation being left is no question in the next one: a
        # "yes" typed in a new chat switched on a helper that "Switch it on?" had been about.
        self.fixing, self.fix_yes = None, ""
        self.just_asked = False
        self.pending_lookup = None
        self.chore_spoken_at = 0.0
        self._drop_design()
        if self.builder:
            self.builder.draft = None
        if self.planner:
            self.planner.draft = None
        if self.chat:
            self.chat.reset()

    def _drop_design(self) -> None:
        """A helper that was being worked out is left there, and so is one that was set
        aside: nothing was made, and a design model on this computer leaves the graphics
        memory. (One set aside let go of its model when it was set aside.)"""
        if self.designer is None:
            return
        if self.designer.sketch is not None:
            self.designer.sketch.model.done()
            self.designer.sketch = None
        self.designer.aside = None

    # ------------------------------------------- a helper set aside for something else

    def _then_carry_on(self, events: Iterator[Event], quiet: bool = False) -> Iterator[Event]:
        """One exchange, and under it, while a helper that was being worked out waits set
        aside, the question whether to carry on with it. What they asked is answered first
        and whole. The question comes again under each answer for as long as the helper
        waits: the buttons of an earlier question stop working once something else is
        typed, so only the last one can be clicked. It does not come under an answer that
        ends in a question or a card of its own (it comes under the next one), and when
        another helper was begun meanwhile the one set aside is left. `quiet`: this is no
        moment to ask (safety.py)."""
        asks = False
        for event in events:
            if isinstance(event, (Question, AgentCard, IdeaCard)):
                asks = True
            elif isinstance(event, (NoirText, Result, Error)):
                asks = False
            yield event
        designer = getattr(self, "designer", None)
        if designer is None or designer.aside is None:
            return
        if any(flow is not None and flow.active for flow in (designer, self.builder, self.planner)):
            designer.aside = None  # another helper is being made now
            return
        if asks or quiet:
            return
        aside = designer.aside
        self.carry_asked = True
        yield Question(CARRY_ON, f"Carry on with the changes to {aside.replaces}?" if aside.editing
                       else "Carry on with the helper we were working out?", [CARRY_ON_YES, DROP_IT])

    def _carry_on(self, choice: str) -> Iterator[Event]:
        """The answer to that question: the helper comes back as it stood, or is left."""
        designer = self.designer
        if designer is None or designer.aside is None:
            yield from say("That question has already been answered.")
        elif choice == CARRY_ON_YES:
            yield from designer.carry_on()
        elif choice == DROP_IT:
            yield from designer.drop()
        # Anything else is no answer: the helper goes on waiting, and the question comes again.

    # ------------------------------------------------------ making a helper

    def _can_design(self) -> bool:
        """Whether a helper can be worked out in a conversation right now."""
        return self.designer is not None and self.designer.available()

    def _new_helper(self, text: str, blueprint: str | None, request: str) -> Iterator[Event]:
        """A helper is wanted. Whenever a model can hold the conversation, it is worked out
        there, from nothing: what the router made of the request is not passed on. Without
        one, the plain way makes what it can; a helper for the files that land in a folder
        is not among that, and is told so rather than half made."""
        if self._can_design():
            yield Thinking("This asks for a new helper, so we'll work out together what it should do.")
            yield from self._made(self.designer.start(text))
        elif WATCHES.search(text):
            yield Thinking("This asks for a helper that works on files as they land, which can only be worked out "
                           "by talking it through.")
            yield from say(NO_DESIGNER)
        elif blueprint in self.blueprints:
            yield Thinking(f"This asks for a new agent: {self.blueprints[blueprint].name}.")
            yield from self._made(self.builder.start(blueprint, text))
        else:
            yield Thinking("This is an idea for a new kind of helper, so I'll check what it needs.")
            yield from self._idea(text, request or text)

    def _change(self, agent: store.Agent, text: str, unsure: bool = False) -> Iterator[Event]:
        """A change to a helper they have. A card is changed by talking it through whenever
        a model can hold that conversation. Without one, a card that works on text and a
        helper that answers from documents are changed the plain way, setting by setting;
        one that works on a folder's files can't be, since its rule is the whole of it.
        `unsure`: only the router's model took the message for a change (designer.edit)."""
        if agent.blueprint == parts.CUSTOM and self._can_design():
            yield from self._made(self.designer.edit(agent, text, unsure=unsure))
        elif parts.watches(agent):
            yield from say(f"I can't change {agent.name} by myself. {NO_DESIGNER}")
        else:
            yield from self._made(self.builder.edit(agent, text))

    def _idea(self, text: str, request: str) -> Iterator[Event]:
        """Talk an idea through the plain way; when every part already exists, make it at
        once instead of showing the idea card."""
        for event in self._remember_ideas(text, self.planner.start(request)):
            if isinstance(event, IdeaCard) and event.level == "ready":
                yield from self._make(*self.planner.take_plan())
                return
            yield event

    def _make(self, blueprint: str, request: str, blocks: list[str]) -> Iterator[Event]:
        """Make an idea whose every part exists. By now a model may be there to work it out
        with (the user picked one since); without one, the plain way makes a helper that
        works on text or answers from documents, and says so when the idea is one that
        works on a folder's files."""
        if self._can_design():
            yield Thinking("Every part exists, so we can work it out together now.")
            yield from self._made(self.designer.start(request))
        elif blueprint == parts.CUSTOM and FILE_PARTS & set(blocks):
            yield Thinking("Every part exists, but a helper that works on files can only be worked out by "
                           "talking it through.")
            yield from say(NO_DESIGNER)
        elif blueprint == parts.CUSTOM:
            yield Thinking("Every part already exists, so I can build it now.")
            yield from self._made(self.builder.compose(request, blocks))
        else:
            yield Thinking("Every part already exists, so I can build it now.")
            yield from self._made(self.builder.start(blueprint, request))

    def _add_starter(self, starter: Starter, switch_on: bool) -> Iterator[Event]:
        """A ready-made agent: added at once, and switched on if the user said so."""
        agent = store.find_agent(starter.name)
        if agent is None:
            yield Thinking(f"{starter.name} is ready-made, so there's nothing to set up.")
            agent = install(starter)
        if not parts.is_switchable(agent):
            yield from say(f"{agent.name} is ready. {self._ask_it_line(agent)}")
        elif switch_on:
            yield from self._toggle(agent.name, on=True)
            return
        else:
            yield from say(f'{agent.name} is ready. Say "turn on {agent.name}" or use its switch, then '
                           "highlight text in any program.")
        yield self._agent_list()

    def _is_on(self, agent: store.Agent) -> bool:
        if parts.watches(agent):
            return self.folderwatch.is_on(agent.name)
        return bool(self.quick and self.quick.is_on(agent.name))

    def _design_model(self) -> DesignModel | None:
        """Who works a helper out with the user (agents/designer.py). A plan or key model
        the user picked, or the one Auto sends hard questions to: it is the better model,
        and this is the rare conversation where that matters most. Else a model on this
        computer that passed designer_eval, is installed and fits beside Noir's own. Else
        nobody. A local model picked in the menu doesn't design unless it is on that list:
        a bigger one decided worse than a smaller."""
        if not self.designs or self.chat is None:
            return None
        chosen = self.menu.chosen()
        talker = self.auto_cloud or self.chat.talker
        if chosen and not chosen.get("here") and talker is not self.ollama:
            return DesignModel(talker_form(talker), self.talker_name, here=False)
        model = self._local_designer()
        if model is None:
            return None
        tag = model.tag
        fill = local_form(self.ollama, tag)

        def loaded() -> bool:
            return any(m["name"] in (tag, f"{tag}:latest") for m in self.ollama.loaded())

        def form(note: str, turns: list[dict], schema: dict) -> dict:
            # While the design model talks, Noir's own model isn't asked anything, so it
            # makes room first: the two together, with what the desktop takes, fill a 16 GB
            # card (9.2 + 3.9 + 2.6, measured). That holds whenever the design model has to
            # come in, not only at its first turn: a try-out in between is the built-in
            # model's work, for which the design model left and Noir's own came back.
            try:
                if not loaded():
                    self.ollama.unload(noir.NOIR_MODEL)
            except Exception:  # noqa: BLE001 - Ollama busy: both stay loaded this once
                pass
            return fill(note, turns, schema)

        return DesignModel(form, model.name, here=True, loaded=loaded, release=lambda: self.ollama.unload(tag))

    def _local_designer(self) -> ModelEntry | None:
        """The first model on the designers list (models.yaml) that is installed and fits
        in the graphics memory Noir's own model leaves free. Never on the processor: a turn
        would take most of a minute there."""
        list_models = getattr(self.ollama, "list_models", None)
        try:
            installed = set(list_models()) if list_models else set()
        except OllamaError:
            return None
        listed = [model for model in load_designers() if model.tag in installed or f"{model.tag}:latest" in installed]
        if not listed:
            return None
        room, on_cpu = helper_room(*self._hardware())
        return next((model for model in listed if not on_cpu and model.memory_gb <= room), None)

    def _built_in_name(self) -> str:
        """What the built-in model is called, for a card's "Runs on" line: "" when it isn't known."""
        tag = noir.load_state().get("base_model", "")
        model = find_model(tag) if tag else None
        return model.name if model else tag

    def _made(self, events: Iterator[Event]) -> Iterator[Event]:
        """The events of a conversation in which a helper is made or changed, then what
        follows once one was. That goes by what the card is made of, the same however it
        was made: one that works on a folder's new files is switched on and offered a first
        pass over the folder, one that works on highlights is switched on and says how it
        is used, one that is asked in the chat says how to ask it. (A helper that answers
        from documents is finished where it is made, and says so itself.)"""
        # Which ones are on is noted first: once the conversation has saved a helper, the
        # lists are brought in step with what is saved, and a name that is gone is off by then.
        on_before = {*self.folderwatch.active, *(self.quick.active if self.quick else ())}
        yield from events
        for flow in (self.designer, self.builder):
            if flow is None:
                continue
            created, edited = flow.take_created(), flow.edited
            replaced, flow.replaced = flow.replaced, None
            was_on = False
            if replaced:
                # A change gave it another name: nothing may be left working, or kept, under
                # the old one. If it was on, it carries on under the new one.
                was_on = replaced in on_before
                self.folderwatch.forget(replaced)
                self._settled(replaced)
                if self.quick:
                    self.quick.refresh(store.list_agents())
            if created is not None:
                yield from self._after_made(created, edited, was_on)
                return
            if replaced:
                yield self._agent_list()

    def _after_made(self, agent: store.Agent, edited: bool, was_on: bool) -> Iterator[Event]:
        """What follows for one card that was just made, or (edited) changed. `was_on`: it
        was switched on under the name it had before."""
        watches = parts.watches(agent)
        highlights = parts.is_switchable(agent) and not watches
        stopped = False
        if edited:
            self._settled(agent.name)  # one an update had switched off: its rule has been talked through now
        kept = (self.folderwatch.since, self.folderwatch.made, self.folderwatch.skipped)
        if not watches and (self.folderwatch.is_on(agent.name) or any(agent.name in one for one in kept)):
            # It worked on a folder until this change, and no longer does: it stops there,
            # and what was kept about that folder goes.
            self.folderwatch.forget(agent.name)
            stopped = True
        if self.quick and not highlights and self.quick.is_on(agent.name):
            self.quick.switch(agent, False)  # it worked on highlights until this change
            stopped = True
        if watches:
            yield from self._after_watcher(agent, edited, was_on)
        elif highlights:
            yield from self._after_highlighter(agent, edited, was_on)
        else:
            if stopped:
                yield self._agent_list()
            if not edited:
                yield from say(self._ask_it_line(agent))

    def _after_watcher(self, agent: store.Agent, edited: bool, was_on: bool) -> Iterator[Event]:
        """A card that works on a folder's new files was made or changed. A new one is
        switched on at once, and only what lands from then on counts: the files already
        there are asked about, never taken. A changed one stays as it was, on or off."""
        self.folderwatch.refresh(store.list_agents())  # one that is on works by the changed card from here
        name = agent.name
        if edited and self.folderwatch.is_on(name):
            yield self._agent_list()
            yield from say("It's on, and works the new way from the next file that lands.")
            return
        if edited and not was_on:
            yield self._agent_list()
            self.fixing, self.fix_yes = (name, {}, True), SWITCH_IT_ON
            yield Question(FIX_AGENT, f"{name} is switched off right now. Switch it on?", [SWITCH_IT_ON, LEAVE_IT])
            return
        self._switch_watcher(agent, True)
        yield self._agent_list()
        on = self._watching_line(agent)
        if edited:
            yield from say(on)
            return
        yield Thinking("Each new file's name is judged by the built-in model on this computer, so nothing leaves it."
                       if agent.slots.get("looks_at") == parts.NAME_ONLY else
                       "Each new file is read and judged by the built-in model on this computer, so nothing leaves it.")
        count = self.folderwatch.count_files(agent)
        if count:
            self.going_through, self.just_asked, self.all_asked = name, True, False
            there = f"There {'is' if count == 1 else 'are'} {_count(count, 'file')} there already."
            yield Question(FIRST_PASS, f"{on} {there} Go through them now?", [GO_THROUGH, ONLY_NEW])
        else:
            yield from say(on)

    def _after_highlighter(self, agent: store.Agent, edited: bool, was_on: bool) -> Iterator[Event]:
        """A card that works on highlighted text was made or changed. A new one is switched
        on and says how it is used; a changed one stays as it was, on or off."""
        if self.quick is None:
            yield self._agent_list()
            if not edited:
                yield from say(f"{agent.name} works on text you highlight, which I can read on Windows only for now.")
            return
        if edited and not was_on:
            self.quick.refresh(store.list_agents())  # a change reaches one that is on at once
            yield self._agent_list()
            return
        self.quick.switch(agent, True)
        yield self._agent_list()
        yield from say(f"It's on. {self._highlight_line(agent)}")

    def _watching_line(self, agent: store.Agent) -> str:
        """What is said when a card that works on a folder's new files is on."""
        folder = parts.shown_place(Path(agent.slots.get("folder") or ""))
        return (f"It's on: new files in {folder} are handled as they land, and everything it does shows in your "
                "chores.")

    def _highlight_line(self, agent: store.Agent) -> str:
        """How a card that works on highlights is used, once it is on."""
        how = {CLIPBOARD: "and the result is copied, ready to paste",
               BOTH: "and the result appears above it and is copied"}.get(
                   agent.slots.get("show"), "and the result appears right above it")
        return (f"Highlight text in any program {how}. "
                f'Say "turn off {agent.name}" or use its switch to stop it.')

    def _ask_it_line(self, agent: store.Agent) -> str:
        """How a card that is asked in the chat is used."""
        return f'To use it, start your message with its name, like "{agent.name}: your text here".'

    # ------------------------------------------------ helpers an update changed

    def _keep_changed(self, names: list[str]) -> None:
        """Helpers an update just turned into cards. The ones that work on a folder's files
        came back switched off, since each one's rule is now a guess at what it did before.
        The user is told once in the chat, at their next message, and each one's line in
        the chores list says why it is off until it has been changed or switched on: said
        only once in the chat, a helper that had worked for weeks was simply off in the
        list, with no reason. The names are kept in the app's state, and which of them the
        chat has told about, so closing the app loses neither."""
        state = noir.load_state()
        waiting, told = _names(state.get(CHANGED_HELPERS)), _names(state.get(CHANGED_TOLD))
        # One that is gone by now, or no longer works on a folder, has nothing left to say.
        self.changed_off = [name for name in dict.fromkeys([*waiting, *names])
                            if (agent := store.find_agent(name)) and parts.watches(agent)]
        self.changed_over = [name for name in self.changed_off if name not in told]
        if self.changed_off != waiting:
            self._write_changed(state, self.changed_off, [name for name in told if name in self.changed_off])

    def _write_changed(self, state: dict, off: list[str], told: list[str]) -> None:
        """Keep both lists in the app's state; an empty one is not kept at all."""
        for key, names in ((CHANGED_HELPERS, off), (CHANGED_TOLD, told)):
            if names:
                state[key] = names
            else:
                state.pop(key, None)
        noir.save_state(state)

    def _settled(self, name: str) -> None:
        """A helper an update switched off has been changed or switched on by the user (or
        is gone): its rule is no longer a guess nobody has looked at. Its line in the
        chores list stops saying so, and the chat no longer has to."""
        if name not in self.changed_off and name not in self.changed_over:
            return
        self.changed_off = [kept for kept in self.changed_off if kept != name]
        self.changed_over = [kept for kept in self.changed_over if kept != name]
        state = noir.load_state()
        self._write_changed(state, [kept for kept in _names(state.get(CHANGED_HELPERS)) if kept != name],
                            [kept for kept in _names(state.get(CHANGED_TOLD)) if kept != name])

    def _switch_watcher(self, agent: store.Agent, on: bool) -> None:
        """Switch a helper that works on a folder's new files on or off."""
        self.folderwatch.switch(agent, on)
        if on:
            self._settled(agent.name)

    def _say_changed(self) -> Iterator[Event]:
        """Say, once, which helpers came back as cards and switched off, and how each is
        made theirs."""
        names, self.changed_over = self.changed_over, []
        if not names:
            return
        state = noir.load_state()
        self._write_changed(state, _names(state.get(CHANGED_HELPERS)),
                            list(dict.fromkeys([*_names(state.get(CHANGED_TOLD)), *names])))
        agents = [agent for name in names if (agent := store.find_agent(name)) and parts.watches(agent)]
        for agent in agents:
            rule = str(agent.slots.get("instruction") or "").strip()
            guess = f' I wrote down what it did before as its rule, which is only my guess: "{rule}"' if rule else ""
            if self._can_design():
                then = (f"Say \"change {agent.name}\" and tell me what it should do with your files and what it should "
                        "leave alone, then switch it on.")
            else:
                # With nobody here to talk a rule through, "change it" would only be refused.
                then = ("You can switch it on as it is, if that rule is right. To change its rule we would talk it "
                        f"through: {_lower(NO_DESIGNER)}")
            yield from say(f"{agent.name} works a new way since this update: it follows a rule in plain words, which "
                           f"you and I work out by talking.{guess} So it is switched off for now. {then}")

    # ------------------------------- what people ask a helper that works on files

    def _places(self, watchers: list[store.Agent]) -> str:
        """Where each of them keeps its folders, or writes, as whole paths."""
        lines = []
        for agent in watchers:
            if parts.mode(agent.slots) == parts.CHOOSE:
                folders = ", ".join(parts.choices_of(agent.slots))
                lines.append(f"{agent.name} keeps its folders in {parts.destination(agent.slots)}"
                             + (f" ({folders})." if folders else "."))
            else:
                lines.append(f"{agent.name} writes in {parts.notes_path(agent.slots)}.")
        return " ".join(lines)

    def _say_where(self, text: str, watchers: list[store.Agent]) -> Iterator[Event]:
        """Where a file was put, and where the folders are, from the record of what was
        done and the cards' settings, never from the model's memory. Always the whole path."""
        moves = self.folderwatch.last_moves(50)
        named, stayed = _named(text, moves, self.folderwatch.last_skipped(30))
        if stayed and not named:
            yield from say("; ".join(f"{s['name']} is still in {s['where']}, where it stayed: {s['why']}"
                                     for s in stayed[:3]) + ".")
            return
        about_folder = bool(re.search(r"\bfolders?\b", text, re.IGNORECASE)) and not re.search(r"\bfiles?\b|\.pdf\b", text, re.IGNORECASE)
        if (about_folder and not named) or not moves:
            where = self._places(watchers)
            if moves:
                where += f" The last file, {moves[0]['name']}, went to {moves[0]['to']} ({chores.ago(moves[0]['when'])})."
            else:
                where += (" Nothing has been moved yet: only files that land after it was switched on count, and "
                          "a file is looked at a few seconds after it has finished arriving.")
            yield from say(where)
            return
        picked = named[:3] or moves[:3]
        lines = [f"{m['name']} is in {m['to']} ({chores.ago(m['when'])})" for m in picked]
        yield from say(("" if len(lines) == 1 else "The last ones: ") + "; ".join(lines) + ". Undo is in your chores.")

    def _follows_a_chore(self, text: str, asks: bool = True) -> bool:
        """A short question with a pronoun within CHORE_FRESH_SECONDS of the last word or
        move about the files in this chat, that asks where something is or went, or why: it
        means the files, not the world. `asks`: False for a report of trouble ("it's not
        working"), which asks nothing of the kind."""
        fresh = time.time() - self.chore_spoken_at < CHORE_FRESH_SECONDS
        return (fresh and len(text.split()) <= 10 and bool(FOLLOWS_A_CHORE.search(text))
                and (not asks or bool(FOLLOW_UP_ASKS.search(text))))

    def _names_a_file(self, text: str) -> bool:
        """Whether the message names a file that was moved or left ("the insurance letter"),
        by a word of its name said whole."""
        return any(_says_file(text, item["name"])
                   for item in [*self.folderwatch.last_moves(50), *self.folderwatch.last_skipped(30)])

    def _file_named(self, what: str, movers: list[store.Agent]) -> tuple[store.Agent, Path] | None:
        """The file in a watched folder that these words name, with the card whose folder it
        is in: the one whose whole name was typed, else the one whose name has the most of
        the words in it, and of several alike the newest, which is the one they have just
        seen land. Any shared word used to do, and the first file by name won: "put the
        summer price list in Staff" moved the spring one, and so did the summer one's
        whole name, typed out.

        A file the card moved itself and that is still where it put it can be meant as
        well: that is the file people correct. With only the loose files looked at, the
        summer list, which the card had just put in the wrong folder, was not among them,
        and the spring one was moved in its place."""
        best: tuple[int, float, store.Agent, Path] | None = None
        typed = what.lower()
        for agent in movers:
            for path in self._placeable(agent):
                if path.name.lower() in typed:
                    return agent, path
                shared = _words_shared(what, path.name)
                if not shared:
                    continue
                try:
                    landed = path.stat().st_mtime
                except OSError:
                    landed = 0.0
                if best is None or (shared, landed) > best[:2]:
                    best = (shared, landed, agent, path)
        return (best[2], best[3]) if best else None

    def _placeable(self, agent: store.Agent) -> list[Path]:
        """The files of one card that "put X in Y" can mean: the ones loose in the folder it
        watches, and the ones on record as moved into one of its own folders that are
        still there."""
        paths = list(self.folderwatch.files(agent, settled=False))
        kept_in = parts.destination(agent.slots)
        for move in self.folderwatch.last_moves(50):
            path = Path(move["to"]) / move["name"]
            if Path(move["to"]).parent == kept_in and path not in paths and path.is_file():
                paths.append(path)
        return paths

    def _say_why(self, text: str, watchers: list[store.Agent]) -> Iterator[Event]:
        """Why a file stayed, or why it moved, from the record of what was decided about each one."""
        skipped = self.folderwatch.last_skipped(30)
        moves = self.folderwatch.last_moves(50)
        left, moved = _named(text, skipped, moves)
        moves_files = any(parts.mode(a.slots) == parts.CHOOSE for a in watchers)
        # What to do when the answer isn't the one they wanted: the rule is theirs to change,
        # and a helper that moves files also learns from a file put somewhere by hand.
        remedy = ("If that's wrong, tell me how its rule should change"
                  + (', or say "put <file> in <folder>" and I\'ll move it and keep that as an example.' if moves_files
                     else "."))
        if left:
            lines = [f"{s['name']} stayed in {s['where']}: {s['why']}." for s in left[:3]]
            yield from say(" ".join(lines) + f" {remedy}")
        elif moved:
            lines = [f"I put {m['name']} in {m['to']} ({chores.ago(m['when'])}), following its rule." for m in moved[:3]]
            yield from say(" ".join(lines) + " Undo is in your chores if that was wrong, and you can tell me how the "
                           "rule should change.")
        elif skipped:
            yield from say("These stayed where they were: "
                           + "; ".join(f"{s['name']} ({s['why']})" for s in skipped[:4]) + ".")
        elif moves:
            yield from say("Nothing has been left behind: everything I looked at was moved. The last, "
                           f"{moves[0]['name']}, went to {moves[0]['to']}.")
        else:
            yield from say("Nothing has been looked at yet: only files that land after it was switched on count, and "
                           "a file is looked at a few seconds after it has finished arriving. Say \"go through them\" "
                           "for what has landed since, or \"go through everything\" for all of it.")

    def _say_status(self, watchers: list[store.Agent]) -> Iterator[Event]:
        """What the helpers that work on files are and did lately, from their cards and records."""
        said = []
        for agent in watchers:
            on = self.folderwatch.is_on(agent.name)
            said.append(f"{agent.name} is {'on' if on else 'off'}: {_lower(parts.how(agent))}")
            if on and (now := self.folderwatch.status(agent.name)):
                said.append(f"Right now: {_lower(now)}.")
        names = {agent.name for agent in watchers}
        jobs = [job for job in self.folderwatch.done_lately() if job.get("agent") in names][-3:]
        if jobs:
            said.append("Lately: " + "; ".join(f"{_lower(job['text'])} ({chores.ago(job['when'])})" for job in reversed(jobs))
                        + "." + (" Undo is in your chores." if any(job.get("undo") for job in jobs) else ""))
        else:
            said.append("Nothing has been done yet.")
        by_why: dict[str, list[str]] = {}
        for item in self.folderwatch.last_skipped(6):
            by_why.setdefault(item["why"], []).append(item["name"])
        if by_why:
            said.append("Left where they were: "
                        + "; ".join(f"{', '.join(found)} ({why})" for why, found in by_why.items()) + ".")
        yield from say(" ".join(said))

    def _chores_note(self, full: bool = False, away: bool = False) -> str:
        """What the chat model is told about the helpers that work on files before each
        answer, so a question it gets anyway is answered from facts, with whole paths, not
        from what it imagines. `full`: for a question about them, how such helpers work is
        said as well, in the catalog's own facts (parts.py), and each one's rule when the
        model that answers is on this computer: a rule is the user's own words about
        their own things. `away`: for a model off this computer, which is told places by
        name and of each file only its kind, never its name, where it is to the last folder,
        or what it was read as (a few words of what is in it)."""
        watchers = [a for a in store.list_agents() if parts.watches(a)]
        if not watchers:
            return ""
        here = not away and (self.chat is None or (self.chat.talker is self.ollama and self.auto_cloud is None))

        def place(path) -> str:
            return parts.shown_place(Path(path)) if away else str(path)

        def file(name: str) -> str:
            ending = Path(name).suffix.lower()
            return (f"a {ending} file" if ending else "a file") if away else name

        lines = ["YOUR CHORES RIGHT NOW (facts: when asked where a file or folder is, give the whole path from here, "
                 "and never say you can't work on files, since these chores do)" if not away else
                 "YOUR CHORES RIGHT NOW (facts: folders are given by name, and files only by their kind; never say "
                 "you can't work on files, since these chores do)"]
        for agent in watchers:
            slots = agent.slots
            line = (f"- {agent.name} is {'on' if self.folderwatch.is_on(agent.name) else 'off'}: it watches "
                    f"{place(slots.get('folder', ''))}. {parts.how(agent)}")
            if parts.mode(slots) == parts.CHOOSE and slots.get("into"):
                line += f" Its folders are in {place(slots['into'])}."
            elif parts.mode(slots) != parts.CHOOSE:
                line += f" It writes in {place(parts.notes_path(slots))}."
            if full and here and slots.get("instruction"):
                line += f' Its rule: "{slots["instruction"]}"'
            lines.append(line)
        for move in self.folderwatch.last_moves(3):
            lines.append(f"- {file(move['name'])} was put in {place(move['to'])} ({chores.ago(move['when'])}).")
        for item in self.folderwatch.last_skipped(3):
            why = item["why"].partition(": ")[0] if away else item["why"]
            lines.append(f"- {file(item['name'])} stayed in {place(item['where'])}: {why}.")
        for agent in watchers:
            if not away and (now := self.folderwatch.status(agent.name)):  # it names the file in hand
                lines.append(f"- Right now, {agent.name}: {_lower(now)}.")
        if full:
            thens = dict.fromkeys(parts.then_of(agent.slots) for agent in watchers)
            for part in [parts.WHENS[parts.NEW_FILE], *(parts.THENS[then] for then in thens if then in parts.THENS)]:
                lines += [f"- {fact}" for fact in part.facts]
            seer = self.folderwatch.seer()
            lines.append("- The built-in model can see, so pictures and scanned pages are read." if seer == noir.NOIR_MODEL
                         else f"- A model that can see is installed ({seer}), so pictures and scanned pages are read." if seer
                         else "- No model here can see, so nothing can be read from a picture or a scanned page.")
        return "\n".join(lines)

    def _go_through(self, agent: store.Agent, everything: bool = False, text: str = "") -> Iterator[Event]:
        """Go through the card's folder now, saying how it goes: what has landed since it
        was switched on, (everything) all of it, or the file the message names, looked at
        again. When nothing is new, what was looked at already is said instead of "wait"."""
        named = [p for p in self.folderwatch.files(agent, settled=False) if text and _mentions(text, p.name)]
        if not everything and not named and not self.folderwatch.is_on(agent.name):
            # Switched off, it has watched nothing, so there is no "since it was switched on":
            # a pass now would take every file in the folder for a new one.
            self.fixing, self.fix_yes = (agent.name, {}, True), SWITCH_IT_ON
            yield Question(FIX_AGENT, f"{agent.name} is switched off right now, so it hasn't been watching. "
                                      "Switch it on?", [SWITCH_IT_ON, LEAVE_IT])
            return
        outcome: dict = {"moved": 0, "where": [], "left": 0, "why": [], "looked": 0}
        for step in self.folderwatch.run_once(agent, everything=everything, only=named or None):
            if isinstance(step, str):
                yield Progress(step)
            else:
                outcome = step
        writes = parts.mode(agent.slots) != parts.CHOOSE
        if outcome["moved"]:
            activity.record(activity.HELPED if writes else activity.SORTED, outcome["moved"])
        moved, left = outcome["moved"], outcome["left"]
        if not outcome["looked"]:
            yield from self._nothing_new(agent)
            return
        if writes:
            notes = parts.notes_path(agent.slots).name
            said = f"Wrote about {_count(moved, 'file')} in {notes}." if moved else "Nothing written."
        else:
            where = " · ".join(f"{w['folder']} {w['count']}" for w in outcome["where"])
            said = f"Moved {_count(moved, 'file')}: {where}." if moved else "Nothing moved."
        if left:
            reasons = ", ".join(f"{r['why']} ({r['count']})" if len(outcome["why"]) > 1 else r["why"] for r in outcome["why"])
            said += (f" Nothing written about {_count(left, 'file')}: {reasons}." if writes
                     else f" {left} left where {'it was' if left == 1 else 'they were'}: {reasons}.")
        if outcome.get("already"):
            # Files the look that runs on its own dealt with while this pass was getting to them.
            count = outcome["already"]
            said += (f" {count} more {'was' if count == 1 else 'were'} dealt with just now as "
                     f"{'it' if count == 1 else 'they'} landed: your chores list has {'it' if count == 1 else 'them'}.")
        if moved and not writes:
            said += " Undo is in your chores."
        self.chat.remember(f"{agent.name}: go through the files", f"({agent.name} answered) {said}")
        yield Result(agent.name, said)

    def _nothing_new(self, agent: store.Agent) -> Iterator[Event]:
        """Nothing has landed since the card was switched on: say what was looked at already
        and why it stayed, and only then suggest waiting."""
        folder = parts.shown_place(Path(agent.slots.get("folder") or ""))
        skipped = list(reversed(self.folderwatch.skipped.get(agent.name, [])))[:3]
        said = [f"Nothing new has landed in {folder} since {agent.name} was switched on."]
        if skipped:
            again = "name a file to have it looked at again"
            said.append("Looked at already: " + "; ".join(f"{s['name']} ({s['why']})" for s in skipped) + ". "
                        + (f'Say "put <file> in <folder>" to place one yourself, or {again}.'
                           if parts.mode(agent.slots) == parts.CHOOSE else f"{again[:1].upper()}{again[1:]}."))
        else:
            said.append("A file is looked at a few seconds after it has finished arriving; ask again in a moment, "
                        "or say which file.")
        line = " ".join(said)
        self.chat.remember(f"{agent.name}: go through the files", f"({agent.name} answered) {line}")
        yield Result(agent.name, line)

    def _place(self, found: tuple[store.Agent, Path] | None, folder: str, movers: list[store.Agent],
               said: str = "") -> Iterator[Event]:
        """ "Put output.pdf in Letters": the file the words name, moved where the user says
        and kept with the card as an example for later files. The file must be in a watched
        folder; the folder is made if need be. `said`: their message, as typed."""
        if found is None:
            folders = ", ".join(parts.shown_place(Path(a.slots.get("folder") or "")) for a in movers)
            yield from say(f"I can't see a file like that in {folders}. Which file do you mean? Its name is enough.")
            return
        agent, path = found
        yield Thinking(f"You're placing {path.name} yourself, so I'll move it, and {agent.name} keeps that as an "
                       "example.")
        move = self.folderwatch.place(agent, path, folder)
        if move:
            yield from say(f"Put {path.name} in {Path(move['to']).parent}. {agent.name} keeps that as an example for "
                           "later files. Undo is in your chores.")
            yield from self._offer_rule(agent, path.name, Path(move["to"]).parent.name, said)
        else:
            yield from say(f"I couldn't move {path.name}.")

    def _offer_rule(self, agent: store.Agent, file: str, folder: str, said: str) -> Iterator[Event]:
        """After a file was put somewhere by hand: ask whether files like it should always
        go there. An example kept with the card helps the files that look just like it;
        the rule written again from what the user did was as good or better for them every
        time it was measured (20 Nov 2026, the built-in model on 22 made-up files), and
        the rule is theirs, so it is asked and never done. Only when a model can talk the
        change through; once for a file; never while another helper is being worked out
        or waits set aside; and not for a helper they have said no for since the app opened."""
        asked = (agent.name, file.lower())
        if agent.name in self.rule_refused or asked in self.rule_asked:
            return
        busy = any(flow is not None and flow.active for flow in (self.designer, self.builder, self.planner))
        if busy or self.designer is None or self.designer.aside is not None or not self._can_design():
            return
        self.rule_asked.add(asked)
        self.ruling = (agent.name, file, folder, said)
        yield Question(RULE_FROM_MOVE, f"Should files like {file} always go in {folder}? If so, we put that into the "
                                       f"rule of {agent.name} together.", [CHANGE_THE_RULE, JUST_THIS_ONE])

    def _rule_from_move(self, choice: str) -> Iterator[Event]:
        """The answer to that question. A yes opens the conversation in which the helper is
        changed, with one plain sentence that says what they did and what they want of it:
        it ends in the card, a try-out and Save changes, like any change. A no is kept for
        that helper until the app closes, and nothing more is said."""
        ruling, self.ruling = self.ruling, None
        agent = store.find_agent(ruling[0]) if ruling else None
        if agent is None:
            yield from say("That question has already been answered.")
            return
        name, file, folder, said = ruling
        if choice != CHANGE_THE_RULE:
            self.rule_refused.add(name)
            yield from say("Okay, just this one.")
            return
        # A model off this computer is never sent a file's name (the conversation says so
        # when it opens): it reads what they typed and the folder, which they named.
        model = self._design_model()
        here = model is not None and model.here
        what = file if here else "a file"
        if not here:
            # What they typed is theirs to send, but not the file's name in it: "put
            # dentist_invoice_march.txt in Bills" went out whole, beside a line that said such
            # a model never sees a file's name.
            for name in dict.fromkeys((file, Path(file).stem)):
                if len(name) >= 4:  # a name that short would take ordinary words with it
                    said = re.sub(re.escape(name), "a file", said, flags=re.IGNORECASE)
        typed = f' (I said: "{said.strip()}")' if said.strip() else ""
        yield Thinking(f"So that files like it go in {folder} by themselves, we change the rule of {name}. Nothing "
                       "changes until you save it.")
        yield from self._made(self.designer.edit(agent, f"I put {what} in {folder} myself{typed}. Files like it "
                                                        f"should always go in {folder}."))

    def _answer_about_chores(self, text: str, think: bool) -> Iterator[Event]:
        """A question about the chores. With a plan or key model set up, that model gets the
        record of what was done and the question, so the user can check and talk through
        what went wrong with the better model; else its own model answers from the same
        record.

        What goes off this computer is what the designing conversation sends such a model:
        places by name, never a whole path (it has the user's name in it), and of the files
        only their kind, never a name or what one was read as. The record goes with this one
        question only: kept in its memory of the chat, it went again with every later answer
        from the plan, a file's name among it."""
        talker = self.auto_cloud or (self.chat.talker if self.chat and self.chat.talker is not self.ollama else None)
        if talker is None:
            yield Thinking("This asks about your chores, so I'll answer from the record of what they did.")
            yield from self._answer(text, think, about_chores=True)
            return
        yield Thinking(f"This asks about your chores: {self.talker_name} gets your question and what they did, with "
                       "folders by name and no file's name, so it can check what happened and explain.")
        asked = f"{self._chores_note(full=True, away=True)}\n\nThe user asks: {text}"
        yield from self._reply(asked, think, where=auto.CLOUD)
        for turn in reversed(self.chat.history):
            if turn["role"] == "user" and turn["content"] == asked:
                turn["content"] = text  # remembered as they asked it
                break

    # Outside the contract, like details(): what the chores lists and the windows show.

    def chore_agents(self) -> list[dict]:
        """The helpers that run without being asked in the chat, for the chores lists."""
        lines = []
        for agent in store.list_agents():
            if parts.watches(agent):
                # `now`: what it is doing this very moment, so the lists show it is alive and at
                # what; `since`: when it was switched on, for "nothing new has landed since".
                on = self.folderwatch.is_on(agent.name)
                since = self.folderwatch.since.get(agent.name, 0) if on else 0
                # `left`: the last file it looked at and left since then, so the line never says
                # "nothing new has landed" about a folder where something did and stayed.
                left = next((dict(item) for item in reversed(list(self.folderwatch.skipped.get(agent.name, [])))
                             if on and item.get("when", 0) >= since), None)
                # `why_off`: why it is off, when an update switched it off and it has not
                # been changed or switched on since; "" for any other.
                why_off = NEEDS_TALKING if not on and agent.name in self.changed_off else ""
                lines.append({"name": agent.name, "kind": "files", "on": on, "how": parts.how(agent),
                              "now": self.folderwatch.status(agent.name) if on else "", "since": since, "left": left,
                              "why_off": why_off})
            elif parts.is_switchable(agent) and self.quick:
                lines.append({"name": agent.name, "kind": "highlight", "on": self.quick.is_on(agent.name),
                              "how": parts.how(agent)})
        return lines

    def chore_doing(self) -> str:
        """The one thing being done on a folder's files right now, as a sentence with the
        helper's name, or ""."""
        return self.folderwatch.doing()

    def chore_done(self) -> list[dict]:
        """Every job done on a folder's files that is still remembered, oldest first."""
        return self.folderwatch.done_lately()

    def undo_move(self, id: str) -> int:
        """Put one job's files back. How many went back: 0 when the id isn't one of these jobs."""
        return self.folderwatch.undo(id)

    def details(self, name: str) -> dict:
        """What an agent's page shows. Empty if there's no such agent."""
        agent = store.find_agent(name)
        return parts.describe(agent) if agent else {}

    def _agent_list(self) -> AgentList:
        agents = store.list_agents()
        return AgentList(
            [a.name for a in agents],
            [a.name for a in agents if parts.is_switchable(a) and (parts.watches(a) or self.quick)],
            [a.name for a in agents if self._is_on(a)],
        )

    def _full_lists(self, events: Iterator[Event]) -> Iterator[Event]:
        """The builder and runner only know agent names; the UI also needs
        which agents can be switched on and which are on."""
        for event in events:
            if isinstance(event, AgentList):
                self.folderwatch.refresh(store.list_agents())
                if self.quick:
                    self.quick.refresh(store.list_agents())  # changed settings apply at once
                event = self._agent_list()
            yield event

    def _toggle(self, name: str, on: bool | None = None) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is not None and parts.watches(agent):
            on = not self.folderwatch.is_on(agent.name) if on is None else on
            self._switch_watcher(agent, on)
            if on:
                yield from say(f"{agent.name} is on. {parts.how(agent)} Only files that land from now on are handled.")
            else:
                yield from say(f"{agent.name} is off.")
            yield self._agent_list()
            return
        if agent is not None and parts.is_switchable(agent) and self.quick is None:
            yield Error(f"Switch-on helpers work on Windows for now. You can still ask {agent.name} in the chat.")
            return
        if agent is None or not parts.is_switchable(agent) or self.quick is None:
            yield Error(f"{name} isn't an agent that can be switched on.")
            return
        on = not self.quick.is_on(agent.name) if on is None else on
        self.quick.switch(agent, on)
        if on:
            yield from say(f"{agent.name} is on. {self._highlight_line(agent)}")
        else:
            yield from say(f"{agent.name} is off.")
        yield self._agent_list()

    # --------------------------------------------------------- trouble

    def _diagnose(self, agent: store.Agent, report: str) -> Iterator[Event]:
        """Why a helper seems not to work. Code looks at the mechanics, which are the same
        for every helper whatever it is for: whether it can run on this computer, whether
        it is switched on, where its result goes, whether the model can be reached, whether
        a highlight has reached it and what came of the last one. What it finds it says,
        with a fix to click where there is one.

        What a helper does with a text is its rule, and code never reads a rule to judge
        it. So when the mechanics are in order the trouble is the rule's, and a rule is put
        right by talking: with a model that can hold that conversation, the report opens it
        (designer.edit); without one, what was checked is said, and how the rule is changed.
        `report`: the user's message."""
        if parts.watches(agent):
            yield from self._diagnose_watcher(agent)
            return
        name, slots = agent.name, agent.slots
        if agent.blueprint != parts.CUSTOM:
            # One that answers from a folder's documents: nothing to switch on, nothing shown
            # anywhere but the chat. (Told it was "on and set up right" and where highlights
            # can be read, nobody learned how to ask it.)
            yield from say(f"{name} only answers when you ask it in the chat. {self._ask_it_line(agent)}")
            return
        highlights = parts.is_switchable(agent)
        if highlights and self.quick is None:
            yield from say(f"{name} works on text you highlight, which I can read on Windows only for now, so it "
                           "can't work on this computer.")
            return
        problems, fixes = [], {}
        if not highlights and self.quick is not None and not slots.get("then"):
            # Only a card saved before cards said what they do with their result: one that
            # was meant to work on highlights could be saved asked in the chat by mistake. A
            # card that says it answers in the chat was worked out that way on purpose, and
            # "fixed", every text highlighted in any program would have gone through its rule.
            problems.append("it's set to work only when you ask in the chat, so it ignores highlights")
            fixes["when"] = parts.WHILE_ON
        if slots.get("show") == CLIPBOARD and (highlights or fixes):
            problems.append("it copies the result to the clipboard instead of showing it")
            fixes["show"] = BUBBLE
        on = bool(self.quick and self.quick.is_on(name))
        switch_on = self.quick is not None and not on
        if problems:
            yield Thinking(f"Checked {name}'s settings: " + "; ".join(problems) + ".")
            fix = ", ".join(_fix_words(fixes))
            if switch_on:
                fix += (", and switch it on" if fix else "switch it on")
            self.fixing, self.fix_yes = (name, fixes, switch_on), FIX_IT
            yield Question(FIX_AGENT, f"I found why: {', and '.join(problems)}. Should I {fix}?", [FIX_IT, LEAVE_IT])
            return
        if highlights and switch_on:
            self.fixing, self.fix_yes = (name, {}, True), SWITCH_IT_ON
            yield Question(FIX_AGENT, f"{name} is switched off right now. Switch it on?", [SWITCH_IT_ON, LEAVE_IT])
            return
        # What was checked is said without "you" or "I": the same words go to the user and,
        # with their report, into the conversation, where a model reads them as the user's turn.
        if not highlights:
            # Asked in the chat, as it was made to be or on a computer where highlights can't
            # be read: there is nothing to switch on and nowhere else for its answer to go.
            checked = f'it works when it is asked in the chat, by a message that starts with "{name}:"'
        else:
            came = self.quick.last.get(name)
            if not self._model_reached():
                yield from say(f"{name} is on and set up right, but I can't reach Ollama, the program that runs my "
                               "model, so it has nothing to work with. Open the Ollama app, or restart me, then "
                               "highlight the text again.")
                return
            if came == NO_MODEL:
                yield from say(f"{name} is on and set up right. The last time you highlighted something I couldn't "
                               "reach Ollama, the program that runs my model, so nothing came of it. I can reach it "
                               "now: highlight the text once more.")
                return
            leaves = parts.skip_language(slots)
            if came == LEFT_OUT and leaves:
                # (A highlight with no letters in it is passed over too: parts.leaves_out.)
                change = f' If it should work on such text too, say "change {name}" and tell me.' if self._can_design() else ""
                yield from say(f"{name} is on and set up right. The last text you highlighted is one it leaves out: "
                               f"text that is already in {leaves}, or that has no letters in it. So nothing was shown "
                               f"for it.{change}")
                return
            if came in (None, LEFT_OUT):
                yield from say(f"{name} is on and set up right, but no highlighted text has reached it since it was "
                               "switched on. Some programs don't tell me what's highlighted. It works in browsers "
                               "like Edge, Chrome and Whale, and in Word and Notepad. Highlight by dragging over the "
                               "text or double-clicking a word, then wait a second for the bubble.")
                return
            shown = {CLIPBOARD: "copies its result, ready to paste", BOTH: "shows its result above the text and "
                     "copies it"}.get(slots.get("show"), "shows its result in a bubble above the text")
            gave = ("the built-in model gave nothing back for the last text that was highlighted"
                    if came == NOTHING_BACK else "it gave a result for the last text that was highlighted")
            checked = f"it is switched on, it {shown}, and {gave}"
        # Nothing mechanical is wrong: what is left is what it does with the text.
        if self._can_design():
            yield Thinking(f"Checked {name}: {checked}. So how it is set up isn't the trouble. What it does with the "
                           "text is its rule, and that we can put right by talking.")
            # What code checked goes with their words, so the conversation starts from there
            # and not from "is it switched on?".
            yield from self._made(self.designer.edit(agent, f"{report.strip()}\n(Checked by the app just now: "
                                                            f"{checked}. How it is set up is not the trouble.)"))
            return
        rule = re.sub(r"\s+", " ", str(slots.get("instruction") or "")).strip()
        yield from say(f"I checked {name}: {checked}. So how it is set up isn't the trouble."
                       + (f' Its rule is: "{rule}"' if rule else "")
                       + f' If that isn\'t what it should do, say "change {name}" and tell me what it should do '
                       "instead, and I'll change its rule.")

    def _model_reached(self) -> bool:
        """Whether Ollama, which runs the built-in model, answers this moment."""
        loaded = getattr(self.ollama, "loaded", None)
        if loaded is None:
            return True  # it can't be asked: the next job will say what's wrong, if anything is
        try:
            loaded()
        except Exception:  # noqa: BLE001 - whatever stopped it, it can't be reached
            return False
        return True

    def _diagnose_watcher(self, agent: store.Agent) -> Iterator[Event]:
        """Why a helper that works on a folder's files seems not to work: it is switched
        off, or its own record says what it did with what landed and why."""
        if not self.folderwatch.is_on(agent.name):
            self.fixing, self.fix_yes = (agent.name, {}, True), SWITCH_IT_ON
            yield Question(FIX_AGENT, f"{agent.name} is switched off right now, so nothing is handled as it lands. "
                                      "Switch it on?", [SWITCH_IT_ON, LEAVE_IT])
            return
        self.chore_spoken_at = time.time()
        yield Thinking(f"{agent.name} is on, so I'll say what it has done with what landed: its record answers.")
        yield from self._say_status([agent])

    def _apply_fix(self, choice: str) -> Iterator[Event]:
        fixing, self.fixing = self.fixing, None
        agent = store.find_agent(fixing[0]) if fixing else None
        if agent is None or choice == LEAVE_IT:
            yield from say("Okay, I left it as it is." if agent else "That question has already been answered.")
            return
        name, fixes, switch_on = fixing
        if parts.watches(agent):
            # Nothing about its card is fixed here: it is only switched on, and from then on
            # only what lands counts.
            self.folderwatch.refresh(store.list_agents())
            self._switch_watcher(agent, True)
            yield from say(f"{name} is on. {parts.how(agent)} Only files that land from now on are handled.")
            yield self._agent_list()
            return
        agent.slots.update(fixes)
        if "when" in fixes:
            if agent.slots.get("then"):
                agent.slots["then"] = parts.SHOW  # what it does with its result goes with when it works
            # Whatever a card of that WHEN can say and this one didn't, with its usual value.
            agent.slots.update(parts.defaults(agent.slots))
        store.save(agent)
        if switch_on and self.quick:
            self.quick.switch(agent, True)
        elif self.quick:
            self.quick.refresh(store.list_agents())
        state = "It's on: highlight text in any program to try it." if switch_on or (
            self.quick and self.quick.is_on(name)) else "Switch it on in your helpers list to try it."
        yield from say(f"Fixed. {state}")
        yield self._agent_list()

    def _remember_ideas(self, text: str, events: Iterator[Event]) -> Iterator[Event]:
        """Noir hears about idea cards too, so a follow-up in the chat makes sense."""
        for event in events:
            if isinstance(event, IdeaCard):
                self.chat.remember(text, f"(Idea card: {event.title}) {event.verdict}")
            yield event

    def _hardware(self) -> tuple[hardware.HardwareReport, float]:
        """This computer, and how much memory Noir's model takes on it."""
        report = hardware.detect()
        tag = noir.load_state().get("base_model")
        model = find_model(tag) if tag else recommend(report).model
        return report, model.memory_gb if model else 3.0

    def _run_agent(self, name: str, request: str, text: str, think: bool = False) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"I can't find an agent called {name}.")
            return
        if parts.watches(agent):
            if WANTS_PASS.search(text) or not WANTS_ANSWER.search(text):
                self.chore_spoken_at = time.time()
                # Everything in the folder only when asked for in so many words, and then
                # asked about first: "Paper sorter, show me all my files" went through it all.
                if WANTS_EVERYTHING.search(text):
                    yield from self._ask_all(agent)
                else:
                    yield from self._go_through(agent)
            else:
                # A question about it ("which folder did the letter go into?"), sent here by
                # the router: answered with the facts note in front, not run as a pass.
                yield from self._answer_about_chores(text, think)
            return
        if agent.blueprint == parts.CUSTOM:
            # Asked in the chat ("Word explainer: serendipity"): do its job here.
            result = run_instruction(self.chat.talker, noir.NOIR_MODEL, agent.slots.get("instruction", ""),
                                     request, self.chat.think)
            activity.record(activity.HELPED)
            self.chat.remember(text, f"({agent.name} answered) {result}")
            yield Result(agent.name, result)
            return
        for event in runner.run(self.ollama, noir.NOIR_MODEL, agent, request, self.chat.think):
            if isinstance(event, Result):
                # Noir hears the answer too, so "and what about...?" follows on.
                self.chat.remember(text, f"({agent.name} answered) {event.text}")
            yield event

    # ------------------------------------------------------ deleting agents

    def _confirm_delete(self, name: str) -> Iterator[Event]:
        agent = store.find_agent(name)
        if agent is None:
            yield Error(f"There is no agent called {name}.")
            return
        self.deleting = agent.name
        folder = agent.slots.get("folder")
        files = f" Your files in {folder} are not touched." if folder else ""
        yield Question(DELETE_AGENT, f"Delete {agent.name}? It forgets everything it read.{files}",
                       [DELETE_IT, KEEP_IT])

    def _ask_which_to_delete(self, agents: list[store.Agent]) -> Iterator[Event]:
        if len(agents) == 1:
            yield from self._confirm_delete(agents[0].name)
            return
        yield Question(PICK_AGENT_TO_DELETE, "Which agent should I delete?",
                       [a.name for a in agents] + ["None of them"])

    def _finish_delete(self, choice: str) -> Iterator[Event]:
        name, self.deleting = self.deleting, None
        agent = store.find_agent(name) if name else None
        if choice != DELETE_IT or agent is None:
            yield from say("Okay, I kept it." if agent else "That question has already been answered.")
            return
        if self.quick:
            self.quick.switch(agent, False)
        if parts.watches(agent):
            # Switched off, and what was kept about it goes with it: a new agent of the same
            # name once began with the deleted one's list of files already seen.
            self.folderwatch.forget(agent.name)
            self._settled(agent.name)
        store.delete(agent)
        # A change to it that was being worked out, or waits set aside, ends with it: Save
        # changes on its card once saved the deleted helper again, and then asked about it.
        stopped = False
        if self.designer is not None:
            if self.designer.sketch is not None and self.designer.sketch.replaces == agent.name:
                self.designer.sketch.model.done()
                self.designer.sketch, stopped = None, True
            if self.designer.aside is not None and self.designer.aside.replaces == agent.name:
                self.designer.aside, stopped = None, True
        if self.builder is not None and self.builder.draft is not None and self.builder.draft.replaces == agent.name:
            self.builder.draft, stopped = None, True
        for asked in ("fixing", "ruling"):
            if (getattr(self, asked) or ("",))[0] == agent.name:
                setattr(self, asked, None)
        if self.going_through == agent.name:
            self.going_through = None
        yield from say(f"Deleted {agent.name}." + (" I stopped changing it, since it is deleted." if stopped else ""))
        yield AgentList([a.name for a in store.list_agents()])


def _fix_words(fixes: dict) -> list[str]:
    """What a fix does, in plain words, for the question that offers it."""
    words = {"when": "make it work on highlights", "show": "show the result in a bubble above the text"}
    return [words[key] for key in fixes if key in words]
