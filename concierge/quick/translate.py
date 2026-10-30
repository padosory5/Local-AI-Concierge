"""Recognise language names ("into Korean", "한국어로") and scripts in code,
so the model is never asked what language something is in."""

from __future__ import annotations

import re


# Languages the small models translate well enough to offer, with the words
# people use for them. The first word is how the language is matched.
LANGUAGES = {
    "Korean": ["korean", "한국어", "한국말", "한글"],
    "English": ["english", "영어"],
    "Japanese": ["japanese", "일본어"],
    "Chinese": ["chinese", "mandarin", "중국어"],
    "Spanish": ["spanish", "스페인어"],
    "French": ["french", "프랑스어"],
    "German": ["german", "독일어"],
    "Italian": ["italian", "이탈리아어"],
    "Portuguese": ["portuguese", "포르투갈어"],
    "Russian": ["russian", "러시아어"],
    "Vietnamese": ["vietnamese", "베트남어"],
    "Thai": ["thai", "태국어"],
    "Indonesian": ["indonesian", "인도네시아어"],
    "Arabic": ["arabic", "아랍어"],
    "Hindi": ["hindi", "힌디어"],
    "Dutch": ["dutch", "네덜란드어"],
    "Turkish": ["turkish", "터키어"],
    "Polish": ["polish", "폴란드어"],
}

# Characters that only a few languages use, for "is this already in Korean?".
_SCRIPTS = {
    "Korean": r"[가-힣]",
    "Japanese": r"[぀-ヿ]",
    "Chinese": r"[一-鿿]",
    "Russian": r"[Ѐ-ӿ]",
    "Arabic": r"[؀-ۿ]",
    "Thai": r"[฀-๿]",
    "Hindi": r"[ऀ-ॿ]",
}


def _lookup(word: str) -> str | None:
    word = word.lower()
    return next((name for name, words in LANGUAGES.items() if word in words), None)


def language_in(text: str, target_only: bool = False) -> str | None:
    """The language the user wants to translate into, or None if unclear.

    target_only: only an explicit target counts ("into Korean", "to English",
    "Korean translator", "한국어로"), because "translate English text" names
    the source, not the target. Otherwise a single language named is enough,
    as in an answer to "Which language?".
    """
    lowered = text.lower()
    for match in re.finditer(r"\b(?:into|to|in)\s+([a-z]+)", lowered):
        if name := _lookup(match.group(1)):
            return name
    for match in re.finditer(r"\b([a-z]+)\s+translat", lowered):
        if name := _lookup(match.group(1)):
            return name
    for name, words in LANGUAGES.items():
        if any(f"{w}로" in text for w in words if not w.isascii()):
            return name
    if target_only:
        return None
    found = {name for name, words in LANGUAGES.items()
             if any(re.search(rf"\b{re.escape(w)}\b" if w.isascii() else re.escape(w), lowered) for w in words)}
    return found.pop() if len(found) == 1 else None


def looks_like(text: str, language: str) -> bool:
    """True when the text is clearly already in that language, so there is nothing to do."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True  # numbers or symbols only
    if language in _SCRIPTS:
        share = len(re.findall(_SCRIPTS[language], text)) / len(letters)
        return share > 0.5
    if language == "English":
        return all(c.isascii() for c in letters) and bool(re.search(r"\b(the|and|is|are|to|of|you|it)\b", text.lower()))
    return False
