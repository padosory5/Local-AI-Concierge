"""The conversation that sets an agent up, with a model in it.

Until now code asked a blueprint's questions in order and a small model reworded each
line without seeing the chat, so nobody was really talking: "Inside that folder is
simplest" once came back as "inside the Sorted Folders folder", a folder that doesn't
exist. Here one model, the conductor, reads the whole setup so far, what code knows about
this computer and the draft as code has checked it, and fills one form: what it now
understands for each setting, whether something is still missing, and what to say.

The model talks and proposes; it decides nothing. Code checks every value it gives
(AgentBuilder._take_form: a folder must exist, a place must be one this computer has),
keeps the draft, shows the card when nothing is missing, and only the card makes the
agent. Four local models were tried on one setup (10 Nov 2026): all of them talked
naturally and three decided wrongly (switched it on with no yes, said they would move a
bank statement), so a model's word that something is ready or on is never taken for it.

Who conducts is the engine's choice (NoirEngine._conductor): the plan or key model when
one is picked, else a local model that passed conductor_eval and fits beside Noir's own,
else nobody, and the builder asks its plain questions as before.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..noir import CLOSING_FILLER
from ..ollama import Ollama, OllamaError
from .blueprint import Blueprint, Slot

# What the model may say about where the setup stands. Code checks each one: "nothing
# missing" with something missing is asked again, and none of them creates anything.
STILL_ASKING, NOTHING_MISSING, CALLED_OFF, MOVED_ON = "asking", "ready", "cancel", "other"
CONDUCT = "conduct"  # the id of a question that is about no setting in particular
# The places a form can name. A place is an enum, never free text, so a model can't
# misspell one or invent a path; only a new folder's own name is free.
PLACE_NAMES = ["Desktop", "Documents", "Downloads", "Pictures"]
INSIDE = "inside the watched folder"
# Text settings that say where new folders go: a place and a folder to make there, which
# need not exist yet. (Until agents are specs of their own, the key says so.)
PLACE_SLOTS = {"into"}
CONDUCT_CONTEXT = 8192  # a whole setup read about 2,000 tokens in the probe; room to spare
CONDUCT_TEMPERATURE = 0.4  # at 0 a model asked "Shall I turn this on now?" in the same words every turn
CONDUCT_KEEP_ALIVE = "3m"  # between two turns of one setup; freed as soon as the setup ends
MAX_TURNS = 24  # of the setup's own conversation the model reads
MAX_SAY = 600
VOICE = (
    'You are Noir, a helper that lives on this person\'s computer. You speak as "I", in plain everyday words, warm '
    "and short, the way a capable friend would. No technical words, no lists, no emoji, no greeting, and never an "
    'opening offer to help ("I can certainly help with that"): start with what you have to say. One or two '
    "sentences, and at most one question. Reply in the language they write in."
)
HOW_TO_CONDUCT = (
    "They are not technical. Work it out with them the way a person would: understand what they want, use what is "
    "already known instead of asking for it again, and ask only for what you cannot sensibly guess. When you do "
    "guess, say what you assumed. If they answer something you did not ask, take it. If they ask you something, "
    "answer it from HOW IT WORKS, then carry on. Never say it is on, started, created or done: only they can "
    "create it, with the button on the card that appears below your words once nothing needed is missing."
)
FORM_NOTE = (
    "Fill in the form.\n"
    "- Each setting: what you now understand. Leave it empty if they have not said and you would only be guessing "
    "blindly; a setting that is already known stays as it is when you leave it empty.\n"
    f'- status: "{STILL_ASKING}" while something needed is still not known, or when you are answering a question '
    f'of theirs; "{NOTHING_MISSING}" when nothing needed is missing'
    "{more_status}.\n"
    "- asks: the setting your question is about, or empty when you ask nothing.\n"
    "- say: your words to them, written last. {ready_say}"
)
# What to say with nothing missing: the first time, the card is new; after that it is on
# their screen already, and told to point at its button each time, a model did, in every
# answer ("...your CV will stay where it is. The card below has the button to create it.").
CARD_COMES = (f'With "{NOTHING_MISSING}", sum it up in one or two sentences and tell them the card below has the '
              "button to create it.")
CARD_IS_UP = ("The card is already on their screen: only answer them, or say what you changed, in a sentence or "
              "two. Say nothing about the card or its button.")
# "I can certainly help you with that." A model opens with it however it is told not to,
# so code takes it off, as voice.OPENER does for chat answers. Only an offer that says
# nothing: "I can watch your Downloads folder" stays.
OPENING_OFFER = re.compile(
    r"^(?:(?:sure|certainly|of course|absolutely|okay|ok|great|got it)[!.,]\s*)?"
    r"(?:i (?:can|could|will|would)|i'll|i'd)(?: certainly| definitely| gladly| happily| absolutely)? "
    r"(?:help(?: you)?(?: with (?:that|this))?(?: set (?:that|this|it) up)?|do (?:that|this|it)|set (?:that|this|it) up|"
    r"make (?:that|one)|handle (?:that|this|it)|take care of (?:that|this|it))(?: for you)?[.!]\s+(?=\S)",
    re.IGNORECASE)
MORE_STATUS = (f'; "{CALLED_OFF}" if they no longer want it; "{MOVED_ON}" if their message has nothing to do with '
               "setting this up")
# "Shall we begin?" at the end of an answer at the card: only the button begins anything,
# and a yes to it would be taken for an answer to a question instead of a yes to the card.
CLOSING_NUDGE = re.compile(r"^(shall|should|can) (we|i) (begin|start|get started|go ahead|get going)\b[^.!?]*\?$", re.IGNORECASE)
JSON_ONLY = "Reply with one JSON object and nothing else, matching this JSON Schema exactly:"

# (the note for the model, the setup's conversation, the form's schema) -> the filled form
Form = Callable[[str, list[dict], dict], dict]


class ConductorError(Exception):
    """The conductor couldn't take its turn; the builder goes back to its plain questions."""


