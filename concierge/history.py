"""The user's past conversations with ChatGPT and Claude, read from the files those
services let people download, so Noir can get to know them (portrait.py).

Nothing here is automatic: both companies keep the chats on their own servers, so
the user asks once for a download (Settings, then Export data) and gets a zip by
email. Noir never signs in as the user and never reads their screen.

Only the user's own side is kept. The answers were written by another AI and say
little about the person, and keeping them would copy someone's whole chat history
for no reason. What's kept stays in the data folder and can be forgotten at once.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .noir import data_dir

CHATGPT, CLAUDE = "ChatGPT", "Claude"
# Where each company's download button is. They move now and then, so the windows
# also say the steps in words.
EXPORT_PAGES = {
    CHATGPT: "https://chatgpt.com/#settings/DataControls",
    CLAUDE: "https://claude.ai/settings/data-privacy-controls",
}
# A long message is usually something pasted in, a document or code, not the
# person talking about themselves.
MAX_MESSAGE_CHARS = 1500
MAX_EXPORT_MB = 4000  # a zip with years of pictures in it; only its chat file is read
CONVERSATIONS = re.compile(r"(^|/)conversations(-\d+)?\.json$", re.IGNORECASE)


class HistoryError(Exception):
    """A file that can't be brought in, said in plain words."""


@dataclass
class PastChat:
    source: str  # CHATGPT or CLAUDE
    id: str
    title: str
    when: float  # seconds since 1970, when the chat started
    asked: list[str] = field(default_factory=list)  # the user's own messages, in order


def history_path() -> Path:
    return data_dir() / "history.json"


def is_export(path: Path) -> bool:
    """A zip that holds a chat download, for noticing one in Downloads."""
    try:
        with zipfile.ZipFile(path) as archive:
            return any(CONVERSATIONS.search(name) for name in archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def read_export(path: Path) -> list[PastChat]:
    """Every conversation in a download: the zip as it came, the folder it was
    unpacked into, or its conversations.json on its own."""
    path = Path(path)
    if not path.exists():
        raise HistoryError("I can't find that file.")
    raw = []
    if path.is_dir():
        for file in sorted(path.rglob("*.json")):
            if CONVERSATIONS.search(file.as_posix()):
                raw.extend(_load(file.read_bytes()))
    elif zipfile.is_zipfile(path):
        if path.stat().st_size > MAX_EXPORT_MB * 1024 * 1024:
            raise HistoryError("That download is too big for me to open.")
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if CONVERSATIONS.search(name):
                    raw.extend(_load(archive.read(name)))
    elif path.suffix.lower() == ".json":
        raw = _load(path.read_bytes())
    chats = [chat for chat in map(_one_chat, raw) if chat and chat.asked]
    if not chats:
        raise HistoryError("That isn't a ChatGPT or Claude download I can read. It should be the zip "
                           "they email you after Export data, or the conversations.json inside it.")
    return chats


def bring_in(path: Path) -> dict:
    """Read a download and add it to what's kept. A chat brought in twice is kept once,
    with whatever the newer download says."""
    chats = read_export(path)
    kept = {(chat.source, chat.id): chat for chat in brought_in()}
    new = sum((chat.source, chat.id) not in kept for chat in chats)
    kept.update({(chat.source, chat.id): chat for chat in chats})
    _save(list(kept.values()))
    if Path(path).is_file():
        _mark_read(Path(path))
    sources = sorted({chat.source for chat in chats})
    return {"read": len(chats), "new": new, "sources": sources, "total": len(kept)}


def brought_in() -> list[PastChat]:
    """Everything kept, newest first."""
    try:
        rows = json.loads(history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    chats = [PastChat(**row) for row in rows if isinstance(row, dict)]
    return sorted(chats, key=lambda chat: chat.when, reverse=True)


def forget() -> None:
    history_path().unlink(missing_ok=True)
    read_files_path().unlink(missing_ok=True)


def read_files_path() -> Path:
    """Which downloads were read already, by size and time, so none is read twice."""
    return data_dir() / "history_files.json"


def find_exports(folder: Path, since: float = 0) -> list[Path]:
    """Chat downloads in a folder (Downloads) not read yet, oldest first: zips with a
    chat file inside, or a conversations.json on its own. A file still downloading
    isn't a whole zip yet, so it's picked up on a later look."""
    if not folder.is_dir():
        return []
    done, found = _read_files(), []
    for entry in folder.iterdir():
        try:
            if not entry.is_file() or entry.suffix.lower() not in (".zip", ".json"):
                continue
            info = entry.stat()
        except OSError:
            continue
        if info.st_mtime < since or done.get(str(entry)) == [info.st_size, info.st_mtime]:
            continue
        if is_export(entry) if entry.suffix.lower() == ".zip" else bool(CONVERSATIONS.search(entry.name)):
            found.append(entry)
    return sorted(found, key=lambda entry: entry.stat().st_mtime)


# ------------------------------------------------------------- reading


def _read_files() -> dict:
    try:
        return json.loads(read_files_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _mark_read(path: Path) -> None:
    done = _read_files()
    info = path.stat()
    done[str(path)] = [info.st_size, info.st_mtime]
    read_files_path().parent.mkdir(parents=True, exist_ok=True)
    read_files_path().write_text(json.dumps(done), encoding="utf-8")


def _save(chats: list[PastChat]) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(chat) for chat in chats], ensure_ascii=False), encoding="utf-8")


