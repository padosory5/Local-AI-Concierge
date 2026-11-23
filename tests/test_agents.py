import os
import sys
from pathlib import Path

import docx
import pytest

from concierge.agents import runner, store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder, describe_files, find_folders, is_blocked
from concierge.agents.files import SearchIndex, passages_of, scan, split
from concierge.agents.router import route
from concierge.events import AgentCard, AgentList, NoirText, Progress, Question, Result


class FakeModel:
    """Answers chat_json by which schema it is asked to fill."""

    def __init__(self, choice="chat", folder="", place="not said"):
        self.choice, self.folder, self.place = choice, folder, place
        self.schemas = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.schemas.append(schema)
        fields = schema["properties"]
        if "choice" in fields:
            return {"choice": self.choice}
        if "folder" in fields:
            return {"folder": self.folder, "place": self.place}
        if "question" in fields:
            return {"question": "How much is the deposit?"}
        return {"answer": "The deposit is 2,700 dollars [1]. Excerpt [1] used.", "used": [1, 9]}


def make_pdf(path: Path, text: str) -> None:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(out)


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "Lease docs"
    folder.mkdir()
    (folder / "lease.txt").write_text(
        "Monthly rent is 1,350 dollars.\nA security deposit of 2,700 dollars is returned within 21 days.",
        encoding="utf-8",
    )
    document = docx.Document()
    document.add_paragraph("Pets: one cat is allowed with a pet fee of 300 dollars.")
    document.save(folder / "pets.docx")
    make_pdf(folder / "parking.pdf", "Parking space 12 costs 80 dollars a month")
    (folder / "photo.jpg").write_bytes(b"\xff\xd8")
    (folder / ".hidden").mkdir()
    (folder / ".hidden" / "secret.txt").write_text("hidden", encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def agents_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    runner._loaded.clear()


# ------------------------------------------------------------------ files


def test_scan_reads_supported_files_and_skips_hidden(docs):
    found = scan(docs)
    assert sorted(p.name for p in found.files) == ["lease.txt", "parking.pdf", "pets.docx"]
    summary = describe_files(found.files)
    assert summary.startswith("3 files: ") and all(k in summary for k in ("1 text", "1 Word", "1 PDF"))


def test_pdf_and_word_text_is_read_with_pages(docs):
    pdf = passages_of(docs, docs / "parking.pdf")
    assert pdf[0].page == 1 and "Parking space 12" in pdf[0].text
    assert "one cat" in passages_of(docs, docs / "pets.docx")[0].text


def test_long_text_is_split_with_overlap():
    pieces = split(". ".join(f"Sentence number {i} is here" for i in range(200)))
    assert len(pieces) > 3
    assert all(len(p) <= 950 for p in pieces)


def test_search_finds_the_right_passage(docs):
    passages = [p for f in scan(docs).files for p in passages_of(docs, f)]
    index = SearchIndex(passages)
    assert index.search("how much is the deposit")[0].path == "lease.txt"
    assert index.search("can I have a cat")[0].path == "pets.docx"
    assert index.search("zebra quantum") == []


# ----------------------------------------------------------------- router


def test_naming_an_agent_skips_the_model():
    model = FakeModel()
    agents = [store.Agent("Sample_docs helper", "documents_qa", {"folder": "x"})]
    where = route(model, "noir", "sample docs helper: who signed?", load_blueprints(), agents)
    assert (where.kind, where.agent, where.request) == ("run_agent", "Sample_docs helper", "who signed?")
    assert model.schemas == []


def test_model_choice_maps_to_a_route():
    agents = [store.Agent("Contracts helper", "documents_qa", {"folder": "x"})]
    model = FakeModel(choice="use agent: Contracts helper")
    assert route(model, "noir", "who signed?", load_blueprints(), agents).kind == "run_agent"
    model = FakeModel(choice="new agent: Ask my documents")
    assert route(model, "noir", "search my notes", load_blueprints(), agents).blueprint == "documents_qa"


def test_a_helper_that_works_on_text_is_run_from_the_chat_by_its_name_only():
    """Picked by the model for a message that did not name it, such a helper was handed the
    whole message, so its rule was applied to the request itself; and one that turns text
    into one language was picked for a request to turn some into another."""
    cards = [store.Agent("Korean translator", "custom", {"instruction": "Translate the text into Korean.",
                                                         "when": "While it's switched on"}),
             store.Agent("Grammar Fixer", "custom", {"instruction": "Fix the grammar of the text.",
                                                     "when": "When you ask in the chat"}),
             store.Agent("Paper sorter", "custom", {"instruction": "Bills go in Bills.", "folder": "x",
                                                    "when": "When a new file lands in a folder", "then": "Moves the file into a folder"}),
             store.Agent("Contracts helper", "documents_qa", {"folder": "x"})]
    blueprints = load_blueprints()
    for text, choice in (("translate 'thank you very much' into Japanese", "use agent: Korean translator"),
                         ("translate 'good morning' into Korean", "use agent: Korean translator"),
                         ("fix this: me and him goes", "use agent: Grammar Fixer")):
        model = FakeModel(choice=choice)
        assert route(model, "noir", text, blueprints, cards).kind == "chat", text
        assert choice in model.schemas[0]["properties"]["choice"]["enum"]  # the model is asked as before
    # Named, it is that helper's, decided in code, and its name is taken off the text it gets.
    model = FakeModel()
    where = route(model, "noir", "Korean translator: see you tomorrow", blueprints, cards)
    assert (where.kind, where.agent, where.request) == ("run_agent", "Korean translator", "see you tomorrow")
    assert model.schemas == []
    # A change to it is still the model's to see, and helpers that answer from documents
    # or work on a folder's files are picked as before.
    for choice, kind, agent in (("change agent: Korean translator", "change_agent", "Korean translator"),
                                ("use agent: Contracts helper", "run_agent", "Contracts helper"),
                                ("use agent: Paper sorter", "run_agent", "Paper sorter")):
        where = route(FakeModel(choice=choice), "noir", "do what you think is meant", blueprints, cards)
        assert (where.kind, where.agent) == (kind, agent)


def test_asking_for_a_new_agent_never_offers_existing_ones():
    agents = [store.Agent("Contracts helper", "documents_qa", {"folder": "x"})]
    model = FakeModel(choice="chat")
    route(model, "noir", "make me another agent for my contracts", load_blueprints(), agents)
    assert "use agent: Contracts helper" not in model.schemas[0]["properties"]["choice"]["enum"]


# ---------------------------------------------------------------- builder


def builder(model):
    return AgentBuilder(model, "noir", None, load_blueprints())


@pytest.fixture(autouse=True)
def allow_temp_folders(request, monkeypatch):
    # pytest's temp folders are under AppData, which agents may never read.
    if request.node.name != "test_system_folders_are_blocked":
        monkeypatch.setattr("concierge.agents.builder.is_blocked", lambda folder: False)


def test_create_an_agent_end_to_end(docs):
    b = builder(FakeModel())
    events = list(b.start("documents_qa", "make an agent for my documents"))
    assert isinstance(events[-1], Question) and events[-1].id == "folder"

    events = list(b.answer(str(docs)))
    card = events[-1]
    assert isinstance(card, AgentCard)
    assert card.name == "Lease docs helper"
    assert "3 right now" in card.reads[0] and "Lease docs" in card.reads[0]
    assert card.kind == "When you ask in the chat"  # the card the catalog writes, as for any agent

    events = list(b.choose(card.id, "Create it"))
    assert any(isinstance(e, Progress) for e in events)
    result = next(e for e in events if isinstance(e, Result))
    assert result.text.endswith("The deposit is 2,700 dollars.")  # excerpt numbers removed
    assert len(result.sources) == 1  # the made-up excerpt 9 is ignored
    assert events[-1] == AgentList(["Lease docs helper"])
    assert not b.active

    saved = store.find_agent("Lease docs helper")
    assert sorted(saved.contents) == ["lease.txt", "parking.pdf", "pets.docx"]


def test_moving_on_mid_setup_hands_the_message_back(docs):
    b = builder(FakeModel(folder=""))
    list(b.start("documents_qa", "make an agent"))
    events = list(b.answer("what's the capital of Australia?"))
    assert not b.active and b.handoff == "what's the capital of Australia?"
    assert isinstance(events[0], NoirText)


def test_cancel_and_empty_folder(docs, tmp_path):
    b = builder(FakeModel())
    list(b.start("documents_qa", "make an agent"))
    empty = tmp_path / "empty"
    empty.mkdir()
    events = list(b.answer(str(empty)))
    assert "no files I can read" in events[1].text
    list(b.answer("cancel"))
    assert not b.active and store.list_agents() == []


def test_a_yes_typed_at_the_card_creates_and_a_yes_but_does_not(docs):
    # "ok but ..." and "yesterday ..." both begin like a yes, and once made the agent.
    b = builder(FakeModel())
    list(b.start("documents_qa", "make an agent"))
    list(b.answer(str(docs)))
    list(b.answer("ok but I meant another folder"))
    assert store.list_agents() == []
    b = builder(FakeModel())
    list(b.start("documents_qa", "make an agent"))
    list(b.answer(str(docs)))
    list(b.answer("yes please"))
    assert [a.name for a in store.list_agents()] == ["Lease docs helper"]


def test_an_agent_that_works_on_the_same_folders_new_files_is_no_duplicate(docs):
    from concierge.agents import parts

    store.save(store.Agent("Lease sorter", parts.CUSTOM, {"when": parts.NEW_FILE, "then": parts.MOVE,
                                                         "folder": str(docs), "instruction": "x", "name": "Lease sorter"}))
    b = builder(FakeModel())
    list(b.start("documents_qa", "make an agent"))
    assert isinstance(list(b.answer(str(docs)))[-1], AgentCard)  # no "you already have one that reads this folder"


def test_change_the_name_on_the_card(docs):
    b = builder(FakeModel())
    list(b.start("documents_qa", "make an agent"))
    card = list(b.answer(str(docs)))[-1]
    question = list(b.choose(card.id, "Change something"))[-1]
    assert "Name" in question.choices
    list(b.choose(question.id, "Name"))
    card = list(b.answer("Landlord papers"))[-1]
    assert card.name == "Landlord papers"


def test_folder_found_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("concierge.agents.builder.known_folder", lambda name, home=None: tmp_path / name)  # not Windows' real ones
    (tmp_path / "Desktop" / "Work" / "Contracts").mkdir(parents=True)
    (tmp_path / "Documents").mkdir()
    assert find_folders("contracts", None) == [tmp_path / "Desktop" / "Work" / "Contracts"]
    assert find_folders("Documents", None) == [tmp_path / "Documents"]
    assert find_folders("nothing like it", None) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system folders")
def test_system_folders_are_blocked():
    assert is_blocked(Path(os.environ["SystemRoot"]))
    assert is_blocked(Path("C:\\"))
    assert is_blocked(Path.home() / "AppData" / "Local" / "Temp")
    assert not is_blocked(Path.home() / "Documents")


def test_answer_cleanup():
    assert runner.clean_answer("It is due in 30 days [1, 2]. Excerpt [1] was used.") == "It is due in 30 days."


def test_a_blueprint_an_older_version_left_behind_is_passed_over_and_the_app_still_starts(tmp_path, capsys):
    """Installed over a build that had blueprints this one took out, those files stayed in
    the program's folder, and reading them stopped the app before any window opened."""
    import shutil

    from concierge.agents.blueprint import BLUEPRINT_DIR

    for shipped in BLUEPRINT_DIR.glob("*.yaml"):
        shutil.copy(shipped, tmp_path / shipped.name)
    (tmp_path / "an_old_kind.yaml").write_text(
        "id: an_old_kind\nname: An old kind\npitch: x\nwhen: x\nexamples: []\nswitchable: true\nfacts: [x]\n"
        "slots: {}\n", encoding="utf-8")
    loaded = load_blueprints(tmp_path)
    assert set(loaded) == set(load_blueprints()) and "an_old_kind" not in loaded
    assert "an_old_kind.yaml" in capsys.readouterr().out
