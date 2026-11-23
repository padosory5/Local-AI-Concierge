"""What the eval of helpers worked out by talking runs on (concierge/designer_eval.py): the
made-up home that stands in for the user's, the made-up files, what its checks are made
of, and what it does when it cannot run. None of it needs a model: the conversations
themselves are played with the real ones, by hand."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from concierge import accounts, designer_eval, noir, places
from concierge import engine as engine_mod
from concierge.agents import builder, designer, parts
from concierge.agents.designer import DesignerError
from concierge.agents.files import read_pages
from concierge.designer_eval import (CONVERSATIONS, HOBBY_PICTURES, HOUSE, HOUSE_PAPERS, KOREAN_HOME, KOREAN_WANTS,
                                     MANUALS, SHOP, SHOP_LATER, SHOP_SAYS, SHOP_SAYS_TWO, SHOP_WANTS, SHOP_WANTS_TWO,
                                     Bubbles, Home, NoWatcher, Plan, Play, Run, Talk, aged, as_wanted, card_in,
                                     claims_done, drop, ends_asking, first_wrong, folder_like, question_in, result_in,
                                     words_in)
from concierge.events import AgentCard, AgentList, NoirText, Question, Result, Thinking
from concierge.ollama import OllamaError


def test_the_evals_check_for_claims_tells_now_from_later():
    assert claims_done("It is now on, and you can undo any move.")
    assert claims_done("Great, I've created it for you.")
    assert claims_done("Everything is up and running.")
    assert not claims_done("It will only move new ones that arrive while it is running.")
    assert not claims_done("Once it is on, new files get sorted as they land.")
    assert not claims_done("The card below has the button to create it.")


def test_the_made_up_home_is_all_the_app_sees_and_is_left_again(tmp_path):
    before_env = {name: os.environ.get(name) for name in ("LOCALAPPDATA", "XDG_DATA_HOME", "USERPROFILE", "HOME")}
    before = {module: (module.known_folder, getattr(module, "is_blocked", None))
              for module in (places, builder, designer, parts)}
    home = Home(tmp_path / "eval")
    home.move_in()
    try:
        assert Path.home() == home.home and noir.data_dir().is_relative_to(tmp_path / "eval" / "appdata")
        # Every module asks the made-up home, each through the reference it holds itself.
        for module in (places, builder, designer, parts):
            assert module.known_folder("Desktop") == home.home / "OneDrive" / "바탕 화면", module.__name__
            assert module.known_folder("Downloads") == home.downloads and module.known_folder("home") == home.home
            assert module.known_folder("Music") == home.home / "Music"
        # And so would a module added later: none of the app's is left with the real one.
        for name, module in list(sys.modules.items()):
            if module is not None and name.startswith("concierge.") and "known_folder" in vars(module):
                assert module.known_folder == home.place, name
        # A folder is one a helper may use when it is in the made-up home, and only then.
        for module in (builder, designer):
            assert not module.is_blocked(home.downloads) and not module.is_blocked(home.desktop / "New")
            assert module.is_blocked(tmp_path) and module.is_blocked(home.appdata) and module.is_blocked(Path.cwd())
        (home.documents / "Papers").mkdir()
        assert builder.find_folders("Papers", None) == [home.documents / "Papers"]  # looked for by name, here
        assert builder.find_folders("Desktop", None) == [home.desktop]
    finally:
        home.leave()
    assert {name: os.environ.get(name) for name in before_env} == before_env
    for module, (known, blocked) in before.items():
        assert module.known_folder is known and getattr(module, "is_blocked", None) is blocked, module.__name__
    home.leave()  # twice changes nothing


def test_a_home_that_did_not_take_starts_nothing(tmp_path, monkeypatch):
    home = Home(tmp_path / "eval")
    monkeypatch.setattr(noir, "data_dir", lambda: Path("C:/Users/someone/AppData/Local/NoirAgents"))
    before = builder.known_folder
    try:
        home.move_in()
    except RuntimeError as problem:
        assert "never reach the user's own folders" in str(problem)
    else:
        raise AssertionError("it moved in with the app's data somewhere else")
    assert builder.known_folder is before  # and what it had replaced by then is put back


def test_the_made_up_files_are_the_kinds_their_names_say(tmp_path):
    from PIL import Image

    for number, files in enumerate((SHOP, SHOP_LATER, HOUSE, HOUSE_PAPERS, MANUALS, KOREAN_HOME, HOBBY_PICTURES)):
        drop(tmp_path / str(number), files)
        assert sorted(path.name for path in (tmp_path / str(number)).iterdir()) == sorted(files)

    def text(folder: int, name: str) -> str:
        return "\n".join(words for _, words in read_pages(tmp_path / str(folder) / name))

    assert "INVOICE 88120" in text(0, "invoice_velo_parts_88120.pdf")  # a PDF with its text
    assert "staff rota, November" in text(0, "staff_rota_november.docx")
    assert "Basic tune-up" in text(0, "price_list_spring.xlsx")
    assert "Simmer the beans" in text(0, "recipe_feijoada.txt")
    assert text(0, "label_printer_setup.exe") == "" and text(0, "shop_radio_mix.mp3") == ""  # nothing to read
    assert Image.open(tmp_path / "0" / "whiteboard_jobs.png").size == (900, 470)  # a picture with writing in it
    assert Image.open(tmp_path / "0" / "IMG_2207.jpg").size == (1200, 800)  # a photo with none
    assert "한빛초등학교" in text(5, "가정통신문_11월.docx") and "청구금액" in text(5, "전기요금_청구서_10월.txt")
    assert "top up the pressure" in text(4, "boiler_quick_guide.pdf")
    # What each person wants, and what they say when it came out otherwise, is about files they have.
    assert set(SHOP_WANTS) <= set(SHOP) and set(SHOP_SAYS) == set(SHOP_WANTS) and set(SHOP_WANTS_TWO) == set(SHOP_WANTS)
    assert set(SHOP_WANTS_TWO.values()) == set(SHOP_SAYS_TWO) and set(KOREAN_WANTS) <= set(KOREAN_HOME)


def test_files_that_have_been_there_a_while_are_a_minute_apart_and_the_last_is_the_newest(tmp_path):
    import time

    aged(tmp_path, SHOP, days=2)
    times = [(tmp_path / name).stat().st_mtime for name in SHOP]
    assert times == sorted(times) and all(round(later - earlier) == 60 for earlier, later in zip(times, times[1:]))
    assert 2 * 86400 + 300 <= time.time() - times[-1] < 2 * 86400 + 400  # the newest: two days and five minutes old
    # So the eight a try-out reads are the last eight of the list, whatever order the disk gives them in.
    newest = sorted(SHOP, key=lambda name: (tmp_path / name).stat().st_mtime)[-8:]
    assert newest == list(SHOP)[-8:] and set(SHOP_WANTS) <= set(newest)


def test_every_word_of_a_turn_is_printed_and_kept(tmp_path, capsys):
    run = Run(tmp_path / "eval")
    inside = str(run.home.downloads / "Boat")
    events = [Thinking("Working it out"), NoirText("It would watch "), NoirText(f"{run.home.downloads}."),
              Result("Try-out", f"Tried on 1 file.\nboat.pdf → {inside}"),
              AgentCard("card", "Paper sorter", "When a new file lands in Downloads", ["New files"], ["Rule: boats"],
                        ["Delete a file"], "the built-in model", ["Create it", "Cancel"]),
              Question("design", "Is that right?")]
    assert run.show(iter(events), "tidy my downloads") == events
    assert run.said == ["It would watch ~" + os.sep + "Downloads.", "Is that right?"]  # the long temporary path as ~
    shown = capsys.readouterr().out
    assert str(tmp_path) not in shown
    for words in ("USER  tidy my downloads", "[think] Working it out", "NOIR  It would watch ~", "RESULT (Try-out):",
                  "boat.pdf → ~", "CARD Paper sorter (When a new file lands in Downloads)", "- Rule: boats",
                  "- never: Delete a file", "buttons ['Create it', 'Cancel']", "NOIR  Is that right?"):
        assert words in shown, words
    run.check(True, "one thing held")
    run.check(False, "another did not")
    assert run.checks == [True, False] and run.failed == ["another did not"]
    assert "  OK    one thing held\n  FAIL  another did not" in capsys.readouterr().out


def test_what_the_checks_are_made_of():
    # Where a file came out, held against what the person wants: a word of the folder, or "" for staying.
    assert as_wanted("Velo Parts", "velo") and as_wanted("", "") and not as_wanted("Bills", "velo") and not as_wanted("Bills", "")
    assert folder_like(["Velo Parts", "Bills"], "bill") == "Bills" and folder_like(["Velo Parts"], "kestrel") == ""
    rows = [{"name": "a.pdf", "choice": "Bills"}, {"name": "b.pdf", "choice": ""}, {"name": "c.pdf", "choice": "Bills"}]
    assert first_wrong(rows, {"a.pdf": "bill", "b.pdf": "", "c.pdf": "velo", "not_tried.pdf": "velo"}) == "c.pdf"
    assert first_wrong(rows, {"a.pdf": "bill", "b.pdf": ""}) == ""
    # What an answer put on the screen.
    card = AgentCard("card", "Sorter", "When a new file lands in Downloads", [], [], [], "the built-in model", ["Create it"])
    events = [Thinking("hm"), NoirText("It rains. "), Result("Try-out", "Tried on 2 files."), card,
              Question("carry_on", "Carry on with the helper we were working out?", ["Carry on", "Drop it"]),
              AgentList(["Sorter"], [], [])]
    assert card_in(events) is card and question_in(events).id == "carry_on" and result_in(events, "Try-out").text == "Tried on 2 files."
    assert result_in(events, "Sorter") is None and card_in([NoirText("hello")]) is None
    assert words_in(events) == "It rains.  Tried on 2 files. Carry on with the helper we were working out?"
    # The last thing drawn is the question with its two buttons: whatever was said came before it.
    assert ends_asking(events, "carry_on") and not ends_asking(events, "first_pass")
    assert not ends_asking([events[4], NoirText("and one more thing")], "carry_on")
    assert not ends_asking([Question("carry_on", "Carry on?", ["Carry on"])], "carry_on")


def test_a_helper_switched_on_in_the_eval_never_listens_to_the_real_mouse(tmp_path, monkeypatch):
    """With the real watcher, a helper for highlighted text made in the eval would read
    whatever the user highlights in any program while it runs, and show bubbles on their screen."""
    monkeypatch.setattr(designer_eval, "card_memory", lambda: None)
    talk = Talk(Play(tmp_path), "one", "a conversation")
    quick = talk._pretend_quick(None, "noir", None)
    assert isinstance(quick._make_watcher(lambda *more: None), NoWatcher)
    assert quick._make_bubble() is talk.bubbles and isinstance(talk.bubbles, Bubbles)
    quick._set_clipboard("copied")
    assert talk.copied == ["copied"] and quick._highlighted() == ""
    talk.bubbles.show("Working on it...", None, title="Explainer")
    assert talk.bubbles.shown == [("Explainer", "Working on it...")]


def test_the_conversations_are_listed_and_a_name_that_is_none_of_them_plays_nothing(capsys, monkeypatch):
    names = [script.__name__ for script in CONVERSATIONS]
    assert names == ["thin", "notes", "highlight", "chat", "documents", "cannot", "korean", "at_once", "called_off",
                     "aside", "change", "by_hand", "trouble"]
    assert all((script.__doc__ or "").strip() for script in CONVERSATIONS)
    monkeypatch.setattr(designer_eval.tempfile, "mkdtemp", lambda **more: pytest.fail("a made-up home was built"))
    assert designer_eval.main(["--list"]) == 0
    shown = capsys.readouterr().out
    assert all(f"{name:<11} " in shown for name in names)
    assert designer_eval.main(["--only", "thin", "nonsense"]) == 2
    assert "No conversation is called nonsense." in capsys.readouterr().out
    # A plan is charged for every turn: only the ChatGPT plan, and one conversation at a time.
    assert designer_eval.main(["--plan", "claude", "--only", "thin"]) == 2
    assert "Only the ChatGPT plan can be played with" in capsys.readouterr().out
    assert designer_eval.main(["--plan", "codex", "--only", "thin", "notes"]) == 2
    assert "one conversation at a time" in capsys.readouterr().out
    assert designer_eval.main(["--plan", "codex"]) == 2


def test_a_play_through_the_plan_is_designed_by_the_plan(tmp_path, capsys, monkeypatch):
    """The designer is handed the engine's way of choosing who designs when the engine
    starts. A play "through the plan" once set the plan on the engine alone: the local
    model talked the whole conversation through, nothing reached the plan, and the line
    above the conversation named the plan's model all the same."""
    chosen_at_start = []

    class Engine:
        def __init__(self, ollama):
            self.ollama = ollama
            self.folderwatch = type("Watch", (), {"moved": None, "stayed": None, "_thread": None})()
            self.designer = None

        def _design_model(self):
            return designer.DesignModel(lambda *_: {}, "Gemma 4 12B", here=True)

        def _local_designer(self):
            return type("Entry", (), {"tag": "gemma4:12b"})()

        def startup(self):
            # As the real engine does: the designer keeps the method it was given now.
            self.designer = type("Designer", (), {})()
            self.designer.design_model = self._design_model
            chosen_at_start.append(self.designer.design_model)
            return iter(())

        def close(self):
            pass

    class Quiet:
        calls: list = []

        def unload(self, tag):
            pass

    plan_model = designer.DesignModel(lambda *_: {}, "GPT X", here=False)
    plan = type("FakePlan", (), {"model": lambda self: plan_model, "calls": None})()
    monkeypatch.setattr(designer_eval, "NoirEngine", Engine)
    monkeypatch.setattr(designer_eval, "Counted", Quiet)
    monkeypatch.setattr(designer_eval, "card_memory", lambda: None)
    talk = Talk(Play(tmp_path, plan=plan), "one", "a conversation")
    try:
        assert talk.open(lambda home: None) is not None
        assert chosen_at_start and talk.engine.designer.design_model() is plan_model
        assert talk.design_tag == "" and talk.play.designer_name == "GPT X"
        assert "(design model: GPT X, off this computer;" in capsys.readouterr().out
    finally:
        talk.close()