def _load(data: bytes) -> list:
    try:
        rows = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HistoryError("Part of that download is damaged, so I couldn't read it.") from exc
    return rows if isinstance(rows, list) else []


def _one_chat(row) -> PastChat | None:
    if not isinstance(row, dict):
        return None
    if isinstance(row.get("mapping"), dict):
        return _chatgpt(row)
    if isinstance(row.get("chat_messages"), list):
        return _claude(row)
    return None


def _chatgpt(row: dict) -> PastChat:
    """A ChatGPT conversation is a tree, because an edited message starts a new
    branch. The branch the user last saw ends at current_node; it's followed back
    to the start, so old drafts aren't read as things they asked."""
    mapping = row["mapping"]
    path, node = [], row.get("current_node")
    while node in mapping and len(path) <= len(mapping):
        path.append(mapping[node])
        node = mapping[node].get("parent")
    if not path:  # no branch marked: every message, by time
        path = sorted(mapping.values(), key=lambda n: ((n.get("message") or {}).get("create_time") or 0))
    else:
        path.reverse()
    asked = []
    for node in path:
        message = node.get("message") or {}
        if (message.get("author") or {}).get("role") != "user":
            continue
        content = message.get("content") or {}
        if content.get("content_type") not in ("text", "multimodal_text"):
            continue
        words = " ".join(part for part in content.get("parts") or [] if isinstance(part, str))
        asked.append(words)
    return PastChat(CHATGPT, str(row.get("conversation_id") or row.get("id") or _id_of(row)),
                    str(row.get("title") or ""), float(row.get("create_time") or 0), _clean(asked))


def _claude(row: dict) -> PastChat:
    asked = []
    for message in row["chat_messages"]:
        if not isinstance(message, dict) or message.get("sender") != "human":
            continue
        words = message.get("text") or " ".join(
            part.get("text", "") for part in message.get("content") or []
            if isinstance(part, dict) and part.get("type") == "text")
        asked.append(words)
    return PastChat(CLAUDE, str(row.get("uuid") or _id_of(row)), str(row.get("name") or ""),
                    _seconds(row.get("created_at")), _clean(asked))


def _clean(messages: list[str]) -> list[str]:
    return [text.strip()[:MAX_MESSAGE_CHARS] for text in messages if text and text.strip()]


def _seconds(stamp) -> float:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _id_of(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:16]