@dataclass
class Turn:
    values: dict = field(default_factory=dict)  # what it understands for each setting, unchecked
    status: str = STILL_ASKING
    asks: str = ""  # the setting its question is about
    say: str = ""


class Conductor:
    """One model that takes the turns of a setup. `here`: it runs on this computer."""

    def __init__(self, form: Form, name: str, here: bool, loaded: Callable[[], bool] | None = None,
                 release: Callable[[], None] | None = None):
        self.form, self.name, self.here = form, name, here
        self._loaded, self._release = loaded, release

    def turn(self, blueprint: Blueprint, known: list[tuple[str, str]], facts: list[str], turns: list[dict],
             problems: list[str] = (), first: bool = False, card_up: bool = False) -> Turn:
        """One turn: the model reads the note and the conversation, and fills the form.
        `card_up`: the card is on the user's screen already."""
        schema = schema_for(blueprint, first)
        filled = self.form(note_for(blueprint, known, facts, problems, first, card_up), turns[-MAX_TURNS:], schema)
        if not isinstance(filled, dict):
            raise ConductorError("it didn't fill in the form")
        status = filled.get("status")
        allowed = schema["properties"]["status"]["enum"]
        asks = filled.get("asks") if isinstance(filled.get("asks"), str) else ""
        return Turn(values={slot.key: filled.get(slot.key) for slot in blueprint.slots},
                    status=status if status in allowed else STILL_ASKING,
                    asks=asks if blueprint.slot(asks) else "", say=tidy_say(filled.get("say")))

    def waking(self) -> bool:
        """Whether its model still has to be loaded, so the first turn takes a while."""
        if self._loaded is None:
            return False
        try:
            return not self._loaded()
        except OllamaError:
            return False

    def done(self) -> None:
        """The setup is over: a local model leaves the graphics memory at once."""
        if self._release is not None:
            try:
                self._release()
            except Exception:  # noqa: BLE001 - Ollama already stopped: nothing is loaded
                pass


def tidy_say(said: object) -> str:
    """The model's words as one clean paragraph: no wrapping quotes, no line breaks, not endless."""
    text = re.sub(r"\s+", " ", said if isinstance(said, str) else "").strip()
    text = re.sub(r'^["“”]+|["“”]+$', "", text).strip()
    rest = OPENING_OFFER.sub("", text, count=1)
    if rest != text:
        text = rest[:1].upper() + rest[1:]
    # A closing offer ("Is there anything else you would like to change before we begin?")
    # comes off too, as in chat answers: it asks nothing, and a question at the card makes
    # the next yes an answer to it instead of a yes to the card.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    while len(sentences) > 1 and (CLOSING_FILLER.match(sentences[-1]) or CLOSING_NUDGE.match(sentences[-1])):
        sentences.pop()
    text = " ".join(sentences)
    if len(text) > MAX_SAY:
        cut = text[:MAX_SAY]
        text = cut[:max(cut.rfind(". "), cut.rfind("? ")) + 1] or cut
    return text


def field_for(slot: Slot) -> dict:
    """The form field for one setting: a choice is an enum, a folder is a place and a name,
    and only what must be free (a folder's own name, a list of names) is free text."""
    if slot.type == "folder" or slot.key in PLACE_SLOTS:
        places = ["", *([INSIDE] if slot.key in PLACE_SLOTS else []), *PLACE_NAMES]
        return {"type": "object", "properties": {"place": {"enum": places}, "name": {"type": "string"}},
                "required": ["place", "name"]}
    if slot.type == "choice" and slot.choices:
        return {"enum": ["", *slot.choices]}
    return {"type": "string"}


