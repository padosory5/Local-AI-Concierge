"""The conversation in which an agent is worked out, with a model in it.

An agent is a card: WHEN it works, what it LOOKS AT, the RULE, and what it does THEN
(agents/parts.py). Nobody writes a card by hand and no question is scripted: the user says
what they want, and one model, the design model, works the card out with them from
nothing. Each turn it reads how to talk and how to design, what a helper can be made of,
the card as code has checked it so far, what code can see on this computer and the
conversation itself, and fills one form: what it now understands for the WHEN, the THEN
and every setting, where things stand, and what to say.

The model talks and proposes; it decides nothing. Code checks every value it gives (a
WHEN and a THEN that go together, a folder that exists, a place this computer has), keeps
the card, tries it on the user's own things without changing anything as soon as nothing
needed is missing (the try-out), shows the card, and only the card's button makes the
agent. Four local models were tried on one setup (10 Nov 2026): all of them talked
naturally and three decided wrongly (switched it on with no yes, said they would move a
file nobody had asked about), so a model's word that something is ready, on or made is
never taken for it.

A message about something else in the middle does not end the conversation. The helper
is set aside as it stood and is no longer the one that is talked to; the engine answers
the message as it answers any other, and the helper is taken up again where it was when
the user says so (`set_aside`, `carry_on`, `drop`).

Who designs is the engine's choice: the plan or key model when one is picked, else a
model on this computer that is fit to and has room on the graphics card, else nobody.
This file knows neither the engine nor the code that watches folders: the design model,
the dry run on the user's files (`rehearse`) and the built-in model's name are handed in.

Nothing here knows what any particular agent is for, and nothing here may: no subject, no
kind of document, no question that only one agent would be asked, and in what a model
reads no example of a folder's, a subject's or a helper's name. Given one, a model
offered it to the user as if it were theirs, and a smaller one filled it in as the answer.
"""

from __future__ import annotations

import json
import os
import re
import sys
from difflib import SequenceMatcher
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ..events import AgentCard, AgentList, Event, Question, Result, Thinking
from ..noir import CLOSING_FILLER
from ..ollama import Ollama, OllamaError
from ..places import known_folder
from . import parts, planner, store
from .builder import (CANCEL_WORDS, CARD, CARD_YES, CREATE_IT, DUPLICATE, MAKE_ANOTHER, SAVE_CHANGES,
                      create_documents_agent, files_in, find_folders, is_blocked, place_dirs, say)
from .files import scan
from .parts import INSIDE, PLACE_NAMES
from .recipe import run_instruction

# What the model may say about where things stand. Code checks each one: "nothing missing"
# with something missing is asked again, and none of them creates anything.
STILL_ASKING, NOTHING_MISSING, CALLED_OFF, MOVED_ON, CANT_BE_MADE = "asking", "ready", "cancel", "other", "cannot"
DESIGN = "design"  # the id of a question that is about no setting in particular
# What the form can say of the WHEN and the THEN besides one of the parts.
NOT_CLEAR, NONE_FIT = "Not clear yet", "None of these"
# What is decided about a first message before anything is worked out: whether it says what
# they want done. (Not "a trouble or a wish": under that name a message that began "I want
# something that turns ..." and said what into what counted as a wish, and was asked about
# instead of worked on.)
TOLD, NOT_TOLD = "They have said what they want done", "They have only said what bothers them"
# The room a local design model is given: gemma4:12b at 8,192 is 9.2 GB on the user's card
# (measured 13 Nov 2026). Its note lists every part with its settings and facts, and is
# about 18,500 characters (22 Nov 2026) before a word of the conversation, so the 4,096 a
# setup with fixed questions was talked through in would not hold it.
DESIGN_CONTEXT = 8192
DESIGN_TEMPERATURE = 0.4  # at 0 a model asked "Shall I turn this on now?" in the same words every turn
DESIGN_KEEP_ALIVE = "3m"  # between two turns of one conversation; freed as soon as it ends
REHEARSE_FILES = 8  # how many of the user's files a try-out is run on
MAX_TURNS = 24  # of the conversation the model reads
MAX_SAY = 600
MAX_WANTS = 200
MAX_SAMPLE = 400  # of a text a helper is tried on
NOTE_SHOWN = 300  # of what a helper would write about one file, in a try-out
# The settings that say where a result goes or how it looks, never what it is.
SAME_OUTCOME = ("name", "into", "notes", "show", "keep")
MAX_NAME = 40
NEARLY = 0.85  # how alike two folder names must be for one to be a slip of the other ("Appliance" for "Applience")
MAX_LOOKED = 400  # folders looked at in one folder when a name is looked for nearly
MAX_FOLDERS_TOLD = 12  # of the folders inside one of the places people name, said to the model by name
TRY_OUT = "Try-out"  # who a try-out's result is from, on the screen
NOT_KNOWN = "not known yet"
A_PATH = re.compile(r"^([A-Za-z]:[\\/]|~|/)")
SYSTEM_FOLDER = "That's a system folder, so for safety a helper can't use it."
NO_DESIGNER = ("Working a helper out is a conversation, and that takes a stronger model than the built-in one: your "
               "ChatGPT or Claude plan, or a bigger model on this computer.")
# The WHEN and the THEN as code asks for them and names them, when the model didn't.
WHEN = parts.Setting("when", "When it works", "choice", "What would you like it to do, and when should it work?", "")
THEN = parts.Setting("then", "What it does then", "choice", "What should it do when that happens?", "")
# The user giving the helper itself a name: "call it ...", "a helper called ...".
NAMES_IT = re.compile(r"\b(call|name) (it|this|the (agent|helper|assistant))\b|"
                      r"\b(agent|helper|assistant) (called|named)\b|\brename (it|this|the (agent|helper|assistant))\b",
                      re.IGNORECASE)
# The user giving anything a name. In a message that isn't naming the helper, the name is
# something else's: "can you call the folder ..." once named the agent after the folder.
NAMES_A_THING = re.compile(r"\b(call(ed|ing)?|named?|naming|renamed?)\b", re.IGNORECASE)
# A yes to the card of a helper that is being changed, besides the words that say yes to any card.
SAVE_YES = ("save", "save it", "save changes", "save the changes")
# A whole message that only agrees, in words the list of plain yeses does not have. "ok
# good", typed under a card that had just been put right, went to the model, which took
# it for a request to change the card, changed nothing, and the user was told "I couldn't
# work that into the card". Only words of agreement, and nothing after them: "ok but ..."
# and "is that right?" are not this.
_YES = (r"(?:ok(?:ay)?|yes|yeah|yep|yup|sure|alright|great|good|perfect|nice|cool|fine|awesome|"
        r"(?:that|it|this)(?:'s|s| is)? (?:right|good|great|fine|perfect|it|correct)|"
        r"(?:(?:that|it|this) )?(?:looks|sounds) (?:good|great|right|fine|perfect|correct)|"
        r"create it|make it|do it|go ahead|let'?s do it|"
        r"네|넵|응|예|좋아요?|좋습니다|그래요?|맞아요?|만들어 ?줘요?|만들어 ?주세요|그렇게 해 ?줘요?|그렇게 해 ?주세요)")
AGREES = re.compile(rf"^(?:{_YES}(?: now| then| thanks| thank you| please)?[\s,.!]*)+$", re.IGNORECASE)
# The words that call it off only when nothing comes after them: "stop moving the
# pictures" is a change, and the model reads it.
STANDS_ALONE = ("stop", "그만")
# A name in double quotes in a list of names, and the "and" between two names.
QUOTED_NAME = re.compile(r'"([^"]+)"|“([^”]+)”')
AND_WORD = re.compile(r"(?:^|\s+)and\s+", re.IGNORECASE)

VOICE = (
    'You are Noir, an assistant that lives on this person\'s computer. You speak as "I", in plain everyday words, '
    "warm and short, the way a capable friend would. No technical words, no lists, no emoji, no greeting, and never "
    'an opening offer to help ("I can certainly help with that"): start with what you have to say. One or two '
    # "What kind of files are cluttering it, and how would you like them organized into
    # folders?": two questions in one, and people answer the second.
    'sentences, and at most one question: one thing asked, never two joined by "and". Reply in the language they '
    "write in."
)
HOW_TO_DESIGN = (
    "HOW TO DESIGN\n"
    "You and the user are working this helper out together, from nothing. You know nothing about what they want "
    "until they say it, and there is no ready-made helper to offer: never assume one.\n"
    "\n"
    "A helper is always four things: WHEN it works, what it LOOKS AT, the RULE, and what it does THEN. WHEN and THEN "
    "can only be ones listed below.\n"
    "The rule is the heart of it. Later a small model reads the rule for every single item, knowing nothing about "
    "this conversation. So write the rule as plain, complete sentences that stand on their own: what should happen "
    "to which things, in the user's own terms, and what must be left alone. "
    # How a rule is written decides how well the built-in model follows it. One and the same
    # rule, for a made-up person's folder of 23 files in which some files fit two of its
    # folders, written five ways and run twice each with Noir's own 4B model (20 Nov 2026):
    # as a list of "If the content is related to ..., move it to ..." the way a model writes
    # one, 20 of 23 right; the same with a sentence added that says which part wins, 19; as
    # an ordered list with "Otherwise", 20; as plain statements in the person's own voice
    # that say what each kind is and that the one is not the other, 22 both times.
    "Write it the way they would say it to someone helping them: statements about their things, not a list of "
    '"if" conditions. Where one thing could be taken for two kinds, say plainly what each kind is and that the one '
    "is not the other; a sentence about which part of the rule wins is not followed. "
    # Asked for a few lines about each new document, a model added "Do not include any
    # personal information or sensitive private data" to the rule and said nothing of it.
    # The user found it on the card: the names and the sums were what they wanted to read.
    # (Not yet followed for what a helper leaves alone: "Do not explain words that are
    # already simple or common" stood in the rule of a helper that was to explain a
    # highlighted word in simple words, three plays out of three on 22 Nov 2026. A sentence
    # added here, that the rule names nothing to leave alone when they named nothing, took
    # that out three times of three; but in the same three plays a helper that turns text
    # into one language kept the old language as the one it leaves out when its rule was
    # changed to another, once, and "I've set it up" was said before any button, once,
    # neither of which had happened in nine plays without it. So it is not here.)
    "Nothing goes into the rule that they did not ask for or agree to.\n"
    "\n"
    "How to get there:\n"
    # (A first message that names only a trouble is asked about before this note is read:
    # see OPENING. What is here is for the turns after it.)
    "1. Understand first: what their things are, what bothers them about it, what must never be touched. "
    # "What would you like to happen to the files, and are there any specific rules for
    # where they should go?": the person had asked because they did not know, and was
    # handed the designing.
    "They may not know what they want done, which is why they came to you. Never hand them the work: how they "
    "would like it organized, what rules to use, which folders or groups they want and what should happen to the "
    "things are yours to work out and propose, from what they tell you about their things. "
    # Asked what was in the folder, they said, and the next question was "What is the most
    # frustrating part about not being able to find those files?".
    "Once they have answered a question about their situation, that is enough: propose.\n"
    # A model that asked "Which folder should it watch for new files?" had put its own guess
    # for that folder in the same form, so nothing was missing, and the try-out and the card
    # came under its question, for a folder nobody had named. The card now waits until they
    # have agreed (_turn), and the model is told that it does.
    # ("How they use it": a helper asked in the chat was described as working "whenever you
    # paste your notes into the chat", with not a word about asking it by its name.)
    "2. Then propose. Say in plain words what the helper would do: when it works and how they use it, what it does "
    "with which things and what it leaves alone, and ask whether that is right. Fill in the form with what you "
    "propose, the rule written out, and keep the "
    f'status "{STILL_ASKING}": until they have agreed, the app shows your words and nothing else. Use what is '
    "under ABOUT THIS COMPUTER; never say you have seen inside their files. "
    # Rough notes to be written out properly were given a helper for highlighted text, three
    # times out of three, when one asked in the chat would have done as well. (Told as well
    # that a message which already says all of it needs no proposing, the model stopped
    # asking "Is that how you want it to work?" and asked again for things the message had
    # said; so that is left to code: _said_it_all.)
    "Where more than one WHEN would do (a helper for a piece of text can work on what they highlight, or on what "
    "they send it in the chat), say the ways and ask which suits them.\n"
    # With everything known a model asked whether a bubble should stay up or go away by
    # itself, and of a helper asked in the chat whether its answer should be copied as well,
    # which no such helper can do.
    "3. Ask only for what you cannot work out and what has no usual value. Never ask again for something they told "
    "you. A setting that has a usual value is never worth a question: it gets its usual value, and they can ask "
    "for another once they see the card.\n"
    "4. When they have agreed to what you proposed, or their own message already said all of it, and nothing "
    f'needed is missing, the status is "{NOTHING_MISSING}": say so in one short line. The app then tries the helper '
    "on their real things without changing anything, shows what it would have done, and shows a card; only the "
    "card's button creates the helper.\n"
    # Told that two files had gone to the wrong folder, a model answered "I have updated the
    # rules to ensure..." over a rule that said nothing new about them, and when told they
    # still went there, "I've fixed the rule" over the same rule, word for word.
    "5. After a try-out they may correct it. Put every correction into the rule or the settings so the small model "
    "gets it right next time, and keep everything else they agreed to. THE TRY-OUT shows what the small model took "
    "each thing for: when something came out wrong, the rule as it stands let it, and the same rule written again "
    "changes nothing. Rewrite it so that it tells apart the things that were mixed up. Then say what you changed, "
    "never that it works now: the app tries it again and shows the result under your words.\n"
    f'If what they want cannot be made from what is listed, say so honestly and what it would take, and choose '
    f'"{NONE_FIT}".\n'
    "\n"
    "They are not technical. Work it out with them the way a person would: understand what they want, use what is "
    "already known instead of asking for it again, and ask only for what you cannot sensibly guess. When you do "
    "guess, say what you assumed. If they answer something you did not ask, take it. If they ask you something "
    "about the helper, answer it from HOW THESE WORK, then carry on. Never say it is on, started, created or done: "
    "only they can create it, with the button on the card that appears below your words once nothing needed is "
    "missing."
)
# The opening: a first message is read on its own, with this short note and a form of two
# fields, before the long note and the whole form are used at all. Told in the long note
# to ask about their situation when a message only named a trouble, the model answered "my
# downloads folder is a mess, can you do something about it" with a helper that moves files
# and "What specific categories or folders should I move them into, and what rules should I
# use to decide where each file goes?", four times out of four. Asked as the first field of
# the whole form, the same decision came out one way for nearly every first message, one
# that asked for something no helper can do included. With this note alone it was right
# for 42 of 45 first messages (fifteen, three times each, gemma4:12b, 20 Nov 2026), in half
# a second each.
OPENING = (
    "Someone has just asked you for a helper on their computer: something that does a job for them, by itself or "
    "when they ask. Below is their first message. Before anything is worked out, decide one thing: have they said "
    "what they want done?\n"
    f'- "{TOLD}": the message says, even roughly, what is to be done: something answered, written, explained, '
    "moved, kept track of, sent, booked... Whether it can be made is not the question here.\n"
    f'- "{NOT_TOLD}": the message says only that something bothers them, or asks for help with it, and nothing of '
    "what should be done about it.\n"
    # (Told to ask what the things are and only otherwise what bothers them, it asked in
    # Korean how they would like the files organized, three times out of three; with the
    # two side by side it asked what kinds of files pile up there.)
    f'With "{NOT_TOLD}", write the one short question you ask them now: what their things are, mostly, or what '
    "bothers them most about it. Not what they would like to happen, and nothing about folders, groups or rules: "
    f'they came to you because they do not know. With "{TOLD}", leave the question empty.'
)
OPENING_SCHEMA = {"type": "object", "properties": {"heard": {"enum": [TOLD, NOT_TOLD]}, "question": {"type": "string"}},
                  "required": ["heard", "question"]}
# The aside: whether a message in the middle is part of this conversation at all is decided
# on its own, with this short note and a form of one field, before the whole form is
# filled. Left to the status of the whole form, a model on this computer handed back one
# such message of three (22 Nov 2026, through the real engine): asked at the card how many
# legs a spider has, it answered that itself in a form that said a change had been asked
# for, and the person read "Nothing changed on the card: as far as I can tell it already
# does that"; asked for the tallest mountain in Africa under a helper it had just
# proposed, it took that for a yes, said "I'm ready to set this up for you", and the
# try-out and the card came. With this note alone it was right for 153 of 153 (fifty-one
# messages in seven conversations, two of them changes to a helper, thirty-three of the
# messages part of the conversation, three times each, gemma4:12b), a quarter of a second
# each. The built-in model, given the same note, took three of twenty-six that were part
# of it for something else ("why did the ... go to ...?" among them), so the decision is
# only made when the design model is on this computer; a plan's model is left to say it
# in the whole form, where a turn more would cost a whole answer.
PART_OF_THIS, SOMETHING_ELSE = "Part of this", "Something else"
ASIDE = (
    "You and this person are in the middle of working out a helper for their computer: something that does a job "
    "for them. Below is what the helper is for, the last thing you said to them, and what they have just written. "
    "Decide one thing: is what they wrote part of this conversation, or is it about something else?\n"
    f'- "{PART_OF_THIS}": an answer to what you said, a yes or a no, anything about the helper, its card, its try-out '
    "or their own files and folders, something they want changed, a question about how it works or what it will do, "
    "a piece of text to try it on, or that they no longer want it.\n"
    f'- "{SOMETHING_ELSE}": a question about the world, something to look up or work out, or a piece of work that has '
    "nothing to do with this helper.\n"
    f'When you cannot tell, it is "{PART_OF_THIS}".'
)
ASIDE_SCHEMA = {"type": "object", "properties": {"about": {"enum": [PART_OF_THIS, SOMETHING_ELSE]}}, "required": ["about"]}
ASIDE_ASKS = "THE HELPER\n{helper}\n\nYOUR LAST WORDS TO THEM\n{last}\n\nTHEY HAVE JUST WRITTEN\n{said}"
# The mender: a rule that did not do what they asked is written again with this short note
# and a form of one field. In the whole form a model that read its own rule as saying the
# right thing wrote it out unchanged, twice, with the try-out that said otherwise in the
# same note. Given only the rule, what the try-out did with the files they spoke of and
# what they said, it writes a new rule every time, in about a second (gemma4:12b, 20 Nov
# 2026). What it is told to write matters: told to say which part of the rule wins, its
# rules got 6 of the 8 files of a try-out right in three rewrites out of three, one fewer
# than the rule it was mending; told to say what the thing is and what it is not, 8 of 8
# in four out of four.
MEND = (
    "A small model on this person's computer follows one rule, written in plain words, for every new file in a "
    "folder: it reads the rule and the beginning of the file, knows nothing else, and does what the rule says with "
    "the file. The person has seen what it did with some of their files and wants something to come out "
    "differently. Write the whole rule again so that it does.\n"
    "- Keep everything the rule says that they have not asked to change, in the same plain sentences.\n"
    "- The rule as it stands let the small model do what they are unhappy with, so adding nothing changes "
    "nothing. Say in the rule, as a plain statement the way the person would say it, what such a thing is and "
    "what happens to it; and when it was taken for another kind of thing, that it is not that kind. Do not add a "
    "sentence about which part of the rule wins: the small model does not follow those.\n"
    '- You may write the whole rule anew as plain statements about their things, in place of a list of "if" '
    "conditions: the small model follows those better.\n"
    # A sentence written for the one file they had spoken of ("An invoice for ... services
    # is a ... file") took the next file like it along, into the wrong folder.
    "- Say it of the kind of thing, in their words, not of the one file. What the rule did with the other files "
    "is listed too: those are to come out as they did.\n"
    "- Only what they asked for: nothing of your own.\n"
    # (A rule that had grown by a sentence at each correction came back longer than a rule
    # may be, and its last sentence, the one that said which part wins, was cut off.)
    "- At most {limit} characters. If it would be longer, say the same in fewer words: one sentence for each kind "
    "of thing.\n"
    "Fill in `rule`: the whole new rule, word for word as the small model will read it."
)
MEND_SCHEMA = {"type": "object", "properties": {"rule": {"type": "string"}}, "required": ["rule"]}
# The writer: before a rule from the whole form goes on a card, it is written out once
# more from this short note, which has only what the helper does, the conversation and the
# draft. In the whole form a model put things into the rule that nobody had said, with
# HOW TO DESIGN saying not to: asked for a few lines about each new document with who it
# is with and how much, it added "Do not include any information about the file name or
# date", and the person, who wanted the dates, found that on the card. From
# this note alone the same model left that sentence out 3 times of 3; put back a word of
# the person's own that its draft had lost, 3 of 3; took "When the user highlights ..."
# out of a rule, which is when the helper works and not its job, 3 of 3; and wrote a
# draft with nothing wrong in it out again word for word, 3 of 3, which the built-in model
# then followed as before (23 of 23 files, twice each). A third of a second each
# (gemma4:12b, 20 Nov 2026).
WRITE = (
    "A small model on this person's computer will follow one rule, written in plain words, for every single thing a "
    "helper of theirs works on: it reads the rule and the thing, knows nothing else, and does what the rule says. "
    "Below is what the helper does, what the person and you said while working it out, and a draft of the rule. Write "
    "the rule the small model will read.\n"
    "- Keep what the draft says that was said in the conversation, by them or by you: what you proposed and they did "
    "not turn down is agreed.\n"
    "- Leave out what was never said in the conversation: a limit, an exception or an extra that neither of you "
    "spoke of is not theirs.\n"
    "- Put in what they asked for and the draft left out.\n"
    "- Plain statements, in their own words for their things. Only what is done with the thing, never when the "
    "helper works or where anything is kept.\n"
    # (A draft that said "to help the user remember" was written out with "the user" in it,
    # and the notes made from it spoke of "the user".)
    '- Never "the user" in it: where the rule has to speak of the person at all, they are "I" and "my".\n'
    "- At most {limit} characters.\n"
    "Fill in `rule`: the whole rule, word for word as the small model will read it."
)
# What the parts cannot reach, said outright. With only the parts listed, a wish for
# something that reads the person's mail every morning and says which messages matter was
# answered "I can help with that" and then worked into a helper asked in the chat, with a
# rule about "the emails provided" and not a word that it could not see a mailbox. (What is
# listed here is what the parts are: three ways in, and the results there are. Nothing in
# it is about what any one helper is for.)
NO_HELPER_CAN = (
    "WHAT NO HELPER CAN DO\n"
    "Only three things can ever go into a helper: text the person highlights, text the person sends it in the chat, "
    "and the files of one folder on this computer. And only the results listed above come out of one. So no helper "
    "can read their mail, their messages, their calendar or a website, look anything up on the internet, open or "
    "work another program, or send, post, book, buy or pay for anything.\n"
    "When what they ask for needs one of those, say so plainly in your very next words, and never work around it in "
    f'silence. If nothing of it is left without that, it cannot be made: the status is "{CANT_BE_MADE}". If a part of '
    "it could be made from what is listed, say which part cannot be done, say what could be made instead and how "
    "they would use it, and ask whether that would be of any use to them."
)
EDITING = ("They already have this helper and want it changed. KNOWN SO FAR is how it is now: change what they ask "
           "for and keep everything else as it is. "
           # Asked to have a helper take one more kind of thing, a model answered "I have
           # updated the helper to include ...", with nothing saved and no card shown yet.
           "Their helper stays exactly as it was until they press the button on the card that saves the changes: "
           "say what the card would now do, never that the helper has been updated or changed.")
