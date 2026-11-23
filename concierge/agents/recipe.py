"""Agents that work on text: one instruction, done on whatever text comes in.

There is no code per kind of agent. What an agent does with a piece of text is one
instruction in plain words ("Explain this English word in simple Korean, with one
example."), and run_instruction() applies it to whatever text comes in, whether
highlighted (quick/agents.py) or sent in the chat (engine.py). What an agent can be made
of, and how one is shown, is the catalog's (parts.py); this file is what is left for
text: running an instruction, and writing or rewriting one on a computer where no model
can talk an agent through (builder.py). The model writes and rewrites instructions; code
decides everything else.
"""

from __future__ import annotations

import re

from ..noir import KEEP_ALIVE
from ..ollama import Ollama, OllamaError
from ..quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT
from . import parts
# The texts an agent is saved with, and what one is shown and tried with, are the
# catalog's. They are passed on from here because agents, starters and shared recipes have
# always taken them from this file.
from .parts import CUSTOM, IN_CHAT, SAMPLE_QUESTION, SAMPLE_TEXT, WHILE_ON, describe, is_switchable  # noqa: F401

MAX_INSTRUCTION = 300

# What words mean for an agent's settings, decided in code. Users say these
# in many ways; the model guessed them wrong ("highlight" became "answers in
# the chat", "show it above" became "copy it").
HIGHLIGHT_WORDS = re.compile(r"highlight|\bselect|하이라이트|드래그|선택", re.IGNORECASE)
CHAT_WORDS = re.compile(r"in the chat|when i ask|i paste|paste (it )?here|채팅", re.IGNORECASE)
SHOW_WORDS = re.compile(r"bubble|above|on (the )?screen|\bshow|display|pop ?up|위에|보여", re.IGNORECASE)
COPY_WORDS = re.compile(r"clipboard|\bcopy|ready to paste|복사", re.IGNORECASE)
STAY_WORDS = re.compile(r"\bstay|until i unhighlight|disappear|vanish|keep it (up|there)|사라지", re.IGNORECASE)
SHORT_WORDS = re.compile(r"few seconds|after a (few|couple)|go away (by itself|on its own)|quickly", re.IGNORECASE)
# An instruction that describes when or where instead of what to do with the
# text ("When I highlight a sentence it should display it above").
MECHANICS = re.compile(r"highlight|display|above|bubble|\bwhen i\b|\bwhenever\b|clipboard|하이라이트", re.IGNORECASE)

# Worked examples, because small models follow examples far better than rules. None names
# a language or one of the ready-made helpers: a small model copies what it is shown, and
# with a Korean translator first among them, a request that named no language could come
# back translating into Korean.
_EXAMPLES = """Examples:
"make what I write sound more polite" ->
{"name": "Polite rewriter", "instruction": "Rewrite the text so it sounds polite and friendly. Keep its meaning.", "example": "send me the report now"}
"turn what I highlight into a short to-do list" ->
{"name": "To-do maker", "instruction": "Turn the text into a short list of the things to do, one on each line.", "example": "call the bank on Monday and pay the gas bill before Friday"}
"spell out the short forms in what I paste" ->
{"name": "Short form expander", "instruction": "Write the text again with every abbreviation spelled out in full. Change nothing else.", "example": "Pls send the ETA asap."}"""


