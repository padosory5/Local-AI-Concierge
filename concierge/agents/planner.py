"""Talk an agent idea through with the user before anything is built.

The user describes a helper they would like ("translate what I highlight
when I press Ctrl+F1"). Elaina's model only breaks the idea into building
blocks from capabilities.yaml. Code then decides, from the blocks and this
computer's hardware:

    - is it easy (Elaina's own model or plain code), does it need a bigger
      model, and does that model fit on this computer?
    - can the app build it today, is it planned but not built yet, or is it
      something the app will not do?

The answer is an IdeaCard. The user can make it (when every block is
ready), save it to their ideas list, change it, or drop it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from ..catalog import HelperModel, pick_helper
from ..elaina import data_dir
from ..events import Event, IdeaCard, IdeaStep, Question, Thinking
from ..hardware import HardwareReport
from ..ollama import Ollama
from .builder import say
from .recipe import COPY_WORDS

BLOCKS_PATH = Path(__file__).with_name("capabilities.yaml")
OTHER = "other"
MAX_STEPS = 6

IDEA, IDEA_CHANGE = "idea", "idea_change"
# "Ctrl+F", "control + shift + T", "Alt-F4": a key combination in a message.
KEY_COMBO = re.compile(r"\b(ctrl|control|alt|shift|win|cmd)\s*[+\-]\s*\w+", re.IGNORECASE)
MAKE_IT, SAVE_IDEA, CHANGE_IDEA, DROP_IDEA = "Make it", "Save the idea", "Change the idea", "Cancel"

# What each kind of AI need is called on the card, and which helper role covers it.
HELPER_ROLES = {"large": "general", "vision": "vision", "speech": "speech"}
ROLE_WORDS = {"general": "a bigger all-round model", "vision": "a model that understands images",
              "speech": "a speech-to-text model"}


@dataclass(frozen=True)
class Block:
    id: str
    kind: str  # "trigger", "input", "action" or "output"
    name: str
    ai: str  # "none", "small", "large", "vision" or "speech"
    status: str  # "ready", "planned" or "unsupported"
    note: str = ""


@dataclass(frozen=True)
class PlanStep:
    block: Block | None  # None: a part no building block covers
    detail: str = ""


@dataclass
class Assessment:
    level: str  # "ready", "not_built", "too_big", "not_possible" or "unclear"
    steps: list[IdeaStep]
    difficulty: str
    verdict: str
    actions: list[str]
    blueprint: str | None = None
    helpers: list[HelperModel] = field(default_factory=list)


def load_blocks(path: Path = BLOCKS_PATH) -> dict[str, Block]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {key: Block(id=key, **spec) for key, spec in data["blocks"].items()}


# ------------------------------------------------------------- judging


def assess(steps: list[PlanStep], report: HardwareReport, elaina_gb: float,
           blueprints: dict | None = None) -> Assessment:
    """Decide what is possible. Plain code: the model never judges itself.

    blueprints: the agent types that exist. An idea can be made when one of
    them is built from at least every block the idea needs.
    """
    card_steps = [_card_step(s) for s in steps]
    blocks = [s.block for s in steps if s.block]
    unsupported = [b for b in blocks if b.status == "unsupported"]
    unknown = [s for s in steps if s.block is None]
    # A helper must do something: an action, or at least an output like
    # "put the screenshot on the clipboard". Only a trigger is not a helper.
    does_something = [b for b in blocks if b.kind in ("action", "output")]

    if unsupported:
        b = unsupported[0]
        return Assessment("not_possible", card_steps, "", f"I can't make this. {b.name}: {b.note}",
                          [CHANGE_IDEA, DROP_IDEA])
    if unknown or not does_something:
        what = f'"{unknown[0].detail}"' if unknown and unknown[0].detail else "what it should do"
        return Assessment("unclear", card_steps, "",
                          f"I'm not sure how to do {what} yet. Tell me more, or put it a different way.",
                          [CHANGE_IDEA, DROP_IDEA])

    difficulty, helpers, too_big = _difficulty(blocks, report, elaina_gb)
    if too_big:
        return Assessment("too_big", card_steps, difficulty,
                          "This computer can't run that part. It could work on one with more graphics memory.",
                          [SAVE_IDEA, CHANGE_IDEA, DROP_IDEA], helpers=helpers)

    missing = [b for b in dict.fromkeys(blocks) if b.status != "ready"]
    if missing:
        names = ", ".join(f'"{b.name}"' for b in missing)
        return Assessment(
            "not_built", card_steps, difficulty,
            f"Your computer can do this, but the app can't build it yet: {names} "
            f"{'is' if len(missing) == 1 else 'are'} not built. Save the idea, and the most "
            "wanted parts get built first.",
            [SAVE_IDEA, CHANGE_IDEA, DROP_IDEA], helpers=helpers,
        )
    needed = {b.id for b in blocks} - {"on_request"}  # any agent can be asked in the chat
    blueprint = next((bp.id for bp in (blueprints or {}).values() if needed <= set(bp.blocks)), None)
    if blueprint is None:
        return Assessment("not_built", card_steps, difficulty,
                          "Every part exists, but no agent puts them together this way yet. Save the "
                          "idea, and it can be built from the parts already there.",
                          [SAVE_IDEA, CHANGE_IDEA, DROP_IDEA], helpers=helpers)
    return Assessment("ready", card_steps, difficulty, "I can make this now.",
                      [MAKE_IT, CHANGE_IDEA, DROP_IDEA], blueprint, helpers)


def _difficulty(blocks: list[Block], report: HardwareReport, elaina_gb: float
                ) -> tuple[str, list[HelperModel], bool]:
    """(sentence for the card, helper models it needs, whether one does not fit)."""
    roles = list(dict.fromkeys(HELPER_ROLES[b.ai] for b in blocks if b.ai in HELPER_ROLES))
    if not roles:
        if all(b.ai == "none" for b in blocks):
            return "Easy: plain code, no AI model needed.", [], False
        return "Easy: Elaina's own model can do this, nothing extra to download.", [], False

    helpers, sentences = [], []
    for role in roles:
        helper, room, on_cpu = pick_helper(role, report, elaina_gb)
        if helper is None:
            return (f"Too big for this computer: it needs {ROLE_WORDS[role]}, and only "
                    f"{max(room, 0):g} GB is free next to Elaina."), helpers, True
        helpers.append(helper)
        slow = " It would run on the processor, so expect it to be slow." if on_cpu and role != "speech" else ""
        sentences.append(f"{helper.name} ({helper.download_gb:g} GB download, about {helper.memory_gb:g} GB "
                         f"of memory while it works).{slow}")
    return ("Needs a bigger model: " + " ".join(sentences)
            + " Your computer has room for it next to Elaina."), helpers, False


# Words that show the user really asked for a shortcut key.
ASKED_FOR_KEY = re.compile(r"shortcut|hot ?key|key|press|ctrl|control \+|alt|단축", re.IGNORECASE)


def settle_triggers(steps: list[PlanStep], request: str, blocks: dict[str, Block]) -> list[PlanStep]:
    """Fix the trigger the model picked, where code can tell better.

    The model adds a shortcut key to ideas like "explain words I highlight"
    although the user named none, and "what you copied" to "fix sentences I
    paste here". Highlighted text with no key asked for
    works while the helper is switched on; with "when you ask in the chat" it
    could never see a highlight at all.
    """
    ids = [s.block.id if s.block else None for s in steps]
    if "on_request" in ids and "clipboard_in" in ids and "selected_text" not in ids:
        # "fix sentences I paste here": an agent asked in the chat already gets
        # the pasted text as its message; reading the clipboard is not needed.
        return [s for s in steps if not (s.block and s.block.id == "clipboard_in")]
    if "selected_text" not in ids:
        return steps
    settled = []
    for step in steps:
        block_id = step.block.id if step.block else None
        if block_id == "hotkey" and not ASKED_FOR_KEY.search(request):
            step = PlanStep(blocks["while_on"])
        elif block_id == "on_request":
            step = PlanStep(blocks["while_on"])
        elif block_id == "copy_clipboard" and not COPY_WORDS.search(request):
            # Same rule as the agent itself: a highlight helper shows a bubble
            # unless the user asked for copying (recipe.settings_from_words).
            step = PlanStep(blocks["show_popup"])
        settled.append(step)
    if not any(s.block and s.block.kind == "trigger" for s in settled):
        settled.insert(0, PlanStep(blocks["while_on"]))
    return list(dict.fromkeys(settled))  # no step twice


def clean_detail(detail: str, block: Block | None) -> str:
    """Keep a step's detail only when it is a real specific from the user.

    The model sometimes fills it with labels ("audio_to_text"), a copy of the
    block's name, or a long paraphrase of the whole idea.
    """
    detail = (detail or "").strip().strip("\"'")
    if block is None:
        return detail[:80]  # for "other" the detail is the only description
    if not detail or len(detail) > 40 or ("_" in detail and " " not in detail):
        return ""
    if detail.lower() in block.name.lower() or block.name.lower() in detail.lower():
        return ""
    return detail


def _card_step(step: PlanStep) -> IdeaStep:
    if step.block is None:
        return IdeaStep(step.detail or "Something I don't know how to do", "unclear")
    text = step.block.name + (f" ({step.detail})" if step.detail else "")
    status = {"ready": "ready", "planned": "not_built", "unsupported": "not_possible"}[step.block.status]
    return IdeaStep(text, status, step.block.note)


# ------------------------------------------------------------ talking it through


@dataclass
class IdeaDraft:
    request: str
    title: str = ""
    plan: list[dict] = field(default_factory=list)  # the model's last answer, for revisions
    steps: list[PlanStep] = field(default_factory=list)
    assessment: Assessment | None = None
    waiting: str | None = None  # IDEA (the card) or IDEA_CHANGE (a typed change)


class IdeaPlanner:
    def __init__(self, ollama: Ollama, model: str, think: bool | None,
                 hardware: Callable[[], tuple[HardwareReport, float]], blueprints: dict | None = None):
        """hardware() returns this computer's report and Elaina's model memory in GB."""
        self.blueprints = blueprints or {}
        self.ollama = ollama
        self.model = model
        self.think = think
        self.hardware = hardware
        self.blocks = load_blocks()
        self.draft: IdeaDraft | None = None
        self.handoff: str | None = None  # same meaning as AgentBuilder.handoff

    @property
    def active(self) -> bool:
        return self.draft is not None

    def start(self, request: str) -> Iterator[Event]:
        self.draft = IdeaDraft(request)
        yield from self._plan(request)

    def answer(self, text: str) -> Iterator[Event]:
        """Typed text while an idea is open: a change to it, or moving on."""
        if self.draft.waiting == IDEA_CHANGE or self._is_about_idea(text):
            self.draft.request = f"{self.draft.request}\nChange: {text}"
            yield from self._plan(text, revising=True)
        else:
            # The card is up but the user typed something else: they moved
            # on, so the idea is dropped and the engine handles the text.
            self.draft = None
            self.handoff = text

    def choose(self, id: str, choice: str) -> Iterator[Event]:
        draft = self.draft
        if choice == CHANGE_IDEA:
            draft.waiting = IDEA_CHANGE
            yield Question(IDEA_CHANGE, "What should be different?")
        elif choice == SAVE_IDEA:
            count = save_idea(draft)
            self.draft = None
            yield from say(f'Saved "{draft.title}" to your ideas ({count} saved). Say "my ideas" '
                           "to see them; the parts they need most get built first.")
        elif choice == DROP_IDEA:
            self.draft = None
            yield from say("Okay, I've put that idea aside.")
        else:
            yield from say("That question has already been answered.")

    def take_blueprint(self) -> tuple[str, str] | None:
        """For "Make it": (blueprint id, the idea as the user described it), and close the idea."""
        plan = self.take_plan()
        return plan[:2] if plan else None

    def take_plan(self) -> tuple[str, str, list[str]] | None:
        """For an idea that can be made: (blueprint id, the idea as the user
        described it, its building block ids), and close the idea."""
        draft, self.draft = self.draft, None
        if draft and draft.assessment and draft.assessment.blueprint:
            blocks = [s.block.id for s in draft.steps if s.block]
            return draft.assessment.blueprint, draft.request, blocks
        return None

    # ----------------------------------------------------------- model

    def _plan(self, text: str, revising: bool = False) -> Iterator[Event]:
        draft = self.draft
        # Decided in code: asked to use "the user's language", the model
        # titled English ideas in Spanish and Portuguese.
        self._language = "Korean" if re.search(r"[가-힣]", draft.request) else "English"
        messages = [{"role": "system", "content": self._prompt()}]
        if revising:
            messages += [
                {"role": "user", "content": draft.request.split("\nChange: ")[0]},
                {"role": "assistant", "content": json.dumps({"title": draft.title, "steps": draft.plan})},
                {"role": "user", "content": f"Change it: {text}"},
            ]
        else:
            messages.append({"role": "user", "content": text})
        reply = self.ollama.chat_json(self.model, messages, self._schema(), think=self.think)

        draft.title = (reply.get("title") or "New helper").strip()[:60]
        draft.plan = reply.get("steps", [])[:MAX_STEPS]
        draft.steps = []
        for s in draft.plan:
            block = self.blocks.get(s.get("block"))
            detail = clean_detail(s.get("detail", ""), block)
            if PlanStep(block, detail) not in draft.steps:
                draft.steps.append(PlanStep(block, detail))
        draft.steps = settle_triggers(draft.steps or [PlanStep(None, "")], draft.request, self.blocks)
        report, elaina_gb = self.hardware()
        draft.assessment = assess(draft.steps, report, elaina_gb, self.blueprints)
        draft.waiting = IDEA
        a = draft.assessment
        parts = " → ".join(s.text[:1].lower() + s.text[1:] for s in a.steps)
        yield Thinking(f"Broke the idea into parts: {parts}.")
        if a.difficulty:
            yield Thinking(f"Checked this computer. {a.difficulty}")
        yield IdeaCard(IDEA, draft.title, a.steps, a.difficulty, a.verdict, a.level, a.actions)

    def _is_about_idea(self, text: str) -> bool:
        """Is a message typed while the idea card is up a change to that idea?

        People answer the card by typing ("control + F is the shortcut")
        rather than clicking Change the idea. A key combination settles it in
        code; otherwise the model makes a forced choice.
        """
        if KEY_COMBO.search(text):
            return True
        draft = self.draft
        schema = {"type": "object", "properties": {"about": {"enum": ["the idea", "something else"]}},
                  "required": ["about"]}
        system = (f'The user is discussing an idea for a helper: "{draft.title}" '
                  f"({draft.request.splitlines()[0]}). Is their next message a change, detail or answer "
                  'about that helper ("the idea"), or about something else ("something else")?')
        try:
            reply = self.ollama.chat_json(self.model, [{"role": "system", "content": system},
                                                       {"role": "user", "content": text}],
                                          schema, think=self.think)
        except Exception:
            return False
        return reply.get("about") == "the idea"

    def _schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "block": {"enum": [*self.blocks, OTHER]},
                            "detail": {"type": "string"},
                        },
                        "required": ["block", "detail"],
                    },
                },
            },
            "required": ["title", "steps"],
        }

    def _prompt(self) -> str:
        groups = {"trigger": "When it runs", "input": "What it works on",
                  "action": "What it does", "output": "Where the result goes"}
        lines = []
        for kind, heading in groups.items():
            lines.append(f"{heading}:")
            lines += [f'- "{b.id}": {b.name}' for b in self.blocks.values() if b.kind == kind]
        blocks = "\n".join(lines)
        # Small models follow examples far better than rules.
        return f"""The user describes a helper they would like on their computer. Break it into building blocks, in order: when it runs, what it works on, what it does, where the result goes.

