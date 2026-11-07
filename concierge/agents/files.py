"""Read a folder of documents, cut them into passages, and search them.

All plain code. The model only ever sees the few passages the search picks,
which keeps answers grounded in the files and fits a small context window.
Search is keyword based (BM25), so it needs no extra model; a small
embedding model can replace it later if keyword search proves too weak.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".log", ".rst", ".json", ".html", ".htm"}
SUPPORTED = TEXT_TYPES | {".pdf", ".docx"}

MAX_FILES = 2000
MAX_FILE_MB = 30
# About 150 to 200 words per passage: long enough to hold an answer, short
# enough that four of them fit comfortably in Noir's 4,096-token window.
PASSAGE_CHARS = 900
PASSAGE_OVERLAP = 150

_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Passage:
    path: str  # relative to the agent's folder
    page: int | None  # PDF page, 1-based
    text: str

    def where(self) -> str:
        return f"{self.path}, page {self.page}" if self.page else self.path


@dataclass
class ScanResult:
    files: list[Path]
    skipped: int  # unsupported, too big, or over MAX_FILES


def scan(folder: Path) -> ScanResult:
    """The supported files under folder, skipping hidden folders."""
    files, skipped = [], 0
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith((".", "$", "__"))]
        for name in sorted(names):
            path = Path(root) / name
            if path.suffix.lower() not in SUPPORTED or name.startswith(("~$", ".")):
                skipped += 1
                continue
            try:
                too_big = path.stat().st_size > MAX_FILE_MB * 1024 * 1024
            except OSError:
                too_big = True
            if too_big or len(files) >= MAX_FILES:
                skipped += 1
                continue
            files.append(path)
    return ScanResult(files, skipped)


def read_pages(path: Path) -> list[tuple[int | None, str]]:
    """The text of a file, as (page number or None, text) pieces."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return [(None, "\n".join(parts))]
    return [(None, path.read_text(encoding="utf-8", errors="replace"))]


def split(text: str) -> list[str]:
    """Cut text into overlapping passages, preferring to break between paragraphs."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= PASSAGE_CHARS:
        return [text] if text else []
    passages, start = [], 0
    while start < len(text):
        end = min(start + PASSAGE_CHARS, len(text))
        if end < len(text):
            cut = max(text.rfind("\n", start + PASSAGE_CHARS // 2, end),
                      text.rfind(". ", start + PASSAGE_CHARS // 2, end))
            end = cut + 1 if cut > 0 else end
        passages.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - PASSAGE_OVERLAP, start + 1)
    return [p for p in passages if p]


def passages_of(folder: Path, path: Path) -> list[Passage]:
    """One file's passages; empty when the file cannot be read (damaged,
    password-protected, or a scanned PDF with no text in it)."""
    try:
        pages = read_pages(path)
    except Exception:
        return []
    relative = path.relative_to(folder).as_posix()
    return [Passage(relative, page, piece) for page, text in pages for piece in split(text)]


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 or not w.isascii()]


class SearchIndex:
    """BM25 keyword search over passages."""

    K1, B = 1.5, 0.75

    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self.counts = [Counter(tokens(p.text) + tokens(p.path)) for p in passages]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0
        doc_freq = Counter(word for c in self.counts for word in c)
        n = len(passages)
        self.idf = {w: math.log(1 + (n - df + 0.5) / (df + 0.5)) for w, df in doc_freq.items()}

    def search(self, query: str, limit: int = 4) -> list[Passage]:
        words = set(tokens(query))
        scored = []
        for i, counts in enumerate(self.counts):
            score = 0.0
            for word in words:
                tf = counts.get(word)
                if not tf:
                    continue
                norm = tf * (self.K1 + 1) / (
                    tf + self.K1 * (1 - self.B + self.B * self.lengths[i] / (self.avg_length or 1))
                )
                score += self.idf[word] * norm
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [self.passages[i] for _, i in scored[:limit]]

    def to_json(self) -> list[dict]:
        return [asdict(p) for p in self.passages]

    @classmethod
    def from_json(cls, rows: list[dict]) -> SearchIndex:
        return cls([Passage(**row) for row in rows])


def folder_signature(files: list[Path]) -> str:
    """Changes when files are added, removed or edited, to know when to re-read."""
    newest = 0.0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    return f"{len(files)}:{newest:.0f}"