FORM_NOTE = (
    "FORM NOTE\n"
    "Fill in the form, in its order.\n"
    "- wants: what they want, in one plain sentence and in their own terms, as far as they have said it. Only "
    "what they said, nothing you assume.\n"
    # Written before the settings, so the change is said before it is made: a correction
    # that was only spoken of in the words at the end was left out of the rule twice.
    "- changes: once a card is on their screen, what their last message asks to be different on it, in one plain "
    "sentence. Then make that change in the settings or the rule below: said only here or in your words, it "
    "changes nothing. Empty while there is no card, and when their message asks for no change or the card "
    "already does what they ask.\n"
    "- when, then: the WHEN and the THEN of this helper, each written exactly as it is listed above, and only two "
    f'that go together. "{NOT_CLEAR}" while they have not told you what should happen. "{NONE_FIT}" only when what '
    "they want cannot be made from what is listed at all.\n"
    "- Each setting ({settings}): what you now understand, filled the way its line above says. Fill only the "
    "settings of the WHEN and the THEN you chose. Leave a setting empty if they have not said and you would only "
    "be guessing blindly; a setting that is already known stays as it is when you leave it empty.\n"
    "- try_on: only for a helper that works on text: a short piece of text to try it on. Their own text, word for "
    "word, when they gave you one; else one you make up that fits what they described. Empty for any other helper.\n"
    f'- status: "{STILL_ASKING}" while you are still finding out what they want, while something needed is not '
    "known, when you have described how the helper would work and are asking whether that is right, or when you "
    f'are answering a question of theirs; "{NOTHING_MISSING}" when they have agreed to what you described, or said '
    f'all of it themselves, and nothing needed is missing; "{CANT_BE_MADE}" when the helper cannot be '
    "made from what is listed (when only a part of what they ask for cannot be done, say so and carry on with the "
    "rest instead)"
    "{more_status}.\n"
    # What a question is about is not taken from the same form (_take_form): a model asked
    # which folder to watch and filled in a guess for it, and the card came for the guess.
    '- asks: the one setting your question asks them for ("when" or "then" when it asks for those), which you '
    "then leave empty, since you do not know it yet; empty when you ask nothing, or ask about no setting in "
    "particular, as when you ask whether what you described is right. Never the rule: that is yours to write.\n"
    "- say: your words to them, written last. {ready_say}"
)
# What to say with nothing missing: the first time, the card is new; after that it is on
# their screen already, and told to point at its button each time, a model did, in every
# answer ("...that one will stay where it is. The card below has the button to create it.").
CARD_COMES = (f'With "{NOTHING_MISSING}", sum up in one or two sentences what it will do and what it leaves alone, and '
              "tell them the card below has the button to create it.")
CARD_SAVES = (f'With "{NOTHING_MISSING}", say what you changed in one or two sentences and tell them the card below '
              "has the button to save it.")
CARD_IS_UP = ("The card is already on their screen: only answer them, or say what you changed, in a sentence or "
              "two. Say nothing about the card or its button.")
# For the second form of a turn in which code could not use something: no card follows
# that turn, so its words must not point at one. Still told the card comes, a model wrote
# "The card below has the button to create it" with nothing below.
CARD_WAITS = ("No card is shown after your words this time, whatever the status, because something in your last form "
              "could not be used: say plainly what could not be used and ask about it. Say nothing about a card or a "
              "button.")
# A sentence that points at the card, to take off words that no card follows.
POINTS_AT_CARD = re.compile(r"\b(card|button)\b", re.IGNORECASE)
# Asked in the middle whether it would rain tomorrow, a model that had just read what no
# helper can do answered for itself: "I cannot check the weather because I am not allowed
# to look at websites or the internet", which is untrue of the chat, where that is looked
# up. Such a message is handed back to the app, which answers it as it answers any other.
MORE_STATUS = (f'; "{CALLED_OFF}" if they no longer want it; "{MOVED_ON}" when their message is about something else '
               "than this helper (a question about the world, something to look up or work out, another job): that "
               "is not yours to answer here, and what a helper cannot do says nothing about it. The app answers it")
# "I can certainly help you with that." A model opens with it however it is told not to,
# so code takes it off, as voice.OPENER does for chat answers. Only an offer that says
# nothing: "I can watch your Downloads folder" stays.
OPENING_OFFER = re.compile(
    r"^(?:(?:sure|certainly|of course|absolutely|okay|ok|great|got it)[!.,]\s*)?"
    r"(?:i (?:can|could|will|would)|i'll|i'd)(?: certainly| definitely| gladly| happily| absolutely)? "
    r"(?:help(?: you)?(?: with (?:that|this))?(?: set (?:that|this|it) up)?|do (?:that|this|it)|set (?:that|this|it) up|"
    r"make (?:that|one)|handle (?:that|this|it)|take care of (?:that|this|it))(?: for you)?[.!]\s+(?=\S)|"
    # "I can help tidy that up." "I can help you organize those files." Every first answer
    # began with one of these. Only a whole sentence with no "but" or comma in it, which may
    # carry something they need to know.
    r"^(?:i (?:can|could|will|would)|i'll|i'd)(?: certainly| definitely| gladly| happily)? (?:be (?:happy|glad) to )?"
    r"help\b(?![^.!?]*\bbut\b)[^.!?,;:]*[.!]\s+(?=\S)",
    re.IGNORECASE)
# "Shall we begin?" at the end of an answer at the card: only the button begins anything,
# and a yes to it would be taken for an answer to a question instead of a yes to the card.
# ("Should I proceed with setting this up?" stood under an answer at the card, and the "ok
# make it" typed next went to the model, which said it had everything it needed.)
CLOSING_NUDGE = re.compile(r"^(shall|should|can|may) (we|i) (now )?(begin|start|get started|go ahead|get going|proceed|"
                           r"continue|create|make|build|finish|save|set (it|this|that|things) up)\b[^.!?]*\?$",
                           re.IGNORECASE)
# An offer of more help at the end of an answer, which asks nothing whether or not it ends
# in a question mark.
MORE_HELP = re.compile(r"^\s*(is there anything|anything else|let me know|just let me know|feel free|if you need|"
                       r"if you have any|hope (this|that) helps|happy to help|더 필요한|궁금한 (점|게)|언제든)",
                       re.IGNORECASE)
# "Is this correct?" "Does that sound like the right plan?": a question that asks only
# whether what was just described is right. Not one with an "if" in it, which asks about
# something: "Is it okay if we start with just the new ones?".
# (With one word after "this" or "that": "Does this setup look correct to you?" stood under
# a card, and a yes typed under it would have gone to the model as an answer.)
CONFIRMS = re.compile(r"^(?:is|does|do|did|would|will|how does)\s+(?:(?:this|that)(?:\s+[a-z]+)?|it|everything)\s+(?:all\s+)?"
                      r"(?:sound|look|seem|work|cover|correct|right|ok|okay|fine|good|what you|how you)\b(?![^?]*\bif\b)"
                      r"[^.!?]{0,40}\?$", re.IGNORECASE)
# Where a second question is joined to a first: ", and what would you like ...".
SECOND_QUESTION = re.compile(r",?\s+(?:and|or)\s+(?:what|how|which|where|who|when|why|is|are|do|does|did|should|would|"
                             r"could|can|will)\b", re.IGNORECASE)
# A field that was to be left empty sometimes comes back holding a word for empty.
NO_CHANGE = re.compile(r"^\W*(n/?a|none|nothing|no changes?|empty|null|no)?\W*$", re.IGNORECASE)
# What code says when the model said a change was asked for and, asked twice, made none.
# Left to the model's words, the user read "I've fixed the rule" over a rule that was word
# for word what it had been.
NOT_CHANGED = ("I couldn't work that into the card: it is still as it was. Could you tell me another way what should be "
               "different?")
# The same, when the model's second form says that all is ready: it takes the card to do
# what they said already. (Thanked for a change it had made a turn before, a model wrote
# that change down again as what was asked for now; "I couldn't work that into the card"
# was then said to someone who had asked for nothing.)
ALREADY_SO = ("Nothing changed on the card: as far as I can tell it already does that. If something should still be "
              "different, tell me what.")
# Words that say a change was made.
CLAIMS_CHANGE = re.compile(r"\b(updated?|chang(?:ed|ing)|fix(?:ed)?|corrected|adjusted|modified|revised|rewr\w+|added|"
                           r"removed|amended|renamed)\b|수정|변경|추가|바꿨|고쳤", re.IGNORECASE)
# Words of the settings' labels and choices that nearly every message and answer about a
# helper has in it ("make sure", "the rule", "the result is too long", "call it ..."), and
# so say nothing of which setting is meant (_setting_words).
PLAIN_WORDS = {"what", "when", "only", "make", "text", "file", "rule", "result", "long", "call"}
# A question that offers more than one thing to pick: "a bubble, the clipboard, or both?".
# A plain yes picks none of them, and is answered with this, under the same buttons.
OFFERS_MORE = re.compile(r"\bor\b|아니면|또는", re.IGNORECASE)
WHICH_ONE = "Which one would you like?"
ECHOED = 0.6  # the share of a change's telling words that earlier changes already had, for it to be one of them again
# The same, for a change that has no word of their message in it: one that is not about
# what they just said needs less to be taken for an earlier one said again.
ECHOED_LOOSELY = 1 / 3
# What a rule may not say, because it is a setting and not the job: how a result is shown.
# The built-in model reads the rule as its whole job, and one that ended "The result should
# be shown in a bubble above the text" came back with its answer between two round emoji.
SHOWN_HOW = re.compile(r"\b(bubbles?|clipboard)\b", re.IGNORECASE)
JSON_ONLY = "Reply with one JSON object and nothing else, matching this JSON Schema exactly:"

# (the note for the model, the conversation, the form's schema) -> the filled form
Form = Callable[[str, list[dict], dict], dict]


class DesignerError(RuntimeError):
    """The design model couldn't take its turn; the conversation ends, plainly, with nothing made."""


class DesignModel:
    """One model that takes the turns of a designing conversation. `here`: it runs on this computer."""

    def __init__(self, form: Form, name: str, here: bool, loaded: Callable[[], bool] | None = None,
                 release: Callable[[], None] | None = None):
        self.form, self.name, self.here = form, name, here
        self._loaded, self._release = loaded, release

    def fill(self, note: str, turns: list[dict], schema: dict) -> dict:
        """One turn: the model reads the note and the conversation, and fills the form."""
        try:
            filled = self.form(note, turns[-MAX_TURNS:], schema)
        except OllamaError as exc:  # a form the engine wrapped: whatever stopped it, it is the same to the user
            raise DesignerError(str(exc)) from exc
        if not isinstance(filled, dict):
            raise DesignerError("it didn't fill in the form")
        return filled

    def waking(self) -> bool:
        """Whether its model still has to be loaded, so the first turn takes a while."""
        if self._loaded is None:
            return False
        try:
            return not self._loaded()
        except OllamaError:
            return False

    def done(self) -> None:
        """Its work is over, or the built-in model needs the room for a try-out: a local model
        leaves the graphics memory at once. (It comes back by itself at its next turn.)"""
        if self._release is not None:
            try:
                self._release()
            except Exception:  # noqa: BLE001 - Ollama already stopped: nothing is loaded
                pass


def local_form(ollama: Ollama, tag: str) -> Form:
    """A form filled by a model on this computer, forced into the schema by Ollama."""
    think = None

    def form(note: str, turns: list[dict], schema: dict) -> dict:
        nonlocal think
        try:
            if think is None:  # a thinking model left to itself thinks first, and a turn takes ten times as long
                think = "thinking" in ollama.capabilities(tag)
            return ollama.chat_json(tag, [{"role": "system", "content": note}, *turns], schema,
                                    think=False if think else None, keep_alive=DESIGN_KEEP_ALIVE,
                                    options={"num_ctx": DESIGN_CONTEXT, "temperature": DESIGN_TEMPERATURE})
        except OllamaError as exc:
            raise DesignerError(str(exc)) from exc

    return form


def talker_form(talker, model: str = "") -> Form:
    """A form filled by a plan or key model, which only writes text: the note, the
    conversation and the schema go as one message (the plans' apps drop system messages,
    accounts.transcript), and the JSON is read out of what comes back."""

    def form(note: str, turns: list[dict], schema: dict) -> dict:
        said = "\n".join(f"{'You' if turn['role'] == 'assistant' else 'Them'}: {turn['content']}" for turn in turns)
        prompt = f"{note}\n\nTHE CONVERSATION SO FAR\n{said}\n\n{JSON_ONLY}\n{json.dumps(schema)}"
        try:
            text = "".join(talker.chat(model, [{"role": "user", "content": prompt}]))
        except Exception as exc:  # noqa: BLE001 - signed out, used up, no internet: whatever it was, the conversation ends plainly
            raise DesignerError(str(exc)) from exc
        return read_form(text)

    return form


