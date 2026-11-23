import pytest

from concierge.agents import store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder
from concierge.conversations import ChatBook, title_from
from concierge.events import ChatList, NoirDone, NoirText, Question, Result, Source, Transcript
from concierge.fake_engine import FakeEngine


def reply(*events):
    yield from events


@pytest.fixture
def memory():
    """Stands in for Noir's model history."""
    return []


@pytest.fixture
def book(tmp_path, memory):
    return ChatBook(tmp_path / "conversations", history=lambda: memory)


def talk(book, memory, user, answer):
    memory += [{"role": "user", "content": user}, {"role": "assistant", "content": answer}]
    return list(book.record(user, reply(NoirText(answer), NoirDone())))


def test_first_message_creates_a_saved_conversation(book, memory, tmp_path):
    events = talk(book, memory, "Remember my favourite colour is green", "Got it.")
    assert isinstance(events[0], ChatList) and events[0].chats[0].title.startswith("Remember")
    assert len(list((tmp_path / "conversations").glob("*.json"))) == 1


def test_new_chat_keeps_the_old_one_with_its_memory(book, memory):
    talk(book, memory, "My favourite colour is green", "Got it.")
    first = book.current.id
    book.new()
    memory.clear()  # what the engine does to Noir's memory after book.new()
    talk(book, memory, "Something else", "Sure.")

    opened = book.open(first)
    assert [m["content"] for m in opened.history] == ["My favourite colour is green", "Got it."]
    assert [i.text for i in book.transcript().items] == ["My favourite colour is green", "Got it."]
    assert [c.title for c in book.chat_list().chats] == ["Something else", "My favourite colour is green"]


def test_agent_answers_and_questions_are_kept(book, memory):
    events = reply(Question("folder", "Which folder?"),
                   Result("Docs helper", "It ends in August.", [Source("lease.txt", "ends on 31 August")]))
    list(book.record("when does the lease end?", events))
    roles = [(i.role, i.agent) for i in book.transcript().items]
    assert roles == [("user", ""), ("noir", ""), ("result", "Docs helper")]
    assert book.transcript().items[2].sources[0].path == "lease.txt"


def test_delete_the_open_conversation_clears_the_screen(book, memory, tmp_path):
    talk(book, memory, "hello", "hi")
    events = book.delete(book.current.id)
    assert events[0] == Transcript(None, [])
    assert events[1].chats == [] and book.current is None
    assert list((tmp_path / "conversations").glob("*.json")) == []


def test_ids_cannot_reach_outside_the_folder(book):
    assert book.open("../../secrets") is None


def test_long_titles_are_shortened():
    assert title_from("word " * 30).endswith("...")
    assert len(title_from("word " * 30)) <= 42


# ---------------------------------------------------------- fake engine


def test_fake_engine_new_open_and_delete_chats():
    engine = FakeEngine(delay=0)
    list(engine.send("hello"))
    first = engine.book.current.id
    events = list(engine.new_chat())
    assert events[0] == Transcript(None, []) and isinstance(events[1], ChatList)
    list(engine.send("second chat"))
    events = list(engine.open_chat(first))
    assert events[0].items[0].text == "hello"
    assert [type(e) for e in engine.delete_chat(first)] == [Transcript, ChatList]


def test_fake_engine_deletes_an_agent_after_asking():
    engine = FakeEngine(delay=0)
    question = next(e for e in engine.delete_agent("Contracts helper") if isinstance(e, Question))
    assert question.choices == ["Delete it", "Keep it"]
    events = list(engine.choose(question.id, "Delete it"))
    assert events[-1].agents == ["Korean translator", "Home papers"]


# ------------------------------------------------------- duplicate folder


class FakeModel:
    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        if "question" in schema["properties"]:
            return {"question": "What is the rent?"}
        return {"answer": "1,350 dollars.", "used": [1]}


@pytest.fixture
def docs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr("concierge.agents.builder.is_blocked", lambda folder: False)
    folder = tmp_path / "Lease"
    folder.mkdir()
    (folder / "lease.txt").write_text("Monthly rent is 1,350 dollars.", encoding="utf-8")
    return folder


def create(builder, folder):
    list(builder.start("documents_qa", "make an agent"))
    return list(builder.answer(str(folder)))


def test_same_folder_asks_before_making_a_second_agent(docs):
    builder = AgentBuilder(FakeModel(), "noir", None, load_blueprints())
    card = create(builder, docs)[-1]
    list(builder.choose(card.id, "Create it"))

    question = create(builder, docs)[-1]
    assert isinstance(question, Question) and question.id == "duplicate"
    assert question.choices == ["Use Lease helper", "Replace it", "Make another one"]
    list(builder.choose(question.id, "Use Lease helper"))
    assert not builder.active and [a.name for a in store.list_agents()] == ["Lease helper"]


def test_replace_keeps_one_agent_with_the_same_name(docs):
    builder = AgentBuilder(FakeModel(), "noir", None, load_blueprints())
    list(builder.choose(create(builder, docs)[-1].id, "Create it"))
    question = create(builder, docs)[-1]
    card = list(builder.choose(question.id, "Replace it"))[-1]
    assert card.name == "Lease helper"
    list(builder.choose(card.id, "Create it"))
    assert [a.name for a in store.list_agents()] == ["Lease helper"]


def test_make_another_gives_it_a_new_name(docs):
    builder = AgentBuilder(FakeModel(), "noir", None, load_blueprints())
    list(builder.choose(create(builder, docs)[-1].id, "Create it"))
    question = create(builder, docs)[-1]
    card = list(builder.choose(question.id, "Make another one"))[-1]
    assert card.name == "Lease helper 2"
