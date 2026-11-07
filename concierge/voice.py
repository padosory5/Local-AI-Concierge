"""Noir's way of answering, the same whichever model writes the words: its own,
Claude or GPT through the user's plan, or one with an API key.

Two halves, because a model's habits win over a polite request. Each question goes
with a short note on how to answer it (`guide`): the answer first, then a few short
points only if they help, and a word budget that code picks from the kind of
question. Then every answer passes through `tidy`, which does in code what models
forget: it drops "Great question!", turns headings into bold lines, takes out lines
and tables the window can't show, and closes up gaps. Closing offers ("Let me know
if...") and a question tacked on after a whole answer are dropped by
`noir.without_closing_filler`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# The kinds of question, how many words an answer gets, and how many points at most.
# Every model, big or small, treats "up to six points" as six, so the caps are low.
BUDGETS = {
    "small_talk": (30, 0),
    "fact": (40, 0),
    # Plain chat and explanations get no points: offered "up to 2", a 4B model made two
    # up every time ("230 million sq km of urban sprawl"), and a greeting got advice
    # about memory. An explanation is paragraphs; steps, options and plans are lists.
    "chat": (60, 0),
    "explain": (110, 0),
    "decide": (90, 3),
    "how-to": (90, 4),
    "code": (120, 4),
    "plan": (170, 8),
    # Maths is worked through step by step with the formulas in LaTeX; science gets
    # the why and the key equation. Both are the long answers the user asked for.
    "math": (220, 0),
    "science": (180, 0),
    # The two buttons under an answer. "Shorter" is sized from the answer before it.
    "shorter": (40, 2),
    "more": (220, 6),
}
SHORTER_SHARE = 0.5
# Checked in this order: the first kind whose words appear wins. "Should I learn Python
# or JavaScript?" is a choice, not a coding question, so choosing comes before code.
# Small talk comes first: "hello" or "thanks!" is the whole message, with nothing to
# answer, and the note for answers made its re-answer the last question instead.
KIND_WORDS = (
    ("small_talk", r"^\s*(hi|hello|hey|yo|hiya|thanks?|thank you|thx|ty|ok(ay)?|cool|nice|great|awesome|perfect|"
                   r"good (morning|night|evening|afternoon)|bye|see (you|ya)|lol|haha|안녕\S*|고마워\S*|감사\S*|ㅋ+|ㅎ+|응|네|좋아\S*)"
                   r"([\s,!.~]+[\w']+){0,3}[\s!.~]*$"),  # a few words at most, and never a question
    # "hey how are you doing today?" is small talk too, though it ends in a question mark:
    # answered as a question, it got two bullet points about this computer's memory.
    ("small_talk", r"^\s*((hi|hello|hey|yo|hiya|good (morning|evening|afternoon))[\s,!.~]*)?"
                   r"(how('s| is| are| r|s)? (it going|things|you|u|ya|life|your day)|what'?s up|sup|"
                   r"how( have|'ve) you been|how do you do|잘 지내\S*|뭐 ?해\S*)(?!\s+with\b)"
                   r"([\s,!.~?]+[\w']+){0,3}[\s!.~?]*$"),
    ("plan", r"\b(plan|itinerary|schedule|routine|timetable)\b|계획|일정"),
    # Working something out comes before how-to: "how do I solve x^2 = 4" is maths.
    ("math", r"\b(solve|calculate|compute|evaluate|simplify|factor|factorise|factorize|expand|integral|integrate|"
             r"derivative|differentiate|limit of|equation|prove|proof|theorem|probability|odds|sqrt|square root|"
             r"logarithm|log of|sine|cosine|tangent|matrix|matrices|vector|fraction|percent of|percentage|"
             r"times|divided by|plus|minus|sum of|average of|mean of|remainder|modulo|polynomial|quadratic)\b"
             r"|\d\s*[-+*/×÷^=]\s*\d|\^\d|\bx\s*[=^]|\b(sin|cos|tan|ln)\s*\(|풀어|계산|방정식|미분|적분|확률|증명"),
    ("science", r"\b(physics|chemistry|biology|forces?|velocity|acceleration|momentum|inertia|kinetic|potential "
                r"energy|energy|gravity|gravitational|friction|torque|voltage|volts?|amps?|current|resistor|"
                r"resistance|circuit|ohm'?s?|capacitor|magnet|magnetic|electric|electrons?|protons?|neutrons?|"
                r"photons?|wave|wavelength|frequency|quantum|relativity|atoms?|atomic|molecules?|molecular|"
                r"chemical|reaction|acid|alkali|enzyme|cells?|dna|rna|protein|evolution|orbit|planets?|stars?|"
                r"galaxy|black hole|thermodynamics|entropy|optics|refraction|newton'?s|einstein)\b"
                r"|물리|화학|생물|가속도|중력|마찰|전압|전류|회로|파동|원자|분자|반응|에너지"),
    ("decide", r"\bshould i\b|\bwhich (is|one|should)\b|\bbetter\b|\bvs\.?\b|\bor\b.*\?\s*$|추천|뭐가 (나아|좋아)"),
    ("how-to", r"^\s*how (do|can|should|to)\b|\bhow to\b|\bsteps?\b|방법|어떻게"),
    ("code", r"error|exception|traceback|\bbug\b|\bcode\b|python|javascript|\bsql\b|function|에러|오류|코드"),
    ("fact", r"\b(capital|population|how (many|much|old|tall|far|long)|when (is|was|did)|who (is|was|wrote|made))\b"
             r"|언제|누구|몇"),
    ("explain", r"^\s*(what|why)\b|\bexplain\b|\bmean(s|ing)?\b|\btell me about\b|\bdescribe\b|뭐야|무엇|왜|설명|의미"),
)
STYLE = (
    "How to answer:\n"
    "- Start with the answer itself, in one or two short sentences of at most 15 words each. No greeting, "
    "no \"Great question\", and don't repeat the question.\n"
    "{more}\n"
    "- No headings, tables, horizontal lines or emoji.{extra}\n"
    "- At most one short tip or warning, and only if it really matters.\n"
    "- Don't end with an offer or a question. Ask a question only if you can't answer without it.\n"
    "- Keep it under {words} words, in the same language as the user."
)
# Small talk isn't a question: a greeting answered "the answer first, no greeting" came
# out as a list of what it can do, and "thanks!" as the last answer all over again.
SMALL_TALK_STYLE = (
    "How to answer:\n"
    "- This is small talk, not a question. Reply as yourself in one or two warm, natural sentences.\n"
    "- Don't answer an earlier question again, don't list what you can do, and don't explain how you answer.\n"
    "- Nothing about this computer, your model, or what you know about the user.\n"
    "- One short friendly question back is fine. No headings, lists or emoji.\n"
    "- Keep it under {words} words, in the same language as the user."
)
# Small models write points as loose lines unless told how each one starts, and
# turn "up to three" into three, so a simple fact is told plainly to stop. People
# skim the first words of each line, so each point starts with its key words in bold.
POINTS = ("- Then, only if it helps, up to {points} short points, one line each, each starting with \"- \" "
          "(or \"1.\", \"2.\" for steps in order). Start each point with its key words in bold, like "
          "\"- **Whole screen:** ...\", so someone who reads only the bold still gets it.")
NO_POINTS = "- That's all it needs: no list and no extra facts."
# An explanation is prose, as long as it needs and no longer: "no list" alone made
# its clip a real explanation to one line.
EXPLAIN_SHAPE = ("- Then explain in plain words, in as many short paragraphs as it needs, usually one or two. "
                 "No list: write it as sentences.")
EXTRA = {
    "code": " If code helps, one short code block, with its language after the opening ```.",
    "plan": " For a plan, a bold label for each day or part that names its main place, then its short points.",
    "decide": " Say which one first, then one point per option starting \"**Pick X if**\".",
    "how-to": " Write keys like Win + Shift + S.",
    "shorter": " Say your last answer again, keeping only what matters most.",
    "more": " Go further than your last answer: the why, an example or the next step. Don't repeat it.",
}
# Maths and science have shapes of their own: the working, and the why with its equation.
MATH_STYLE = (
    "How to answer:\n"
    "- Work it through step by step, one short numbered step per line, and say what each step does.\n"
    "- Write every formula and calculation in LaTeX between $...$, and the main equation or result on a line of "
    "its own between $$...$$. Never write maths as plain words or ASCII like x^2, sqrt() or 3/4.\n"
    "- End with the answer on its own line in bold.\n"
    "- No headings, tables or emoji. Keep it under {words} words, in the same language as the user."
)
SCIENCE_STYLE = (
    "How to answer:\n"
    "- Start with the answer itself in one or two plain sentences, then explain why in a short paragraph or two.\n"
    "- Write any formula in LaTeX between $...$ (the key one on a line of its own between $$...$$), never as "
    "plain words or ASCII.\n"
    "- A list only if the answer has separate parts, up to 3 points, each starting with its key words in bold.{extra}\n"
    "- No headings, tables or emoji. Keep it under {words} words, in the same language as the user."
)
# Only a model that draws well is asked to: its own 4B model's drawings came out
# black on black and off the edge, so hers draw only when the user asks for a drawing.
DRAWING = (" If a simple drawing would make it clearer (forces on a body, a circuit, a graph's shape), add one as "
           "SVG in a ```svg code block: viewBox 0 0 480 300, black lines on white, arrows and short labels, "
           "nothing decorative.")
DRAW_WORDS = re.compile(r"\b(draw|diagram|sketch|illustrate|graph it|plot)\b|그려|그림|도식", re.IGNORECASE)
# Openers that say nothing. Only ever taken off the very start of an answer.
OPENER = re.compile(
    r"^\s*(?:(?:great|good|excellent|nice) question[.!]*|(?:sure|certainly|of course|absolutely|okay|ok)[!.,]"
    r"|(?:i'd|i would|i'm|i am) (?:be )?(?:happy|glad) to help[^.!\n]*[.!]|좋은 질문(?:이에요|입니다)[.!]*)\s*",
    re.IGNORECASE,
)
QUOTE = re.compile(r"^\s*>\s?")  # "> Note:" shows as a stray mark
# "**- Right side:** ..." has the bullet inside the bold, so it drew as bold text with a
# dash instead of a point; the dash comes out in front.
BOLD_BULLET = re.compile(r"^(\s*)\*\*\s*[-•*]\s*(.+?)\*\*")
# A whole line that only echoes the note on how to answer: "No special conditions are
# needed for this answer.", "That's all it needs.", "Word count: 38". Dropped, since it
# tells the user nothing. A line that merely starts with "No" waits to be whole first
# (ECHO_START), so it can be checked; "No, the capital is Tokyo." then goes through.
RULE_ECHO = re.compile(
    r"^\s*\W*(?:(?:there (?:are|is) )?no (?:additional |special |extra |further |other |more )?"
    r"(?:tips?|questions?|conditions?|lists?|points?|warnings?|offers?)\b[^.!?]{0,80}"
    r"|that'?s all (?:it|this) needs|no list (?:is )?needed|word count:?\s*\d+|\(?(?:under|within) \d+ words\)?)"
    r"\W*$", re.IGNORECASE)
ECHO_START = re.compile(r"^\s*\W*(?:no |there (?:are|is) no|that'?s all|word count|\(?(?:under|within) \d)", re.IGNORECASE)
HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_LINE = re.compile(r"^\s*\|?\s*:?-{3,}")
# The start of a line that can only be ordinary words, a bullet or a numbered step.
SAFE_START = re.compile(r"^\s*(?:[^\W_]|[\"'(]|[-*•] \S|\d+[.)] \S|\*\*[^\W_])", re.UNICODE)
FIRST_SENTENCE = re.compile(r"[.!?。]\s")


def kind_of(question: str) -> str:
    lowered = question.strip().lower()
    kind = next((kind for kind, words in KIND_WORDS if re.search(words, lowered)), "chat")
    # "what?", "why?" or "and then?" after an answer is a follow-up to it, not a new
    # question to explain at length: told to explain with points, its model made some up.
    if kind not in ("small_talk", "fact") and len(lowered.split()) <= 3:
        return "chat"
    return kind


def guide(question: str, kind: str = "", before: str = "", draws: bool = False) -> str:
    """The note that goes with a question: how to answer it, and in how many words.
    `kind` is set when code already knows it (the Shorter and More detail buttons);
    `before` is its previous answer, which Shorter halves. `draws`: the model answering
    draws well, so a science answer may bring a drawing; any model may when asked to."""
    kind = kind if kind in BUDGETS else kind_of(question)
    words, points = BUDGETS[kind]
    drawing = DRAWING if draws or DRAW_WORDS.search(question) else ""
    if kind == "small_talk":
        return SMALL_TALK_STYLE.format(words=words)
    if kind == "math":
        return MATH_STYLE.format(words=words)
    if kind == "science":
        return SCIENCE_STYLE.format(words=words, extra=drawing)
    if kind == "shorter" and before:
        words = max(15, min(words, int(len(before.split()) * SHORTER_SHARE)))
    more = EXPLAIN_SHAPE if kind == "explain" else POINTS.format(points=points) if points else NO_POINTS
    extra = EXTRA.get(kind, "") + (drawing if kind in ("explain", "chat", "how-to") else "")
    return STYLE.format(more=more, words=words, extra=extra)


def tidy(chunks: Iterator[str]) -> Iterator[str]:
    """A streamed answer, line by line, in Noir's shape. Code blocks pass untouched."""
    pending, table, started, in_code, gap = "", [], False, False, False

    def shaped(line: str) -> str | None:
        nonlocal started, in_code, gap
        if line.strip().startswith("```"):
            in_code = not in_code
            return line
        if in_code:
            return line
        if not started:
            line = OPENER.sub("", line, count=1)
            if not line.strip():
                return None  # the whole line was "Great question!"
            line = line[:1].upper() + line[1:]
        if RULE.match(line) or RULE_ECHO.match(line):
            return None
        line = QUOTE.sub("", line, count=1)
        line = BOLD_BULLET.sub(r"\1- **\2**", line, count=1)
        if heading := HEADING.match(line):
            line = f"**{heading.group(1).strip('*').rstrip(':')}**"
        if not line.strip():
            if not started or gap:
                return None
            gap = True
            return ""
        started, gap = True, False
        return line

    def flush_table() -> Iterator[str]:
        rows = [row for row in table if not TABLE_LINE.match(row)]
        header = len(table) > 1 and TABLE_LINE.match(table[1])
        for row in rows[1:] if header else rows:
            cells = [cell.strip() for cell in TABLE_ROW.match(row).group(1).split("|") if cell.strip()]
            if cells:
                yield f"- **{cells[0]}**: {', '.join(cells[1:])}" if len(cells) > 1 else f"- {cells[0]}"
        table.clear()

    def lines_out(line: str) -> Iterator[str]:
        if not in_code and (TABLE_ROW.match(line) or (table and TABLE_LINE.match(line))):
            table.append(line)
            return
        if table:
            for row in flush_table():
                if (done := shaped(row)) is not None:
                    yield done + "\n"
        if (done := shaped(line)) is not None:
            yield done + "\n"

    mid = False  # part of the current line already went out, so the rest follows as it is
    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            if mid:
                yield line + "\n"
                mid = False
            else:
                yield from lines_out(line)
        # The first line goes out once its first sentence is whole, when any opener can
        # be taken off it, so a one-paragraph answer doesn't wait for its very end.
        if pending and not started and not table and FIRST_SENTENCE.search(pending):
            line = OPENER.sub("", pending, count=1)
            if line.strip() and SAFE_START.match(line):
                pending, started = line[:1].upper() + line[1:], True
        # An ordinary line streams as it comes, so the answer still appears word by word;
        # only a line that could turn out to be a heading, table or rule waits to be whole.
        if pending and started and not table and (mid or (SAFE_START.match(pending) and not ECHO_START.match(pending))):
            yield pending
            pending, mid, gap = "", True, False
    if mid:
        if pending:
            yield pending
        return
    if pending:
        last = list(lines_out(pending))
        if last:
            yield from last[:-1]
            yield last[-1].rstrip("\n")  # the answer doesn't end with a stray new line
    elif table:
        for row in flush_table():
            if (done := shaped(row)) is not None:
                yield done + "\n"
