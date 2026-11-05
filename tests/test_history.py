import json
import zipfile

import pytest

from concierge import history
from concierge.history import CHATGPT, CLAUDE, MAX_MESSAGE_CHARS, HistoryError


@pytest.fixture(autouse=True)
def kept_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "history_path", lambda: tmp_path / "history.json")
    monkeypatch.setattr(history, "read_files_path", lambda: tmp_path / "history_files.json")


def chatgpt_chat(title="Polish email", when=1_700_000_000.0):
    """The shape ChatGPT's download uses: a tree of messages, with an edited-away
    draft on a side branch that must never be read as something they asked."""
    def node(id, parent, role, text, children=()):
        return {"id": id, "parent": parent, "children": list(children),
                "message": {"author": {"role": role}, "content": {"content_type": "text", "parts": [text]}}}

    mapping = {
        "root": {"id": "root", "parent": None, "children": ["sys"], "message": None},
        "sys": node("sys", "root", "system", "", ["draft", "ask"]),
        "draft": node("draft", "sys", "user", "an old draft I edited away"),
        "ask": node("ask", "sys", "user", "I'm a nurse. Make this email polite.", ["answer"]),
        "answer": node("answer", "ask", "assistant", "I'm a teacher, here you go", ["again"]),
        "again": node("again", "answer", "user", "Shorter please"),
    }
    return {"title": title, "create_time": when, "mapping": mapping, "current_node": "again", "conversation_id": "c1"}


def claude_chat():
    return {"uuid": "u1", "name": "Explain recursion", "created_at": "2026-10-01T12:00:00.000000Z",
            "chat_messages": [
                {"sender": "human", "text": "Explain recursion simply", "content": []},
                {"sender": "assistant", "text": "Sure, I'm Claude", "content": []},
                {"sender": "human", "text": "", "content": [{"type": "text", "text": "Now with an example"}]},
            ]}


def zipped(path, rows, name="conversations.json"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, json.dumps(rows))
        archive.writestr("chat.html", "<html></html>")
    return path


def test_a_chatgpt_download_keeps_only_what_the_person_asked_on_the_branch_they_kept(tmp_path):
    [chat] = history.read_export(zipped(tmp_path / "export.zip", [chatgpt_chat()]))
    assert chat.source == CHATGPT and chat.title == "Polish email" and chat.when == 1_700_000_000.0
    assert chat.asked == ["I'm a nurse. Make this email polite.", "Shorter please"]


def test_a_claude_download_keeps_only_the_persons_messages(tmp_path):
    [chat] = history.read_export(zipped(tmp_path / "data.zip", [claude_chat()]))
    assert chat.source == CLAUDE and chat.title == "Explain recursion" and chat.when > 0
    assert chat.asked == ["Explain recursion simply", "Now with an example"]


def test_the_unpacked_folder_and_the_file_alone_work_too(tmp_path):
    folder = tmp_path / "unpacked"
    folder.mkdir()
    (folder / "conversations.json").write_text(json.dumps([claude_chat()]), encoding="utf-8")
    assert len(history.read_export(folder)) == 1
    assert len(history.read_export(folder / "conversations.json")) == 1


def test_something_else_gets_a_plain_answer(tmp_path):
    other = zipped(tmp_path / "photos.zip", [{"not": "a chat"}], name="photos.json")
    with pytest.raises(HistoryError, match="ChatGPT or Claude"):
        history.read_export(other)
    damaged = tmp_path / "conversations.json"
    damaged.write_text("{not json", encoding="utf-8")
    with pytest.raises(HistoryError, match="damaged"):
        history.read_export(damaged)
    with pytest.raises(HistoryError, match="find"):
        history.read_export(tmp_path / "missing.zip")


def test_a_pasted_document_is_cut_short(tmp_path):
    chat = claude_chat()
    chat["chat_messages"][0]["text"] = "word " * 2000
    [read] = history.read_export(zipped(tmp_path / "data.zip", [chat]))
    assert len(read.asked[0]) <= MAX_MESSAGE_CHARS


def test_bringing_in_the_same_download_twice_keeps_each_chat_once(tmp_path):
    export = zipped(tmp_path / "export.zip", [chatgpt_chat(), claude_chat()])
    assert history.bring_in(export) == {"read": 2, "new": 2, "sources": [CHATGPT, CLAUDE], "total": 2}
    assert history.bring_in(export)["new"] == 0
    kept = history.brought_in()
    assert len(kept) == 2 and kept[0].when >= kept[1].when  # newest first
    history.forget()
    assert history.brought_in() == []


def test_a_download_is_recognised_by_whats_inside(tmp_path):
    assert history.is_export(zipped(tmp_path / "a1b2c3-2026-11-04.zip", [claude_chat()]))
    assert not history.is_export(zipped(tmp_path / "photos.zip", [], name="photo.json"))
    (tmp_path / "notes.txt").write_text("hi")
    assert not history.is_export(tmp_path / "notes.txt")


def test_downloads_already_read_are_never_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "read_files_path", lambda: tmp_path / "history_files.json")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    zipped(downloads / "data-2026-11-04.zip", [claude_chat()])
    zipped(downloads / "photos.zip", [], name="photo.json")
    (downloads / "notes.txt").write_text("hi")
    found = history.find_exports(downloads)
    assert [path.name for path in found] == ["data-2026-11-04.zip"]
    history.bring_in(found[0])
    assert history.find_exports(downloads) == []


def test_a_download_older_than_the_wait_is_left_for_find_it(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(history, "read_files_path", lambda: tmp_path / "history_files.json")
    old = zipped(tmp_path / "old.zip", [claude_chat()])
    os.utime(old, (time.time() - 86400, time.time() - 86400))
    assert history.find_exports(tmp_path, since=time.time() - 60) == []
    assert len(history.find_exports(tmp_path, since=0)) == 1
