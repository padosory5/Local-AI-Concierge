import pytest

from concierge.agents import store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder
from concierge.agents.recipe import CUSTOM, WHILE_ON
from concierge.agents.router import refers_to, route, wants_change
from concierge.events import AgentCard, AgentList, Question
from concierge.quick.agents import BUBBLE, CLIPBOARD, FEW_SECONDS, UNTIL_UNHIGHLIGHT, QuickAgents

BLUEPRINTS = load_blueprints()


class FakeModel:
    """Counts model calls. Rewrites an instruction only when told to."""

    def __init__(self, reply=None, rewrite=None):
        self.reply = reply or {}
        self.rewrite = rewrite
        self.asked = 0

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        yield "번역"

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.asked += 1
        if list(schema["properties"]) == ["instruction"]:
            return {"instruction": self.rewrite or messages[0]["content"].split('"')[1]}
        return {k: self.reply.get(k, "no change") for k in schema["properties"]}


@pytest.fixture(autouse=True)
def agents_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")


@pytest.fixture
def translator():
    agent = store.Agent("Korean translator", CUSTOM, {
        "instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE,
        "keep": FEW_SECONDS, "name": "Korean translator"})
    store.save(agent)
    return agent


def builder(model=None):
    return AgentBuilder(model or FakeModel(), "noir", None, BLUEPRINTS)


# --------------------------------------------------------------- editing


def test_the_users_own_words_change_how_long_it_stays(translator):
    b = builder()
    events = list(b.edit(translator, "Can you make the translate stay on until I unhighlight it"))
    card = events[-1]
    assert isinstance(card, AgentCard) and card.name == "Korean translator"
    assert card.actions[0] == "Save changes"
    assert f"The result stays: {UNTIL_UNHIGHLIGHT}" in card.can_do
    assert b.ollama.asked == 0  # found in code

    events = list(b.choose(card.id, "Save changes"))
    assert events[0].text.startswith("Saved. Korean translator now:")
    assert isinstance(events[-1], AgentList)
    saved = store.find_agent("Korean translator")
    assert saved.slots["keep"] == UNTIL_UNHIGHLIGHT and saved.slots["instruction"] == "Translate the text into Korean."
    assert [a.name for a in store.list_agents()] == ["Korean translator"]  # no "Korean translator 2"


def test_change_the_language_rewrites_what_it_does(translator):
    model = FakeModel(rewrite="Translate the text into Japanese.")
    card = list(builder(model).edit(translator, "make it Japanese"))[-1]
    assert card.can_do[0] == "Does: Translate the text into Japanese."
    assert card.name == "Korean translator"  # a name is never changed behind the user's back


def test_rename(translator):
    card = list(builder().edit(translator, "rename it to My translator"))[-1]
    assert card.name == "My translator"


def test_model_picks_a_setting_when_code_cannot(translator):
    b = builder(FakeModel({"keep": UNTIL_UNHIGHLIGHT}))
    card = list(b.edit(translator, "it vanishes way too quickly, leave it up for me"))[-1]
    assert f"The result stays: {UNTIL_UNHIGHLIGHT}" in card.can_do


def test_unknown_change_says_what_can_change(translator):
    events = list(builder().edit(translator, "make it sing a song"))
    assert "isn't something I can change" in events[0].text
    question = events[-1]
    assert isinstance(question, Question) and "What it does" in question.choices


def test_typed_follow_up_changes_at_the_card(translator):
    b = builder()
    list(b.edit(translator, "make it stay until I unhighlight it"))
    card = list(b.answer("and copy it to the clipboard too"))[-1]
    assert isinstance(card, AgentCard) and card.can_do[1] == f"Shows the result: {CLIPBOARD}"


def test_cancel_an_edit_leaves_it_as_it_was(translator):
    b = builder()
    list(b.edit(translator, "make it stay until I unhighlight it"))
    events = list(b.choose("card", "Cancel"))
    assert events[0].text == "Okay, I left Korean translator as it was."
    assert store.find_agent("Korean translator").slots["keep"] == FEW_SECONDS


def test_asking_for_what_it_already_does(translator):
    store.save(store.Agent("Korean translator", CUSTOM, {**translator.slots, "keep": UNTIL_UNHIGHLIGHT}))
    b = builder()
    events = list(b.edit(store.find_agent("Korean translator"),
                         "Can you make the translate stay on until I unhighlight it"))
    assert "already works that way" in events[0].text and not b.active


# --------------------------------------------------------------- routing


def test_router_knows_a_change_from_a_job(translator):
    agents = store.list_agents()
    assert wants_change("make the Korean translator stay longer", agents[0])
    assert not wants_change("Korean translator: keep calm and carry on", agents[0])
    assert not wants_change("make another Korean translator agent", agents[0])
    assert refers_to("the translation keeps disappearing", agents, BLUEPRINTS).name == "Korean translator"
    where = route(FakeModel(), "noir", "I want the Korean translator to use the clipboard instead",
                  BLUEPRINTS, agents)
    assert where.kind == "change_agent" and where.agent == "Korean translator"


def test_two_agents_alike_need_a_name(translator):
    store.save(store.Agent("Japanese translator", CUSTOM, {"instruction": "Translate the text into Japanese."}))
    assert refers_to("the translation keeps disappearing", store.list_agents(), BLUEPRINTS) is None


def test_make_another_named_agent_is_never_a_job_for_it(translator):
    where = route(FakeModel(), "noir", "make another Korean translator agent", BLUEPRINTS, store.list_agents())
    assert where.kind != "run_agent"  # never translated as if it were text to translate


# --------------------------------------------- settings apply while it's on


def test_changed_settings_reach_an_agent_that_is_on(translator):
    q = QuickAgents(FakeModel(), "noir", None, lambda *a: type("W", (), {"start": lambda s: None,
                    "stop": lambda s: None})(), lambda: type("B", (), {"close": lambda s: None,
                    "pressed": lambda s, x, y: None})())
    q.switch(translator, True)
    changed = store.Agent("Korean translator", CUSTOM, {**translator.slots, "keep": UNTIL_UNHIGHLIGHT})
    q.refresh([changed])
    assert q.active["Korean translator"].slots["keep"] == UNTIL_UNHIGHLIGHT
    q.refresh([])  # deleted elsewhere
    assert not q.is_on("Korean translator")
