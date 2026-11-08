"""What the live runs taught the organizer (concierge/organizer.py, builder.py, engine.py):
a changed folder starts fresh, "from Downloads" is the watched folder, bills and CVs
are never course material, and the ways people say "organize it"."""

from __future__ import annotations

import time
from pathlib import Path

from concierge import organizer as org
from concierge.agents import store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder
from concierge.engine import WANTS_EVERYTHING, WANTS_ORGANIZE
from concierge.events import AgentCard, NoirText, Question
from concierge.organizer import CONTENT, NOT_SURE, ORGANIZER, SOMETHING_ELSE, SUBJECT, Organizer


class CourseModel:
    """Files like the user's Downloads: course material goes to its course, the rest is
    something else, however many course names it mentions."""

    def __init__(self):
        self.asked = []
        self.told = []  # the system notes, with the folders listed
        self.seen = []  # the pictures shown to the vision model

    def list_models(self):
        return ["noir:latest", "qwen3-vl:8b"]

    def capabilities(self, tag):
        return ["vision"] if "vl" in tag else ["completion"]

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        content = messages[-1]["content"].lower()
        self.asked.append(content)
        self.told.append(messages[0]["content"])
        fields = schema["properties"]
        if "what" in fields:  # the vision model, describing a picture
            self.seen.append(messages[-1].get("images"))
            return {"what": "A whiteboard photo: PHYS 122 Lab A5 optics bench notes"}
        if "kind" in fields:
            if any(word in content for word in ("tuition", "statement", "résumé", "resume", "i-20", "certificate")):
                return {"kind": SOMETHING_ELSE, "folder": "PHYS122"}  # a weak model still names a folder
            if "lab" in content or "physics" in content:
                return {"kind": SUBJECT, "folder": "PHYS122"}
            if "cse163" in content or "cse 163" in content or "data science" in content:
                return {"kind": SUBJECT, "folder": "CSE163"}
            return {"kind": SOMETHING_ELSE, "folder": NOT_SURE}
        return {"topic": "physics", "sure": "yes"}


def agent(folder: Path, into: Path) -> store.Agent:
    return store.Agent(name="File organizer", blueprint=ORGANIZER,
                       slots={"folder": str(folder), "by": CONTENT, "groups": "PHYS122, CSE163", "into": str(into),
                              "name": "File organizer"})


def make(tmp_path):
    return Organizer(CourseModel(), "noir", tmp_path / "organizer.json", tmp_path / "organizer_done.json",
                     clock=lambda: time.time() + 1000, settle_seconds=20)


