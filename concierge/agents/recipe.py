"""Agents made from parts: when it works, what it works on, what it does with
the text, and how it shows the result.

There is no code per kind of agent. What an agent does is one instruction
Noir writes ("Explain this English word in simple Korean, with one
example."), and run_instruction() applies it to whatever text comes in,
whether highlighted (quick/agents.py) or sent in the chat (engine.py). The
model writes and rewrites instructions; code decides everything else.
"""

from __future__ import annotations

from pathlib import Path
import re

from ..noir import KEEP_ALIVE
from ..ollama import Ollama, OllamaError
from ..quick.agents import BOTH, BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT
from ..quick.translate import language_in
from . import store
from .blueprint import Blueprint

CUSTOM = "custom"
WHILE_ON, IN_CHAT = "While it's switched on", "When you ask in the chat"
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
# What an agent can be tried with on its page.
SAMPLE_TEXT = "The committee reached a quorum, so the motion carried."
SAMPLE_QUESTION = "What are these files about?"
MECHANICS = re.compile(r"highlight|display|above|bubble|\bwhen i\b|\bwhenever\b|clipboard|하이라이트", re.IGNORECASE)

# Worked examples, because small models follow examples far better than rules.
_EXAMPLES = """Examples:
"translate what I highlight into Korean" ->
{"name": "Korean translator", "instruction": "Translate the text into Korean.", "example": "The meeting moved to Thursday at 3 pm."}
"explain hard English words I highlight, simply, in Korean" ->
{"name": "Word explainer", "instruction": "Explain what this English word or phrase means in simple Korean, in one or two sentences, with one short example sentence.", "example": "serendipity"}
"fix the grammar of what I write" ->
{"name": "Grammar fixer", "instruction": "Correct the grammar and spelling of the text. Keep its meaning and tone.", "example": "me and him goes to the store yesterday"}"""


def describe(agent) -> dict:
    """What an agent's page shows, in the user's words: what it does, how it's
    set up, and something to try it with."""
    slots = agent.slots
    if agent.blueprint == "documents_qa":
        files = len(agent.contents)
        return {"does": "Answers questions about your files, and shows which file each answer came from.",
                "facts": [["Reads", Path(slots.get("folder", "")).name or "Your files"],
                          ["Knows", f"{files} file{'' if files == 1 else 's'}"],
                          ["How it answers", "In the chat"], ["Runs on", "This computer"]],
                "sample": SAMPLE_QUESTION}
    when = slots.get("when", WHILE_ON)
    facts = [["When it works", when]]
    if when == WHILE_ON:
        facts += [["How it answers", slots.get("show", "A bubble above the text")],
                  ["How long it stays", slots.get("keep", "Until you unhighlight the text")]]
    else:
        facts.append(["How it answers", "In the chat"])
    facts.append(["Runs on", "This computer"])
    return {"does": slots.get("instruction", ""), "facts": facts, "sample": SAMPLE_TEXT}


def run_instruction(ollama: Ollama, model: str, instruction: str, text: str,
                    think: bool | None = None) -> str:
    """Do the agent's job on one piece of text and return only the result."""
    system = (f"{instruction.strip()}\n\nYou are given a piece of text. Reply with the result only: "
              "no quotes around it, no notes, no explanation of what you did.")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    chunks = ollama.chat(model, messages, think=think, options={"temperature": 0.3}, keep_alive=KEEP_ALIVE)
    return "".join(chunks).strip()


def target_language(instruction: str) -> str | None:
    """For a translating agent, the language it translates into; else None.
    Used to skip text that is already in that language."""
    if not re.search(r"translat|번역", instruction, re.IGNORECASE):
        return None
    return language_in(instruction, target_only=True) or language_in(instruction)


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


def needs_language(instruction: str) -> bool:
    """A translating instruction that does not say into which language."""
    return bool(re.search(r"translat|번역", instruction, re.IGNORECASE)) and target_language(instruction) is None


def with_language(instruction: str, language: str) -> str:
    """The instruction with its target language filled in."""
    if re.match(r"\s*translate", instruction, re.IGNORECASE):
        return f"Translate the text into {language}."
    return f"{instruction.rstrip('.')}. Reply in {language}."


def is_switchable(agent: store.Agent, blueprints: dict[str, Blueprint]) -> bool:
    """Works outside the chat while switched on (rather than being asked in it)."""
    if agent.blueprint == CUSTOM:
        return agent.slots.get("when", WHILE_ON) == WHILE_ON
    blueprint = blueprints.get(agent.blueprint)
    return bool(blueprint and blueprint.switchable)


def migrate() -> list[str]:
    """Turn agents of the retired "Highlight translator" blueprint into agents
    made from parts, keeping their settings. Returns the names changed."""
    changed = []
    for agent in store.list_agents():
        if agent.blueprint != "translate_selection":
            continue
        slots = agent.slots
        agent.blueprint = CUSTOM
        agent.slots = {
            "instruction": f"Translate the text into {slots.get('language', 'English')}.",
            "when": WHILE_ON,
            "show": slots.get("show", "A bubble above the text"),
            "keep": slots.get("keep", "Until you unhighlight the text"),
            "name": agent.name,
        }
        store.save(agent)
        changed.append(agent.name)
    return changed


def _clean(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip("\"'")
    return text[:limit]
