import pytest

from concierge.agents import planner
from concierge.agents.planner import (
    IdeaPlanner,
    PlanStep,
    assess,
    clean_detail,
    describe_ideas,
    list_ideas,
    load_blocks,
)
from concierge.agents.blueprint import load_blueprints
from concierge.catalog import load_helpers, pick_helper
from concierge.events import IdeaCard, Question
from concierge.fake_engine import FakeEngine
from tests.test_catalog import machine, nvidia

BLOCKS = load_blocks()
BLUEPRINTS = load_blueprints()


def steps(*ids):
    return [PlanStep(BLOCKS[i]) if i != "other" else PlanStep(None, "play music") for i in ids]


BIG_PC = machine(ram=32, gpus=[nvidia(16)])
LAPTOP = machine(ram=16, ram_free=8)


# ---------------------------------------------------------------- judging


def test_every_block_is_well_formed():
    for block in BLOCKS.values():
        assert block.kind in ("trigger", "input", "action", "output")
        assert block.ai in ("none", "small", "large", "vision", "speech")
        assert block.status in ("ready", "planned", "unsupported")
        assert block.status != "unsupported" or block.note  # always say why not
    for blueprint in BLUEPRINTS.values():  # every agent type is built from ready blocks
        assert blueprint.blocks and all(BLOCKS[b].status == "ready" for b in blueprint.blocks)


def test_easy_idea_that_is_not_built_yet():
    a = assess(steps("hotkey", "selected_text", "rewrite", "replace_text"), BIG_PC, 3.8, BLUEPRINTS)
    assert a.level == "not_built"
    assert a.difficulty.startswith("Easy: Elaina's own model")
    assert a.actions[0] == "Save the idea"
    assert [s.status for s in a.steps] == ["not_built", "ready", "ready", "not_built"]


def test_plain_code_idea():
    a = assess(steps("new_screenshot", "copy_clipboard"), BIG_PC, 3.8)
    assert a.level == "not_built" and "no AI model" in a.difficulty


def test_ready_idea_can_be_made_with_its_blueprint():
    a = assess(steps("on_request", "folder_files", "ask_documents"), LAPTOP, 2.1, BLUEPRINTS)
    assert a.level == "ready" and a.blueprint == "documents_qa"
    assert a.actions[0] == "Make it"


def test_switch_on_translator_idea_is_ready():
    a = assess(steps("while_on", "selected_text", "translate", "show_popup"), LAPTOP, 2.1, BLUEPRINTS)
    assert a.level == "ready" and a.blueprint == "custom"  # made from parts, no blueprint of its own


def test_ready_parts_that_no_agent_combines():
    a = assess(steps("on_request", "folder_files", "translate"), BIG_PC, 3.8, BLUEPRINTS)
    assert a.level == "not_built" and "no agent puts them together" in a.verdict


def test_bigger_model_that_fits_is_named_with_its_size():
    a = assess(steps("new_screenshot", "read_image", "save_file"), BIG_PC, 3.8)
    assert a.level == "not_built"
    assert "Qwen 3 VL 8B" in a.difficulty and "6.1 GB download" in a.difficulty


def test_bigger_model_that_does_not_fit():
    small_card = machine(ram=16, gpus=[nvidia(8)])
    a = assess(steps("on_request", "write_long"), small_card, 2.1)
    assert a.level == "too_big" and a.difficulty.startswith("Too big for this computer")
    assert a.actions[0] == "Save the idea"


def test_speech_runs_on_a_laptop_processor():
    a = assess(steps("on_request", "transcribe", "summarize"), LAPTOP, 2.1)
    assert a.level == "not_built" and "Whisper Small" in a.difficulty


def test_unsupported_part_explains_why():
    a = assess(steps("on_request", "money"), BIG_PC, 3.8)
    assert a.level == "not_possible" and "safety" in a.verdict
    assert "Save the idea" not in a.actions


def test_unknown_part_asks_for_more():
    a = assess(steps("on_request", "other"), BIG_PC, 3.8)
    assert a.level == "unclear" and "play music" in a.verdict