def read_form(text: str) -> dict:
    """The JSON object in a model's reply, with or without a code fence around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DesignerError("it answered without the form")
    try:
        filled = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise DesignerError("its form couldn't be read") from exc
    if not isinstance(filled, dict):
        raise DesignerError("its form couldn't be read")
    return filled


def tidy_say(said: object, asking: bool = False) -> str:
    """The model's words as one clean paragraph: no wrapping quotes, no line breaks, no
    opening or closing offer, not endless. `asking`: something needed is still not known,
    so a question at the end that asks for it stays."""
    text = re.sub(r"\s+", " ", said if isinstance(said, str) else "").strip()
    # Only a pair of quotes around the whole of it: taken off either end on its own, words
    # that ended in a quoted name lost one of its quote marks.
    text = _unquoted(text)
    rest = OPENING_OFFER.sub("", text, count=1)
    if rest != text:
        text = rest[:1].upper() + rest[1:]
    # A closing offer ("Is there anything else you would like to change before we begin?")
    # comes off too, as in chat answers: it asks nothing, and a question at the card makes
    # the next yes an answer to it instead of a yes to the card.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    while len(sentences) > 1 and _closing_offer(sentences[-1], asking):
        sentences.pop()
    text = " ".join(sentences)
    if len(text) > MAX_SAY:
        cut = text[:MAX_SAY]
        text = cut[:max(cut.rfind(". "), cut.rfind("? ")) + 1] or cut
    return text


def _closing_offer(sentence: str, asking: bool) -> bool:
    """Whether the last sentence of an answer is one to take off. At the card every closing
    offer goes. Before it, working a helper out is asking what people would like ("Do you
    want me to leave those alone?"), and the list that takes "Shall I..." and "Would you
    like..." off the end of a chat answer would take those questions off too, leaving an
    answer that asks nothing; so then only an offer of more help goes."""
    if CLOSING_NUDGE.match(sentence):
        return True
    if not CLOSING_FILLER.match(sentence):
        return False
    return not asking or not sentence.rstrip().endswith(("?", "？")) or bool(MORE_HELP.match(sentence))


def field_for(setting: parts.Setting) -> dict:
    """The form field for one setting: a choice is an enum, a folder is a place and a name,
    and only what must be free (a folder's own name, a list of names, the rule) is free text."""
    if setting.type in ("folder", "place"):
        places = [*PLACE_NAMES, *([INSIDE] if setting.type == "place" else []), ""]
        return {"type": "object", "properties": {"place": {"enum": places}, "name": {"type": "string"}},
                "required": ["place", "name"]}
    if setting.type == "choice" and setting.choices:
        return {"enum": [*_choices(setting), ""]}
    return {"type": "string"}


def _choices(setting: parts.Setting) -> list[str]:
    """What can be picked for a setting that is a choice, on the form and as buttons. One
    whose usual value is none of its choices has a word for that too (parts.NONE): an
    empty value never erases a known one, so without the word such a setting, once set,
    could not be taken off again."""
    return [*setting.choices, *([parts.NONE] if setting.default == "" else [])]


def schema_for(first: bool = False) -> dict:
    """The one form of every turn: what they want, what their last message asks to be
    changed, the WHEN and the THEN, every setting there is, then where things stand, then
    the words, in that order, so what it says agrees with what it filled in. On the first
    turn the request can't be "something else" or "never mind": it is what started the
    conversation."""
    settings = parts.all_settings()
    # Only what this computer can run is on the lists, as in the note: a THEN that goes with
    # no WHEN there is here could only be picked to be refused.
    properties: dict = {"wants": {"type": "string"},
                        "changes": {"type": "string"},
                        "when": {"enum": [*(part.key for part in parts.whens()), NOT_CLEAR, NONE_FIT]},
                        "then": {"enum": [*_thens(), NOT_CLEAR, NONE_FIT]}}
    properties.update({setting.key: field_for(setting) for setting in settings})
    properties["try_on"] = {"type": "string"}
    ends = [] if first else [CALLED_OFF, MOVED_ON]
    properties["status"] = {"enum": [STILL_ASKING, NOTHING_MISSING, *ends, CANT_BE_MADE]}
    properties["asks"] = {"enum": ["", WHEN.key, THEN.key, *(setting.key for setting in settings)]}
    properties["say"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties)}


def _setting_line(setting: parts.Setting) -> str:
    usual = "" if parts.needed(setting) else ", has a usual value"
    # Names in a list are told apart by commas, and by an "and" before the last of them.
    more = ' A name that has "and" in it goes in double quotes.' if setting.type == "list" else ""
    return f"  - {setting.label} (`{setting.key}`{usual}): {setting.how}{more}"


def _thens() -> list[str]:
    """Every THEN that goes with a WHEN this computer can run, in the catalog's order."""
    offered = [part.key for part in parts.whens()]
    return [then for then in parts.THENS if any(parts.fits(when, then) for when in offered)]


def _catalog() -> list[str]:
    """What a helper can be made of, as the model reads it: each WHEN and each THEN with what
    it does, which go together, and under each its settings."""
    lines = ["WHAT A HELPER CAN BE MADE OF", "WHEN it works, one of:"]
    for part in parts.whens():
        goes = ", ".join(f'"{then}"' for then in parts.FITS.get(part.key, ()))
        lines.append(f'- "{part.key}": {part.about} Its THEN can be: {goes}.')
        lines += [_setting_line(setting) for setting in part.settings]
    lines.append("What it does THEN, one that goes with the WHEN:")
    for then in _thens():
        lines.append(f'- "{then}": {parts.THENS[then].about}')
        lines += [_setting_line(setting) for setting in parts.THENS[then].settings]
    no_rule = [f'"{then}"' for then in _thens() if parts.RULE not in parts.settings_for("", then)]
    lines.append("And for every helper" + (f" (no rule for {', '.join(no_rule)})" if no_rule else "") + ":")
    lines += [_setting_line(parts.RULE), _setting_line(parts.NAME)]
    return lines


def _facts() -> list[str]:
    """How the parts work, each fact true to the code that runs the part."""
    lines = []
    for part in [*parts.whens(), *(parts.THENS[then] for then in _thens())]:
        lines.append(f'"{part.key}":')
        lines += [f"- {fact}" for fact in part.facts]
    return lines


def note_for(known: list[str], computer: list[str], tryout: list[str] = (), problems: list[str] = (),
             first: bool = False, card_up: bool = False, editing: bool = False, waits: bool = False) -> str:
    """Everything the model is told for one turn. Built again each turn from what code has
    checked, so the model never has to remember the card: it reads it. `known`: the card so
    far. `computer`: what code can see. `tryout`: what the last try-out did, when there was
    one. `waits`: code could not use something in this turn's first form, so no card follows it."""
    lines = [VOICE, "", HOW_TO_DESIGN]
    if editing:
        lines += ["", EDITING]
    lines += ["", *_catalog()]
    lines += ["", NO_HELPER_CAN]
    lines += ["", "HOW THESE WORK (you may tell the user; say nothing that isn't here)", *_facts()]
    lines += ["", "KNOWN SO FAR (checked by code)", *(f"- {line}" for line in known)]
    lines += ["", "ABOUT THIS COMPUTER (read by code just now)", *(f"- {fact}" for fact in computer)]
    if tryout:
        lines += ["", *tryout]
    if problems:
        lines += ["", "PROBLEMS WITH YOUR LAST FORM (put them right in this one, and tell them if they need to know)"]
        lines += [f"- {problem}" for problem in problems]
    ready_say = CARD_IS_UP if card_up else CARD_WAITS if waits else CARD_SAVES if editing else CARD_COMES
    settings = ", ".join(f"`{setting.key}`" for setting in parts.all_settings())
    lines += ["", FORM_NOTE.format(settings=settings, more_status="" if first else MORE_STATUS, ready_say=ready_say)]
    return "\n".join(lines)


def names_in(text: str) -> list[str]:
    """The folder names in a list as it was typed or filled in: told apart by commas, new
    lines and the "and" before the last of them ("A, B and C", "A and B"). Each is kept as
    it was given, less only what no folder's name can hold, and none comes twice
    (parts.choices_of, which is also how the list is read back when the agent runs). A name
    in double quotes is one name whatever is in it and wherever it stands, so a folder can
    have "and" in its name: `A and "B and C"` is two folders."""
    quoted: list[str] = []

    def hold(match: re.Match) -> str:
        # Out of the way while the list is taken apart. A comma can't be kept in a name: the
        # list is saved as names with commas between them.
        quoted.append(re.sub(r"[,;\n]+", " ", match.group(1) or match.group(2)))
        return f"\x00{len(quoted) - 1}\x00"

    held = QUOTED_NAME.sub(hold, text.replace("\x00", " "))
    pieces = [piece.strip() for piece in re.split(r"[,;\n]+", held) if piece.strip()]
    if pieces:
        pieces += AND_WORD.split(pieces.pop())
    whole = [re.sub(r"\x00(\d+)\x00", lambda match: quoted[int(match.group(1))], piece) for piece in pieces]
    return parts.choices_of({"choices": [piece.strip(" \"“”") for piece in whole]})


def _listed(names: list[str]) -> str:
    """A list of folder names the way names_in reads it back: a name it would take apart
    at an "and" goes in double quotes. The model fills a list in again as it reads it, and
    shown without them, a folder with "and" in its name came back as two folders."""
    return ", ".join(f'"{name}"' if AND_WORD.search(name) else name for name in names)


def row_line(row: dict, then: str, was: dict | None = None) -> str:
    """One file of a try-out as the user reads it. `was`: the same file in the try-out
    before this one, when the card was changed in between, so a different outcome says what
    it was before. A file that would be moved says what the built-in model took it for, as
    one that stays already does in its reason: a file's name, an arrow and a folder gave
    nobody a way to see that the file was being taken for something it was not, neither
    the user nor the model that had to put the rule right."""
    name = row.get("name")
    why = _one_line(row.get("why"), 200)
    if then == parts.NOTE:
        # The note as it would be written, on one line: a few lines about a file are what
        # the helper is for, and shown only the start of the first of them, nobody could
        # see whether what they had asked to have in it was there.
        note, old = _note_shown(row.get("note")), _note_shown(was.get("note")) if was else ""
        if note:
            return f"{name}: {note}" + (" (nothing before)" if was is not None and not old else "")
        if old:
            return f"{name}: nothing to write now (was: {old})"
        return f"{name}: nothing to write" + (f" ({why})" if why else "")
    choice = str(row.get("choice") or "")
    old = str(was.get("choice") or "") if was else ""
    if choice:
        took = _one_line(row.get("what"), 120)
        different = was is not None and old != choice
        more = [*(["a new folder"] if row.get("new") else []),
                *([f"was {old}" if old else "stayed before"] if different else []),
                *([f"read as {took}"] if took else [])]
        return f"{name} → {choice}{' now' if different else ''}" + (f" ({'; '.join(more)})" if more else "")
    if old:
        return f"{name}: stays now (was {old}" + (f"; {why})" if why else ")")
    return f"{name}: stays" + (f" ({why})" if why else "")


@dataclass(frozen=True)
class Refused:
    """A value in the model's form that code didn't take."""
    key: str  # the setting
    value: str  # what the form gave, to know it again
    told: str  # for the model: why not, and what would be right
    said: str  # for the user, in plain words, if the model doesn't put it right
    # Whether the card waits in a turn where this was refused. It does when something the
    # user said couldn't be used, since the model may have guessed its way around that (a
    # WHEN and a THEN that don't go together are that too: refused a bubble for each new
    # file, a model picked a notes file instead, and the card came for a helper nobody had
    # asked for); not when only the model's own writing was at fault (a rule too long) and
    # its second form put that right.
    waits: bool = True


@dataclass
class Sketch:
    """The card being worked out."""
    slots: dict
    request: str  # the message that started it
    model: DesignModel
    turns: list = field(default_factory=list)  # the conversation's own turns
    wants: str = ""  # what the user wants, in one sentence, as last understood
    waiting: str | None = None  # DESIGN, CARD, or DUPLICATE while they are asked about a helper they have
    shown: dict | None = None  # the slots the card last showed
    tried: list | None = None  # the last try-out's rows
    tried_with: dict | None = None  # what that try-out ran with
    try_on: str = ""  # a helper that works on text: the sample it is tried on
    try_theirs: bool = False  # that sample is the user's own text, not one that was made up
    same: str | None = None  # the helper they have that this one would repeat, while they are asked about it
    same_asked: bool = False  # they were asked about one once: not again
    replaces: str | None = None  # the agent being changed
    editing: bool = False
    # A change that only the router's model took the message for (code did not decide it):
    # its first turn may say the message is about something else, or that they don't want it.
    unsure: bool = False
    ignored: set = field(default_factory=set)  # (setting, value) refused twice: passed over from then on
    named: bool = False  # the user gave it its name themselves
    proposed: bool = False  # a whole helper was described to them once, and the card waited for their answer
    written: dict = field(default_factory=dict)  # each draft of the rule the form gave, and how the writer wrote it out
    changes_made: list = field(default_factory=list)  # what the model wrote as the change, each time the card changed
    told_how: bool = False  # the model was told once to say how a helper asked in the chat is asked
    told_folders: bool = False  # the model was told once that the folders are its to propose
    told_thens: bool = False  # the model was told once which results go with the WHEN it chose
    took: dict = field(default_factory=dict)  # folder settings: the form's value that was last taken
    # A helper they have, for which the model's form gave another name than the one it has:
    # "tell" until they have been told once how a name is changed, "told" after.
    rename: str = ""
    readable: tuple | None = None  # (folder, how many of its files a documents helper can read)
    asked: str = ""  # the setting the last question was about, so it gets its buttons when it is asked again
    which_asked: str = ""  # the question under which a plain yes was answered "Which one?": only once


@dataclass
class _Filled:
    """One filled form, read: what is not on the form's lists is taken for nothing."""
    values: dict
    wants: str = ""
    changes: str = ""  # what it says the user's last message asks to be different on the card
    when: str = ""
    then: str = ""
    try_on: str = ""
    status: str = STILL_ASKING
    asks: str = ""
    say: str = ""  # as the model wrote it; tidied once it is known whether something is missing


class Designer:
    def __init__(self, ollama: Ollama, model: str, think: bool | None, rehearse: Callable[[store.Agent], list[dict]],
                 design_model: Callable[[], DesignModel | None], model_name: Callable[[], str]):
        """`ollama`, `model`: the built-in model, which a text helper is tried with.
        `rehearse`: a dry run of a card on the newest files in its folder, changing nothing.
        `design_model`: who talks right now, or None; asked at each start, so a change in the
        model menu applies at once. `model_name`: the built-in model's name, for the card."""
        self.ollama = ollama
        self.model = model
        self.think = think
        self.rehearse = rehearse
        self.design_model = design_model
        self.model_name = model_name
        self.sketch: Sketch | None = None
        # Set when the user turned to something else mid-way: the engine handles this
        # text normally, as it handles any message.
        self.handoff: str | None = None
        # The helper that was being worked out then. It is kept as it stood, and it is not
        # active: nothing typed or clicked is routed to it until they say to carry on
        # (carry_on). An aside used to end the conversation, and what had been worked
        # out with them over several turns was gone for one question about the weather.
        self.aside: Sketch | None = None
        self.created: store.Agent | None = None
        self._offered: dict[str, str] = {}  # see _turn
        self._put_right: set[str] = set()  # see _turn
        self._unnamed: dict[str, str] = {}  # code's sentences of this turn that name files, without the names
        self._change_asked = False  # by this turn's form, their message asked for a change to the card
        self.edited = False  # whether the agent made last was a change to one they had
        self.replaced: str | None = None  # the name it had before, when that change renamed it

    @property
    def active(self) -> bool:
        return self.sketch is not None

    def available(self) -> bool:
        """Whether a design model can be had right now."""
        return self.design_model() is not None

    def take_created(self) -> store.Agent | None:
        """The card made by the last Create it or Save changes, once; None otherwise. (A
        helper that answers from documents is finished where it is made, and is never here.)"""
        created, self.created = self.created, None
        return created

    # ------------------------------------------------------------ entry

    def start(self, request: str) -> Iterator[Event]:
        """A new helper, from nothing: the request is the conversation's first turn."""
        model = self.design_model()
        if model is None:
            yield from say(NO_DESIGNER)
            return
        yield from self._leave_aside()
        self.sketch = Sketch({}, request, model)
        yield from self._open()

    def edit(self, agent: store.Agent, request: str, unsure: bool = False) -> Iterator[Event]:
        """Change a card they have by talking: the sketch starts as the card is saved, the
        request is the first turn, and nothing is saved until they say so on the card.
        `unsure`: only the router's model took the request for a change to this helper, so
        the first turn may hand it back (`handoff`) or call it off."""
        if agent.blueprint != parts.CUSTOM:
            yield from say(f"I don't know how to change {agent.name} by talking it through.")
            return
        model = self.design_model()
        if model is None:
            yield from say(NO_DESIGNER)
            return
        slots = dict(agent.slots)
        # A card saved before there were THENs has the one its WHEN always meant, and one
        # with no WHEN works while switched on, as it always has.
        slots["when"] = slots.get("when") or parts.WHILE_ON
        slots["then"] = parts.then_of(slots)
        slots["name"] = agent.name
        yield from self._leave_aside()
        self.sketch = Sketch(slots, request, model, replaces=agent.name, editing=True, unsure=unsure)
        yield from self._open()

    # ------------------------------------------------------------ set aside, and taken up again

    def set_aside(self) -> None:
        """Keep the helper being worked out as it stands, and stop being the one that is
        talked to: from here on nothing typed or clicked reaches it until `carry_on`. A
        model on this computer leaves the graphics memory meanwhile, since nobody knows
        how long that is; it comes back by itself at its next turn."""
        sketch, self.sketch = self.sketch, None
        if sketch is not None:
            sketch.model.done()
            self.aside = sketch

    def carry_on(self) -> Iterator[Event]:
        """Take up the helper that was set aside, where it stood: one line that says where
        that was, then the question that was open, or the card as it was with the try-out
        it had. Nothing is asked of a model for this: the try-out is shown from what was
        kept of it, and the design model takes its next turn when they next say something
        (one on this computer loads again then, by itself). It is the model the helper was
        begun with, whatever the model menu says by now: what was said so far was said to
        that one, and a conversation held on this computer is not handed to a model off it."""
        sketch, self.aside = self.aside, None
        if sketch is None:
            yield from say("That question has already been answered.")
            return
        self.sketch = sketch
        what = f"the changes to {sketch.replaces}" if sketch.editing else "the helper we were working out"
        if self._card_is_current():
            button = "Save the changes" if sketch.editing else "Create it"
            yield from say(f"Back to {what}. Here is {sketch.slots['name']} as we left it: {button.lower()} if it looks "
                           "right, or tell me what to change.")
            again = self._tried_before()
            if again:
                yield Result(TRY_OUT, again)
            yield self._card()
            # Nothing is asked in those words, so a plain yes typed now is a yes to the card.
            sketch.waiting = CARD
            return
        if sketch.waiting == DUPLICATE and sketch.same:
            question = self._same_question()
            yield Question(question.id, f"Back to {what}. {question.text}", question.choices)
            return
        last = next((turn["content"] for turn in reversed(sketch.turns) if turn["role"] == "assistant"), "")
        sketch.waiting = DESIGN
        if "?" in last:
            setting = self._choice_setting(sketch.asked)
            yield Question(setting.key if setting else DESIGN, f"Back to {what}. {last}",
                           _choices(setting) if setting else None)
        elif last:
            yield from say(f"Back to {what}. Where we left it: {last}")
        else:
            yield Question(DESIGN, f"Back to {what}. What should it do?")

    def drop(self) -> Iterator[Event]:
        """Leave the helper that was set aside: nothing was made of it."""
        sketch, self.aside = self.aside, None
        if sketch is None:
            yield from say("That question has already been answered.")
            return
        yield from say(_left_alone(sketch))

    def _leave_aside(self) -> Iterator[Event]:
        """Another helper is begun: one that was set aside is left, and that is said."""
        sketch, self.aside = self.aside, None
        if sketch is not None:
            kept = f"{sketch.replaces} is as it was" if sketch.editing else "nothing was created"
            yield Thinking(f"This begins another one, so I've left the helper we were working out before: {kept}.")

    def _open(self) -> Iterator[Event]:
        sketch = self.sketch
        model = sketch.model
        sketch.turns.append({"role": "user", "content": sketch.request})
        sees = ""
        if not model.here:
            # Everything a model off this computer is sent, said before it is sent (_computer,
            # _known): the line once named only what they type and their folders' names.
            own = f"how {sketch.replaces} is set up, " if sketch.editing else ""
            sees = (f" It sees what you type, {own}the names of your folders and {'other ' if sketch.editing else ''}"
                    "helpers, and how many files of each kind are in those folders, never your files' names or "
                    "what's in them.")
        yield Thinking(f"Working a helper out is a conversation, so {model.name} talks it through with you.{sees}")
        if model.waking():
            yield Thinking(f"Loading {model.name} first, which takes a few seconds.")
        if not sketch.editing:
            asked = yield from self._opening()
            if asked:
                return
        yield from self._turn()

    def _opening(self) -> Iterator[Event]:
        """The first message of a new helper, read on its own (OPENING): when it only says
        what bothers them, one question about their situation is asked and nothing is
        worked out yet. Returns whether that question was asked; if not, or if the model
        couldn't take this small turn, the conversation goes on to its first whole turn."""
        sketch = self.sketch
        computer = "\n".join(f"- {fact}" for fact in self._computer())
        note = f"{VOICE}\n\n{OPENING}\n\nABOUT THIS COMPUTER (read by code just now)\n{computer}"
        try:
            filled = sketch.model.fill(note, sketch.turns, OPENING_SCHEMA)
        except DesignerError:
            return False  # the whole turn says so plainly if the model really can't be had
        question = filled.get("question")
        question = _one_question(tidy_say(question, asking=True)) if filled.get("heard") == NOT_TOLD else ""
        if not question:
            return False
        sketch.turns.append({"role": "assistant", "content": question})
        sketch.waiting = DESIGN
        yield Question(DESIGN, question)
        return True

    def answer(self, text: str) -> Iterator[Event]:
        """The user typed something while a helper is being worked out."""
        sketch = self.sketch
        whole = text.strip().lower().strip("!. ")
        yes = (*CARD_YES, *(SAVE_YES if sketch.editing else ()))
        picked = self._same_choice(whole)
        if _calls_off(whole):
            yield from self._cancel()
        elif picked:
            yield from self._same_answer(picked)  # typed word for word instead of clicked
        elif sketch.waiting == CARD and (whole in yes or AGREES.match(whole)) and self._card_is_current():
            # A plain yes is a yes to the card on screen. Only the whole message counts
            # ("ok but put them somewhere else" is a change), and not when Noir has just
            # asked something: then the yes answers that.
            yield from self._create()
        elif sketch.waiting == CARD and whole in ("no", "nope", "아니"):
            yield from self._cancel()
        elif self._yes_to_more_than_one(whole):
            # Asked "a bubble above the text, the clipboard, or both?", they typed "yes",
            # which picks none of them. Sent on, the model picked "Both" for them, and once
            # made the helper copied every highlight over what was on their clipboard. The
            # question is asked again with its buttons, and nothing is filled in or kept.
            # Once: someone who answers "Which one?" with another yes is not asked it a third
            # time (in a play that ran "yes", "yes thats right", "ok", it was asked three
            # times and the helper was never made), and that yes goes on to the model.
            setting = self._choice_setting(sketch.asked)
            sketch.which_asked = self._question_now()
            yield Question(setting.key, WHICH_ONE, _choices(setting))
        elif self._is_aside(text):
            yield from self._answer_it_first(text)
        else:
            sketch.turns.append({"role": "user", "content": text})
            yield from self._turn()

    def _yes_to_more_than_one(self, whole: str) -> bool:
        """Whether the message is a plain yes typed under a question that has buttons and
        offers more than one of them ("... or ...?"). A yes to a question about one of them
        ("Is it okay if it shows above the text?") is an answer, and goes to the model."""
        sketch = self.sketch
        if sketch.waiting != DESIGN or not (whole in CARD_YES or AGREES.match(whole)):
            return False
        if self._choice_setting(sketch.asked) is None:
            return False
        last = self._question_now()
        return bool(OFFERS_MORE.search(last)) and last != sketch.which_asked

    def _question_now(self) -> str:
        """What Noir last said in the conversation (a "Which one?" is never kept in it)."""
        return next((turn["content"] for turn in reversed(self.sketch.turns) if turn["role"] == "assistant"), "")

    def _is_aside(self, text: str) -> bool:
        """Whether what they typed is about something else than this helper, decided on its
        own before anything is worked out with it (ASIDE). Only asked of a design model on
        this computer; when it can't be asked, the message is taken for part of the
        conversation, and the whole turn says so plainly if the model really can't be had."""
        sketch = self.sketch
        if not sketch.model.here:
            return False
        last = next((turn["content"] for turn in reversed(sketch.turns) if turn["role"] == "assistant"), "")
        helper = sketch.wants or sketch.request
        if sketch.editing:
            helper = f"A change to their helper {sketch.replaces}: {helper}"
        asks = ASIDE_ASKS.format(helper=_one_line(helper, MAX_SAY), last=last or "(nothing yet)", said=text.strip())
        try:
            filled = sketch.model.fill(ASIDE, [{"role": "user", "content": asks}], ASIDE_SCHEMA)
        except DesignerError:
            return False
        return filled.get("about") == SOMETHING_ELSE

    def _answer_it_first(self, text: str) -> Iterator[Event]:
        """Their message is about something else: the engine handles it as any message, and
        the helper is set aside as it stood. Nothing is said here in words, so the answer
        to what they asked is the first thing they read."""
        self.handoff = text
        self.set_aside()
        yield Thinking("That is about something else, so I'll answer it first. The helper we were working out waits "
                       "as it is.")

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        sketch = self.sketch
        if sketch is None:
            yield from say("That question has already been answered.")
        elif id == CARD and choice in (CREATE_IT, SAVE_CHANGES) and not self._card_is_current():
            yield from self._turn()  # the card isn't up, or isn't the card any more: the open question again
        elif id == CARD and choice in (CREATE_IT, SAVE_CHANGES):
            # The button creates whether or not a question is open at the card.
            yield from self._create()
        elif id == CARD and choice == "Change something":
            # A change is said in words, not picked from a list of settings.
            sketch.waiting = DESIGN
            sketch.turns.append({"role": "assistant", "content": "What should I change?"})
            yield Question(DESIGN, "What should I change?")
        elif id == CARD:
            yield from self._cancel()
        elif id == DUPLICATE:
            yield from self._same_answer(choice)
        else:
            # A click on a question's button sets that setting in code, and is said to the
            # model like anything typed.
            setting = self._choice_setting(id)
            if setting is not None and choice in setting.choices:
                sketch.slots[id] = choice
            elif setting is not None and choice in _choices(setting):
                sketch.slots[id] = ""  # the button that says none of them
            sketch.turns.append({"role": "user", "content": choice})
            yield from self._turn()

    # ------------------------------------------------------------ one turn

    def _turn(self) -> Iterator[Event]:
        """One turn of the conversation: the model fills its form, code checks each value
        and keeps the card, and what the model says is shown, with the try-out and the card
        once nothing needed is missing. A value code refuses goes back to the model once,
        with the reason and what would be right; refused twice, code says its own plain
        line and the value is not listened to again unless the user brings it up. Whatever
        the model says about where things stand, nothing is made here."""
        sketch = self.sketch
        model = sketch.model
        if not sketch.turns or sketch.turns[-1]["role"] != "user":
            # Nothing new was said (a click on a card that isn't up): the open question again.
            if sketch.waiting == DUPLICATE and sketch.same:
                yield self._same_question()
                return
            last = next((turn["content"] for turn in reversed(sketch.turns) if turn["role"] == "assistant"), "")
            yield Question(DESIGN, last or "What should it do?")
            return
        # The message that starts a new helper can't be "never mind" or "something else". Nor
        # can one code took for a change to a helper they have; but one only the router's
        # model took for a change can be either: "explain why I should update my drivers"
        # shares a word with a helper's rule, and was nothing to do with it.
        first = sum(turn["role"] == "user" for turn in sketch.turns) == 1 and not sketch.unsure
        schema = schema_for(first)
        computer = self._computer()
        before = dict(sketch.slots)
        wanted, asked_before = sketch.wants, sketch.asked  # put back if this message turns out to be about something else
        sketch.asked = ""
        stood = self._stands()  # the card and what it is tried on, as they were before this turn
        # The settings for which a folder of nearly the name they typed was asked about in
        # this turn, each with that folder's name.
        self._offered = {}
        self._put_right = set()  # the settings code told the model to put right in this turn
        self._unnamed = {}
        self._change_asked = False
        refused: list[Refused] = []
        nudges: list[str] = []
        lacking: list[parts.Setting] = []
        # Code refused something the user said in this turn, even if the model then put it right.
        stumbled = False
        missed: list[str] = []  # what code said it could not use in the turn's first form
        mended = False  # the rule was written again by the mender in this turn
        ended = ""  # the status that ends the conversation, when the model gave one
        try:
            for attempt in range(2):
                problems = [refusal.told for refusal in refused] + nudges
                note = self._note(computer, problems, first, waits=stumbled)
                filled = self._read(model.fill(note, sketch.turns, schema), schema)
                refused, nudges = [], []
                sketch.wants = filled.wants or sketch.wants
                # (What the status says of their message comes first. "hm its not worth it.
                # forget about it", said before a WHEN and a THEN were chosen, came back as
                # "cancel" with "None of these" for both; read as a helper that cannot be
                # made, it was answered "Nothing was created, and I've kept the idea in your
                # list", the opposite of what they had asked.)
                if filled.status in (CALLED_OFF, MOVED_ON):
                    ended = filled.status
                elif self._cannot(filled):
                    ended = CANT_BE_MADE
                if ended:
                    break
                refused = self._take_form(filled, last_try=attempt == 1, asked_before=asked_before, before=before)
                self._write_out()
                skipped = self._skips_its_own_sample()
                if skipped and attempt == 0:
                    # The setting was read as the language of the text the helper is given.
                    # Told once what it is; said the same again, it is taken off below.
                    self._put_right.add("skip_language")
                    nudges.append(f"`skip_language` is {skipped}, and the text you gave to try the helper on is already "
                                  f"in {skipped}: as you filled it in, the helper would pass over the very text it is "
                                  "for. `skip_language` is the language the RESULT comes out in, never the language "
                                  "of the text it is given. Put it right: the language the rule turns text into, when "
                                  f'that is one on its list, else "{parts.NONE}". (If the helper is right and the '
                                  "sample is not a text it is for, give another sample.)")
                    sketch.try_on = ""  # so the sample of the next form is the one that counts
                elif skipped:
                    # A helper that leaves nothing out works on every text; one that leaves
                    # out the text it is for does nothing at all.
                    sketch.slots["skip_language"] = ""
                stumbled = stumbled or any(refusal.waits for refusal in refused)
                if attempt == 0:
                    missed = [refusal.said for refusal in refused if refusal.waits and refusal.said]
                lacking = self._lacking()
                labels = ", ".join(setting.label for setting in lacking)
                # The rule is the one thing that is the model's to write: told only that it is
                # "not known", it would ask the user to say the rule for it.
                yours = (" The rule is yours to write from what they have told you: fill it in if you know enough."
                         if any(setting.type == "rule" for setting in lacking) else "")
                if lacking and filled.status == NOTHING_MISSING:
                    nudges.append(f"Still not known: {labels}. Don't say it is ready.{yours} Ask for the first thing "
                                  "you cannot work out yourself.")
                elif lacking and "?" not in tidy_say(filled.say, asking=True):
                    nudges.append(f"You asked nothing, and this is still not known: {labels}.{yours} Say what you "
                                  "said, then ask for the first thing you cannot work out yourself.")
                elif (filled.status == STILL_ASKING and filled.asks == THEN.key and filled.when in parts.WHENS
                      and not sketch.told_thens and sketch.shown is None and "?" in filled.say):
                    # It asks them what the helper should do with its result, and may offer
                    # what cannot be made: of someone who wanted rough notes written out
                    # properly it asked "Would you like it to just reply with the tidy
                    # version, or should it also save that entry into a specific notes file
                    # for you?", three plays out of three, and a sentence in its note that
                    # a helper for a piece of text keeps nothing in a file changed nothing.
                    # Told once, from the catalog, which results go with the WHEN it chose.
                    sketch.told_thens = True
                    # Only the results that follow a rule are offered side by side. Told that
                    # with the chat the result could be an answer there or answers from the
                    # documents in a folder, the model asked someone who wanted rough notes
                    # tidied whether it should "also look for information in a specific
                    # folder of documents", in two plays of three (22 Nov 2026): a helper
                    # nobody had asked for, offered as an extra it can never be. A result
                    # that follows no rule is named on its own, as the helper of another
                    # kind it is. (Not yet played with a real model: the lines for a WHEN
                    # whose every result follows a rule are as they were measured.)
                    fits = parts.FITS.get(filled.when, ())
                    ruled = [then for then in fits if parts.RULE in parts.settings_for(filled.when, then)] or list(fits)
                    apart = [then for then in fits if then not in ruled]
                    goes = " or ".join(f'"{then}"' for then in ruled)
                    that = "a helper that follows a rule" if apart else "that"
                    others = "".join(f' ("{then}" is a helper of another kind. {parts.THENS[then].about} Offer it only '
                                     "when that is all they want, never beside another result.)" for then in apart)
                    nudges.append(f'Your question asks them what the helper should do THEN. With "{filled.when}" {that} '
                                  f"can only be {goes}: nothing else can be made, and a question that offers anything "
                                  f"else offers what cannot be done.{others} If one of those is plainly what they "
                                  "described, take it and say how the helper would work; ask only when more than one "
                                  "of those would do, and offer nothing but those.")
                elif filled.status == STILL_ASKING and filled.asks == parts.RULE.key and lacking == [parts.RULE]:
                    # Only the rule is missing and its question asks them for the rule. With
                    # the folders named and what to leave alone said, a model asked whether
                    # the helper should go by "the content of the document ... or should it
                    # look for specific keywords?": the designing, handed to them.
                    nudges.append("Everything but the rule is known, and your question asks them how the helper "
                                  "should decide. That is yours to work out: write the rule now, from what they "
                                  "have told you. Ask only if they have not said what should happen to some kind "
                                  "of thing, and then ask about that thing, in their words. (If your words said "
                                  "that something they want cannot be done, keep saying that.)")
                elif self._asks_them_for_folders(filled, lacking):
                    # Told what was in the folder ("stuff from my clients and bills and random
                    # things"), a model answered "What specific folder names would you like it
                    # to use for these categories?", and in another language the same: the
                    # designing handed to someone who came because they did not know. Told once.
                    sketch.told_folders = True
                    nudges.append("Your question asks them which folders they want. That is yours to propose: name "
                                  "the folders yourself, after the kinds of things they told you about and in their "
                                  "words, write the rule, say what would go where and what would be left alone, and "
                                  "ask whether that suits them. Ask them about their things only if they have told "
                                  "you too little to propose anything.")
                elif lacking and sketch.shown is None and getattr(self._asks_for_usual(filled), "type", "choice") != "choice":
                    # Something needed is still not known, and the question is about a
                    # setting that has a usual value. With the rule not written yet, a model
                    # asked "Would you like that notes file to be named something specific,
                    # or should I just name it after the helper?", and asked it again when
                    # the answer was about something else. Told once. (Not for a choice
                    # among a few: that goes out with its buttons, and costs them a click.)
                    usual = self._asks_for_usual(filled)
                    nudges.append(f"Your question asks for `{usual.key}` ({usual.label}), which has a usual value, so "
                                  f"it is not worth a question: leave it empty. What is still not known is: {labels}."
                                  f"{yours} Say how the helper would work and ask whether that is right, or ask for "
                                  "the first thing you cannot work out yourself.")
                elif not lacking and self._leaves_out_how_to_ask(filled):
                    # A helper asked in the chat, proposed without a word on how it is asked.
                    # "How do I give it my notes?" was answered "whenever you paste your messy
                    # notes into the chat, it will automatically rewrite them", with the facts
                    # about it in the note: a message without its name is not for it. Told once.
                    sketch.told_how = True
                    nudges.append("Your words do not tell them how they will ask this helper. It is asked in the "
                                  f'chat by writing its name, a colon and then the text ("{sketch.slots.get("name")}: '
                                  '..."); a message that does not begin with its name is not for it. Say what you '
                                  "said, with that in it, in your own words.")
                elif not lacking and sketch.shown is None and self._asks_for_usual(filled):
                    # Everything needed is known and it asks about a setting that has a usual
                    # value ("should the bubble stay up or go away by itself?"): told once.
                    usual = self._asks_for_usual(filled)
                    nudges.append(f"Your question asks for `{usual.key}` ({usual.label}), which has a usual value, so "
                                  "it is not worth a question: leave it as it is. If they have agreed to what you "
                                  f'described, or said all of it themselves, the status is "{NOTHING_MISSING}". If '
                                  "you have not yet described how the helper would work, do that and ask whether "
                                  "it is right.")
                elif not refused and self._changed_nothing(filled, stood):
                    # Their message speaks of files of the try-out, and the form leaves the
                    # rule as it was: the mender writes it again. (Shown the same try-out
                    # in a line of its own and told that the same rule changes nothing, a
                    # model that read its rule as saying the right thing already wrote it
                    # out unchanged a second time.)
                    if self._on_files() and self._spoken_of() and self._mend(self._spoken_of()):
                        mended = True
                        break
                    # (Not when what it wrote is a change that was made a turn or two ago:
                    # asked at the card "will it touch what is already in there?", a model
                    # wrote the last two corrections down again as what was asked for now,
                    # and answered the question well in its words.)
                    if not self._echoes(filled.changes):
                        nudges.append(f'You wrote that their message asks for this change: "{filled.changes}". But '
                                      "the settings and the rule in your form are the same as on the card, so "
                                      "nothing would change. Make the change now: write the rule again so that it "
                                      "says it, or change the setting. If the card already does what they ask, "
                                      "leave `changes` empty and tell them so.")
                if not refused and not nudges:
                    break
        except DesignerError as exc:
            # A model that can't take its turn ends the conversation; nothing is half made.
            model.done()
            self.sketch = None
            yield Thinking(f"{model.name} couldn't carry on ({exc}).")
            kept = f"{sketch.replaces} is as it was." if sketch.editing else "Nothing was created."
            yield from say(f"I couldn't carry on working this helper out just now. {kept} Please try again in a "
                           "little while.")
            return
        if ended == CANT_BE_MADE:
            yield from self._cant_be_made(tidy_say(filled.say))
            return
        if ended == CALLED_OFF:
            model.done()
            self.sketch = None
            yield from say(tidy_say(filled.say) or _left_alone(sketch))
            return
        if ended == MOVED_ON:
            # Their message was about something else, by the whole form's word (a plan's
            # model is not asked on its own first: _is_aside). The helper is set aside as
            # it stood before that message, which is taken out of its conversation again.
            sketch.wants, sketch.asked = wanted, asked_before  # what that message was about is not what the helper is for
            text = sketch.turns.pop()["content"]
            if not any(turn["role"] == "user" for turn in sketch.turns):
                # The very message that opened a change was about something else: nothing
                # was worked out, so nothing is kept to carry on with, and it is answered as
                # any message is.
                model.done()
                self.sketch = None
                self.handoff = text
                yield Thinking(f"That isn't about changing {sketch.replaces}, so I'll answer it as usual. "
                               f"{sketch.replaces} is as it was.")
                return
            yield from self._answer_it_first(text)
            return
        # Refused twice: said once, below, and after that the same value is passed over, or
        # every later answer would be "I can't find a folder called ..." again.
        sketch.ignored |= {(refusal.key, refusal.value) for refusal in refused}
        self._change_asked = bool(filled.changes)
        if (sketch.shown is not None and not filled.changes and not mended and sketch.try_theirs
                and sketch.try_on != stood[1] and sketch.slots != stood[0]):
            # They gave a text of their own to try the helper on, and by the model's own
            # word their message asks for no change: the card stays as it was. Asked "what
            # would it say for ...?", a model wrote that very word into the rule, with what
            # the answer for it should be, and described the answer itself instead of
            # letting the try-out show it.
            sketch.slots.clear()
            sketch.slots.update(stood[0])
        if (sketch.shown is not None and not mended and not refused and sketch.slots != stood[0]
                and self._last_said().rstrip().endswith(("?", "？")) and self._echoes(filled.changes)
                and not (_telling_words(filled.changes) & _telling_words(self._last_said()))):
            # They asked a question at the card, and what the model wrote down as the change
            # asked for is one that was made a turn or two ago, with not a word of their
            # question in it: the card stays as it was. Asked "will it touch the stuff thats
            # already in there?", a model answered that well and, in the same form, wrote
            # the rule out in other words than the ones the try-out had been run with: the
            # helper was tried again under its answer, and three files came out otherwise
            # on a card nobody had asked to change.
            sketch.slots.clear()
            sketch.slots.update(stood[0])
        learned = self._learned(before)
        if learned:
            yield Thinking("Understood so far: " + "; ".join(line.rstrip(".") for line in learned) + ".")
        if not refused and not sketch.editing and not sketch.same_asked:
            # As soon as it is clear this would repeat a helper they have, that is asked
            # about first, in code and once, before anything more is worked out. The model
            # reads which helpers they have but has no way to hand over to one: without this
            # a second helper was made beside the first, without a word.
            same = self._same_helper()
            if same:
                yield from self._ask_same(*same)
                return
        # Before there is a card, a model that says it is still asking is taken at its word:
        # its question stays on the end of what it says, and the card waits for the answer.
        # (Not when what it asks for has a usual value: that was told above, and holds
        # nothing back.) Shown as soon as nothing needed was missing, a card came under
        # "Which folder should it watch for new files?", for a folder the model had guessed.
        # Once: when they have answered what was proposed and nothing needed is missing, the
        # try-out and the card are the next thing they see, whatever the model asks. They
        # said "yes, but ... too", and it described the whole of it again and asked "Is
        # this correct?"; a "Does that sound right?" that only asks the same again comes
        # off, so a yes typed under the card is a yes to the card.
        open_question = (sketch.shown is None and filled.status == STILL_ASKING and not sketch.proposed
                         and not self._asks_for_usual(filled))
        words, asks = tidy_say(filled.say, asking=bool(lacking) or open_question), filled.asks
        if (open_question and not lacking and (self._said_it_all() or self._just_agreed() or sketch.editing)
                and _without_confirming(words) != words):
            # Their first message said all of it, and all that is asked is whether what was
            # said back to them is right: the try-out and the card answer that better. The
            # same when they have just said a plain yes: asked "Should I set it up so you
            # type its name and then your notes?", they said "ok sure", and were asked "Is
            # that how you would like to use it?", the third such question in a row. And
            # the same for a change to a helper they have: they said what to change, and
            # the card with the changes on it is where they say yes.
            open_question = False
        waits = open_question and "?" in words
        if not lacking and not waits and sketch.shown is None and filled.status == STILL_ASKING:
            words = _without_confirming(words)
        if not lacking and sketch.shown is None and self._asks_for_usual(filled):
            # Told that its question asks for something that has a usual value, it asked
            # all the same: the question comes off, and the card is what they answer. Left
            # on, "Is it okay if I call this helper ...?" stood over a card that had another
            # name, and a yes to it created nothing.
            words = _without_question(words)
        if lacking and nudges:
            words = _without_card(words)  # no card comes: what it says of one comes off
        if (not refused and missed and self._offered
                and not any(name.casefold() in words.casefold() for name in self._offered.values())):
            # They typed a folder's name a letter off, and the model, told to ask whether
            # they mean the one that is there, said nothing of it: "theyre in my applience
            # manuals folder" was answered "I will call this helper House Manuals. Is that
            # a good name for it?". Code asks, by the folder's real name.
            words = next((line for line in missed if line.rstrip().endswith("?")), words)
            asks = ""
        if refused or (lacking and "?" not in words):
            # Refused twice, or still no question: code's own plain words, so nothing wrong is
            # said. One question at most: a refusal that asks ("Which one do you mean?") is it.
            # (A question of the model's own stays, also when it was told to do otherwise
            # and did not: put in its place, code's question for the rule asked someone
            # who had just said what should go where "What should it do, and what should it
            # leave alone?".)
            lines = [refusal.said for refusal in refused if refusal.said]
            if not lines and stumbled:
                # What code asked in the turn's first form, when the second neither put it
                # right nor asked: "Did you mean ...?" says more than the setting's own question.
                lines = [line for line in missed if line.rstrip().endswith("?")][:1]
            if lacking and not any(line.rstrip().endswith("?") for line in lines):
                lines.append(lacking[0].ask.strip())
            words = " ".join(lines)
            asks = lacking[0].key if lacking else asks
        elif stumbled and sketch.shown is None:
            # No card follows a turn in which something was refused, so words that point at
            # one come off, whatever the model was told. If nothing else was said, code says
            # what it could not use.
            words = _without_card(words) or " ".join(missed) or words
        elif (not lacking and self._changed_nothing(filled, stood)
              and (not self._echoes(filled.changes) or CLAIMS_CHANGE.search(words))):
            # Told once that its form changed nothing, and it still changes nothing: code
            # says so, in place of words that say a change was made. (Words that only
            # answer a question stand: put in their place, "Nothing changed on the card"
            # was all someone heard who had asked whether their old files would be touched.)
            words = ALREADY_SO if filled.status == NOTHING_MISSING else NOT_CHANGED
        if not lacking and not stumbled and not refused and not waits:
            # Nothing needed is missing and nothing is being asked, so the card comes. A
            # question about a setting that has a usual value does not hold it back: let do
            # so, a model asked one more of those each turn. Such a question still shows,
            # above the card, to answer or not. A turn in which code refused something
            # waits too: asked for a folder that isn't there, a model said it couldn't find
            # one, asked which folder to use, and showed a card under that for a folder it
            # had only guessed.
            sketch.slots.update(parts.defaults(sketch.slots))
            if not sketch.slots.get("name"):
                sketch.slots["name"] = self._unique(self._usual_name())
            button = "Save the changes" if sketch.editing else "Create it"
            # Tried once, and again only when what it would do has changed: a new name alone
            # is the same helper, and a try-out asks the built-in model about every file. (A
            # text of their own to try it on is tried, on the card as it is.)
            retry = self._runs_with() != sketch.tried_with
            results: list[Event] = []
            if retry and sketch.tried and self._on_files() and sketch.slots.get("instruction") != before.get("instruction"):
                # A change to the rule of a helper that was tried on their files before: it is
                # tried again before anything is said, and when files they spoke of still come
                # out as they did, the model is shown that and has one more go at the rule.
                words, results = yield from self._tried_again(words, mended, asked=bool(filled.changes))
                retry = False
            if sketch.shown is not None:
                words = _without_confirming(words)  # "Is that right?" under a card: the card is where they say so
            if sketch.shown == sketch.slots and sketch.try_theirs and sketch.try_on != stood[1]:
                # They gave a text of their own to try it on, and nothing else changed: said
                # by code. Asked only to "try it on this", a model answered "I have updated
                # the rule to ensure ...", naming a change it had made a turn ago.
                words = "Here is what it gives on your own text."
            words = words or f"Here is {sketch.slots['name']}. {button} if it looks right."
            if sketch.editing and sketch.shown is None and not POINTS_AT_CARD.search(words):
                # Said by code, once, under the first card of a change: told not to, a model
                # still wrote "I have updated the helper to include ..." over a card whose
                # button nobody had pressed.
                words = f"{words} {sketch.replaces} stays as it is until you press Save changes on the card."
            if sketch.rename == "tell":
                sketch.rename = "told"
                words = f'{words} To give it another name, say "call it ...".'
            if filled.changes and self._stands() != stood:
                sketch.changes_made.append(filled.changes)
            if (sketch.shown == sketch.slots and self._stands() == stood and self._just_agreed()
                    and "?" not in words and not POINTS_AT_CARD.search(words)):
                # A plain yes to something Noir had asked at the card, and nothing changed:
                # said "ok make it", someone heard "I have everything I need to set this up
                # for you" and nothing more. Only the card makes anything, so code says so.
                words = f"{words} The button on the card {'saves the changes' if sketch.editing else 'creates it'}."
            sketch.turns.append({"role": "assistant", "content": self._for_turns(words)})
            yield from say(words)
            if retry:
                yield from self._try_out()
            yield from results
            if sketch.shown != sketch.slots:
                sketch.shown = dict(sketch.slots)
                yield self._card()
            # A plain yes typed now is a yes to the card on screen, unless Noir has just asked
            # something: then the yes answers that, and the button is what creates.
            sketch.waiting = DESIGN if "?" in words else CARD
            return
        words = words or "Could you say that another way?"
        sketch.turns.append({"role": "assistant", "content": self._for_turns(words)})
        sketch.waiting = DESIGN
        sketch.proposed = sketch.proposed or (waits and not lacking and not stumbled and not refused)
        if "?" not in words:
            yield from say(words)  # an answer to their question, with nothing asked back
            return
        setting = self._asked_about(asks, words)
        sketch.asked = setting.key if setting else ""
        yield Question(setting.key if setting else DESIGN, words, _choices(setting) if setting else None)

    def _asked_about(self, asks: str, words: str) -> parts.Setting | None:
        """The choice among a few that a question's buttons are for: the one the form said
        its question asks for, unless the words of the question are plainly about another
        choice of this card: they have more of the words of that one's choices in them.

        "Should the explanation stay on the screen until you unhighlight the word, or
        should it disappear after a few seconds?" went out with the buttons for where the
        result is shown, a bubble, the clipboard or both: the form had named the wrong
        setting, and a click on any of them answered a question nobody had asked. (And
        again as "Would you like that bubble to stay there until ...?", with one word of
        the setting it had named.) Words in another language share none with any choice,
        and keep the buttons the form named."""
        named = self._choice_setting(asks)
        if named is None:
            return None
        said = _telling_words(words)

        def shared(setting: parts.Setting) -> int:
            return len(said & set().union(*(_telling_words(choice) for choice in setting.choices)))

        slots = self.sketch.slots
        others = [setting for setting in parts.settings_for(slots.get("when", ""), slots.get("then", ""))
                  if setting.type == "choice" and setting.choices and setting.key != named.key]
        best = max(others, key=shared, default=None)
        if best is None or shared(best) <= shared(named):
            return named
        return best if sum(shared(setting) == shared(best) for setting in others) == 1 else named

    def _read(self, raw: dict, schema: dict) -> _Filled:
        """A filled form as code takes it. A plan model's form is only text read back, so
        nothing in it is known to be on the form's lists: a status that isn't becomes "still
        asking", and a question about no setting there is, a question about none."""
        fields = schema["properties"]
        status, asks, said = raw.get("status"), raw.get("asks"), raw.get("say")
        text = lambda key: raw.get(key) if isinstance(raw.get(key), str) else ""  # noqa: E731
        changes = _one_line(raw.get("changes"), MAX_WANTS)
        return _Filled(values=raw, wants=_one_line(raw.get("wants"), MAX_WANTS),
                       changes="" if NO_CHANGE.match(changes) else changes, when=text("when"), then=text("then"),
                       try_on=_one_line(raw.get("try_on"), MAX_SAMPLE),
                       status=status if status in fields["status"]["enum"] else STILL_ASKING,
                       asks=asks if isinstance(asks, str) and asks in fields["asks"]["enum"] else "",
                       say=said if isinstance(said, str) else "")

    def _cannot(self, filled: _Filled) -> bool:
        """Whether the model says this helper can't be made from the parts there are. With a
        WHEN and a THEN already chosen, "none of these" on the form alone is taken like any
        empty value, which never erases a known one: only the status ends a card that was
        being worked out."""
        if filled.status == CANT_BE_MADE:
            return True
        slots = self.sketch.slots
        chosen = parts.fits(slots.get("when", ""), slots.get("then", ""))
        return NONE_FIT in (filled.when, filled.then) and not chosen

    def _skips_its_own_sample(self) -> str:
        """The language a helper for text leaves out, when the text the model itself made
        up to try it on is already in that language: as filled in, the helper would do
        nothing with what it is for. "" otherwise, and for a text of the user's own, which
        may well be one the helper passes over (and the try-out then says so).

        A helper that was to show what Japanese sentences mean in English came with
        Japanese as the language it leaves out. Its try-out said "it does nothing: the
        text is already in Japanese", its card said the same, and once it was made an
        English sentence was turned into Japanese."""
        sketch = self.sketch
        if not self._on_text() or not sketch.try_on or sketch.try_theirs:
            return ""
        return parts.leaves_out(sketch.slots, sketch.try_on)

    def _asks_for_usual(self, filled: _Filled) -> parts.Setting | None:
        """The setting the model's question asks for, when it is one of this card's that has
        a usual value (or is given one, like the name): such a question is never needed."""
        if filled.status != STILL_ASKING or not filled.asks or "?" not in filled.say:
            return None
        slots = self.sketch.slots
        return next((setting for setting in parts.settings_for(slots.get("when", ""), slots.get("then", ""))
                     if setting.key == filled.asks and not parts.needed(setting)), None)

    def _asks_them_for_folders(self, filled: _Filled, lacking: list[parts.Setting]) -> bool:
        """Whether the model's question asks the person to name the folders things go into,
        when none are known yet and it has not been told before that they are its to propose."""
        sketch = self.sketch
        if sketch.told_folders or sketch.shown is not None or sketch.editing:
            return False
        asked = next((setting for setting in lacking if setting.key == filled.asks), None)
        return filled.status == STILL_ASKING and asked is not None and asked.type == "list" and "?" in filled.say

    def _just_agreed(self) -> bool:
        """Whether their last message is a plain yes and nothing more."""
        whole = self._last_said().strip().strip("!. ")
        return whole in CARD_YES or bool(AGREES.match(whole))

    def _speaks_of(self, setting: parts.Setting, value: str, filled: _Filled) -> bool:
        """Whether this turn speaks of a choice setting being made `value`: a word of its
        label or of that choice is in their last message, in the change the form says they
        asked for, or in the words the model is about to say to them. (Their message alone
        would not do: a change asked for in another language shares no word with a label,
        and the form's change and words are where the model says what it changed. And not
        a word of the other choices: "make the bubble go away by itself" is no word about
        how the result is shown.)"""
        said = _setting_words(" ".join((self._last_said(), filled.changes, filled.say)))
        return bool(said & _setting_words(f"{setting.label} {value or parts.NONE}"))

    def _leaves_out_how_to_ask(self, filled: _Filled) -> bool:
        """Whether this form proposes a helper that is asked in the chat, to someone who has
        not seen its card yet and has not been told how it is asked, in words that do not
        have its name in them."""
        sketch = self.sketch
        slots = sketch.slots
        name = str(slots.get("name") or "")
        if sketch.told_how or sketch.shown is not None or not name:
            return False
        if (slots.get("when"), slots.get("then")) != (parts.IN_CHAT, parts.ANSWER):
            return False
        return name.casefold() not in filled.say.casefold()

    def _said_it_all(self) -> bool:
        """Whether the card as it stands came from their first message alone, with the
        folder it works in and the folders it moves things into (if it has any) named in
        that message. Such a message was said back to them with "Is that how you want it to
        work?", four times out of four; so a question that only asks that does not hold the
        card back then. A folder they did not name is a guess, and a guess is asked about.

        Only a helper that works in a folder. Of one that works on a piece of text, nothing
        in a message lets code see that it said how they want to use it: asked for
        something that turns rough notes into a letter, a model chose for them that it
        would be asked in the chat, and with nothing to check the card came at once."""
        sketch = self.sketch
        told = [turn["content"] for turn in sketch.turns if turn["role"] == "user"]
        if len(told) != 1 or not sketch.slots.get("folder"):
            return False
        said = told[0].casefold()
        folder = sketch.slots.get("folder")
        if folder:
            path = Path(folder)
            names = {path.name.casefold(), *(place.casefold() for place in PLACE_NAMES if known_folder(place) == path)}
            if not any(name and name in said for name in names):
                return False
        return all(name.casefold() in said for name in parts.choices_of(sketch.slots))

    def _stands(self) -> tuple[dict, str]:
        """The card as it stands and the text it is tried on: what a change would change."""
        return dict(self.sketch.slots), self.sketch.try_on

    def _changed_nothing(self, filled: _Filled, stood: tuple[dict, str]) -> bool:
        """Whether the model wrote that the user's message asks for a change to the card on
        their screen, and its form then left the card exactly as it was."""
        return self.sketch.shown is not None and bool(filled.changes) and self._stands() == stood

    def _echoes(self, changes: str) -> bool:
        """Whether what the model wrote as the change asked for now says again a change
        that was made in an earlier turn: most of its telling words are words of those.

        Fewer will do when not one of its words is a word of the message it is supposed to
        be about. Asked at the card "will it touch the stuff thats already in there?", a
        model wrote the correction of the turn before down as "The rule was updated to
        ensure electricity bills are specifically included in the Shop Bills folder":
        three of its seven telling words were the earlier change's, the rest were its own
        padding, and none was the person's. That counted as a change asked for and not
        made, and code's "Nothing changed on the card" stood where the answer was."""
        made = self.sketch.changes_made
        words = _telling_words(changes)
        before = set().union(*(_telling_words(text) for text in made)) if made else set()
        shared = len(words & before)
        if not words or not shared:
            return False
        if shared >= ECHOED * len(words):
            return True
        return shared >= ECHOED_LOOSELY * len(words) and not (words & _telling_words(self._last_said()))

    def _note(self, computer: list[str], problems: list[str], first: bool, waits: bool = False) -> str:
        sketch = self.sketch
        return note_for(self._known(), computer, self._tried_lines(), problems, first=first,
                        card_up=sketch.shown is not None, editing=sketch.editing, waits=waits)

    def _lacking(self) -> list[parts.Setting]:
        """What the card can't be made without and isn't known yet: a WHEN, a THEN that goes
        with it, and each setting of theirs that has to be asked."""
        slots = self.sketch.slots
        when, then = slots.get("when", ""), slots.get("then", "")
        lacking = [] if when in parts.WHENS else [WHEN]
        if when in parts.WHENS and not parts.fits(when, then):
            lacking.append(THEN)
        return [*lacking, *parts.missing(slots)]

    def _choice_setting(self, key: str) -> parts.Setting | None:
        """The setting of this card that is a choice among a few, by its key."""
        slots = self.sketch.slots
        return next((setting for setting in parts.settings_for(slots.get("when", ""), slots.get("then", ""))
                     if setting.key == key and setting.type == "choice" and setting.choices), None)

    def _card_is_current(self) -> bool:
        """Whether the card on the user's screen is the card as it now stands."""
        sketch = self.sketch
        return sketch.shown is not None and sketch.shown == sketch.slots

    def _last_said(self) -> str:
        return next((turn["content"] for turn in reversed(self.sketch.turns) if turn["role"] == "user"), "").lower()

    # ------------------------------------------------------------ one they already have

    def _same_helper(self) -> tuple[store.Agent, str] | None:
        """A helper they already have that this one would repeat, and what the two share, in
        plain words: one that answers from the same folder's documents, one that works on
        the new files of the same folder with the same THEN, or one that works on text by
        the same rule, word for word. None while the card doesn't say enough to tell."""
        slots = self.sketch.slots
        when, then = slots.get("when", ""), slots.get("then", "")
        if not parts.fits(when, then):
            return None
        folder = slots.get("folder") or ""
        shown = parts.shown_place(Path(folder)) if folder else ""
        rule = _rule_key(slots.get("instruction"))
        for agent in store.list_agents():
            theirs = agent.slots
            there = _same_path(theirs.get("folder"), folder)
            if parts.mode(slots) == parts.SEARCH:
                if agent.blueprint == parts.DOCUMENTS_QA and there:
                    return agent, f"which answers from the documents in {shown}"
            elif agent.blueprint != parts.CUSTOM:
                continue
            elif when == parts.NEW_FILE:
                if theirs.get("when") == when and parts.then_of(theirs) == then and there:
                    return agent, f"which works on the new files in {shown} in the same way"
            elif rule and theirs.get("when") != parts.NEW_FILE and _rule_key(theirs.get("instruction")) == rule:
                return agent, "which does the same"
        return None

    def _ask_same(self, agent: store.Agent, shares: str) -> Iterator[Event]:
        """Ask, once, what to do about a helper they have that this one would repeat."""
        sketch = self.sketch
        sketch.same, sketch.same_asked, sketch.waiting = agent.name, True, DUPLICATE
        sketch.turns.append({"role": "assistant",
                             "content": f"You already have {agent.name}, {shares}. What would you like to do?"})
        yield self._same_question()

    def _same_question(self) -> Question:
        """The question about the helper they have, as it was asked. Only a card can be
        changed by talking, so only a card is offered to be changed."""
        sketch = self.sketch
        name = sketch.same
        words = next((turn["content"] for turn in reversed(sketch.turns) if turn["role"] == "assistant"), "")
        existing = store.find_agent(name)
        change = [f"Change {name}"] if existing is not None and existing.blueprint == parts.CUSTOM else []
        return Question(DUPLICATE, words, [f"Use {name}", *change, MAKE_ANOTHER])

    def _same_choice(self, whole: str) -> str | None:
        """The answer to that question when it was typed word for word instead of clicked."""
        sketch = self.sketch
        if sketch.waiting != DUPLICATE or not sketch.same:
            return None
        return next((choice for choice in self._same_question().choices if choice.lower() == whole), None)

    def _same_answer(self, choice: str) -> Iterator[Event]:
        """What they chose: keep to the helper they have, change that one instead (the
        conversation carries on about it, from what they first asked for), or make this one
        as well, which is said to the model like anything typed."""
        sketch = self.sketch
        name = sketch.same
        if sketch.waiting != DUPLICATE or not name:
            yield from say("That question has already been answered.")
            return
        existing = store.find_agent(name)
        sketch.same = None
        if existing is not None and choice == f"Use {name}":
            sketch.model.done()
            self.sketch = None
            yield from say(f"Okay, keep using {name}. {_how_to_use(existing)}")
        elif existing is not None and existing.blueprint == parts.CUSTOM and choice == f"Change {name}":
            self.sketch = None
            yield from self.edit(existing, sketch.request)
            if self.sketch is None:
                sketch.model.done()  # nobody carried on: its model leaves memory
        else:
            sketch.waiting = DESIGN
            sketch.turns.append({"role": "user", "content": choice})
            yield from self._turn()

    # ------------------------------------------------------------ the form, checked

    def _take_form(self, filled: _Filled, last_try: bool = False, asked_before: str = "",
                   before: dict | None = None) -> list[Refused]:
        """What the model's form says, checked and put into the card. Returns what code
        refused, each with a line for the model and a line for the user. Only the settings
        of the WHEN and THEN that are chosen are read; an empty value never erases one that
        is known; and a value refused in an earlier turn is passed over unless the user's
        last message names it again. `asked_before`: the setting the question they are
        answering asked for with buttons, if it did. `before`: the card as it stood when
        this turn began."""
        sketch = self.sketch
        slots = sketch.slots
        refused: list[Refused] = []
        last = self._last_said()
        # What the model's question asks them for is not known yet, by its own word, so a
        # value for it in the same form is a guess and is not taken: a model asked "Which
        # folder should it watch?" with a folder of its own choosing filled in, and with
        # nothing left missing the card came for that folder. (A value that is known
        # already stays; the question may be about changing it.)
        asked = filled.asks if filled.status == STILL_ASKING else ""
        chosen = parts.fits(slots.get("when", ""), slots.get("then", ""))
        pair = None if asked in (WHEN.key, THEN.key) and not chosen else self._take_pair(filled.when, filled.then)
        if pair:
            refused.append(pair)
        self._take_sample(filled.try_on, last)
        for setting in parts.settings_for(slots.get("when", ""), slots.get("then", "")):
            if (setting.key == asked and (parts.needed(setting) or setting.type in ("folder", "place"))
                    and setting.type != "rule" and not str(slots.get(setting.key) or "").strip()):
                # (Not the rule: that is the model's own to write, and to ask about once
                # written. A place is the person's to name whether or not it has a usual
                # value: "Would you like that notes file to be named something specific?"
                # came with the Documents folder filled in for it, which nobody had named,
                # and the notes file was taken out of the folder it belongs in.)
                continue
            if last_try and setting.key in self._offered:
                # They typed a folder's name one letter off, and the model was told a moment
                # ago, in this turn, to ask whether they mean the one that is there. Whether
                # they do is theirs to say: the folder is not taken from the form that asks,
                # whatever that form says its question is about. (One marked its question as
                # being about the helper's name; the folder was taken unasked, and the
                # question, about a setting with a usual value, was cut off its words.)
                continue
            raw = filled.values.get(setting.key)
            given = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
            if (setting.key, given) in sketch.ignored and not any(word in last for word in _words_in(raw)):
                continue
            if setting.type == "folder":
                if sketch.took.get(setting.key) == given and slots.get(setting.key):
                    continue  # the same folder as it gave before, found then: not looked for again each turn
                problem = self._form_folder(setting, raw)
            elif setting.type == "place":
                if sketch.shown is None and not parts.needed(setting) and not self._place_was_said(raw, filled.say):
                    # Before there is a card: a place with a usual value, filled in though
                    # nobody had said it, in words or in the form's own. A notes file was
                    # given the Documents folder, with nothing asked and nothing said of
                    # it, and the first card came with the notes outside the folder they
                    # are about. Once it has been said, by them or to them, it is taken
                    # like any other; and once a card is up every place is on it to see,
                    # and a change to one is a change like any other.
                    continue
                problem = self._form_place(setting, raw)
            elif setting.type == "choice":
                if ((before or {}).get(setting.key) and setting.key not in (asked_before, *self._put_right)
                        and self._just_agreed()):
                    # A plain yes agrees to what was said and asks for nothing to be
                    # different. Asked "Is it okay if I create these two folders inside
                    # your Downloads folder?", they said yes, and the form that followed
                    # let the helper make new folders of its own, which nobody had spoken
                    # of: the try-out came out differently under a card they had only
                    # agreed to. A choice that was known when they said yes stays through
                    # that turn, unless it is the one the question with its buttons asked
                    # them for, or one code has just told the model to put right (held to
                    # its old value then, the language a helper leaves out could not be
                    # corrected in the turn that found it wrong, and was taken off instead).
                    continue
                if isinstance(raw, str) and raw in setting.choices:
                    value = raw
                elif isinstance(raw, str) and raw in _choices(setting) and slots.get(setting.key):
                    # "None", for a setting that may be none of its choices: a known one is
                    # taken off. Only a known one: on a card that had none, nothing changes,
                    # or the word filled in every turn would make each turn look like a change.
                    value = ""
                else:
                    continue
                known = slots.get(setting.key, setting.default)
                if ((sketch.shown is not None or sketch.editing) and known is not None and value != known
                        and setting.key not in (asked_before, *self._put_right)
                        and not self._speaks_of(setting, value, filled)):
                    # Once there is a card (or a helper they have is being changed), a choice
                    # that has a value changes only when this turn speaks of it: their message,
                    # the change the form says they asked for, or the words they are about to
                    # read. The model fills every setting in again each turn. Told "also leave
                    # the pictures alone", one let the helper make new folders as well, said
                    # only that pictures would stay, and the helper was made that way; and a
                    # helper asked to explain more shortly could as well have had its result
                    # copied to the clipboard instead of shown, without a word of it.
                    continue
                slots[setting.key] = value
                continue
            elif setting.type == "list":
                problem = self._form_list(setting, raw)
            elif setting.type == "rule":
                problem = self._form_rule(setting, raw, last_try)
            elif setting.key == parts.NAME.key:
                problem = self._form_name(raw, filled.values)
            else:
                problem = self._form_text(setting, raw)
            if problem:
                refused.append(Refused(setting.key, given, *problem))
            elif setting.type == "folder" and slots.get(setting.key):
                sketch.took[setting.key] = given
        unreadable = self._must_have_documents(filled)
        if unreadable:
            refused.append(unreadable)
        return refused

    def _take_pair(self, when: str, then: str) -> Refused | None:
        """The WHEN and the THEN from the form: taken when they go together. One given
        alone joins the other that is known; a THEN alone, with no WHEN known, brings the
        one WHEN it goes with. When the pair changes, what belonged to the old one is dropped."""
        sketch = self.sketch
        slots = sketch.slots
        offered = [part.key for part in parts.whens()]
        given = json.dumps([when, then], ensure_ascii=False)
        when = when if when in offered else ""
        then = then if then in parts.THENS else ""
        if not (when or then) or ("pair", given) in sketch.ignored:
            return None
        known_when, known_then = slots.get("when", ""), slots.get("then", "")
        if when and not then:
            then = known_then if parts.fits(when, known_then) else ""  # a new WHEN: the old THEN may not go with it
        elif then and not when:
            fitting = [key for key in offered if parts.fits(key, then)]
            when = known_when or (fitting[0] if len(fitting) == 1 else "")
            if not when:
                return None
        if then and not parts.fits(when, then):
            # The card waits for this turn, and the model is told not to choose again for
            # them: told only to choose two that go together, it guessed another result, and
            # a card came for something they had not asked for.
            goes = ", ".join(f'"{key}"' for key in parts.FITS.get(when, ()))
            return Refused("pair", given,
                           f'That way of working and that result don\'t go together: with "{when}", THEN can only '
                           f"be {goes}. Don't pick another pair for them: say what can't be done that way and ask "
                           f'which of the ways that can be made they would like, or choose "{NONE_FIT}" when none '
                           "of them would do.", "")
        if (when, then) == (known_when, known_then):
            return None
        slots["when"] = when
        if then:
            slots["then"] = then
        else:
            slots.pop("then", None)
        # What the user told a card that chooses where things go ("put this one there") is
        # the card's to keep, like its settings.
        keep = {"when", "then", *(setting.key for setting in parts.settings_for(when, then)),
                *(["examples"] if parts.mode(slots) == parts.CHOOSE else [])}
        for key in [key for key in slots if key not in keep]:
            del slots[key]
        sketch.took.clear()
        return None

    def _take_sample(self, text: str, last: str) -> None:
        """The text a helper that works on text is tried on. The user's own, when their last
        message holds it, always; a made-up one only while there is none and nothing has been
        tried, or a model that makes up another each turn would have the try-out run again
        each turn."""
        sketch = self.sketch
        theirs = bool(text) and re.sub(r"\s+", " ", text.lower()) in re.sub(r"\s+", " ", last)
        if theirs or (text and not sketch.try_on and sketch.tried_with is None):
            sketch.try_on, sketch.try_theirs = text, theirs

    def _place_was_said(self, raw, say: str) -> bool:
        """Whether one of the places people name (Desktop, Documents...), given whole for
        a result with no name of its own, was said in the conversation: by the person, by
        Noir in words they have read, or in the words this form says now. It is looked
        for by its own word, which is an English one: said in another language it waits
        for the card, where it is shown and can be put right."""
        place, name = _place_and_name(raw)
        if name or place not in PLACE_NAMES:
            # A name is the model's proposal or theirs, and is on the card to see; what is
            # looked for here is one of the places people name, given whole and unasked.
            return True
        heard = " ".join([*(turn["content"] for turn in self.sketch.turns), say]).casefold()
        own = known_folder(place).name
        return place.casefold() in heard or bool(own) and own.casefold() in heard

    def _form_folder(self, setting: parts.Setting, raw) -> tuple[str, str] | None:
        """A folder that must exist, from the form's place and name. None when it is taken
        or nothing was given; else why not, for the model and for the user. A setting that
        was known stays as it was."""
        slots = self.sketch.slots
        place, name = _place_and_name(raw)
        if name.lower() in (known.lower() for known in PLACE_NAMES):
            place, name = name.capitalize(), ""  # "downloads" written as a name is the place
        if place not in PLACE_NAMES:
            place = ""
        if not place and not name:
            return None
        if _says_again(slots.get(setting.key), name, known_folder(place) if place else None):
            return None  # the folder it has, filled in again the way the note shows it
        stepped = _by_its_steps(name, place)
        if stepped is None and re.search(r"[\\/]", name) and not A_PATH.match(name):
            name = re.split(r"[\\/]+", name.strip("\\/ "))[-1]  # no such way to it: looked for by its own name
        # A place alone is where the system says it is; a name is looked for, in that place if one was said.
        found = [stepped] if stepped else find_folders(name, place or None) if name else place_dirs(place)[:1]
        if name and place and not found:
            # The place is often the model's guess (a folder was looked for in Documents, which
            # nobody had said): look everywhere before refusing, and refuse without naming it.
            place, found = "", find_folders(name, None)
        kept = f", so that stays as it was ({setting.label}: {self._shown(setting)})" if slots.get(setting.key) else ""
        near = _near_folders(name) if name and not found else []
        if len(near) == 1:
            # One folder has nearly that name: a slip of the fingers, most likely. It is
            # asked about by name, never taken: "Could you tell me the exact name of the
            # folder?" was all someone heard who had typed one letter wrong.
            shown = parts.shown_place(near[0])
            self._offered[setting.key] = near[0].name
            return (f'There is no folder called "{name}" on this computer. One has nearly that name: '
                    f'"{near[0].name}" ({shown}). Ask whether they mean that one, and leave `{setting.key}` empty until '
                    "they have said so; don't put either name in any other setting.",
                    f'I can\'t find a folder called "{name}"{kept}. Did you mean {shown}?')
        if not found:
            # The model is told only that, and to ask. Told as well that a folder which doesn't
            # exist might be meant for another setting, it made a mistyped folder's name into a
            # new place for the results, which nobody had asked for.
            return (f'There is no folder called "{name or place}" on this computer, and `{setting.key}` must be a '
                    "folder that exists. Tell them you can't find it and ask which folder they mean; don't put "
                    "that name in any other setting.",
                    f'I can\'t find a folder called "{name or place}"{kept}.')
        if len(found) > 1:
            which = ", ".join(parts.shown_place(path) for path in found[:4])
            return (f'There is more than one folder called "{name}": {which}. Ask which one they mean.',
                    f'I found more than one folder called "{name}": {which}. Which one do you mean?')
        if str(found[0]) == slots.get(setting.key):
            return None
        problem = self._set_folder(setting, found[0])
        return (problem, problem) if problem else None

    def _set_folder(self, setting: parts.Setting, folder: Path) -> str:
        """Take the folder it works in, or say why not. A place for its results that is this
        same folder only means they go inside it."""
        slots = self.sketch.slots
        if is_blocked(folder):
            return SYSTEM_FOLDER
        for other in parts.settings_for(slots.get("when", ""), slots.get("then", "")):
            if other.type == "place" and slots.get(other.key) and Path(slots[other.key]) == folder:
                slots[other.key] = ""
        slots[setting.key] = str(folder)
        return ""

    def _form_place(self, setting: parts.Setting, raw) -> tuple[str, str] | None:
        """Where its results go, from the form's place and name: inside the folder it watches
        (kept as ""), a place this computer has, something new to make there, or a path they
        typed. It need not exist yet. The name is the user's own, so it is kept as they gave it
        (parts.as_given), and a folder of that name that is there already is the one used:
        cleaned the way a made-up name is, a folder they had with a plus or an apostrophe in
        its name was passed by, and a new one with a plainer name was made beside it."""
        slots = self.sketch.slots
        place, name = _place_and_name(raw)
        if not place and not name:
            return None
        watched = slots.get("folder")
        base = Path(watched) if place == INSIDE and watched else known_folder(place) if place in PLACE_NAMES else None
        if _says_again(slots.get(setting.key), name, base):
            return None  # the place it has, filled in again the way the note shows it
        given = parts.as_given(name)
        if A_PATH.match(name):
            value = str(Path(name).expanduser())
        elif place == INSIDE:
            if name and not watched:
                return None  # inside a folder that isn't known yet: left for the turn that knows it
            value = str(base / _there(base, given)) if given and watched else ""
        elif place in PLACE_NAMES:
            value = str(base / _there(base, given)) if given else str(base)
        else:
            places = ", ".join(PLACE_NAMES)
            return (f'Something new needs a place: ask where "{name}" should be made ({places}, or inside the '
                    "folder it watches).",
                    f'Where should "{name}" go: {places}, or inside the folder it watches?')
        if value and is_blocked(Path(value)):
            return SYSTEM_FOLDER, SYSTEM_FOLDER
        if value and watched and Path(value) == Path(watched):
            value = ""
        slots[setting.key] = value
        return None

    def _form_list(self, setting: parts.Setting, raw) -> tuple[str, str] | None:
        """A list of folder names, however it was written, kept as names told apart by commas."""
        slots = self.sketch.slots
        text = ", ".join(str(piece) for piece in raw) if isinstance(raw, (list, tuple)) else raw
        names = names_in(text) if isinstance(text, str) else []
        if not names:
            return None
        have = parts.choices_of({"choices": slots.get(setting.key)})
        # The list it has, filled in again, is no change, also when it is read with commas
        # alone: a folder with "and" in its name, written back without its quotes, was taken
        # apart into two folders, and the card changed under a question about something else.
        if have and (_same_names(have, names) or _same_names(have, parts.choices_of({"choices": text}))):
            return None
        # A card may hold more folders than a new list may name (one that makes folders as
        # it goes, one from before there were cards): only a list that is longer still is
        # refused, or such a card could not be changed by talking at all.
        if len(names) > max(parts.MAX_CHOICES, len(have)):
            # Said, never cut: a folder left off the end without a word could not be moved into.
            return (f"That is {len(names)} folders, and at most {parts.MAX_CHOICES} can be named. Tell them, and ask "
                    "which ones matter most, or whether it should make folders as it goes.",
                    f"I can keep at most {parts.MAX_CHOICES} folders by name, and that was {len(names)}. Which ones "
                    "matter most?")
        slots[setting.key] = ", ".join(names)
        return None

    def _form_rule(self, setting: parts.Setting, raw, last_try: bool) -> tuple[str, str] | None:
        """The rule, as one paragraph. One that is too long goes back to the model once, to
        be said more briefly; too long again, it is cut at the end of a sentence, and the
        card shows the rule as it will be followed. The same for a rule that says how a
        result is shown, which is a setting and not the job."""
        text = _unquoted(re.sub(r"\s+", " ", raw if isinstance(raw, str) else "").strip())
        if not text:
            return None
        if len(text) > parts.MAX_RULE:
            if not last_try:
                return (f"The rule is {len(text)} characters long and can be at most {parts.MAX_RULE}. Write it more "
                        "briefly: keep what should happen to which things and what must be left alone.", "", False)
            cut = text[:parts.MAX_RULE]
            end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? ")) + 1
            text = cut[:end] if end > parts.MAX_RULE // 2 else cut[:cut.rfind(" ")]
        slots = self.sketch.slots
        if slots.get("then") == parts.SHOW and SHOWN_HOW.search(text):
            # How the result is shown is a setting of this card, and the rule is all the
            # built-in model reads as its job: sent back once to be said without it, then
            # the sentences that say it are left out, when anything is left without them.
            if not last_try:
                word = SHOWN_HOW.search(text).group(0)
                return (f'The rule says how the result is shown ("{word}"). Take that out: how it is shown is the '
                        "setting `show`, and the rule says only what to do with the text and what to reply with.",
                        "", False)
            kept = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if not SHOWN_HOW.search(sentence))
            text = kept or text
        slots[setting.key] = text
        return None

    def _form_name(self, raw, values: dict) -> None:
        """The helper's name. The model's own idea is taken while there is no card yet; from
        then on, and for a helper they already have, only a name the user gave it themselves
        ("call it ..."), or every turn could bring another name and the card with it.
        `values`: the whole form, for the folders it names."""
        sketch = self.sketch
        slots = sketch.slots
        name = _name(raw)
        if not name:
            return None
        told = [turn["content"].lower() for turn in sketch.turns if turn["role"] == "user"]
        theirs = any(name.lower() in turn and NAMES_IT.search(turn) for turn in told)
        if not theirs:
            if sketch.editing and not sketch.rename and not parts.same_name(name, str(slots.get("name") or "")):
                # A name is the person's to give once the helper exists, so this one is not
                # taken. But the model had a reason to offer it: changed to give its result
                # in another language, a helper kept a name that said the old one. They are
                # told once how to rename it (_turn).
                sketch.rename = "tell"
            if sketch.named or sketch.editing or sketch.shown is not None:
                return None
            # A name said for a folder is not the helper's name: asked to call a folder
            # something, a model once gave the agent that name. So not the name of a folder
            # the card has, nor of one this form names (taken or refused), nor a name the
            # user gave to something that isn't the helper.
            settings = parts.settings_for(slots.get("when", ""), slots.get("then", ""))
            folders = [folder for setting in settings if setting.type == "list"
                       for folder in parts.choices_of({"choices": slots.get(setting.key)})]
            folders += [Path(slots[setting.key]).stem for setting in settings
                        if setting.type in ("folder", "place") and slots.get(setting.key)]
            for setting in settings:
                given = values.get(setting.key)
                if setting.type == "list" and isinstance(given, str):
                    folders += names_in(given)
                elif setting.type in ("folder", "place"):
                    folders += list(_steps(_place_and_name(given)[1])[-1:])
            if parts.same_folder(name, folders):
                return None
            if any(name.lower() in turn and NAMES_A_THING.search(turn) for turn in told):
                return None
        name = self._unique(name)
        if theirs:
            sketch.named = True
        if name != slots.get("name"):
            slots["name"] = name
        return None

    def _form_text(self, setting: parts.Setting, raw) -> None:
        text = _one_line(raw, parts.MAX_RULE)
        if text:
            self.sketch.slots[setting.key] = text
        return None

    def _must_have_documents(self, filled: _Filled) -> Refused | None:
        """A helper that answers from documents needs a folder with something it can read:
        one with nothing is refused like a folder that can't be used."""
        slots = self.sketch.slots
        folder = slots.get("folder")
        if parts.mode(slots) != parts.SEARCH or not folder or self._readable(Path(folder)):
            return None
        shown = parts.shown_place(Path(folder))
        del slots["folder"]
        given = json.dumps(filled.values.get("folder"), sort_keys=True, ensure_ascii=False, default=str)
        return Refused("folder", given,
                       f"{shown} has no PDF, Word or text files in it, so there is nothing there to answer from. "
                       "Tell them, and ask which folder their documents are in.",
                       f"{shown} has no files I can read. I can read PDF, Word and text files.")

    def _readable(self, folder: Path) -> int:
        """How many files in a folder a helper that answers from documents can read. Counted
        once for a folder, since it means walking through it; but "none" is never kept: the
        folder is refused then, and when they put a file there and name it again, the count
        from before said it was still empty."""
        sketch = self.sketch
        if sketch.readable is None or sketch.readable[0] != str(folder):
            count = len(scan(folder).files)
            if not count:
                return 0
            sketch.readable = (str(folder), count)
        return sketch.readable[1]

    def _unique(self, base: str) -> str:
        """A name no agent they have is saved under, unless it is the one being changed."""
        base = base[:1].upper() + base[1:]
        own = store.slugify(self.sketch.replaces) if self.sketch.replaces else None
        name, number = base, 2
        while store.name_taken(name) and store.slugify(name) != own:
            name, number = f"{base} {number}", number + 1
        return name

    def _usual_name(self) -> str:
        """A name from what the card is, when the model gave none."""
        slots = self.sketch.slots
        folder = re.sub(r"[_\-]+", " ", Path(slots.get("folder") or "").name).strip()
        if folder:
            return f"{folder} helper"
        return "Highlight helper" if slots.get("when") == parts.WHILE_ON else "Chat helper"

    # ------------------------------------------------------------ what the model reads

    def _shown(self, setting: parts.Setting) -> str:
        """A setting as the model reads it: places by name, never the whole path."""
        slots = self.sketch.slots
        value = slots.get(setting.key)
        if value is None or (value == "" and setting.type not in ("place", "list")):
            if setting.type == "choice" and setting.default == "":
                # A choice that may be none of its choices, said the way the form says it, so
                # filled in again as it is read here, it stays as it is.
                return parts.NONE if value == "" else f"{NOT_KNOWN} (usually: {parts.NONE})"
            if setting.default is not None:
                return f"{NOT_KNOWN} (usually: {setting.default or INSIDE})"
            return f"{NOT_KNOWN} (given one if you leave it empty)" if not parts.needed(setting) else NOT_KNOWN
        if setting.type == "folder":
            return parts.shown_place(Path(value))
        if setting.type == "place":
            return parts.shown_place(Path(value)) if value else INSIDE
        if setting.type == "list":
            return _listed(parts.choices_of({"choices": value})) or "none named"
        return str(value)

    def _known(self) -> list[str]:
        """The card so far, as code has checked it."""
        sketch = self.sketch
        slots = sketch.slots
        when, then = slots.get("when", ""), slots.get("then", "")
        if not (sketch.wants or when or then or any(slots.values())):
            return ["nothing yet"]
        lines = [f"What they want: {sketch.wants}"] if sketch.wants else []
        lines += [f"{WHEN.label}: {when or NOT_KNOWN}", f"{THEN.label}: {then or NOT_KNOWN}"]
        return lines + [f"{setting.label}: {self._shown(setting)}" for setting in parts.settings_for(when, then)]

    def _learned(self, before: dict) -> list[str]:
        """What this turn added to the card or changed on it, for the user to see."""
        slots = self.sketch.slots
        found = [f"{setting.label.lower()}: {slots[setting.key]}" for setting in (WHEN, THEN)
                 if slots.get(setting.key) and slots[setting.key] != before.get(setting.key)]
        return found + [f"{setting.label.lower()}: {self._shown(setting)}"
                        for setting in parts.settings_for(slots.get("when", ""), slots.get("then", ""))
                        if setting.key in slots and before.get(setting.key) != slots[setting.key]]

    def _computer(self) -> list[str]:
        """What code can see that the model may use instead of asking: how many files of
        which endings are in the places people name and in the card's own folder (never a
        file's name: the model may be off this computer), which folders are in those
        places, by name, and the helpers already made (with the start of each one's rule
        only for a model on this computer)."""
        sketch = self.sketch
        named = [known_folder(place) for place in PLACE_NAMES]
        folders = list(named)
        if sketch.slots.get("folder"):
            folders.append(Path(sketch.slots["folder"]))
        facts = []
        for folder in dict.fromkeys(folders):
            if not folder.is_dir():
                continue
            facts.append(_holds(folder))
            # The folders in it, so one they name can be known for what it is. With only
            # the files counted, "my ... folder" in a request was a folder the model had
            # never heard of, and it asked where on the computer that was.
            inside = sorted((path.name for path in _folders_in(folder)), key=str.casefold) if folder in named else []
            if inside:
                more = f" and {len(inside) - MAX_FOLDERS_TOLD} more" if len(inside) > MAX_FOLDERS_TOLD else ""
                facts.append(f"Folders in {parts.shown_place(folder)}: {', '.join(inside[:MAX_FOLDERS_TOLD])}{more}.")
        have = [_helper_line(agent, rule=sketch.model.here) for agent in store.list_agents()
                if agent.name != sketch.replaces]
        facts += [f"A helper they already have: {line}" for line in have] or ["They have no other helper yet."]
        if sys.platform != "win32":
            facts.append("Highlighting works on Windows only, and this is not a Windows computer: no helper here can "
                         "work on highlighted text.")
        return facts

    def _tried_lines(self) -> list[str]:
        """What the last try-out did, for the model's note. A model on this computer reads
        each file's line as the user saw it. A model off it is told only how many files of
        which endings came out which way: never a file's name, what a file says, or the
        name of a folder that was made up from one."""
        sketch = self.sketch
        rows = sketch.tried
        if rows is None:
            return []
        then = sketch.slots.get("then", "")
        # The heading says what was really tried. One heading for all said "on their own
        # things", also for a sample that was made up and for a folder whose files were only
        # counted, and a model told that can tell the user it worked on their text.
        lines = ["THE TRY-OUT (code tried the helper, as the card has it, on the newest files in their folder; "
                 "nothing was changed)"]
        if rows and "text" in rows[0]:
            lines = ["THE TRY-OUT (code tried the helper, as the card has it, on one short text; nothing was changed)"]
            for row in rows:
                whose = "their own text" if row.get("theirs") else "a sample that was made up, not a text of theirs"
                gave = (f"it did nothing: the text is already in {row['left_out']}, and the card leaves such text out"
                        if row.get("left_out") else f"it gave: {row['result']}")
                lines.append(f'- On {whose}, "{row["text"]}", {gave}')
        elif rows and "found" in rows[0]:
            lines = ["THE TRY-OUT (nothing was tried: code counted the files in the folder that it can read)",
                     f"- {rows[0]['found']} files it can read were found in the folder."]
        elif not rows:
            lines.append("- The folder had nothing in it to try it on.")
        elif sketch.model.here:
            lines.append("In brackets after each file: what the small model took it for, or why it stays.")
            lines += [f"- {row_line(row, then)}" for row in rows]
            spoken = self._spoken_of()
            if spoken:
                lines.append("Their last message speaks of: " + "; ".join(row_line(row, then) for row in spoken))
        else:
            lines.append("You are told how many files of which endings came out which way, never a file's name or "
                         "what it says. They see each file by name on their screen.")
            came: dict[str, Counter] = {}
            for row in rows:
                came.setdefault(_outcome_said(row, then), Counter())[_ending(row)] += 1
            for outcome, endings in came.items():
                count = sum(endings.values())
                kinds = ", ".join(f"{number} {ending}" for ending, number in endings.most_common())
                lines.append(f"- {outcome}: {count} file{'' if count == 1 else 's'} ({kinds})")
        return [*lines, "The card is already on their screen, below the try-out."]

    # ------------------------------------------------------------ the try-out and the card

    def _runs_with(self) -> dict:
        """Everything a try-out depends on: the card, less what cannot change what comes out
        of one (its name, where its results are kept, how they are shown), and the text it
        is tried on. Asked only to give the notes file another name, a helper was tried on
        the same five files again, to write the same about each."""
        sketch = self.sketch
        ran = {key: value for key, value in sketch.slots.items() if key not in SAME_OUTCOME}
        if self._on_text():
            ran["try_on"] = sketch.try_on or parts.SAMPLE_TEXT
        return ran

    def _on_text(self) -> bool:
        """A helper that does what its rule says with a piece of text (highlighted, or sent in the chat)."""
        slots = self.sketch.slots
        return parts.mode(slots) == parts.WRITE and slots.get("when") != parts.NEW_FILE

    def _try_out(self) -> Iterator[Event]:
        """The helper as the card now stands, tried on the user's own things by code, with
        nothing changed: what it would have done is shown before the card. The design model
        has no part in it."""
        sketch = self.sketch
        slots = sketch.slots
        # The last try-out is what this one is held against, when it was the same kind of
        # helper in the same folder: only then is "stays now (was ...)" a thing to say.
        ran = sketch.tried_with or {}
        before = sketch.tried if all(ran.get(key) == slots.get(key) for key in ("then", "folder")) else None
        sketch.tried = None
        sketch.tried_with = self._runs_with()
        if parts.mode(slots) == parts.SEARCH:
            folder = Path(slots["folder"])
            count = self._readable(folder)
            sketch.tried = [{"found": count}]
            yield Result(TRY_OUT, f"Found {count} file{'' if count == 1 else 's'} it can read in "
                                  f"{parts.shown_place(folder)}.")
            return
        if sketch.model.here:
            # The built-in model does the trying, and it and a design model on this computer
            # don't both fit on a 16 GB graphics card: the design model makes room first.
            sketch.model.done()
        if self._on_text():
            yield from self._try_on_text()
        else:
            yield from self._try_on_files(before)

    def _on_files(self) -> bool:
        """A helper that works on the files of a folder, which a try-out runs on."""
        return self.sketch.slots.get("when") == parts.NEW_FILE

    def _tried_again(self, words: str, mended: bool = False, asked: bool = False) -> Iterator[Event]:
        """The try-out after a change to the rule, with one more go at the rule when the
        change did not do what was asked. Yields what the user sees meanwhile; returns the
        words to say and the try-out's result to show under them. `mended`: the rule was
        written again by the mender in this turn already, so it is not sent there twice.
        `asked`: by the model's form, their message asked for a change.

        The model writes the rule, and only the try-out shows what the built-in model makes
        of it. Told that two files had gone into the wrong folder and where they belonged,
        a model wrote that down as the change, left the rule saying nothing new about
        them, and said "I have updated the plan so that ... go to their specific folders";
        the try-out under those words put both where they had been put before. So code
        looks: the files their message speaks of that came out exactly as before go to
        the mender (MEND), in the same turn, and what is said is true of what came of it."""
        sketch = self.sketch
        earlier = sketch.tried or []
        results = yield from self._tried_quietly()
        still = self._still_as_before(earlier)
        if still and not mended:
            named = _some(row["name"] for row in still)
            yield Thinking(f"{named} still come{'s' if len(still) == 1 else ''} out as before, so I'm putting the "
                           "rule another way.")
            if self._mend(still):
                # Held against the try-out they saw, not the one in between: what is marked
                # as changed is what changed for them.
                sketch.tried = earlier
                results = yield from self._tried_quietly()
                still = self._still_as_before(earlier)
        if still:
            # Said by code, since the model's words say what it changed and not what came of it.
            ends = "s" if len(still) == 1 else ""
            words = self._code_adds(words, f"In the try-out below, {_some(row['name'] for row in still)} still "
                                           f"come{ends} out as before.",
                                    f"In the try-out below, {len(still)} file{'' if len(still) == 1 else 's'} you "
                                    f"spoke of still come{ends} out as before.")
        elif asked and self._all_as_before(earlier):
            # A change was asked for and not one file came out otherwise. Told "also leave
            # the pictures alone", a model said it had changed the rule to make sure of
            # that, and the one picture in the folder went on going into a folder: no file
            # was named, so nothing above caught it, and the try-out said only that it came
            # out the same. What came of it is said by code, under the model's words.
            words = self._code_adds(words, "In the try-out below, every file still comes out as it did before.")
        return self._with_others(words, earlier), results

    def _code_adds(self, words: str, sentence: str, unnamed: str = "") -> str:
        """The model's words with a sentence of code's own after them. `unnamed`: the same
        sentence without the files' names, which is what a model off this computer reads of
        it in the conversation later (_for_turns), while the user reads the names."""
        if unnamed:
            self._unnamed[sentence] = unnamed
        return f"{_without_confirming(words)} {sentence}"

    def _for_turns(self, words: str) -> str:
        """What Noir said, as it is kept in the conversation the design model reads. For a
        model off this computer, code's sentences that name files are kept without the
        names. The try-out's own lines already went there as counts only, and the opening
        promised "never your files' names"; but a sentence code added to Noir's words after
        a change ("In the try-out below, ... also comes out differently") went into the
        conversation as it was said, and with the next message to a plan's model, names of
        files the user had never typed."""
        if self.sketch.model.here:
            return words
        for named, unnamed in self._unnamed.items():
            words = words.replace(named, unnamed)
        return words

    def _all_as_before(self, earlier: list[dict]) -> bool:
        """Whether the try-out just run was on the same files as the one before it and every
        one of them came out exactly as it did then."""
        sketch = self.sketch
        rows = sketch.tried or []
        then = sketch.slots.get("then", "")
        before = {row.get("name"): row for row in earlier if isinstance(row, dict)}
        if not rows or "name" not in rows[0] or {row["name"] for row in rows} != set(before):
            return False
        return all(_outcome(row, then) == _outcome(before[row["name"]], then) for row in rows)

    def _tried_quietly(self) -> Iterator[Event]:
        """A try-out whose result is held back for now: yields the rest, returns the result."""
        results: list[Event] = []
        for event in self._try_out():
            if isinstance(event, Result):
                results.append(event)
            else:
                yield event
        return results

    def _mend(self, rows: list[dict]) -> bool:
        """Have the rule written again so that these files of the last try-out come out the
        way the user's last message asks (MEND). Returns whether the rule is another one
        now. A model on this computer reads each file's line; one off it reads only how
        many came out which way, and has their message, which says what they want."""
        sketch = self.sketch
        slots = sketch.slots
        then = slots.get("then", "")
        names = {row.get("name") for row in rows}
        rest = [row for row in sketch.tried or [] if row.get("name") not in names]
        if sketch.model.here:
            did = "\n".join(f"- {row_line(row, then)}" for row in rows)
            others = "\n".join(f"- {row_line(row, then)}" for row in rest)
        else:
            did = "\n".join(f"- {count} of them: {outcome.lower()}" for outcome, count in
                            Counter(_outcome_said(row, then) for row in rows).items())
            others = "\n".join(f"- {count} of them: {outcome.lower()}" for outcome, count in
                               Counter(_outcome_said(row, then) for row in rest).items())
        folders = _listed(parts.choices_of(slots))
        content = "\n\n".join(piece for piece in (
            f"THE RULE AS IT STANDS\n{slots.get('instruction', '')}",
            f"ITS FOLDERS\n{folders}" if folders else "",
            "WHAT IT DID WITH THE FILES THEY SPEAK OF (in brackets: what the small model took the file for)\n" + did,
            f"WHAT IT DID WITH THE OTHER FILES, WHICH THEY DID NOT SPEAK OF\n{others}" if others else "",
            f"WHAT THEY SAID\n{self._last_said_as_typed()}") if piece)
        before = slots.get("instruction")
        try:
            filled = sketch.model.fill(MEND.format(limit=parts.MAX_RULE), [{"role": "user", "content": content}],
                                       MEND_SCHEMA)
        except DesignerError:
            return False  # it can't have another go just now: the try-out shows how things stand
        self._form_rule(parts.RULE, filled.get("rule"), last_try=True)
        return slots.get("instruction") != before

    def _write_out(self) -> None:
        """The rule the form just gave, written out by the writer (WRITE) before it goes on
        a card: what was never said in the conversation comes out of it, what they asked
        for and the draft lost goes in. Each draft is written out once: the model fills
        the rule in again every turn, as it reads it or as it first wrote it, and neither
        is a new draft.

        A new draft is only written out until the card is up. After that a change is the
        model's to make and the try-out's to check (_tried_again); a draft that was written
        out before is still known for what it is, or the model's first wording would come
        back onto the card. Not for a helper they already have, whose rule
        was agreed in a conversation this one knows nothing of. And only with a model on
        this computer, where it takes a third of a second: through a plan it would be one
        more whole answer each time, for a failure that was seen with a model here."""
        sketch = self.sketch
        slots = sketch.slots
        draft = slots.get("instruction") or ""
        if not draft or sketch.editing or not sketch.model.here:
            return
        if draft in sketch.written.values():
            return  # the rule as the writer wrote it, filled in again
        if draft not in sketch.written:
            if sketch.shown is not None:
                return
            does = [parts.WHENS[slots["when"]].about] if slots.get("when") in parts.WHENS else []
            does += [parts.THENS[slots["then"]].about] if slots.get("then") in parts.THENS else []
            folders = _listed(parts.choices_of(slots))
            said = "\n".join(f"{'You' if turn['role'] == 'assistant' else 'Them'}: {turn['content']}"
                             for turn in sketch.turns[-MAX_TURNS:])
            content = "\n\n".join(piece for piece in (
                "WHAT THE HELPER DOES\n" + " ".join(does), f"ITS FOLDERS\n{folders}" if folders else "",
                f"WHAT WAS SAID\n{said}", f"THE DRAFT\n{draft}") if piece)
            try:
                filled = sketch.model.fill(WRITE.format(limit=parts.MAX_RULE), [{"role": "user", "content": content}],
                                           MEND_SCHEMA)
            except DesignerError:
                return  # it can't just now: the draft stands, and may be written out at the next turn
            self._form_rule(parts.RULE, filled.get("rule"), last_try=True)
            sketch.written[draft] = slots.get("instruction") or draft
        slots["instruction"] = sketch.written[draft]

    def _last_said_as_typed(self) -> str:
        return next((turn["content"] for turn in reversed(self.sketch.turns) if turn["role"] == "user"), "")

    def _with_others(self, words: str, earlier: list[dict]) -> str:
        """The words, with one sentence from code when the change also changed what happens
        to files their message did not speak of. Asked to leave one file where it was, a
        model added a line to the rule, and with it the built-in model put another file
        into a different folder than before; the model's words said only that the first
        would stay. The try-out marks such a file, and this says to look for it."""
        sketch = self.sketch
        then = sketch.slots.get("then", "")
        before = {row.get("name"): row for row in earlier if isinstance(row, dict)}
        rows = sketch.tried or []
        if not rows or "name" not in rows[0] or {row["name"] for row in rows} != set(before):
            return words
        spoken = {row["name"] for row in self._spoken_of()}
        others = [row for row in rows if _outcome(row, then) != _outcome(before[row["name"]], then)
                  and row["name"] not in spoken]
        changed = len(rows) - sum(_outcome(row, then) == _outcome(before[row["name"]], then) for row in rows)
        if not others or len(others) == changed:
            return words  # nothing else changed, or no file was spoken of by name: the change was about kinds
        ends = "s" if len(others) == 1 else ""
        return self._code_adds(words, f"In the try-out below, {_some(row['name'] for row in others)} also come{ends} "
                                      "out differently than before.",
                               f"In the try-out below, {len(others)} other file{'' if len(others) == 1 else 's'} also "
                               f"come{ends} out differently than before.")

    def _spoken_of(self) -> list[dict]:
        """The files of the last try-out that the user's last message speaks of: the ones
        whose names share the most words with it. (Any shared word used to do, and "put the
        ... one back" about one of two files named alike was taken to speak of both: the
        other, which had come out right, was then reported as still coming out as before.)"""
        rows = self.sketch.tried or []
        if not rows or "name" not in rows[0]:
            return []
        said = _telling_words(self._last_said())
        shared = [len(_telling_words(Path(row["name"]).stem) & said) for row in rows]
        most = max(shared)
        return [row for row, count in zip(rows, shared) if most and count == most]

    def _still_as_before(self, earlier: list[dict]) -> list[dict]:
        """The files of the try-out just run that came out exactly as in the one before it
        and that the user's last message speaks of, by a word of their name. Empty when the
        two try-outs were not on the same files."""
        sketch = self.sketch
        rows = sketch.tried or []
        then = sketch.slots.get("then", "")
        before = {row.get("name"): row for row in earlier if isinstance(row, dict)}
        if not rows or "name" not in rows[0] or {row["name"] for row in rows} != set(before):
            return []
        spoken = {row["name"] for row in self._spoken_of()}
        return [row for row in rows if row["name"] in spoken
                and _outcome(row, then) == _outcome(before[row["name"]], then)]

    def _try_on_text(self) -> Iterator[Event]:
        sketch = self.sketch
        sample = sketch.try_on or parts.SAMPLE_TEXT
        theirs = bool(sketch.try_on) and sketch.try_theirs
        # A text that isn't the user's own is called a sample, so nobody takes a made-up
        # sentence for something of theirs.
        on = f'On "{sample}"' if theirs else f'On a sample, "{sample}",'
        yield Thinking("Trying it on a short piece of text now.")
        leaves_out = parts.leaves_out(sketch.slots, sample)
        if leaves_out:
            # As the helper itself does with a highlight (quick/agents.py): text that is
            # already in the language its card leaves out is passed over. Shown a result
            # for it here, they would wait for one that never comes.
            sketch.tried = [{"text": sample, "result": "", "theirs": theirs, "left_out": leaves_out}]
            yield Result(TRY_OUT, f"{on} it does nothing: the text is already in {leaves_out}, and it leaves such "
                                  "text out.")
            return
        try:
            result = run_instruction(self.ollama, self.model, sketch.slots["instruction"], sample, self.think)
        except OllamaError:
            yield Thinking("I couldn't try it out just now: the built-in model didn't answer.")
            return
        sketch.tried = [{"text": sample, "result": result, "theirs": theirs}]
        was, now = parts.skip_language(sketch.slots), self._comes_out_in(sample, result)
        if now:
            yield Thinking(f"What it gives is in {now}, so that is the language it leaves out, not {was}.")
        yield Result(TRY_OUT, f"{on} it gives:\n{result}")

    def _comes_out_in(self, sample: str, result: str) -> str:
        """Put the language a card leaves out right by what its try-out gave, and return the
        language it now leaves out; "" when nothing was changed. The setting is the language
        the result comes out in, and here is a result: when it is plainly in another
        language that code can tell, and the text it was made from was not, that one is
        it. A result code can't tell the language of changes nothing, and neither does one
        in the language of the text it came from, which says nothing of what the helper
        turns text into.

        A helper that was to show what Japanese sentences mean in English came with
        Japanese as the language it leaves out, for the second time: told what the setting
        is, a model still filled in the language of the text the helper is given, and the
        sample it made up had too many Chinese characters in it to be told for Japanese, so
        nothing caught it (_skips_its_own_sample). And one changed by talking to give its
        result in another language kept the old one as the language it leaves out."""
        sketch = self.sketch
        was = parts.skip_language(sketch.slots)
        if not was or not any(letter.isalpha() for letter in result) or parts.leaves_out(sketch.slots, result):
            return ""
        setting = self._choice_setting("skip_language")
        told = [language for language in (setting.choices if setting else ())
                if language != was and parts.leaves_out({**sketch.slots, "skip_language": language}, result)
                and not parts.leaves_out({**sketch.slots, "skip_language": language}, sample)]
        if len(told) != 1:
            return ""
        sketch.slots["skip_language"] = told[0]
        sketch.tried_with = self._runs_with()  # the same helper, as far as what comes out of it goes
        # The model fills the setting in again each turn as it understood it: the language
        # that was wrong is passed over from here on, unless they name it themselves.
        sketch.ignored.add(("skip_language", json.dumps(was, sort_keys=True, ensure_ascii=False, default=str)))
        return told[0]

    def _try_on_files(self, before: list | None) -> Iterator[Event]:
        sketch = self.sketch
        slots = sketch.slots
        then = slots.get("then", "")
        writes = parts.mode(slots) == parts.WRITE
        folder = parts.shown_place(Path(slots["folder"]))
        yield Thinking(f"Trying it on what's in {folder} now. {'Nothing is written.' if writes else 'Nothing moves.'}")
        try:
            rows = self.rehearse(store.Agent(name=slots["name"], blueprint=parts.CUSTOM, slots=dict(slots)))
        except (OSError, OllamaError):
            yield Thinking("I couldn't try it out just now, so the card comes without a try-out.")
            return
        rows = [dict(row) for row in rows or [] if isinstance(row, dict) and row.get("name")]
        sketch.tried = rows
        if not rows:
            yield Result(TRY_OUT, f"There is nothing in {folder} to try it on yet. It starts with the next file that "
                                  "lands.")
            return
        earlier = {row["name"]: row for row in before or [] if isinstance(row, dict) and row.get("name")}
        again = bool(earlier) and set(earlier) == {row["name"] for row in rows}
        files = f"{len(rows)} file{'' if len(rows) == 1 else 's'}"
        nothing = "Nothing was written." if writes else "Nothing was moved."
        if not again:
            first = f"Tried on the {len(rows)} newest file{'' if len(rows) == 1 else 's'} in {folder}. {nothing}"
        else:
            first = f"Tried again on the same {files} in {folder}. {nothing}"
            if all(_outcome(row, then) == _outcome(earlier[row["name"]], then) for row in rows):
                if not self._change_asked:
                    yield Result(TRY_OUT, f"{first}\nIt came out the same as before.")
                    return
                # A change was asked for and nothing came out otherwise: every file is shown,
                # so they can see the one they meant. Folded into one line, that hid a picture
                # that went on going into a folder after they had said to leave pictures alone.
                first = f"{first} Every file came out as before."
        lines = [row_line(row, then, earlier[row["name"]] if again else None) for row in rows]
        yield Result(TRY_OUT, "\n".join([first, *lines]))

    def _tried_before(self) -> str:
        """The last try-out, said again from what was kept of it, for a helper that is taken
        up again after it was set aside: the card comes back with the try-out it had. It is
        not run again for that (a try-out asks the built-in model about every file), and it
        says so: these are the outcomes from before. "" when the card as it stands was
        never tried (a try-out that could not run)."""
        sketch = self.sketch
        slots = sketch.slots
        rows = sketch.tried
        if rows is None or sketch.tried_with != self._runs_with():
            return ""
        if rows and "found" in rows[0]:
            count = rows[0]["found"]
            return f"Found {count} file{'' if count == 1 else 's'} it can read in {parts.shown_place(Path(slots['folder']))}."
        if rows and "text" in rows[0]:
            row = rows[0]
            on = f'on "{row["text"]}"' if row.get("theirs") else f'on a sample, "{row["text"]}",'
            if row.get("left_out"):
                return (f"The try-out from before: {on} it does nothing: the text is already in {row['left_out']}, and "
                        "it leaves such text out.")
            return f"The try-out from before: {on} it gave:\n{row['result']}"
        folder = parts.shown_place(Path(slots["folder"]))
        if not rows:
            return f"There was nothing in {folder} to try it on. It starts with the next file that lands."
        then = slots.get("then", "")
        nothing = "Nothing was written." if parts.mode(slots) == parts.WRITE else "Nothing was moved."
        first = f"The try-out from before, on {len(rows)} file{'' if len(rows) == 1 else 's'} in {folder}. {nothing}"
        return "\n".join([first, *(row_line(row, then) for row in rows)])

    def _card(self) -> AgentCard:
        """The card, every line written by code from the slots (parts.card)."""
        sketch = self.sketch
        slots = sketch.slots
        # How many files a documents helper can read was counted when its folder was taken.
        # The files already in a watched folder are not counted here: what counts as one is
        # the watcher's to say, and two numbers that differ by one would be worse than none.
        count = self._readable(Path(slots["folder"])) if parts.mode(slots) == parts.SEARCH else None
        kind, reads, can_do, cannot_do, runs_on = parts.card(slots, self.model_name(), count)
        return AgentCard(id=CARD, name=slots["name"], kind=kind, reads=reads, can_do=can_do, cannot_do=cannot_do,
                         runs_on=runs_on,
                         actions=[SAVE_CHANGES if sketch.editing else CREATE_IT, "Change something", "Cancel"])

    # ------------------------------------------------------------ finish

    def _create(self) -> Iterator[Event]:
        """Make the agent the card describes. Reached only from the card's button, or a
        whole-message yes while the card is up and nothing was asked."""
        sketch = self.sketch
        slots = dict(sketch.slots)
        name = slots["name"]
        old = store.find_agent(sketch.replaces) if sketch.replaces else None
        sketch.model.done()
        self.sketch = None
        if sketch.editing and old is None:
            # The helper being changed was deleted meanwhile. The engine ends such a change
            # when it deletes one, but saved here it would come back under its old name.
            yield from say(f"{sketch.replaces} was deleted, so there is nothing to save the changes to.")
            return
        self.edited, self.replaced = sketch.editing, None
        if parts.mode(slots) == parts.SEARCH:
            # The one agent that is not saved as a card: its runtime is the search index.
            agent = store.Agent(name=name, blueprint=parts.DOCUMENTS_QA, slots={"folder": slots["folder"], "name": name})
            maker = create_documents_agent(self.ollama, self.model, agent, self.think)
            made = False
            while True:
                try:
                    event = next(maker)
                except StopIteration as finished:
                    made = bool(finished.value)
                    break
                if not isinstance(event, AgentList):  # sent below, once the helper it replaces is gone
                    yield event
            # The helper being changed goes only once the new one is made. Deleted first, a
            # folder that couldn't be read left them with neither. (Under the same name the
            # new one is saved over it, so there is nothing left to delete.)
            if made and old:
                if store.slugify(old.name) != store.slugify(name):
                    store.delete(old)
                self.replaced = old.name if old.name != name else None
            elif old:
                yield from say(f"{old.name} is as it was.")
            if made:
                yield AgentList([a.name for a in store.list_agents()])
            return
        agent = store.Agent(name=name, blueprint=parts.CUSTOM, slots=slots)
        if old and old.name != name:
            store.delete(old)
            self.replaced = old.name
        elif old:
            agent.created = old.created  # the same agent, changed
        store.save(agent)
        self.created = agent
        yield from say(f"Saved the changes to {name}." if sketch.editing else f"{name} is ready.")
        yield AgentList([a.name for a in store.list_agents()])

    def _cancel(self) -> Iterator[Event]:
        sketch = self.sketch
        sketch.model.done()
        self.sketch = None
        yield from say(_left_alone(sketch))

    def _cant_be_made(self, words: str) -> Iterator[Event]:
        """The model says it can't be made from the parts there are: its words, then one
        plain line from code, so it is clear that nothing was made. The request is kept in
        the ideas list, where it is judged again as parts are built."""
        sketch = self.sketch
        sketch.model.done()
        self.sketch = None
        if sketch.editing:
            line = f"I left {sketch.replaces} as it was."
        elif _keep_idea(sketch):
            line = 'Nothing was created, and I\'ve kept the idea in your list. Say "my ideas" to see it.'
        else:
            line = "Nothing was created."
        yield from say(" ".join(part for part in (words, line) if part))