@pytest.mark.parametrize("read, loaded, holds", [
    (5_700, ["gemma4:12b"], True),
    (6_500, ["gemma4:12b"], False),  # with what it wrote, 0.8 of the room or more
    (5_700, ["gemma4:12b", "noir:latest"], False),  # both models in memory at once
])
def test_a_play_fails_when_a_turn_nears_the_design_models_room_or_both_models_were_in_memory(
        tmp_path, capsys, monkeypatch, read, loaded, holds):
    """The eval of the setups before this one failed a run whose longest turn filled 0.8 of
    its room or more. This one only printed the figure, so a note or a conversation that
    grew past the room (Ollama then drops the earliest turns) would have gone unnoticed."""
    def script(talk):
        """One conversation, as its figures would come back."""
        talk.design_tag = "gemma4:12b"
        talk.ollama = type("Calls", (), {"calls": [{"model": "gemma4:12b", "loaded": loaded}]})()
        talk.turns = [{"label": "hi", "seconds": 1.0, "forms": [{"model": "gemma4:12b", "seconds": 1.0, "read": read,
                                                                 "wrote": 100}], "others": 0, "card": None,
                       "loaded": loaded}]
        talk.check(True, "what the conversation was about")

    monkeypatch.setattr(designer_eval, "CONVERSATIONS", [script])
    monkeypatch.setattr(designer_eval, "card_memory", lambda: None)
    monkeypatch.setattr(designer_eval, "Counted", type("Quiet", (), {"loaded": lambda self: []}))
    assert designer_eval.ROOM_SHARE * designer.DESIGN_CONTEXT > 5_800  # the whole plays' fullest form held 5,805
    play = Play(tmp_path)
    assert play.go() is holds
    shown = capsys.readouterr().out
    assert ("  OK    " if read < 6_000 else "  FAIL  ") + f"the fullest form held {read + 100:,} tokens" in shown
    together = "the design model and the built-in model were never in memory together"
    assert ("  OK    " if len(loaded) == 1 else "  FAIL  ") + together in shown
    assert f"{2 + holds} of 3 checks passed." in shown and ("the play" in shown)