def test_only_a_trigger_is_not_a_helper():
    assert assess(steps("hotkey"), BIG_PC, 3.8).level == "unclear"


def test_helper_models_are_listed_best_first_per_role():
    helpers = load_helpers()
    assert {h.role for h in helpers} == {"general", "vision", "speech"}
    model, room, on_cpu = pick_helper("general", BIG_PC, 3.8)
    assert model.tag == "qwen3.5:9b" and room == pytest.approx(11.2, abs=0.2) and not on_cpu


def test_junk_details_are_dropped():
    translate = BLOCKS["translate"]
    assert clean_detail("into Korean", translate) == "into Korean"
    assert clean_detail("audio_to_text", translate) == ""
    assert clean_detail("Translate text", translate) == ""
    assert clean_detail("x" * 60, translate) == ""
    assert clean_detail("play music", None) == "play music"


# ---------------------------------------------------- talking it through


class FakeModel:
    def __init__(self, *plans):
        self.plans = list(plans)
        self.calls = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.calls.append(messages)
        return self.plans.pop(0)


TRANSLATOR = {"title": "Korean translator", "steps": [
    {"block": "hotkey", "detail": "Ctrl+F1"}, {"block": "selected_text", "detail": ""},
    {"block": "translate", "detail": "into Korean"}, {"block": "show_popup", "detail": ""}]}
DOCS = {"title": "PDF helper", "steps": [
    {"block": "on_request", "detail": ""}, {"block": "folder_files", "detail": "Documents"},
    {"block": "ask_documents", "detail": ""}]}


@pytest.fixture(autouse=True)
def ideas_home(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, "ideas_path", lambda: tmp_path / "ideas.json")


def make(*plans):
    return IdeaPlanner(FakeModel(*plans), "elaina", None, lambda: (BIG_PC, 3.8), BLUEPRINTS)


def test_idea_card_then_save_it():
    p = make(TRANSLATOR)
    card = list(p.start("translate what I highlight with Ctrl+F1"))[-1]
    assert isinstance(card, IdeaCard) and card.title == "Korean translator"
    assert card.steps[0].text == "When you press a shortcut key (Ctrl+F1)"
    list(p.choose(card.id, "Save the idea"))
    assert not p.active
    assert [i["title"] for i in list_ideas()] == ["Korean translator"]
    assert "Korean translator: not built yet" in describe_ideas(BIG_PC, 3.8)


def test_change_the_idea_sends_the_old_plan_back_to_the_model():
    p = make(TRANSLATOR, {**TRANSLATOR, "steps": TRANSLATOR["steps"][:3] + [{"block": "replace_text", "detail": ""}]})
    card = list(p.start("translate what I highlight"))[-1]
    question = list(p.choose(card.id, "Change the idea"))[0]
    assert isinstance(question, Question) and question.choices is None
    card = list(p.answer("replace the text instead of a bubble"))[-1]
    assert card.steps[-1].text.startswith("Replace the highlighted text")
    assert p.ollama.calls[1][-1]["content"] == "Change it: replace the text instead of a bubble"
    assert "Korean translator" in p.ollama.calls[1][-2]["content"]  # the earlier plan


def test_ready_idea_hands_over_to_the_agent_builder():
    p = make(DOCS)
    list(p.start("answer questions about my Documents PDFs"))
    assert p.take_blueprint() == ("documents_qa", "answer questions about my Documents PDFs")
    assert not p.active


def test_typing_something_else_drops_the_idea():
    p = make(TRANSLATOR)
    list(p.start("translate what I highlight"))
    assert list(p.answer("what's the capital of Australia?")) == []
    assert not p.active and p.handoff == "what's the capital of Australia?"