# ---------------------------------------------------------------- small helpers


def _left_alone(sketch: Sketch) -> str:
    """What is said when the conversation is called off: nothing was made, or the helper they have is unchanged."""
    return f"Okay, I left {sketch.replaces} as it was." if sketch.editing else "Okay, I won't create it."


def _keep_idea(sketch: Sketch) -> bool:
    """Put what they asked for in the ideas list (planner.py), as one part nothing covers yet."""
    title = (sketch.wants or sketch.request).strip()[:60] or "New helper"
    try:
        planner.save_idea(planner.IdeaDraft(request=sketch.request, title=title,
                                            steps=[planner.PlanStep(None, sketch.wants)]))
    except OSError:
        return False
    return True


def _place_and_name(raw) -> tuple[str, str]:
    """The place and the name in a form's folder field, whatever the model put there."""
    if not isinstance(raw, dict):
        return "", ""
    place, name = raw.get("place"), raw.get("name")
    return (place if isinstance(place, str) else ""), (name.strip().strip("\"'") if isinstance(name, str) else "")


def _words_in(raw) -> list[str]:
    """The words of a form's value that a message could name: a folder's name, or the text.
    A folder given by its place alone is named by the place: with no word to go by, one
    that was refused twice could never be taken again, whatever the user said."""
    text = raw
    if isinstance(raw, dict):
        text = raw.get("name") or (raw.get("place") if raw.get("place") in PLACE_NAMES else "")
    return re.findall(r"[^\W_]{3,}", text.lower()) if isinstance(text, str) else []