def test_with_ollama_stopped_it_says_so_fails_and_leaves_no_trace(capsys, monkeypatch):
    class Stopped(designer_eval.Counted):
        def ensure_running(self, wait_seconds: float = 20) -> None:
            raise OllamaError("Ollama isn't running.")

        def loaded(self) -> list[dict]:
            return []

        def unload(self, name: str) -> None:
            pass

    made = []
    real = designer_eval.tempfile.mkdtemp
    monkeypatch.setattr(designer_eval.tempfile, "mkdtemp", lambda **more: made.append(real(**more)) or made[-1])
    monkeypatch.setattr(designer_eval, "Counted", Stopped)
    monkeypatch.setattr(designer_eval, "card_memory", lambda: None)
    env = {name: os.environ.get(name) for name in ("LOCALAPPDATA", "XDG_DATA_HOME", "USERPROFILE", "HOME")}
    before = (builder.known_folder, engine_mod.QuickAgents)
    assert designer_eval.main(["--only", "thin", "cannot"]) == 1
    shown = capsys.readouterr().out
    assert shown.count("Noir isn't running: Ollama isn't running.") == 2
    assert shown.count("FAIL  the engine started") == 2 and "0 of 2 checks passed." in shown
    assert "no turn of the design model" in shown and "after the play: None; in memory: nothing" in shown
    assert shown.rstrip().endswith("0 of 2 checks passed in 0s") or "0 of 2 checks passed in" in shown.rstrip().splitlines()[-1]
    # Nothing is left behind: the made-up homes are gone and the app sees the real computer again.
    assert len(made) == 1 and not Path(made[0]).exists()
    assert (builder.known_folder, engine_mod.QuickAgents) == before
    assert {name: os.environ.get(name) for name in env} == env