def test_saved_ideas_are_judged_again_with_todays_blocks(monkeypatch):
    p = make(TRANSLATOR)
    list(p.choose(list(p.start("translate what I highlight with Ctrl+F1"))[-1].id, "Save the idea"))
    assert "Korean translator: not built yet" in describe_ideas(BIG_PC, 3.8, BLUEPRINTS)
    # Once shortcut keys are built and the shared template can use them, the same idea is ready.
    ready = {k: (planner.Block(**{**v.__dict__, "status": "ready"}) if k == "hotkey" else v)
             for k, v in BLOCKS.items()}
    with_hotkey = {**BLUEPRINTS, "hotkey_translator": planner_blueprint(
        BLUEPRINTS["custom"], ["hotkey", "selected_text", "translate", "show_popup"])}
    monkeypatch.setattr(planner, "load_blocks", lambda: ready)
    assert "Korean translator: ready to make now" in describe_ideas(BIG_PC, 3.8, with_hotkey)


def planner_blueprint(base, blocks):
    from dataclasses import replace
    return replace(base, id="hotkey_translator", blocks=blocks)


def test_typed_key_combination_changes_the_idea():
    # No click on "Change the idea": a reply naming a key is a change, decided in code.
    p = make(TRANSLATOR, {**TRANSLATOR, "steps": [{"block": "hotkey", "detail": "Ctrl+Alt+T"}] + TRANSLATOR["steps"][1:]})
    list(p.start("translate what I highlight"))
    card = list(p.answer("control + alt + T is the shortcut"))[-1]
    assert card.steps[0].text == "When you press a shortcut key (Ctrl+Alt+T)"
    assert len(p.ollama.calls) == 2  # two plans, no extra model call to classify


class ClassifyingModel(FakeModel):
    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        if "about" in schema["properties"]:
            self.calls.append(messages)
            return {"about": self.about}
        return super().chat_json(model, messages, schema, think, keep_alive)


def test_typed_reply_about_something_else_drops_the_idea():
    model = ClassifyingModel(TRANSLATOR)
    model.about = "something else"
    p = IdeaPlanner(model, "elaina", None, lambda: (BIG_PC, 3.8), BLUEPRINTS)
    list(p.start("translate what I highlight"))
    assert list(p.answer("what's the weather like?")) == [] and p.handoff == "what's the weather like?"


def test_typed_reply_about_the_idea_revises_it():
    model = ClassifyingModel(TRANSLATOR, TRANSLATOR)
    model.about = "the idea"
    p = IdeaPlanner(model, "elaina", None, lambda: (BIG_PC, 3.8), BLUEPRINTS)
    list(p.start("translate what I highlight"))
    assert isinstance(list(p.answer("make it Japanese instead"))[-1], IdeaCard)


def test_fake_engine_shows_an_idea_card():
    engine = FakeEngine(delay=0)
    card = next(e for e in engine.send("make a shortcut that translates") if isinstance(e, IdeaCard))
    assert card.actions == ["Save the idea", "Change the idea", "Cancel"]
    assert any("Saved" in getattr(e, "text", "") for e in engine.choose(card.id, "Save the idea"))


def test_highlight_ideas_work_while_switched_on_unless_a_key_was_asked_for():
    from concierge.agents.planner import settle_triggers
    picked = steps("hotkey", "selected_text", "translate", "show_popup")
    settled = settle_triggers(picked, "explain difficult English words I highlight", BLOCKS)
    assert [s.block.id for s in settled] == ["while_on", "selected_text", "translate", "show_popup"]
    kept = settle_triggers(picked, "translate what I highlight when I press Ctrl+F1", BLOCKS)
    assert kept[0].block.id == "hotkey"
    added = settle_triggers(steps("selected_text", "translate"), "translate what I highlight", BLOCKS)
    assert added[0].block.id == "while_on"
    chat = settle_triggers(steps("on_request", "summarize"), "summarize what I paste", BLOCKS)
    assert [s.block.id for s in chat] == ["on_request", "summarize"]  # no highlight: left alone


def test_text_pasted_in_the_chat_needs_no_clipboard_part():
    from concierge.agents.planner import settle_triggers
    settled = settle_triggers(steps("on_request", "clipboard_in", "rewrite"), "fix sentences I paste here", BLOCKS)
    assert [s.block.id for s in settled] == ["on_request", "rewrite"]
