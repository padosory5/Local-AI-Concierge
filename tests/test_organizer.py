"""The file organizer (concierge/organizer.py): judging, moving, undoing, what counts
as new, and the setup conversation that makes one (the organizer blueprint)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from concierge import organizer as org
from concierge.agents import store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import CREATE_IT, AgentBuilder
from concierge.events import AgentCard, NoirText, Question
from concierge.organizer import BY_NAME, CONTENT, DECIDE, NOT_SURE, ORGANIZER, SOMETHING_ELSE, SUBJECT, Organizer
from concierge.places import known_folder


class FakeModel:
    """Says what a text is about: physics or integrals; anything else it isn't sure of.
    With the user's own folders it picks one of them the same way."""

    def __init__(self):
        self.asked: list[tuple[dict, str]] = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        content = messages[-1]["content"].lower()
        self.asked.append((schema, content))
        subject = "Physics 122 lab report" if "physics" in content else "Calculus: integrals" if "integral" in content else ""
        if "topic" in schema["properties"]:
            return {"topic": subject, "sure": "yes"} if subject else {"topic": "shopping", "sure": "no"}
        choices = schema["properties"]["folder"]["enum"]
        wanted = "Physics 122" if "physics" in content else "Calculus" if "integral" in content else NOT_SURE
        chosen = wanted if wanted in choices else NOT_SURE
        return {"kind": SUBJECT if chosen != NOT_SURE else SOMETHING_ELSE, "folder": chosen}


def agent(folder: Path, groups: str = DECIDE, by: str = CONTENT, into: str = "") -> store.Agent:
    return store.Agent(name="School files", blueprint=ORGANIZER,
                       slots={"folder": str(folder), "by": by, "groups": groups, "into": into, "name": "School files"})


