import pytest

from concierge.agents import recipe, store
from concierge.agents.blueprint import load_blueprints
from concierge.agents.builder import AgentBuilder
from concierge.agents.recipe import CUSTOM, IN_CHAT, WHILE_ON
from concierge.agents.router import refers_to, route
from concierge.events import AgentCard, AgentList, Question, Result, Thinking
from concierge.quick.agents import BOTH, BUBBLE, CLIPBOARD, UNTIL_UNHIGHLIGHT

BLUEPRINTS = load_blueprints()


class FakeModel:
    """Writes recipes and rewrites instructions from canned answers."""

    def __init__(self, recipe_reply=None, rewrite=None):
        self.recipe_reply = recipe_reply or {
            "name": "Word explainer",
            "instruction": "Explain this English word in simple Korean, with one example sentence.",
            "example": "serendipity",
        }
        self.rewrite = rewrite
        self.asked = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.asked.append(list(schema["properties"]))
        if "example" in schema["properties"]:
            return self.recipe_reply
        if list(schema["properties"]) == ["instruction"]:
            old = messages[0]["content"].split('"')[1]
            return {"instruction": self.rewrite or old}
        return {k: "no change" for k in schema["properties"]}

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        yield f"done: {messages[-1]['content']}"


@pytest.fixture(autouse=True)
def agents_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")


def builder(model=None):
    return AgentBuilder(model or FakeModel(), "noir", None, BLUEPRINTS)


# ---------------------------------------------------------------- making


def test_compose_a_switch_on_agent_from_parts():
    b = builder()
    events = list(b.compose("explain hard English words I highlight, simply, in Korean",
                            ["while_on", "selected_text", "translate", "show_popup"]))
    step = next(e for e in events if isinstance(e, Thinking))
    assert step.text.startswith('Wrote what it does: "Explain this English word')
    card = events[-1]
    assert isinstance(card, AgentCard) and card.name == "Word explainer" and card.kind == "Made from parts"
    assert card.can_do[0] == "Does: Explain this English word in simple Korean, with one example sentence."
    assert card.can_do[1] == f"Shows the result: {BUBBLE}"
    assert card.reads[0].startswith("Text you highlight")

    events = list(b.choose(card.id, "Create it"))
    result = next(e for e in events if isinstance(e, Result))
    assert result.text == 'Test: "serendipity"\ndone: serendipity'
    assert "Switch it on in your helpers list" in events[-3].text
    assert isinstance(events[-1], AgentList)
    saved = store.find_agent("Word explainer")
    assert saved.blueprint == CUSTOM and saved.slots["when"] == WHILE_ON
    assert recipe.is_switchable(saved, BLUEPRINTS)


def test_compose_a_chat_agent():
    model = FakeModel({"name": "Summarizer", "instruction": "Summarize the text in three bullet points.",
                       "example": "A long paragraph."})
    card = list(builder(model).compose("summarize text I paste in the chat", ["on_request", "summarize"]))[-1]
    assert card.reads[0].startswith("What you send it in the chat")
    assert card.can_do == ["Does: Summarize the text in three bullet points.", "Answers in the chat"]


def test_the_users_words_decide_how_it_shows_the_result():
    # The model's parts said "clipboard" for "translate my highlighted texts"
    # and the user saw nothing: a highlight helper shows a bubble unless asked.
    card = list(builder().compose("explain words I highlight",
                                  ["while_on", "selected_text", "translate", "copy_clipboard"]))[-1]
    assert card.can_do[1] == f"Shows the result: {BUBBLE}"
    card = list(builder().compose("explain words I highlight and copy them to the clipboard",
                                  ["while_on", "selected_text", "translate"]))[-1]
    assert card.can_do[1] == f"Shows the result: {CLIPBOARD}"
    card = list(builder().compose("show it above the text and copy it", ["while_on", "selected_text"]))[-1]
    assert card.can_do[1] == f"Shows the result: {BOTH}"


def test_a_translator_without_a_language_asks_which():
    model = FakeModel({"name": "Highlight translator", "instruction": "Translate the highlighted text.",
                       "example": "Good morning"})
    b = builder(model)
    question = list(b.compose("translate my highlighted texts", ["while_on", "selected_text", "translate"]))[-1]
    assert isinstance(question, Question) and question.id == "target_language" and "Korean" in question.choices
    card = list(b.choose(question.id, "Korean"))[-1]
    assert card.can_do[0] == "Does: Translate the text into Korean."


def test_a_language_in_the_request_is_used_without_asking():
    model = FakeModel({"name": "Highlight translator", "instruction": "Translate the highlighted text.",
                       "example": "Good morning"})
    card = list(builder(model).compose("translate what I highlight into Korean", ["while_on", "selected_text"]))[-1]
    assert isinstance(card, AgentCard) and card.can_do[0] == "Does: Translate the text into Korean."