def test_a_plan_is_sent_nothing_of_the_users_own(tmp_path, monkeypatch):
    """One conversation may be played with the user's ChatGPT plan designing. The plan's app
    runs with their real home folder, where its sign-in is, so what is sent is looked
    through for that folder and its name before it goes."""
    sent = []

    class SignedIn:
        def __init__(self, run=None, popen=None, home=None):
            pass

        def status(self, app, fresh=False):
            return {"installed": True, "signed_in": True, "models": [{"id": "gpt-x", "name": "GPT X"}]}

    class Writes:
        def __init__(self, accounts_, app, model, system=""):
            assert system == ""  # no persona goes along: it says what this computer is

        def chat(self, model, messages, think=None, options=None, keep_alive=None):
            sent.append(messages[-1]["content"])
            yield '{"heard": "They have said what they want done", "question": ""}'

    monkeypatch.setattr(accounts, "Accounts", SignedIn)
    monkeypatch.setattr(accounts, "AppModel", Writes)
    real_home = tmp_path / "Users" / "marisol"
    plan = Plan({"USERPROFILE": str(real_home)}, real_home)
    assert plan.ready() and (plan.model_id, plan.model_name) == ("gpt-x", "GPT X")
    plan.calls = []
    model = plan.model()
    assert not model.here and model.name == "GPT X"
    turns = [{"role": "user", "content": "tidy my downloads"}]
    filled = model.fill("A note with nothing of theirs in it.", turns, designer.OPENING_SCHEMA)
    assert filled["heard"] == designer.TOLD and len(sent) == 1 and "tidy my downloads" in sent[0]
    assert [call["model"] for call in plan.calls] == ["plan"] and plan.calls[0]["form"] == filled
    assert accounts.subprocess is designer_eval.subprocess  # the stand-in is only there while the app runs
    for note, said in ((f"Folders in {real_home}\\Documents: Papers.", "tidy my downloads"),
                       ("A note.", "my name is Marisol and my downloads are a mess")):
        with pytest.raises(DesignerError, match="something of the user's own"):
            model.fill(note, [{"role": "user", "content": said}], designer.OPENING_SCHEMA)
    assert len(sent) == 1 and len(plan.calls) == 1  # nothing more went out
    # Not signed in, or no model listed: it is not played with.
    monkeypatch.setattr(SignedIn, "status", lambda self, app, fresh=False: {"installed": True, "signed_in": False, "models": []})
    assert not Plan({}, real_home).ready()