def write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_bill_a_cv_and_a_form_are_never_course_material(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "Desktop" / "College"
    one = make(tmp_path)
    one.switch(agent(downloads, college), True)
    write(downloads, "UWTuitionStatement.txt", "Tuition statement, Autumn 2026. Courses: PHYS 122, CSE 163. Amount due: 4,000.")
    write(downloads, "resume.txt", "Résumé. Experience: teaching assistant, physics lab.")
    write(downloads, "I-20.txt", "Certificate of eligibility, I-20, student status.")
    write(downloads, "lab3.txt", "PHYS 122 Lab A03: analysis and conclusion of the pendulum experiment.")
    write(downloads, "proposal.txt", "CSE163 project proposal: data science on bike trips.")
    one.look()
    assert sorted(p.name for p in downloads.iterdir()) == ["I-20.txt", "UWTuitionStatement.txt", "resume.txt"]
    assert (college / "PHYS122" / "lab3.txt").is_file() and (college / "CSE163" / "proposal.txt").is_file()


def test_changing_the_watched_folder_starts_fresh_there(tmp_path):
    before, after, college = tmp_path / "College", tmp_path / "Downloads", tmp_path / "College"
    write(after, "old-lab.txt", "PHYS 122 lab from last term")
    one = make(tmp_path)
    one.switch(agent(before, college), True)  # watching the destination, by mistake
    changed = agent(after, college)
    one.refresh([changed])  # the saved agent changed under the same name
    one.switch(changed, True)
    one.look()
    assert (after / "old-lab.txt").is_file()  # old at the moment the folder changed: left alone
    write(after, "new-lab.txt", "PHYS 122 lab A04 report")
    one.look()
    assert (college / "PHYS122" / "new-lab.txt").is_file()


def test_the_watched_folder_comes_from_the_words_not_the_destination(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("concierge.agents.builder.is_blocked", lambda folder: False)
    downloads = tmp_path / "Downloads"
    write(downloads, "a.txt", "x")
    (tmp_path / "Desktop" / "College").mkdir(parents=True)
    places = lambda name, home=None: tmp_path / name
    monkeypatch.setattr("concierge.agents.builder.watched_from", lambda text: org.watched_from(text, place=places))
    monkeypatch.setattr("concierge.agents.builder.destination_from", lambda text: org.destination_from(text, tmp_path, place=places))

    class Model:
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            if "folder" in schema["properties"] and "place" in schema["properties"]:
                return {"folder": "College", "place": "Desktop"}  # the mistake the model made live
            return {"choice": "chat"}

    builder = AgentBuilder(Model(), "noir", False, load_blueprints())
    events = list(builder.start(ORGANIZER, "organize my school files from Downloads into a folder on my desktop called "
                                           "College, divided into phys122 and cse163, by what's inside them"))
    card = next(e for e in events if isinstance(e, AgentCard))
    assert builder.draft.slots["folder"] == str(downloads)
    assert builder.draft.slots["into"] == str(tmp_path / "Desktop" / "College")
    assert "Keep the folders in" in " ".join(card.can_do)


def test_a_folder_that_is_the_destination_is_not_watched(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr("concierge.agents.builder.is_blocked", lambda folder: False)
    college = tmp_path / "College"
    college.mkdir()

    class Model:
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            return {"folder": "", "place": "not said"} if "place" in schema["properties"] else {"choice": "chat"}

    builder = AgentBuilder(Model(), "noir", False, load_blueprints())
    list(builder.start(ORGANIZER, "organize my files into folders"))
    builder.draft.slots["into"] = str(college)
    events = list(builder.answer(str(college)))
    assert isinstance(events[-1], Question) and events[-1].id == "folder"
    assert any(isinstance(e, NoirText) and "where the sorted folders go" in e.text for e in events)


def test_the_ways_people_say_organize_it():
    assert WANTS_ORGANIZE.search("can you move the files in downloads depending on which course it is")
    assert WANTS_ORGANIZE.search("Why did you not move the files in downloads")
    assert WANTS_ORGANIZE.search("go through everything in downloads")
    assert WANTS_EVERYTHING.search("go through everything in downloads")
    assert not WANTS_EVERYTHING.search("organize it")
    assert org.watched_from("organize my school files from Downloads into a folder on my desktop called College",
                            place=lambda name, home: Path("/x") / name) == Path("/x/Downloads")
    assert org.watched_from("read the files in my Documents and sort them", place=lambda name, home: Path("/x") / name) == Path("/x/Documents")
    assert org.watched_from("put them on my desktop called College", place=lambda name, home: Path("/x") / name) is None


def test_a_file_that_stayed_keeps_the_reason(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    one.switch(agent(downloads, college), True)
    write(downloads, "UWTuitionStatement.txt", "Tuition statement, Autumn 2026. PHYS 122, CSE 163. Amount due: 4,000.")
    write(downloads, "lab3.txt", "PHYS 122 Lab A03 pendulum")
    one.look()
    skipped = one.last_skipped()
    assert [s["name"] for s in skipped] == ["UWTuitionStatement.txt"]
    assert skipped[0]["why"] == org.NOT_MATERIAL and skipped[0]["where"] == str(downloads)
    assert one.last_moves()[0]["name"] == "lab3.txt"


def test_why_questions_are_recognised():
    from concierge.engine import WANTS_STATUS, WANTS_WHY, _mentions

    for text in ("why didn't you move the receipt?", "why is my tuition statement still in downloads?",
                 "why did you put my tuition pdf in physics", "Why did you not move the files in downloads"):
        assert WANTS_WHY.search(text), text
    assert not WANTS_WHY.search("why is the sky blue")
    assert not WANTS_STATUS.search("why didn't you move the receipt?")
    assert _mentions("why is my tuition statement still in downloads?", "UWTuitionStatement.pdf")
    assert _mentions("why didn't you move the receipt?", "bookstore_receipt.pdf")
    assert _mentions("where did you put the lab handout", "Lab A4 - Handout.pdf")
    assert not _mentions("why didn't you move the receipt?", "Lab A4 - Handout.pdf")


def test_a_question_about_the_chore_never_goes_to_the_web():
    from concierge.engine import ABOUT_CHORES

    for text in ("is the organizer still on? what does it watch", "can you also sort pictures?",
                 "which files did you move today"):
        assert ABOUT_CHORES.search(text), text
    assert not ABOUT_CHORES.search("who won the election")


def test_a_question_about_the_chore_is_a_question_not_a_change_or_a_new_agent():
    from concierge.agents.router import WANTS_NEW, wants_change
    from concierge.engine import ABOUT_CHORES, WANTS_ANSWER

    asks = "can you also sort pictures?"
    assert ABOUT_CHORES.search(asks) and WANTS_ANSWER.search(asks)
    organizer = store.Agent(name="File organizer", blueprint=ORGANIZER, slots={})
    assert not WANTS_NEW.search(asks) and not wants_change(asks, organizer)
    assert WANTS_NEW.search("make a new agent that sorts my pictures")  # that one still builds
    assert not WANTS_ANSWER.search("organize it")


def test_code_and_notebooks_are_course_material_and_data_files_are_not(tmp_path):
    import json

    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    one.switch(agent(downloads, college), True)
    write(downloads, "practice5.py", "# CSE 163\n# Programming Practice 5\nimport networkx as nx\n")
    (downloads / "geopandas_practice.ipynb").write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# CSE163 practice: geopandas\n"]},
        {"cell_type": "code", "source": ["import geopandas as gpd\n"]}]}), encoding="utf-8")
    write(downloads, "settings.json", '{"cse163": true}')
    write(downloads, "trips.csv", "cse163,1")
    one.look()
    assert (college / "CSE163" / "practice5.py").is_file()
    assert (college / "CSE163" / "geopandas_practice.ipynb").is_file()
    assert (downloads / "settings.json").is_file() and (downloads / "trips.csv").is_file()
    assert any("geopandas" in asked for asked in one.ollama.asked)  # the notebook's cells were read