def _calls_off(whole: str) -> bool:
    """Whether a message calls the whole thing off without the model being asked: one of
    the words that do, alone, before a comma or a full stop ("never mind, I'll do it
    myself"), or at the start of more ("cancel this"). Left to the model, each of those
    cost a turn, which through a plan is as much as any answer, and hung on its choosing to
    end it. "Stop" ends it only alone or before a comma or a full stop: "stop moving the
    pictures" is a change, and the model reads it."""
    for word in CANCEL_WORDS:
        if whole == word or whole.startswith(tuple(word + mark for mark in ",.!;")):
            return True
        if word not in STANDS_ALONE and whole.startswith(word + " "):
            return True
    return False


def _one_question(text: str) -> str:
    """The first question in what the model wrote where one question was asked for, and of
    two joined by "and" the first: "What kind of files are making the mess, and what would
    you like to happen to them?" came back for half of the first questions, and people
    answer the second half."""
    text = re.sub(r"\s+", " ", text).strip()
    end = min((at for at in (text.find("?"), text.find("？")) if at >= 0), default=-1)
    if end < 0:
        return ""
    first = text[:end]
    second = SECOND_QUESTION.search(first)
    return (first[:second.start()] if second else first).rstrip(" ,;") + "?"


def _telling_words(text: str) -> set[str]:
    """The words of a message or a file's name that could name a file: five letters or more
    (two in a script with no spaces between letters, where a word is that short), with a
    last "s" aside, so a word said for several files is the word in one file's name.
    Numbers and short words name nothing."""
    words = set()
    for word in re.findall(r"[^\W\d_]+", text.casefold()):
        if len(word) >= (5 if word.isascii() else 2):
            words.add(word[:-1] if word.isascii() and word.endswith("s") else word)
    return words