def test_same_instruction_twice_asks_first():
    b = builder()
    list(b.choose(list(b.compose("x", ["while_on", "selected_text", "translate"]))[-1].id, "Create it"))
    question = list(builder().compose("x again", ["while_on", "selected_text", "translate"]))[-1]
    assert isinstance(question, Question) and question.id == "duplicate"
    assert question.choices[0] == "Use Word explainer"


def test_a_name_already_taken_gets_a_number():
    store.save(store.Agent("Word explainer", CUSTOM, {"instruction": "Something else entirely."}))
    card = list(builder().compose("x", ["while_on", "selected_text", "translate"]))[-1]
    assert card.name == "Word explainer 2"


# -------------------------------------------------------------- changing


@pytest.fixture
def explainer():
    agent = store.Agent("Word explainer", CUSTOM, {
        "instruction": "Explain this English word in simple Korean.", "when": WHILE_ON,
        "show": BUBBLE, "keep": UNTIL_UNHIGHLIGHT, "name": "Word explainer"})
    store.save(agent)
    return agent


def test_change_what_it_does_by_talking(explainer):
    model = FakeModel(rewrite="Explain this English word in simple Japanese.")
    card = list(builder(model).edit(explainer, "explain them in Japanese instead"))[-1]
    assert isinstance(card, AgentCard) and card.actions[0] == "Save changes"
    assert card.can_do[0] == "Does: Explain this English word in simple Japanese."


def test_change_a_setting_needs_no_rewrite(explainer):
    model = FakeModel()
    card = list(builder(model).edit(explainer, "copy it to the clipboard instead"))[-1]
    assert card.can_do[1] == f"Shows the result: {CLIPBOARD}"
    assert ["instruction"] not in model.asked  # found in code, no model needed


def test_change_it_to_work_in_the_chat(explainer):
    b = builder()
    question = list(b.edit(explainer, "make it sing"))[-1]  # nothing matches: what can change
    assert isinstance(question, Question) and "What it does" in question.choices
    list(b.choose(question.id, "When it works"))
    card = list(b.choose("when", IN_CHAT))[-1]
    assert card.can_do[-1] == "Answers in the chat"
    events = list(b.choose(card.id, "Save changes"))
    assert events[0].text.startswith("Saved. Word explainer now:")
    assert not recipe.is_switchable(store.find_agent("Word explainer"), BLUEPRINTS)


def test_typed_new_job_from_the_change_menu(explainer):
    b = builder(FakeModel(rewrite="Give three synonyms of the word."))
    list(b.edit(explainer, "make it sing"))
    question = list(b.choose("change", "What it does"))[-1]
    assert question.id == "instruction" and question.choices is None
    card = list(b.answer("give me synonyms instead"))[-1]
    assert card.can_do[0] == "Does: Give three synonyms of the word."


# ---------------------------------------------------------------- running


def test_run_instruction_returns_only_the_result():
    model = FakeModel()
    assert recipe.run_instruction(model, "noir", "Fix the grammar.", "me go") == "done: me go"


def test_target_language_only_for_translators():
    assert recipe.target_language("Translate the text into Korean.") == "Korean"
    assert recipe.target_language("Explain this English word in simple Korean.") is None


# -------------------------------------------------------------- old agents


def test_old_translators_become_agents_from_parts():
    store.save(store.Agent("Korean translator", "translate_selection",
                           {"language": "Korean", "show": CLIPBOARD, "name": "Korean translator"}))
    assert recipe.migrate() == ["Korean translator"]
    agent = store.find_agent("Korean translator")
    assert agent.blueprint == CUSTOM
    assert agent.slots["instruction"] == "Translate the text into Korean."
    assert agent.slots["show"] == CLIPBOARD and agent.slots["keep"] == UNTIL_UNHIGHLIGHT
    assert recipe.migrate() == []  # only once


# ---------------------------------------------------------------- routing


def test_agents_from_parts_are_found_by_their_words(explainer):
    store.save(store.Agent("Korean translator", CUSTOM, {"instruction": "Translate the text into Korean."}))
    agents = store.list_agents()
    assert refers_to("the translation keeps disappearing", agents, BLUEPRINTS).name == "Korean translator"
    assert refers_to("can the explanation be shorter", agents, BLUEPRINTS).name == "Word explainer"


def test_the_shared_template_is_never_offered_as_a_kind_of_agent():
    class Chooser:
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            self.choices = schema["properties"]["choice"]["enum"]
            return {"choice": "chat"}

    chooser = Chooser()
    route(chooser, "noir", "make me an agent that fixes my grammar", BLUEPRINTS, [])
    assert not any("Made from parts" in c for c in chooser.choices)
    assert "new agent: Ask my documents" in chooser.choices


def test_a_language_the_model_made_up_is_asked_instead():
    model = FakeModel({"name": "Text translator", "example": "Hi",
                       "instruction": "Translate the text into English unless another language is requested."})
    question = list(builder(model).compose("translate my highlighted texts", ["while_on", "selected_text"]))[-1]
    assert isinstance(question, Question) and question.id == "target_language"