def test_each_move_while_watching_is_told_with_undo(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    told = []
    one.moved = told.append
    one.switch(agent(downloads, college), True)
    write(downloads, "lab4.txt", "PHYS 122 lab 4")
    write(downloads, "UWTuitionStatement.txt", "Tuition statement")
    one.look()
    assert len(told) == 1 and told[0]["name"] == "lab4.txt" and told[0]["folder"] == str(Path("College") / "PHYS122")
    assert told[0]["to"] == str(college / "PHYS122") and one.undo(told[0]["sort"]) == 1
    assert (downloads / "lab4.txt").is_file()
    # A pass asked for in the chat tells the chat instead, not the screen.
    write(downloads, "lab5.txt", "PHYS 122 lab 5")
    list(one.run_once(agent(downloads, college)))
    assert len(told) == 1


def test_the_window_hooks_the_organizer_for_move_notes():
    from concierge.ui.window import ChatHub

    class Organizer:
        changed = moved = None

    class Engine:
        organizer = Organizer()

    hub = ChatHub(Engine())
    hub.on_move(print)
    hub.on_chores(print)
    assert Engine.organizer.moved is print and Engine.organizer.changed is print
    hub_without = ChatHub(object())
    hub_without.on_move(print)  # the practice engine has no organizer: nothing to hook


def sheet(path: Path, words: str) -> None:
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as inside:
        inside.writestr("xl/sharedStrings.xml", f"<sst><si><t>{words}</t></si></sst>")
        inside.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")


def test_a_new_kind_is_asked_about_once_then_sorted(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    asked = []
    one.asked = asked.append
    one.switch(agent(downloads, college), True)
    sheet(downloads / "hw3_data.xlsx", "CSE163 HW3 library checkouts")
    one.look()
    assert (downloads / "hw3_data.xlsx").is_file()  # held back until the user says
    assert len(asked) == 1 and asked[0]["id"] == "kind:File organizer:.xlsx"
    assert asked[0]["text"] == "hw3_data.xlsx looks like CSE163 material. Sort .xlsx files like it from now on?"
    assert one.questions()[0]["count"] == 1
    assert one.last_skipped()[0]["why"] == org.KIND_WAITING.format(ext=".xlsx")
    sheet(downloads / "hw4_data.xlsx", "CSE163 HW4")  # a second one joins the same question
    one.look()
    assert len(asked) == 1 and one.questions()[0]["count"] == 2
    again = make(tmp_path)  # a restart keeps the question
    again.refresh([agent(downloads, college)])
    assert again.questions()[0]["count"] == 2
    assert one.answer("kind:File organizer:.xlsx", True) == 2
    assert (college / "CSE163" / "hw3_data.xlsx").is_file() and (college / "CSE163" / "hw4_data.xlsx").is_file()
    assert one.questions() == [] and one.last_skipped() == []
    sheet(downloads / "hw5_data.xlsx", "CSE163 HW5")
    one.look()
    assert (college / "CSE163" / "hw5_data.xlsx").is_file()  # from now on, no question
    assert len(one.last_moves()) == 3 and len(asked) == 1


def test_no_leaves_that_kind_alone_and_the_answer_survives_a_restart(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    asked = []
    one.asked = asked.append
    one.switch(agent(downloads, college), True)
    write(downloads, "whiteboard.png", "not really a picture")
    one.look()
    assert one.ollama.seen and one.ollama.seen[0]  # the picture went to the vision model
    assert asked[0]["id"] == "kind:File organizer:.png" and "whiteboard.png looks like PHYS122 material" in asked[0]["text"]
    assert one.answer(asked[0]["id"], False) == 0
    assert (downloads / "whiteboard.png").is_file()
    assert one.last_skipped()[0]["why"] == org.KIND_REFUSED.format(ext=".png")
    again = make(tmp_path)
    again.refresh([agent(downloads, college)])
    asked_again = []
    again.asked = asked_again.append
    write(downloads, "whiteboard2.png", "not really a picture either")
    again.look()
    assert (downloads / "whiteboard2.png").is_file() and asked_again == [] and again.questions() == []
    assert again.last_skipped()[0]["why"] == org.KIND_REFUSED.format(ext=".png")
    assert one.answer("kind:File organizer:.nothing", True) == 0


def test_a_file_nothing_can_be_read_from_is_judged_by_its_name(tmp_path):
    downloads, college = tmp_path / "Downloads", tmp_path / "College"
    one = make(tmp_path)
    one.switch(agent(downloads, college), True)
    downloads.mkdir()
    (downloads / "setup.exe").write_bytes(bytes(range(256)) * 8)
    one.look()
    assert (downloads / "setup.exe").is_file()
    assert one.last_skipped()[0]["why"] == org.NO_TEXT
    assert "Judge by the name alone" in one.ollama.asked[-1] or "judge by the name alone" in one.ollama.asked[-1]


def test_a_plain_yes_or_no_in_the_chat_answers_the_question():
    from concierge.engine import _plain_answer

    assert _plain_answer("yes") is True and _plain_answer("Sure!") is True and _plain_answer("네") is True
    assert _plain_answer("no") is False and _plain_answer("No thanks.") is False
    assert _plain_answer("yes but only pdfs") is None and _plain_answer("organize it") is None


def test_the_window_shows_an_organizer_question_like_the_watch_does():
    from concierge.ui.window import ChatHub, WatchBridge

    class Engine:
        answered = None

        def organizer_questions(self):
            return [{"id": "kind:File organizer:.xlsx", "text": "hw3.xlsx looks like CSE163 material. Sort .xlsx files like it from now on?", "count": 1}]

        def organizer_answer(self, id, yes):
            self.answered = (id, yes)
            return 1

    class Overlay:
        watch = None
        refreshed = False

        def refresh_mini(self):
            self.refreshed = True

    engine, overlay = Engine(), Overlay()
    bridge = WatchBridge(ChatHub(engine), overlay)
    assert bridge.today()["noticed"]["id"] == "kind:File organizer:.xlsx"
    bridge.answer("kind:File organizer:.xlsx", True)
    assert engine.answered == ("kind:File organizer:.xlsx", True) and overlay.refreshed