def _setting_words(text: str) -> set[str]:
    """The words of a message, or of a setting's label and choices, that could name that
    setting: four letters or more (two in a script with no spaces between letters), with a
    last "s" aside, less the ones every conversation about a helper has in it (PLAIN_WORDS).
    Four, not five as for a file's name, or "copy", "stay" and "name" would name nothing."""
    words = set()
    for word in re.findall(r"[^\W\d_]+", text.casefold()):
        if len(word) >= (4 if word.isascii() else 2):
            words.add(word[:-1] if word.isascii() and word.endswith("s") else word)
    return words - PLAIN_WORDS


def _some(names) -> str:
    """One or two names, and how many more there are."""
    names = list(names)
    if len(names) <= 2:
        return " and ".join(names)
    return f"{names[0]} and {len(names) - 1} more"


def _without_confirming(text: str) -> str:
    """Words without a last sentence that only asks whether what was just said is right,
    for a turn in which the card comes anyway: the card is where they say yes."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) > 1 and CONFIRMS.match(sentences[-1]):
        sentences.pop()
    return " ".join(sentences)


def _without_question(text: str) -> str:
    """Words without the question they end in."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    while sentences and sentences[-1].rstrip().endswith(("?", "？")):
        sentences.pop()
    return " ".join(sentences)