def schema_for(blueprint: Blueprint, first: bool = False) -> dict:
    """The form for a blueprint: every setting, then where things stand, then the words,
    in that order, so what it says agrees with what it filled in. On the first turn the
    request can't be "something else" or "never mind": it is what started the setup."""
    properties = {slot.key: field_for(slot) for slot in blueprint.slots}
    statuses = [STILL_ASKING, NOTHING_MISSING] + ([] if first else [CALLED_OFF, MOVED_ON])
    properties["status"] = {"enum": statuses}
    properties["asks"] = {"enum": ["", *(slot.key for slot in blueprint.slots)]}
    properties["say"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties)}


def needed(slot: Slot) -> bool:
    """A setting the agent can't be made without: it has a question and no usual value."""
    return bool(slot.ask) and not slot.default


def _how_to_fill(slot: Slot) -> str:
    places = ", ".join(PLACE_NAMES)
    # No example of a folder's name in either: given one ("like College"), a model offered
    # it to the user as if it were theirs, and a smaller one filled it in as the answer.
    if slot.key in PLACE_SLOTS:
        return (f'This may be a new folder, which is made for them. `place` is "{INSIDE}" or one of {places}; `name` '
                "is a new folder to make there, or empty for none. Both empty if they have not said.")
    if slot.type == "folder":
        return (f"This must be a folder that already exists. `place` when they name one of {places}; `name` for any "
                "other existing folder, as they wrote it (its name or its full path). Both empty if they have not said.")
    if slot.type == "choice" and slot.choices:
        usual = f" Usually: {slot.default}." if slot.default else ""
        return "One of: " + "; ".join(slot.choices) + "." + usual
    if slot.choices:
        return f'In their words, or exactly "{slot.choices[0]}".'
    return "In their words."


def note_for(blueprint: Blueprint, known: list[tuple[str, str]], facts: list[str], problems: list[str] = (),
             first: bool = False, card_up: bool = False) -> str:
    """Everything the model is told for one turn. Built again each turn from what code has
    checked, so the model never has to remember the draft: it reads it."""
    lines = [VOICE, "", f"You are setting up a helper with them: {blueprint.name}. {blueprint.pitch.strip()}",
             HOW_TO_CONDUCT, "", "HOW IT WORKS (all true; promise nothing beyond this)"]
    lines += [f"- {fact}" for fact in blueprint.extra.get("facts", [])]
    lines += ["", "ITS SETTINGS"]
    for slot in blueprint.slots:
        what = (slot.ask or "What to call it. Leave empty for the usual name.").strip()
        mark = "needed" if needed(slot) else "optional"
        lines.append(f"- {slot.key} ({slot.label}, {mark}): {what} {_how_to_fill(slot)}")
    lines += ["", "KNOWN SO FAR (checked by code)"]
    lines += [f"- {label}: {value}" for label, value in known]
    lines += ["", "ABOUT THIS COMPUTER (read by code just now)"]
    lines += [f"- {fact}" for fact in facts]
    if problems:
        lines += ["", "PROBLEMS WITH YOUR LAST FORM (put them right in this one, and tell them if they need to know)"]
        lines += [f"- {problem}" for problem in problems]
    lines += ["", FORM_NOTE.format(more_status="" if first else MORE_STATUS,
                                   ready_say=CARD_IS_UP if card_up else CARD_COMES)]
    return "\n".join(lines)


def local_form(ollama: Ollama, tag: str) -> Form:
    """A form filled by a model on this computer, forced into the schema by Ollama."""
    think = None

    def form(note: str, turns: list[dict], schema: dict) -> dict:
        nonlocal think
        try:
            if think is None:  # a thinking model left to itself thinks first, and a turn takes ten times as long
                think = "thinking" in ollama.capabilities(tag)
            return ollama.chat_json(tag, [{"role": "system", "content": note}, *turns], schema,
                                    think=False if think else None, keep_alive=CONDUCT_KEEP_ALIVE,
                                    options={"num_ctx": CONDUCT_CONTEXT, "temperature": CONDUCT_TEMPERATURE})
        except OllamaError as exc:
            raise ConductorError(str(exc)) from exc

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
        except Exception as exc:  # noqa: BLE001 - signed out, used up, no internet: whatever it was, the plain questions take over
            raise ConductorError(str(exc)) from exc
        return read_form(text)

    return form


def read_form(text: str) -> dict:
    """The JSON object in a model's reply, with or without a code fence around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ConductorError("it answered without the form")
    try:
        filled = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise ConductorError("its form couldn't be read") from exc
    if not isinstance(filled, dict):
        raise ConductorError("its form couldn't be read")
    return filled
