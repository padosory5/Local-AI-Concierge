import pytest

from concierge.agents import parts, recipe, store
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
    assert isinstance(card, AgentCard) and card.name == "Word explainer" and card.kind == WHILE_ON
    assert card.can_do[0] == "Rule: Explain this English word in simple Korean, with one example sentence."
    assert card.can_do[1] == f"Shows the result: {BUBBLE}"
    assert card.reads[0].startswith("Text you highlight")

    events = list(b.choose(card.id, "Create it"))
    result = next(e for e in events if isinstance(e, Result))
    assert result.text == 'Test: "serendipity"\ndone: serendipity'
    assert events[-3].text == "Word explainer is ready."  # how it is used from here is the engine's to say
    assert isinstance(events[-1], AgentList)
    saved = store.find_agent("Word explainer")
    assert saved.blueprint == CUSTOM and saved.slots["when"] == WHILE_ON and saved.slots["then"] == parts.SHOW
    assert recipe.is_switchable(saved)
    # What the plain questions never ask about is written down with its usual value: the
    # card says that it leaves nothing out, and nothing reads its rule for that later.
    assert saved.slots["skip_language"] == ""
    assert b.take_created().name == "Word explainer" and not b.edited


def test_compose_a_chat_agent():
    model = FakeModel({"name": "Summarizer", "instruction": "Summarize the text in three bullet points.",
                       "example": "A long paragraph."})
    card = list(builder(model).compose("summarize text I paste in the chat", ["on_request", "summarize"]))[-1]
    assert card.reads[0].startswith("What you send it in the chat")
    assert card.can_do == ["Rule: Summarize the text in three bullet points.", "Answers in the chat"]
    assert card.kind == IN_CHAT


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


def test_the_rule_is_shown_as_it_was_written_and_the_card_is_where_it_is_put_right():
    """Code used to read the rule a model wrote, and for one kind of helper it asked a
    question of its own or wrote the rule again from the request. No kind is known any
    more: whatever the rule says is on the card before anything is made, and "Change
    something" changes it."""
    model = FakeModel({"name": "Highlight helper", "instruction": "Translate the text.", "example": "Good morning"},
                      rewrite="Translate the text into Korean.")
    b = builder(model)
    card = list(b.compose("translate my highlighted texts", ["while_on", "selected_text", "translate"]))[-1]
    assert isinstance(card, AgentCard) and card.can_do[0] == "Rule: Translate the text."  # no question about a language
    assert not any("Leaves out" in line for line in card.can_do)  # and no setting worked out from its words
    question = list(b.choose(card.id, "Change something"))[-1]
    assert isinstance(question, Question) and "What it does" in question.choices
    assert list(b.choose(question.id, "What it does"))[-1].id == "instruction"
    card = list(b.answer("it should give me Korean"))[-1]
    assert isinstance(card, AgentCard) and card.can_do[0] == "Rule: Translate the text into Korean."


def test_a_language_in_the_request_changes_nothing_code_does():
    model = FakeModel({"name": "Highlight helper", "instruction": "Translate the text into Spanish, briefly.",
                       "example": "Good morning"})
    b = builder(model)
    card = list(b.compose("translate what I highlight into Korean", ["while_on", "selected_text"]))[-1]
    # The model's rule stands, wrong language and all: the card is the check, and code no
    # longer puts a rule right for one kind of helper.
    assert isinstance(card, AgentCard) and card.can_do[0] == "Rule: Translate the text into Spanish, briefly."
    list(b.choose(card.id, "Create it"))
    assert store.find_agent("Highlight helper").slots["skip_language"] == ""


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
    assert card.can_do[0] == "Rule: Explain this English word in simple Japanese."


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
    assert events[0].text == "Saved the changes to Word explainer."
    saved = store.find_agent("Word explainer")
    assert not recipe.is_switchable(saved)
    assert saved.slots["then"] == parts.ANSWER  # what it does with its result goes with when it works