def make(tmp_path, clock=None):
    clock = clock or (lambda: time.time() + 1000)  # everything written in a test counts as settled
    return Organizer(FakeModel(), "noir", tmp_path / "organizer.json", tmp_path / "organizer_done.json",
                     clock=clock, settle_seconds=20)


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_what_was_there_when_it_was_switched_on_is_left_alone(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    write(downloads, "old.txt", "physics from last year")
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    write(downloads, "new.txt", "physics lecture 7")
    one.look()
    assert (downloads / "old.txt").is_file()  # old: never judged
    assert (downloads / "Physics 122 lab report" / "new.txt").is_file()
    assert len(one.ollama.asked) == 1


def test_a_new_document_is_filed_by_its_subject_and_the_move_can_be_undone(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    write(downloads, "lecture7.txt", "Electric fields and Gauss's law, physics lecture 7.")
    write(downloads, "notes.txt", "The integral of x squared from 0 to 1.")
    write(downloads, "holiday.jpg", "not read")
    write(downloads, "data.json", '{"physics": 1}')  # a data file, not a document
    one.look()
    assert (downloads / "Physics 122 lab report" / "lecture7.txt").is_file()
    assert (downloads / "Calculus integrals" / "notes.txt").is_file()  # the colon is not a folder's
    assert (downloads / "holiday.jpg").is_file() and (downloads / "data.json").is_file()
    done = one.done_lately()
    assert [job["text"] for job in done] == ["Put lecture7.txt in Physics 122 lab report", "Put notes.txt in Calculus integrals"]
    assert all(job["undo"] for job in done)
    last = one.last_moves()[0]
    assert (last["name"], last["to"]) == ("notes.txt", str(downloads / "Calculus integrals"))
    assert one.undo(done[0]["sort"]) == 1
    assert (downloads / "lecture7.txt").is_file()
    assert one.done_lately()[0]["undo"] is False and one.done_lately()[-1]["text"] == "Put 1 file back"


def test_a_folder_made_before_is_reused_when_the_subject_matches(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    one.made["School files"] = ["Physics 122", "History 101"]
    write(downloads, "lab3.txt", "physics lab 3 report")
    one.look()
    assert (downloads / "Physics 122" / "lab3.txt").is_file()  # "Physics 122 lab report" shares its words
    assert one.made["School files"] == ["Physics 122", "History 101"]


def test_a_file_it_cannot_tell_stays_and_is_not_asked_about_again(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    write(downloads, "something.txt", "a shopping list: eggs, milk")
    one.look()
    one.look()
    assert (downloads / "something.txt").is_file()
    assert len(one.ollama.asked) == 1


def test_a_download_still_arriving_and_a_fresh_file_wait(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path, clock=lambda: time.time())
    one.switch(agent(downloads), True)
    write(downloads, "paper.txt.crdownload", "physics")
    write(downloads, "paper.txt", "physics lecture")  # written just now
    one.look()
    assert (downloads / "paper.txt").is_file() and one.ollama.asked == []


def test_named_folders_are_the_only_choices(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads, groups="Physics 122, History"), True)
    write(downloads, "a.txt", "physics homework")
    write(downloads, "b.txt", "the integral of x")  # calculus isn't one of the folders
    one.look()
    schema, _ = one.ollama.asked[0]
    assert schema["properties"]["folder"]["enum"] == ["Physics 122", "History", NOT_SURE]
    assert (downloads / "Physics 122" / "a.txt").is_file() and (downloads / "b.txt").is_file()


def test_sorted_folders_can_live_somewhere_else(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "Desktop" / "College"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads, groups="PHYS122, CSE163", into=str(college)), True)
    write(downloads, "a.txt", "physics homework")
    one.ollama.chat_json = lambda *a, **k: {"kind": SUBJECT, "folder": "PHYS122"}
    one.look()
    assert (college / "PHYS122" / "a.txt").is_file()
    job = one.done_lately()[-1]
    assert job["text"] == f"Put a.txt in {Path('College') / 'PHYS122'}" and job["where"] == str(college / "PHYS122")
    assert one.last_moves()[0]["to"] == str(college / "PHYS122")


def test_by_name_never_reads_the_file(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads, by=BY_NAME), True)
    write(downloads, "physics-week-3.txt", "no telling words inside")
    one.look()
    _, content = one.ollama.asked[0]
    assert "first lines" not in content and (downloads / "Physics 122 lab report" / "physics-week-3.txt").is_file()


def test_run_once_goes_through_what_is_new_or_everything(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    write(downloads, "old.txt", "physics from before")
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    for index in range(2):
        write(downloads, f"p{index}.txt", "physics")
    write(downloads, "list.txt", "eggs")
    steps = list(one.run_once(agent(downloads)))
    assert steps[0] == "Reading list.txt (1 of 3)..."
    outcome = steps[-1]
    assert outcome["moved"] == 2 and outcome["left"] == 1 and outcome["looked"] == 3
    assert (downloads / "old.txt").is_file()
    assert list(one.run_once(agent(downloads)))[-1]["looked"] == 0  # nothing new now
    everything = list(one.run_once(agent(downloads), everything=True))[-1]
    assert everything["looked"] == 2 and not (downloads / "old.txt").exists()  # old.txt went too
    assert one.done_lately()[-1]["text"] == "Sorted 1 document in Downloads"


def test_what_was_on_comes_back_when_the_app_starts_again_with_old_files_as_old(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    one = make(tmp_path)
    one.switch(agent(downloads), True)
    write(downloads, "arrived-while-closed.txt", "physics")
    two = make(tmp_path)
    two.refresh([agent(downloads)])
    assert two.is_on("School files")
    two.look()
    assert (downloads / "arrived-while-closed.txt").is_file()  # old at this start: left alone
    two.refresh([])  # deleted since
    assert not two.is_on("School files")


def test_the_words_people_use():
    assert org.groups_from("you decide") == DECIDE
    assert org.groups_from("Physics 122, Calculus and History.") == "Physics 122, Calculus, History"
    assert org.courses_in("divide phys122 and cse163 files into it, and math 124") == "PHYS122, CSE163, MATH124"
    assert org.courses_in("organize my downloads") == ""
    home = Path("C:/Users/me")
    plain = lambda name, base: base / name  # not this computer's real Desktop
    assert org.destination_from("organize it inside my desktop calling it college", home, place=plain) == str(home / "Desktop" / "College")
    assert org.destination_from("put them in Documents", home, place=plain) == str(home / "Documents")
    assert org.destination_from("in a folder called School stuff", home, place=plain) == str(home / "School stuff")
    assert org.destination_from("inside downloads is fine", home, place=plain) == ""
    assert org.destination_from("organize my school files", home, place=plain) is None
    assert org.destination_from("C:/Users/me/Desktop/College please", home, place=plain) == str(Path("C:/Users/me/Desktop/College"))
    assert org.folder_name("Tax: 2026/returns?") == "Tax 2026 returns"
    assert org.closest("physics lab 3 report", ["Physics 122", "History"]) == "Physics 122"
    assert org.closest("job applications", ["Physics 122"]) is None
    assert org.how(agent(Path("C:/x/Downloads"), into="C:/x/Desktop/College")) == (
        "Watches Downloads and moves each new file into folders it names as it goes in C:/x/Desktop/College, "
        "by what's inside each one. A kind of file it hasn't sorted before, it asks about once.")
    reads, can_do, cannot = org.organizer_card({"folder": "C:/x/Downloads", "by": BY_NAME, "groups": "A, B"}, ["x"])
    assert reads == ["New files in Downloads, their names only"]
    assert "Put each one in the right folder of: A, B" in can_do and "Keep the folders inside Downloads" in can_do


# ---------------------------------------------------------- the setup talk


class SetupModel:
    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        fields = schema["properties"]
        if "folder" in fields and "place" in fields:
            return {"folder": "", "place": "not said"}
        return {"choice": "chat"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("concierge.agents.builder.is_blocked", lambda folder: False)  # the test folder lives under AppData
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    write(downloads, "lecture.txt", "physics")
    return downloads


def test_the_setup_asks_the_folder_where_how_to_tell_files_apart_and_which_folders(home):
    builder = AgentBuilder(SetupModel(), "noir", False, load_blueprints())
    events = list(builder.start(ORGANIZER, "organize my school files into folders"))
    assert isinstance(events[-1], Question) and events[-1].id == "folder"
    events = list(builder.answer(str(home)))
    assert [e for e in events if isinstance(e, Question)][-1].id == "into"
    events = list(builder.answer("inside downloads is fine"))
    asked = [e for e in events if isinstance(e, Question)]
    assert asked and asked[-1].id == "by" and asked[-1].choices == [CONTENT, BY_NAME]
    events = list(builder.choose("by", CONTENT))
    assert [e for e in events if isinstance(e, Question)][-1].id == "groups"
    events = list(builder.answer("Physics 122, Calculus"))
    card = next(e for e in events if isinstance(e, AgentCard))
    assert card.kind == "File organizer" and card.name == "File organizer"
    assert "Put each one in the right folder of: Physics 122, Calculus" in card.can_do
    events = list(builder.choose("card", CREATE_IT))
    assert any("ready" in e.text for e in events if isinstance(e, NoirText))
    made = builder.take_created()
    assert made and made.blueprint == ORGANIZER and made.slots["groups"] == "Physics 122, Calculus"
    assert made.slots["into"] == ""
    assert store.find_agent("File organizer") is not None and builder.take_created() is None


def test_what_the_request_already_says_is_not_asked_again(home, tmp_path):
    builder = AgentBuilder(SetupModel(), "noir", False, load_blueprints())
    request = (f"read my school files in {home} and organize them inside my desktop calling it College, "
               "divide phys122 and cse163 files into it by what's inside them")
    list(builder.start(ORGANIZER, request))
    slots = builder.draft.slots
    assert slots["by"] == CONTENT and slots["groups"] == "PHYS122, CSE163"
    assert slots["into"] == str(known_folder("Desktop") / "College")  # the Desktop Windows shows, OneDrive's or not
    assert builder.draft.waiting == "card"
