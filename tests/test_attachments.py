import base64

from concierge.attachments import MAX_CHARS, MAX_CHARS_PER_FILE, read_attachments
from concierge.conversations import ChatBook
from concierge.elaina import ElainaChat
from concierge.engine import ElainaEngine
from concierge.events import ElainaDone, ElainaText, Thinking


class FakeOllama:
    def __init__(self, capabilities=("completion",)):
        self.can = list(capabilities)
        self.sent = None

    def capabilities(self, model):
        return self.can

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.sent = messages
        yield "The picnic is on Saturday."

    def loaded(self):
        return []


def engine_with(ollama, tmp_path):
    engine = ElainaEngine(ollama)
    engine.book = ChatBook(None)
    engine.chat = ElainaChat(ollama)
    return engine


def test_a_text_file_is_read_with_its_name(tmp_path):
    (tmp_path / "notes.txt").write_text("Picnic on Saturday", encoding="utf-8")
    attached = read_attachments([str(tmp_path / "notes.txt")])
    assert "Picnic on Saturday" in attached.context and "notes.txt" in attached.context
    assert attached.names == ["notes.txt"] and not attached.unread


def test_a_long_file_is_cut_and_says_so(tmp_path):
    (tmp_path / "long.txt").write_text("word " * 5000, encoding="utf-8")
    attached = read_attachments([str(tmp_path / "long.txt")])
    assert "too long" in attached.context
    assert len(attached.context) < MAX_CHARS_PER_FILE + 300


def test_many_files_together_stay_within_what_the_model_can_read(tmp_path):
    paths = []
    for number in range(4):
        path = tmp_path / f"{number}.txt"
        path.write_text("word " * 2000, encoding="utf-8")
        paths.append(str(path))
    attached = read_attachments(paths)
    assert len(attached.context) < MAX_CHARS + 500
    assert attached.unread == ["2.txt", "3.txt"]  # named, never silently dropped


def test_a_program_is_not_read_as_text(tmp_path):
    (tmp_path / "app.exe").write_bytes(b"MZ\0\0\0\0binary")
    attached = read_attachments([str(tmp_path / "app.exe")])
    assert attached.unread == ["app.exe"] and not attached.context


def test_a_missing_file_is_named_not_a_crash(tmp_path):
    assert read_attachments([str(tmp_path / "gone.txt")]).unread == ["gone.txt"]


def test_a_code_file_is_read_as_text(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    assert "print('hello')" in read_attachments([str(tmp_path / "main.py")]).context


def test_pictures_and_folders_are_kept_apart_from_text(tmp_path):
    (tmp_path / "a.png").write_bytes(b"picture")
    (tmp_path / "docs").mkdir()
    attached = read_attachments([str(tmp_path / "a.png"), str(tmp_path / "docs")])
    assert attached.images == [base64.b64encode(b"picture").decode()]
    assert attached.folders == [str(tmp_path / "docs")]


def test_elaina_reads_a_file_and_still_knows_it_next_time(tmp_path):
    ollama = FakeOllama()
    chat = ElainaChat(ollama)
    chat.attach("Picnic on Saturday", [])
    list(chat.send("When is it?"))
    assert "Picnic on Saturday" in ollama.sent[-1]["content"]
    list(chat.send("Where was that again?"))
    assert any("Picnic on Saturday" in message["content"] for message in ollama.sent)


def test_a_picture_only_goes_with_its_own_message(tmp_path):
    ollama = FakeOllama(["completion", "vision"])
    chat = ElainaChat(ollama)
    chat.attach("", ["AAAA"])
    list(chat.send("What's this?"))
    assert ollama.sent[-1]["images"] == ["AAAA"]
    assert all("images" not in message for message in chat.history)  # too big to keep or save
    list(chat.send("And now?"))
    assert all("images" not in message for message in ollama.sent)


def test_a_message_with_a_file_skips_the_router(tmp_path):
    (tmp_path / "notes.txt").write_text("Picnic on Saturday", encoding="utf-8")
    ollama = FakeOllama()
    engine = engine_with(ollama, tmp_path)
    engine.builder = engine.planner = None
    events = list(engine.send_files("When is it?", [str(tmp_path / "notes.txt")]))
    assert any(isinstance(e, Thinking) and "notes.txt" in e.text for e in events)
    assert "".join(e.text for e in events if isinstance(e, ElainaText)) == "The picnic is on Saturday."
    assert any(isinstance(e, ElainaDone) for e in events)
    assert "Attached: notes.txt" in engine.book.current.items[0]["text"]


def test_a_picture_for_a_model_that_cant_see_says_so(tmp_path):
    (tmp_path / "a.png").write_bytes(b"picture")
    ollama = FakeOllama(["completion"])
    engine = engine_with(ollama, tmp_path)
    events = list(engine.send_files("What's this?", [str(tmp_path / "a.png")]))
    assert "can't look at pictures" in "".join(e.text for e in events if isinstance(e, ElainaText))
    assert ollama.sent is None  # never pretends to have looked


def test_a_picture_for_a_model_that_can_see_goes_to_it(tmp_path):
    (tmp_path / "a.png").write_bytes(b"picture")
    ollama = FakeOllama(["completion", "vision"])
    engine = engine_with(ollama, tmp_path)
    list(engine.send_files("", [str(tmp_path / "a.png")]))
    assert ollama.sent[-1]["images"] and ollama.sent[-1]["content"]  # a message even with no words


def test_nothing_readable_is_said_plainly(tmp_path):
    (tmp_path / "app.exe").write_bytes(b"MZ\0\0\0")
    ollama = FakeOllama()
    engine = engine_with(ollama, tmp_path)
    events = list(engine.send_files("", [str(tmp_path / "app.exe")]))
    assert "couldn't read" in "".join(e.text for e in events if isinstance(e, ElainaText))
    assert ollama.sent is None
