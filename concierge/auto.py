"""Auto: for each chat message, Elaina decides whether her own model can answer it
or it's worth the user's plan (Claude through Claude Code, ChatGPT through Codex) or
API key. Most of what people ask is small, and every answer from a plan uses part of
it, so the small things stay on this computer.

Asking the plan's model to decide would cost as much as answering: Claude Code reads
about 29k tokens of its own instructions with every question. So the decision never
leaves the computer. Plain code places the clear cases (pasted code, a proof, an essay,
a greeting, a translation) the same on every computer. Only an unclear message goes to
her small model, and only to fill in one word from `KINDS`; code turns that word into
here or the plan. Whether a kind can stay here depends on how big her own model is
(`STAY_HERE`), not on how well it judges. When in doubt, the plan answers: a wasted
question costs a little of the plan, a bad answer costs the user's trust.

The questions this must get right are in auto_cases.yaml.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

HERE, CLOUD = "here", "cloud"
AUTO = "auto"  # the model menu's provider id for Auto
KINDS = ("small_talk", "quick_fact", "rewrite", "suggestion", "explain", "writing", "planning",
         "analysis", "code", "math")
# What her own model answers well enough, by its size. Code, maths and weighing up
# options always go to the plan: a small mistake there is a wrong answer.
SMALL, MEDIUM, LARGE = "small", "medium", "large"
STAY_HERE = {
    SMALL: {"small_talk", "quick_fact", "rewrite", "suggestion"},
    MEDIUM: {"small_talk", "quick_fact", "rewrite", "suggestion", "explain"},
    LARGE: {"small_talk", "quick_fact", "rewrite", "suggestion", "explain", "writing", "planning"},
}
MEDIUM_FROM_B, LARGE_FROM_B = 7, 14  # billions of parameters
NEARLY_OUT = 0.8  # the plan's fullest window: from here, treat her model as one size bigger
USED_UP = 0.98  # from here, everything stays here until the window starts again
LONG_CHARS = 1200  # a message this long is real work
FOLLOW_UP_WORDS = 6
QUICK_WORDS = 14
CASES_PATH = Path(__file__).with_name("auto_cases.yaml")

_I = re.IGNORECASE
SMALL_TALK = re.compile(
    r"^\s*(hi|hello|hey|yo|hiya|thanks?|thank you|thx|ty|ok(ay)?|k|cool|nice|great|awesome|perfect|"
    r"good (morning|night|evening|afternoon)|bye|see (you|ya)|lol|haha|안녕\S*|고마워\S*|감사\S*|ㅋ+|ㅎ+|응|네|좋아\S*)"
    r"([\s,!.~]+[\w']+){0,5}[\s!.~?]*$", _I)
JOKE = re.compile(r"\b(tell me a joke|make me laugh|a fun fact)\b|농담|웃긴", _I)
CODE = re.compile(
    r"```|traceback \(most recent|\b\w*(error|exception):|\bline \d+\b|\bdef \w+\(|\bfunction\s*\w*\(|=>|"
    r"console\.\w+|#include|\bselect .+ from\b|\bfor \w+ in range\b|\bimport \w+|</?\w+>|"
    r"\b(python|javascript|typescript|node\.?js|react|sql|java|c\+\+|c#|rust|golang|html|css|rest api|api|regex|"
    r"script|code|coding|bug|debug|compile|compiler|database|schema|git|docker|json|excel formula)\b|"
    r"코드|에러|오류|함수|리액트|파이썬|자바스크립트|프로그램", _I)
MATH = re.compile(
    r"\b(prove|proof|derive|derivation|integral|integrate|derivative|differentiate|equation|theorem|"
    r"step by step|time complexity|big[- ]o|matrix|eigen\w*|probability that|limit of)\b|증명|적분|미분|방정식", _I)
WRITING = re.compile(
    r"\b(essays?|reports?|cover letter|stor(y|ies)|articles?|blog post|speech|proposal|resume|résumé|"
    r"thesis|papers?|chapter|statement of purpose)\b|\b\d{3,}[- ]words?\b|보고서|에세이|자기소개서|논문|기사", _I)
WRITING_ACT = re.compile(r"\b(write|draft|review|improve|stronger|feedback|edit|help me)\b|써줘|작성|검토|고쳐", _I)
PLANNING = re.compile(
    r"\bplan (a|an|my|the|out)\b|\b(make|create|build|write) (me )?(a|an|my) [\w\s-]{0,24}"
    r"(plan|schedule|itinerary|roadmap|routine)\b|\bday[- ]by[- ]day\b|\bitinerary\b|계획\S* (세워|짜)|일정\S* (짜|세워)", _I)
ANALYSIS = re.compile(
    r"\b(compare|comparison|pros and cons|analy[sz]e|analysis|evaluate|trade-?offs?|"
    r"which (one )?(should i|to) (buy|choose|pick))\b|장단점|비교|분석", _I)
EXPLAIN = re.compile(r"\b(explain|describe|summari[sz]e|walk me through)\b|설명", _I)
DEEP = re.compile(
    r"\b(in detail|difference between|why|how .{1,40} works?|with examples|arguments?|objections?|"
    r"in depth|thoroughly|history of)\b|자세히|이유|차이", _I)
REWRITE = re.compile(
    r"\b(translate|translation|rewrite|rephrase|paraphrase|proofread|reword|synonyms?|antonyms?)\b|"
    r"^\s*(fix|correct) (the |my )?(grammar|spelling|wording)|\bmake (this|it) (shorter|longer|simpler|"
    r"clearer|more \w+|less \w+)\b|번역|맞춤법|다듬어|고쳐줘", _I)
QUICK = re.compile(
    r"^\s*(what('s)?|who|when|where|which|how (many|much|long|old|far|tall|big|"
    r"do (you|i) spell)|is|are|was|were|does|do|did|can|should)\b|\bconvert\b|\bhow many \w+ (in|are in)\b|\bspell\b", _I)
SUGGESTION = re.compile(
    r"\b(suggest|recommend|ideas? for|a name for|names for)\b|\bwrite (me )?(a |an )?(short|quick|little|one[- ]line|"
    r"cute|funny)\b|\b(message|text|caption|toast|card|tweet|reply|note) (for|to)\b|추천|메시지", _I)
REFERS_BACK = re.compile(
    r"\b(it|that|this|those|these|why|how come|more|again|continue|go on|another|example|shorter|longer|"
    r"simpler|elaborate)\b|그거|이거|왜|더|계속", _I)
WORDS = re.compile(r"\S+")


@dataclass(frozen=True)
class Decision:
    where: str  # HERE or CLOUD
    kind: str  # from KINDS, or "follow_up" / "used_up"
    by: str  # what decided: "code", "model", "follow-up", "unsure" or "limit"


def strength(base_model: str) -> str:
    """How much her own model can take on, from its size in the tag ("qwen3.5:4b").
    Unknown counts as small: then more goes to the plan, never less."""
    found = re.search(r"(\d+(?:\.\d+)?)b\b", base_model.lower())
    size = float(found.group(1)) if found else 0
    return LARGE if size >= LARGE_FROM_B else MEDIUM if size >= MEDIUM_FROM_B else SMALL


def bigger(level: str) -> str:
    return {SMALL: MEDIUM, MEDIUM: LARGE}.get(level, LARGE)


def kind_by_code(text: str) -> str | None:
    """The kind of a clear message, decided by its words alone, or None."""
    words = len(WORDS.findall(text))
    if SMALL_TALK.match(text) or JOKE.search(text):
        return "small_talk"
    if CODE.search(text):
        return "code"
    if MATH.search(text):
        return "math"
    if WRITING.search(text) and WRITING_ACT.search(text):
        return "writing"
    if PLANNING.search(text):
        return "planning"
    if ANALYSIS.search(text):
        return "analysis"
    if EXPLAIN.search(text) and (DEEP.search(text) or words > QUICK_WORDS):
        return "explain"
    if len(text) > LONG_CHARS:
        return "writing"  # a long message is real work, whatever it asks
    if REWRITE.search(text):
        return "rewrite"
    if SUGGESTION.search(text) and words <= QUICK_WORDS + 4:
        return "suggestion"
    if QUICK.search(text) and words <= QUICK_WORDS and not DEEP.search(text):
        return "quick_fact"
    return None


def decide(text: str, *, base_model: str = "", after: str = "", plan_used: float = 0.0,
           attached_chars: int = 0, ask_model=None) -> Decision:
    """Where this message is answered.

    after: what Auto chose for the message before, for "why?" and "go on".
    plan_used: the fullest window of the plan (0 to 1, usage.py), 0 for a key.
    attached_chars: words added with the + button.
    ask_model: fills the form for an unclear message, text -> kind; None for code only.
    """
    if plan_used >= USED_UP:
        return Decision(HERE, "used_up", "limit")
    level = strength(base_model)
    if plan_used >= NEARLY_OUT:
        level = bigger(level)
    if attached_chars > LONG_CHARS * 3:
        return Decision(CLOUD, "analysis", "code")  # a whole document to read
    kind = kind_by_code(text)
    if kind == "small_talk":
        return Decision(HERE, kind, "code")
    words = len(WORDS.findall(text))
    if after in (HERE, CLOUD) and words <= FOLLOW_UP_WORDS and (kind is None or REFERS_BACK.search(text)):
        return Decision(after, "follow_up", "follow-up")  # stays with whoever answered before
    by = "code"
    if kind is None:
        try:
            kind = ask_model(text) if ask_model else None
        except Exception:
            kind = None
        by = "model"
        if kind not in KINDS:
            return Decision(CLOUD, "unclear", "unsure")
    return Decision(HERE if kind in STAY_HERE[level] else CLOUD, kind, by)


HERE_WORDS = {
    "small_talk": "Auto: just chatting, so I'll answer myself.",
    "quick_fact": "Auto: a quick question, so I'll answer it myself and save your {saving}.",
    "rewrite": "Auto: a small job on your words, so I'll do it myself and save your {saving}.",
    "suggestion": "Auto: a few quick ideas, so I'll answer myself and save your {saving}.",
    "follow_up": "Auto: this follows on from my last answer, so I'll answer myself.",
    "used_up": "Auto: your plan is nearly used up for now, so I'll answer myself.",
}
CLOUD_WORDS = {
    "code": "Auto: this is about code, so I'll ask {cloud}.",
    "math": "Auto: this takes careful steps, so I'll ask {cloud}.",
    "writing": "Auto: this is a bigger piece of writing, so I'll ask {cloud}.",
    "planning": "Auto: a good plan takes careful thought, so I'll ask {cloud}.",
    "analysis": "Auto: weighing this up well needs a bigger model, so I'll ask {cloud}.",
    "explain": "Auto: this needs a careful explanation, so I'll ask {cloud}.",
    "follow_up": "Auto: this follows on from {cloud}'s answer, so I'll ask it again.",
    "unclear": "Auto: I'm not sure this is a small one, so I'll ask {cloud} to be safe.",
}


def say(decision: Decision, cloud: str, plan: bool = True) -> str:
    """Her one line about where this message goes and why, in plain words."""
    saving = "plan" if plan else "tokens"
    if decision.where == HERE:
        line = HERE_WORDS.get(decision.kind, "Auto: my model on this computer can handle this, "
                                             "so I'll answer myself and save your {saving}.")
    else:
        line = CLOUD_WORDS.get(decision.kind, "Auto: I'll ask {cloud} for this one.")
    return line.format(cloud=cloud, saving=saving)


def model_form(ollama, model: str):
    """Her small model, asked to fill in one word. The schema only allows KINDS."""
    schema = {"type": "object", "properties": {"kind": {"enum": list(KINDS)}}, "required": ["kind"]}
    meanings = (
        "small_talk: greetings, thanks, feelings, chatting, jokes\n"
        "quick_fact: a short question with a short answer (a fact, a number, a word's meaning, a conversion)\n"
        "rewrite: translate, fix grammar, shorten or reword a short text the user gave\n"
        "suggestion: a few ideas, a name, a short message or recommendation\n"
        "explain: explain a topic or idea in some depth\n"
        "writing: write something long or important (essay, report, letter, story) or review one\n"
        "planning: a plan, schedule or itinerary over days or weeks\n"
        "analysis: compare options, weigh pros and cons, decide what to buy or choose\n"
        "code: anything about programming, software, errors, data or formulas\n"
        "math: maths or logic that takes several steps")

    def fill(text: str) -> str:
        messages = [{"role": "system", "content": "Sort the user's message into one kind. Only sort it; never answer it.\n"
                                                  + meanings},
                    {"role": "user", "content": text[:2000]}]
        return (ollama.chat_json(model, messages, schema, think=False) or {}).get("kind", "")

    return fill


# -------------------------------------------- "Ask Claude instead", counted

_lock = threading.Lock()


def _log_path() -> Path:
    from .elaina import data_dir
    return data_dir() / "auto.json"


def record(kind: str, asked_again: bool = False) -> None:
    """How often each kind stayed here, and how often the user then asked the plan
    instead: a kind people keep asking again for is placed wrong. Only counts."""
    with _lock:
        path = _log_path()
        try:
            counts = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            counts = {}
        mine = counts.setdefault(kind, {"here": 0, "asked_again": 0})
        mine["asked_again" if asked_again else "here"] += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(counts, indent=1), encoding="utf-8")


def counts() -> dict:
    try:
        return json.loads(_log_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_cases() -> list[dict]:
    import yaml
    return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))["cases"]
