"""What the user adds with the + button: files, folders and pictures.

Only what fits goes to the model. A file's words stay in her memory like anything
else that was said, so the user can ask about it again. Pictures are too big for
that, so only the next reply sees them.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from .agents.files import SUPPORTED, read_pages

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_CHARS_PER_FILE = 5000  # small local models lose the thread with much more
MAX_CHARS = 7000
MAX_IMAGE_MB = 8
NOTHING_SAID = "Please look at what I've attached."


@dataclass
class Attached:
    context: str = ""  # the files' words, for the model
    images: list[str] = field(default_factory=list)  # pictures, ready to send
    folders: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)  # what couldn't be read, by name


def _file_text(path: Path) -> str:
    """Its words, or nothing if it isn't text: a program or a zip read as text is only noise."""
    if path.suffix.lower() not in SUPPORTED and b"\0" in path.read_bytes()[:4096]:
        return ""
    return "\n".join(text for _, text in read_pages(path))


def read_attachments(paths: list[str]) -> Attached:
    """Read what was added. A file that can't be read is named, not silently dropped."""
    result = Attached()
    parts: list[str] = []
    room = MAX_CHARS
    for name in paths:
        path = Path(name)
        result.names.append(path.name)
        if path.is_dir():
            result.folders.append(str(path))
        elif path.suffix.lower() in IMAGE_TYPES:
            try:
                if path.stat().st_size > MAX_IMAGE_MB * 1024 * 1024:
                    raise OSError("too big")
                result.images.append(base64.b64encode(path.read_bytes()).decode())
            except OSError:
                result.unread.append(path.name)
        else:
            try:
                words = _file_text(path).strip()
            except Exception:  # every file type fails in its own way; none should stop the message
                words = ""
            if not words or room <= 0:
                result.unread.append(path.name)
                continue
            piece = words[:min(MAX_CHARS_PER_FILE, room)]
            room -= len(piece)
            ending = "\n[The rest of this file was too long to include.]" if len(piece) < len(words) else ""
            parts.append(f"--- {path.name} ---\n{piece}{ending}")
    if parts:
        result.context = "The user attached these files. Use them to answer.\n\n" + "\n\n".join(parts)
    return result