def run_instruction(ollama: Ollama, model: str, instruction: str, text: str,
                    think: bool | None = None) -> str:
    """Do the agent's job on one piece of text and return only the result."""
    system = (f"{instruction.strip()}\n\nYou are given a piece of text. Reply with the result only: "
              "no quotes around it, no notes, no explanation of what you did.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    chunks = ollama.chat(model, messages, think=think, options={"temperature": 0.3}, keep_alive=KEEP_ALIVE)
    return "".join(chunks).strip()


def write_recipe(ollama: Ollama, model: str, request: str, think: bool | None = None) -> dict:
    """The name, instruction and a test example for the agent the user asked for."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "instruction": {"type": "string"},
                       "example": {"type": "string"}},
        "required": ["name", "instruction", "example"],
    }
    system = (
        "The user wants a small helper on their computer that gets a piece of text (something they "
        "highlight, or send in the chat) and does one job with it. Write three things:\n"
        "- instruction: one or two plain sentences telling a small AI exactly what to do with the "
        "text and what to reply with. Only the job itself: never when it runs, highlighting, bubbles "
        "or where the result goes. Name the output language only if the user said one; never guess one.\n"
        "- name: a short name for the helper, two to four words.\n"
        "- example: a short piece of text the helper might get, to test it.\n\n" + _EXAMPLES
    )
    reply = ollama.chat_json(model, [{"role": "system", "content": system},
                                     {"role": "user", "content": request}], schema, think=think)
    return {
        "name": _clean(reply.get("name"), 40) or "My helper",
        "instruction": _clean(reply.get("instruction"), MAX_INSTRUCTION),
        "example": _clean(reply.get("example"), 200),
    }


def rewrite_instruction(ollama: Ollama, model: str, instruction: str, change: str,
                        think: bool | None = None) -> str | None:
    """The instruction with the user's change in it, or None when the message
    does not change what the agent does."""
    schema = {"type": "object", "properties": {"instruction": {"type": "string"}},
              "required": ["instruction"]}
    system = (
        f'A small helper follows this instruction: "{instruction}"\n'
        "The user asks for a change. If the change is about what the helper does with the text "
        "(the language, the length, the style, the job), write the whole new instruction in one or "
        "two plain sentences. The instruction is only the job done on the text: never mention when "
        "it runs, highlighting, bubbles, the screen or the clipboard. If the change is about "
        "something else (when it works, how the result is shown, its name), repeat the instruction "
        "exactly as it is.\n\n"
        "Examples, for the instruction \"Translate the text into Spanish.\":\n"
        '"When I highlight a sentence it should display it in Korean above" -> '
        '{"instruction": "Translate the text into Korean."}\n'
        '"make it shorter" -> {"instruction": "Translate the text into Spanish, as briefly as possible."}\n'
        '"show it in a bubble" -> {"instruction": "Translate the text into Spanish."}'
    )
    try:
        reply = ollama.chat_json(model, [{"role": "system", "content": system},
                                         {"role": "user", "content": change}], schema, think=think)
    except OllamaError:
        return None
    new = _clean(reply.get("instruction"), MAX_INSTRUCTION)
    if not new or new.lower() == instruction.strip().lower() or MECHANICS.search(new):
        return None  # unchanged, or a description of when and where rather than a job
    return new


def settings_from_words(text: str) -> dict:
    """The settings a message names, decided in code: {"when", "show", "keep"}
    for whichever it talks about."""
    settings = {}
    if HIGHLIGHT_WORDS.search(text):
        settings["when"] = WHILE_ON
    elif CHAT_WORDS.search(text):
        settings["when"] = IN_CHAT
    show, copy = SHOW_WORDS.search(text), COPY_WORDS.search(text)
    if show and copy:
        settings["show"] = BOTH
    elif copy:
        settings["show"] = CLIPBOARD
    elif show:
        settings["show"] = BUBBLE
    if STAY_WORDS.search(text):
        settings["keep"] = UNTIL_UNHIGHLIGHT
    elif SHORT_WORDS.search(text):
        settings["keep"] = FEW_SECONDS
    return settings


def migrate() -> list[str]:
    """Turn the agents of older versions into cards, keeping their settings. Every kind
    there ever was is known in one place only, the catalog (parts.migrate); this passes it
    on, because the engine has always asked here. Returns the names of the agents that
    became cards. (Called at startup, before the agents that were on are brought back.)"""
    return parts.migrate()


def _clean(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip("\"'")
    return text[:limit]