def _near_folders(name: str, limit: int = 3) -> list[Path]:
    """The folders in the places people name, and one step inside them, whose name is
    nearly the one given: a letter wrong, a letter missing. Nearest first. Never one with
    other numbers in its name: a folder for one year is not a slip for another year's."""
    wanted = name.casefold()
    numbers = re.findall(r"\d+", wanted)
    found: list[tuple[float, Path]] = []
    for place in PLACE_NAMES:
        base = known_folder(place)
        for folder in [base, *_folders_in(base)]:
            for path in _folders_in(folder):
                alike = SequenceMatcher(None, wanted, path.name.casefold()).ratio()
                if alike >= NEARLY and re.findall(r"\d+", path.name) == numbers:
                    found.append((alike, path))
    found.sort(key=lambda one: (-one[0], len(one[1].parts)))
    return list(dict.fromkeys(path for _, path in found))[:limit]


def _folders_in(folder: Path) -> list[Path]:
    try:
        with os.scandir(folder) as entries:
            return [Path(entry.path) for entry in entries
                    if entry.is_dir() and not entry.name.startswith((".", "$"))][:MAX_LOOKED]
    except OSError:
        return []


def _without_card(text: str) -> str:
    """Words without the sentences that point at the card or its button, for a turn that no
    card follows."""
    return " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if not POINTS_AT_CARD.search(sentence))


