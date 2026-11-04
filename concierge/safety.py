"""Replies that must never be left to a small model.

A local model has no company watching for someone in danger, so when a message
talks about ending one's life or hurting oneself, code answers with fixed, kind
words and the numbers to call, and the model doesn't improvise. Health and money
answers get a plain note to check with a person, because small models make up
doses and figures.
"""

from __future__ import annotations

import re

CRISIS = re.compile(
    r"\b(kill(ing)? myself|end(ing)? my life|suicid\w*|self[- ]?harm\w*|hurt(ing)? myself|"
    r"want(ed)? to die|don'?t want to (live|be alive)|better off dead)\b"
    r"|자살|죽고\s*싶|자해|살기\s*싫|극단적\s*선택|사라지고\s*싶",
    re.IGNORECASE,
)
HEALTH = re.compile(
    r"\b(dose|dosage|medicine|medication|pills?|symptoms?|diagnos\w*|prescri\w*|side effects?|overdose)\b"
    r"|복용|증상|처방|진단|부작용|약\s*(을|를)?\s*(먹|얼마)",
    re.IGNORECASE,
)
MONEY = re.compile(
    r"\b(invest\w*|stocks?|crypto\w*|bitcoin|loans?|mortgage|taxe?s?|retirement|savings)\b"
    r"|주식|투자|대출|코인|세금|연금|적금",
    re.IGNORECASE,
)
CRISIS_REPLY = (
    "I'm really glad you told me, and I'm sorry it's this hard right now. You don't have to carry it alone. "
    "If you might act on these thoughts, please call someone now: 109 in Korea (any time, day or night), "
    "988 in the United States, or your local emergency number. Talking to someone you trust can help too. "
    "I'm here if you want to keep talking."
)
CRISIS_REPLY_KO = (
    "말해줘서 정말 고마워요. 지금 많이 힘드시죠. 혼자 견디지 않아도 돼요. "
    "혹시 위험한 생각이 든다면 지금 바로 자살예방상담전화 109(24시간)나 112, 119에 연락해 주세요. "
    "믿을 수 있는 사람에게 이야기하는 것도 도움이 돼요. 원하시면 저와 계속 이야기해도 괜찮아요."
)
HEALTH_NOTE = "I'm not a doctor, so please check anything important with one."
MONEY_NOTE = "I'm not a financial adviser, so please check big decisions with one."


def _korean(text: str) -> bool:
    return any("가" <= letter <= "힣" for letter in text)


def crisis(text: str) -> bool:
    return bool(CRISIS.search(text))


def crisis_reply(text: str) -> str:
    """In the language the person wrote in."""
    return CRISIS_REPLY_KO if _korean(text) else CRISIS_REPLY


def caution(text: str) -> str:
    """A plain note to add after an answer about health or money, or nothing."""
    if HEALTH.search(text):
        return HEALTH_NOTE
    if MONEY.search(text):
        return MONEY_NOTE
    return ""
