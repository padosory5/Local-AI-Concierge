"""Keeping the user's cloud tokens: when a cloud model is picked, a job a small model
does well is still done on this computer, and what that kept off their plan is counted.

Code decides, never a model. Only jobs on text the user gave stay here: translating,
summing up, rewriting, polishing, fixing, shortening, or explaining a word or a
passage. Facts, advice, how-tos, code and plans still go to the model the user picked,
because a 4B model guesses at those, and one wrong answer costs more than the tokens.
"""

from __future__ import annotations

import re

from . import voice

# Kinds of question (voice.kind_of) that always go to the picked model.
CLOUD_KINDS = ("fact", "decide", "how-to", "code", "plan")
# Jobs on the user's own text, each with the words that ask for it, in English and Korean.
LOCAL_JOBS = (
    ("translate", r"\btranslat(e|es|ed|ing|ion)\b|번역"),
    ("sum up", r"\bsummar(y|ize|ise|ies|izing|ising)\b|\bsum (this|it|that|up)\b|\btl;?dr\b|\bkey points\b|요약"),
    ("rewrite", r"\b(rewrite|rephrase|reword|polish|proofread|tidy up|clean up|shorten|simplify)\b"
                r"|\bfix (the |my |this )?(grammar|spelling|typos|wording)\b"
                r"|\bmake (it|this|that) (shorter|clearer|simpler|more polite|formal|better)\b"
                r"|다듬|고쳐|교정|줄여|짧게"),
    ("explain", r"\bexplain\b|\bwhat does\b.*\bmean\b|\bmeaning of\b|\bin simple (words|terms)\b|뜻|설명"),
)
# What her thinking line says she can do herself.
JOB_WORDS = {"translate": "translate this", "sum up": "sum this up", "rewrite": "rewrite this", "explain": "explain this"}
CHARS_PER_TOKEN = 4  # roughly, for English; a Korean, Chinese or Japanese character is about one token
GUIDE_TOKENS = 170  # the note on how to answer that goes with every question (voice.guide)


def local_job(text: str) -> str:
    """The job a small model can do here instead of the picked model, or "" to send it on."""
    if voice.kind_of(text) in CLOUD_KINDS:
        return ""
    lowered = text.lower()
    return next((job for job, words in LOCAL_JOBS if re.search(words, lowered)), "")


def tokens_in(text: str) -> int:
    """About how many tokens a model would count in the text."""
    wide = sum(1 for ch in text if ord(ch) > 0x2E7F)
    return wide + (len(text) - wide + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def kept(messages: list[dict], system: str = "") -> int:
    """About how many tokens the cloud call would have taken: everything that would have
    been sent, the note on how to answer, and the answer that came back."""
    return sum(tokens_in(m.get("content", "")) for m in messages) + tokens_in(system) + GUIDE_TOKENS