def _steps(text: str) -> tuple[str, ...]:
    """A path or a place as the folders it goes through, with case and the kind of slash aside."""
    return tuple(step.casefold() for step in re.split(r"[\\/]+", text.strip()) if step)


def _says_again(known: str | None, name: str, base: Path | None) -> bool:
    """Whether a name in the form only says again the folder a setting already has. The
    model fills every setting in again each turn, the way KNOWN SO FAR shows it: by the
    folder's own name, from the home folder, from one of the places people name, or as its
    whole path. Looked up like a new folder, one outside the home folder or deep inside it
    couldn't be found again, and the user was told that a folder which was set didn't
    exist. `base`: the place the form gave with the name, if it gave one; a folder of the
    same name in another place is not this one."""
    if not known or not name:
        return False
    path = Path(known)
    said, whole = _steps(name), _steps(known)
    if A_PATH.match(name):
        return _steps(str(Path(name).expanduser())) == whole
    if said == _steps(parts.shown_place(path)):
        return True
    if base is None:
        return said == _steps(path.name)
    under = _steps(str(base))
    return whole == (*under, *said) or (said == _steps(path.name) and whole[:len(under)] == under)


def _by_its_steps(name: str, place: str) -> Path | None:
    """The folder a name means when it is written as the folders it is reached through
    ("Household/Appliance manuals", or with the place in front, the way the note shows a
    folder), if that is a folder that exists: under the place the form gave, under one of
    the places people name, or under the home folder. None for a single name, a whole
    path, and a way that leads to no folder.

    Asked whether they meant "Appliance manuals (Documents\\Household\\Appliance manuals)",
    they said yes, and the model filled the folder in as it had just read it: the place and
    "Household/Appliance manuals". Looked for as one folder's name, that was nowhere, and
    the answer to their yes was "I can't find a folder called ...", three turns running."""
    steps = [step for step in re.split(r"[\\/]+", name.strip()) if step.strip()]
    if len(steps) < 2 or A_PATH.match(name):
        return None
    first = next((known for known in PLACE_NAMES if known.casefold() == steps[0].casefold()), "")
    bases = [(known_folder(first), steps[1:])] if first else []
    bases += [(known_folder(known), steps) for known in ([place] if place in PLACE_NAMES else []) + list(PLACE_NAMES)]
    bases.append((Path.home(), steps))
    for base, rest in bases:
        path = base
        for step in rest:
            path = path / _there(path, step.strip())
        if rest and path.is_dir():
            return path
    return None


def _there(base: Path, name: str) -> str:
    """A folder's name as it is spelled in the place it is in, when one folder of that name
    is there already (case, spaces and marks aside), so the folder they have is the one
    used; else the name as it was given."""
    try:
        with os.scandir(base) as entries:
            there = [entry.name for entry in entries if entry.is_dir()]
    except OSError:
        return name
    alike = ([found for found in there if found.casefold() == name.casefold()]
             or [found for found in there if parts.same_name(found, name)])
    return alike[0] if len(alike) == 1 else name


def _same_names(one: list[str], other: list[str]) -> bool:
    """Whether two lists name the same folders, in whatever order and case."""
    return sorted(name.casefold() for name in one) == sorted(name.casefold() for name in other)


def _same_path(one: object, other: object) -> bool:
    """Whether two saved folders are one folder, however each was written."""
    if not (isinstance(one, str) and isinstance(other, str) and one and other):
        return False
    return os.path.normcase(os.path.normpath(one)) == os.path.normcase(os.path.normpath(other))


def _rule_key(value: object) -> str:
    """A rule as it is held against another: its words, with case and spacing aside."""
    return re.sub(r"\s+", " ", value if isinstance(value, str) else "").strip().casefold()


def _how_to_use(agent: store.Agent) -> str:
    """One plain line on using a helper they already have."""
    if parts.is_switchable(agent):
        return "It works while it's switched on in your helpers list."
    return f'To ask it something, start your message with "{agent.name}:".'


def _unquoted(text: str) -> str:
    """Text without the quotes a model wrapped it in. Only a pair around the whole of it: a
    quote at one end may be part of what is said."""
    for opens, closes in ('""', "“”", "''"):
        if len(text) > 1 and text[0] == opens and text[-1] == closes and closes not in text[1:-1]:
            return text[1:-1].strip()
    return text


def _one_line(value: object, limit: int) -> str:
    text = _unquoted(re.sub(r"\s+", " ", value if isinstance(value, str) else "").strip())
    return text[:limit].rstrip()


def _note_shown(value: object) -> str:
    """What would be written about a file, as one line of a try-out: its lines one after
    the other, and when that is long, as much of it as fits, cut at the end of a word."""
    text = " ".join(line.strip() for line in (value if isinstance(value, str) else "").splitlines() if line.strip())
    if len(text) <= NOTE_SHOWN:
        return text
    cut = text[:NOTE_SHOWN]
    return cut[:max(cut.rfind(" "), NOTE_SHOWN // 2)].rstrip(" ,;:") + "..."


def _name(value: object) -> str:
    """A helper's name as it is kept: one short line. No colon, since a helper asked in the
    chat is asked by its name and a colon."""
    text = _one_line(value, 200).replace(":", " ")
    return re.sub(r"\s+", " ", text).strip()[:MAX_NAME].strip()


def _outcome(row: dict, then: str) -> str:
    """What came out for one file, to tell a changed outcome by: where it went ("" when it
    stays), or what would be written about it."""
    return _note_shown(row.get("note")) if then == parts.NOTE else str(row.get("choice") or "")


def _outcome_said(row: dict, then: str) -> str:
    """What came out for one file, with no word that comes from the file."""
    if then == parts.NOTE:
        return "A note would be written" if _note_shown(row.get("note")) else "Nothing would be written"
    if not row.get("choice"):
        return "Left where it is"
    return "Into a new folder" if row.get("new") else f"Into {row['choice']}"


def _ending(row: dict) -> str:
    ending = row.get("ending")
    if not (isinstance(ending, str) and ending):
        ending = Path(str(row.get("name") or "")).suffix
    return ending.lower() or "no ending"


def _holds(folder: Path) -> str:
    """One line on what a folder holds right now (builder.files_in), the folder said by name:
    a folder outside the places people name is given there as its whole path, which has the
    user's name in it."""
    line = files_in(folder)
    whole = str(folder)
    return parts.shown_place(folder) + line[len(whole):] if line.startswith(whole) else line


def _helper_line(agent: store.Agent, rule: bool = True) -> str:
    """A helper they already have, in one line: its name, when it works, and the start of
    its rule. `rule`: False for a model off this computer, which reads the name and the
    WHEN only: a rule is the user's own words about their own things, and one worked out
    with a model on this computer was never meant to leave it."""
    slots = agent.slots
    folder = f" ({parts.shown_place(Path(slots['folder']))})" if slots.get("folder") else ""
    if agent.blueprint == parts.DOCUMENTS_QA:
        return f"{agent.name}: {parts.IN_CHAT} — {parts.DOCUMENTS}{folder}"
    if agent.blueprint != parts.CUSTOM:
        return agent.name
    line = f"{agent.name}: {slots.get('when') or parts.WHILE_ON}{folder}"
    said = re.sub(r"\s+", " ", str(slots.get("instruction") or "")).strip()[:80]
    return f"{line} — {said}" if rule and said else line