{blocks}

Rules:
- Use only the blocks the idea needs. Never add a trigger the user did not ask for: if they did not say when it runs, use "on_request".
- Use a block only if it really does that part. If no block does the main job, use "other" for that part, with a short description as detail.
- detail: only specifics the user actually said for that step, such as a language, a key, a folder or a file type. Usually empty.
- title: a short name for the helper, two to five words, in {self._language}.

Examples:
"When I press Ctrl+Shift+G, fix the grammar of what I highlighted" ->
{{"title": "Grammar fixer", "steps": [{{"block": "hotkey", "detail": "Ctrl+Shift+G"}}, {{"block": "selected_text", "detail": ""}}, {{"block": "rewrite", "detail": "fix grammar"}}, {{"block": "replace_text", "detail": ""}}]}}
"Remind me to drink water every hour" ->
{{"title": "Water reminder", "steps": [{{"block": "schedule", "detail": "every hour"}}, {{"block": "show_popup", "detail": "drink water"}}]}}
"Summarize the reports in my Work folder" ->
{{"title": "Report summarizer", "steps": [{{"block": "on_request", "detail": ""}}, {{"block": "folder_files", "detail": "Work folder"}}, {{"block": "summarize", "detail": ""}}]}}
"Play songs that fit my mood" ->
{{"title": "Mood music", "steps": [{{"block": "on_request", "detail": ""}}, {{"block": "other", "detail": "choose and play music"}}]}}"""

    _language = "English"


# ---------------------------------------------------------------- ideas list


def ideas_path() -> Path:
    return data_dir() / "ideas.json"


def list_ideas() -> list[dict]:
    try:
        return json.loads(ideas_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_idea(draft: IdeaDraft) -> int:
    """Keep the idea with its block ids, so it can be judged again once blocks are built."""
    ideas = list_ideas()
    ideas.append({
        "title": draft.title,
        "request": draft.request,
        "steps": [{"block": s.block.id if s.block else OTHER, "detail": s.detail} for s in draft.steps],
        "saved": datetime.now().isoformat(timespec="seconds"),
    })
    path = ideas_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ideas, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return len(ideas)


def describe_ideas(report: HardwareReport, elaina_gb: float, blueprints: dict | None = None) -> str:
    """The saved ideas, each judged again against today's building blocks."""
    ideas = list_ideas()
    if not ideas:
        return "You have no saved ideas yet. Describe a helper you'd like, and I'll tell you if it can work."
    blocks = load_blocks()
    words = {"ready": "ready to make now", "not_built": "not built yet", "too_big": "too big for this computer",
             "not_possible": "not possible", "unclear": "needs more detail"}
    lines = [f"You have {len(ideas)} saved idea{'s' if len(ideas) != 1 else ''}:"]
    for idea in ideas:
        steps = [PlanStep(blocks.get(s["block"]), s.get("detail", "")) for s in idea["steps"]]
        lines.append(f"- {idea['title']}: {words[assess(steps, report, elaina_gb, blueprints).level]}")
    return "\n".join(lines)