def test_a_rewritten_rule_takes_off_the_language_a_card_left_out():
    """The plain questions can't tell whether text in that language should still be left
    out once the rule says something else. Kept, a card changed to give another language
    passed over text in the old one without a word; so it goes back to none, and that is said."""
    leaves = {"instruction": "Translate the text into Korean.", "when": WHILE_ON, "show": BUBBLE,
              "keep": UNTIL_UNHIGHLIGHT, "skip_language": "Korean", "name": "Korean Translator"}
    agent = store.Agent("Korean Translator", CUSTOM, dict(leaves))
    store.save(agent)
    b = builder(FakeModel(rewrite="Translate the text into Japanese."))
    events = list(b.edit(agent, "make it Japanese instead"))
    step = next(e for e in events if isinstance(e, Thinking))
    assert "what it does → Translate the text into Japanese." in step.text
    assert "leaves out text already in → nothing" in step.text
    card = events[-1]
    assert card.can_do[0] == "Rule: Translate the text into Japanese."
    assert not any("Leaves out" in line for line in card.can_do)
    list(b.choose(card.id, "Save changes"))
    assert store.find_agent("Korean Translator").slots["skip_language"] == ""

    # A change that leaves the rule alone leaves the setting alone too, and the card goes on saying it.
    store.save(store.Agent("Korean Translator", CUSTOM, dict(leaves)))
    model = FakeModel()
    b = builder(model)
    events = list(b.edit(store.find_agent("Korean Translator"), "copy it to the clipboard instead"))
    assert "leaves out" not in next(e for e in events if isinstance(e, Thinking)).text
    assert events[-1].can_do[1:] == [f"Shows the result: {CLIPBOARD}", "Leaves out text that is already in Korean"]
    list(b.choose(events[-1].id, "Save changes"))
    assert store.find_agent("Korean Translator").slots["skip_language"] == "Korean"


def test_typed_new_job_from_the_change_menu(explainer):
    b = builder(FakeModel(rewrite="Give three synonyms of the word."))
    list(b.edit(explainer, "make it sing"))
    question = list(b.choose("change", "What it does"))[-1]
    assert question.id == "instruction" and question.choices is None
    card = list(b.answer("give me synonyms instead"))[-1]
    assert card.can_do[0] == "Rule: Give three synonyms of the word."


# ---------------------------------------------------------------- running


def test_run_instruction_returns_only_the_result():
    model = FakeModel()
    assert recipe.run_instruction(model, "noir", "Fix the grammar.", "me go") == "done: me go"


def test_nothing_here_reads_a_rule_to_find_out_what_kind_of_helper_it_is():
    for gone in ("target_language", "needs_language", "with_language"):
        assert not hasattr(recipe, gone), gone


# -------------------------------------------------------------- old agents


def test_old_translators_become_agents_from_parts(tmp_path, monkeypatch):
    # The catalog knows every kind there ever was (parts.migrate); this only passes it on.
    monkeypatch.setattr(parts.noir, "data_dir", lambda: tmp_path)
    store.save(store.Agent("Korean translator", "translate_selection",
                           {"language": "Korean", "show": CLIPBOARD, "name": "Korean translator"}))
    assert recipe.migrate() == ["Korean translator"]
    agent = store.find_agent("Korean translator")
    assert agent.blueprint == CUSTOM
    assert agent.slots["instruction"] == "Translate the text into Korean."
    assert agent.slots["show"] == CLIPBOARD and agent.slots["keep"] == UNTIL_UNHIGHLIGHT
    assert agent.slots["skip_language"] == "Korean"  # what it always did, now said by the card
    assert recipe.migrate() == []  # only once


def test_the_agents_that_worked_on_a_folder_become_cards_at_the_same_call(tmp_path, monkeypatch):
    # The catalog turns them into cards (parts.migrate); one call at startup does both.
    monkeypatch.setattr(parts.noir, "data_dir", lambda: tmp_path)
    store.save(store.Agent("Paper sorter", "organizer", {"folder": str(tmp_path), "groups": "A, B", "name": "Paper sorter"}))
    assert recipe.migrate() == ["Paper sorter"]
    card = store.find_agent("Paper sorter")
    assert card.blueprint == CUSTOM and parts.watches(card) and parts.choices_of(card.slots) == ["A", "B"]


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


def test_a_language_the_model_made_up_is_on_the_card_to_be_seen():
    # Told never to guess a language, a model still named one. Code used to ask which
    # language instead; now the rule is shown as written, before anything is made.
    model = FakeModel({"name": "Text helper", "example": "Hi",
                       "instruction": "Translate the text into English unless another language is requested."})
    card = list(builder(model).compose("translate my highlighted texts", ["while_on", "selected_text"]))[-1]
    assert isinstance(card, AgentCard)
    assert card.can_do[0] == "Rule: Translate the text into English unless another language is requested."
    assert card.actions == ["Create it", "Change something", "Cancel"]


def test_the_examples_the_recipe_writer_is_shown_name_no_language_and_no_ready_made_helper():
    """A small model copies what it is shown: with a Korean translator first among the
    examples, a request that named no language could come back translating into Korean."""
    from concierge.agents.starters import load_starters
    from concierge.quick.translate import LANGUAGES

    class Reads(FakeModel):
        def chat_json(self, model, messages, schema, think=None, keep_alive=None):
            self.note = messages[0]["content"]
            return super().chat_json(model, messages, schema, think, keep_alive)

    model = Reads()
    recipe.write_recipe(model, "noir", "translate what I highlight")
    examples = model.note.split("Examples:", 1)[1].lower()
    assert not [language for language in LANGUAGES if language.lower() in examples]
    assert not [s.name for s in load_starters() if any(word in examples for word in (s.name.lower(), *s.words))]
