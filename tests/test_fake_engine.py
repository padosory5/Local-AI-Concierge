from concierge import events
from concierge.agents import parts
from concierge.agents.builder import CARD, CREATE_IT
from concierge.agents.designer import DESIGN, TRY_OUT
from concierge.agents.parts import CUSTOM, DOCUMENTS_QA, INSIDE_FILE, MOVE, NAME_ONLY, NEW_FILE, OPEN_YES
from concierge.engine import FIRST_PASS, GO_THROUGH, ONLY_NEW, NoirEngine
from concierge.events import (
    AgentCard,
    AgentList,
    ChatList,
    NoirDone,
    NoirText,
    Error,
    Progress,
    Question,
    Result,
    SystemInfo,
    Thinking,
)
from concierge.fake_engine import FakeEngine
from concierge.folderwatch import LEFT_BY_RULE, NO_TEXT


def types(evts):
    return [type(e) for e in evts]


def test_startup_sends_system_info_then_agents():
    assert types(FakeEngine(delay=0).startup()) == [SystemInfo, AgentList, ChatList]


def test_chat_streams_then_finishes():
    evts = list(FakeEngine(delay=0).send("hello"))
    assert isinstance(evts[0], ChatList)  # a new conversation appears in the list first
    evts = evts[1:]
    assert all(isinstance(e, NoirText) for e in evts[:-1])
    assert isinstance(evts[-1], NoirDone)


RULE = "keep the manuals together and leave the rest"


def one(evts, kind):
    return next(e for e in evts if isinstance(e, kind))


def said(evts):
    return "".join(e.text for e in evts if isinstance(e, NoirText)).strip()


def at_the_card(engine):
    """The practice conversation played up to its card. Returns the card."""
    list(engine.send("make an agent"))
    list(engine.send(RULE))
    return one(engine.choose("looks_at", INSIDE_FILE), AgentCard)


def test_a_helper_is_worked_out_in_the_order_the_real_conversation_goes():
    engine = FakeEngine(delay=0)
    evts = list(engine.send("make an agent for my contracts"))
    # It starts from nothing: no helper is offered, only a question to answer in words.
    assert isinstance(evts[-1], Question) and evts[-1].id == DESIGN and not evts[-1].choices
    assert Thinking in types(evts) and AgentCard not in types(evts) and not said(evts)

    evts = list(engine.send(RULE))
    question = evts[-1]
    assert isinstance(question, Question) and question.id == "looks_at" and question.choices == [INSIDE_FILE, NAME_ONLY]
    assert question.text.startswith("Practice:")  # what the script made up says so

    evts = list(engine.choose(question.id, INSIDE_FILE))
    # A few words, a try-out on made-up files, then the card: nothing exists yet.
    assert [t for t in types(evts) if t in (NoirDone, Result, AgentCard)] == [NoirDone, Result, AgentCard]
    tried = one(evts, Result)
    assert tried.agent == TRY_OUT and tried.text.startswith("Tried on the 3 newest files in Downloads. Nothing was moved.")
    assert "practice-letter.pdf → Practice folder (a new folder; read as a made-up letter)" in tried.text
    assert f"practice-setup.exe: stays ({NO_TEXT})" in tried.text
    card = evts[-1]
    # The card is the one the real app would show for these settings, with their own words as the rule.
    slots = {"when": NEW_FILE, "then": MOVE, "folder": "C:/Users/you/Downloads", "looks_at": INSIDE_FILE,
             "instruction": RULE, "choices": "", "open": OPEN_YES, "into": "", "name": "Downloads helper"}
    assert (card.kind, card.reads, card.can_do, card.cannot_do, card.runs_on) == parts.card(slots, "Qwen 3.5 4B")
    assert card.name == "Downloads helper" and card.can_do[0] == f"Rule: {RULE}"
    assert card.actions == [CREATE_IT, "Change something", "Cancel"]
    assert "Downloads helper" not in one(engine.startup(), AgentList).agents

    evts = list(engine.choose(card.id, CREATE_IT))
    assert said(evts) == "Downloads helper is ready."
    made = one(evts, AgentList)
    assert made.agents == ["Contracts helper", "Korean translator", "Home papers", "Downloads helper"]
    assert "Downloads helper" in made.switchable and "Downloads helper" in made.active  # switched on, as the real one is
    # The files already there are asked about, never taken.
    question = evts[-1]
    assert isinstance(question, Question) and question.id == FIRST_PASS and question.choices == [GO_THROUGH, ONLY_NEW]
    assert Progress not in types(evts) and len(engine.chore_done()) == 2

    evts = list(engine.choose(question.id, GO_THROUGH))
    assert [e.text for e in evts if isinstance(e, Progress)][0] == "Reading practice-letter.pdf (1 of 3)..."
    assert one(evts, Result).agent == "Downloads helper"
    assert one(evts, Result).text == (f"Moved 2 files: Practice folder 2. 1 left where it was: {NO_TEXT}. "
                                      "Undo is in your chores.")
    job = engine.chore_done()[-1]
    assert (job["text"], job["agent"], job["undo"]) == ("Moved 2 files from Downloads", "Downloads helper", True)


def test_a_change_is_said_in_words_and_the_helper_is_tried_again():
    engine = FakeEngine(delay=0)
    card = at_the_card(engine)
    evts = list(engine.choose(card.id, "Change something"))
    assert isinstance(evts[-1], Question) and evts[-1].id == DESIGN and not evts[-1].choices
    evts = list(engine.send("never touch pictures"))
    assert one(evts, Result).text.startswith("Tried again on the same 3 files in Downloads.")
    assert evts[-1].can_do[0] == f"Rule: {RULE}. never touch pictures"
    # Going by names alone, nothing inside a file is read, and the lines say so.
    list(engine.choose(card.id, "Cancel"))
    list(engine.send("make an agent"))
    list(engine.send(RULE))
    evts = list(engine.choose("looks_at", NAME_ONLY))
    assert "never what's inside it" in evts[-1].reads[0] and f"stays ({LEFT_BY_RULE}: a program)" in one(evts, Result).text
    list(engine.choose(CARD, CREATE_IT))
    evts = list(engine.choose(FIRST_PASS, GO_THROUGH))
    assert one(evts, Progress).text == "Looking at the name of practice-letter.pdf (1 of 3)..."
    assert f"1 left where it was: {LEFT_BY_RULE}." in one(evts, Result).text


def test_a_plain_yes_at_the_card_creates_and_only_new_files_is_taken_at_its_word():
    engine = FakeEngine(delay=0)
    at_the_card(engine)
    evts = list(engine.send("Yes!"))
    assert said(evts) == "Downloads helper is ready." and evts[-1].id == FIRST_PASS
    assert said(engine.choose(FIRST_PASS, ONLY_NEW)) == "Okay, only new files from now on."
    assert len(engine.chore_done()) == 2  # nothing was gone through
    # A second one gets a name of its own.
    assert at_the_card(engine).name == "Downloads helper 2"


def test_what_is_typed_while_a_helper_is_worked_out_is_no_chat_answer():
    # With a plan's model picked, a chat answer is marked as written by it. The lines of the
    # conversation about a helper are set phrases: no dot, no model's name, no thinking aloud.
    engine = FakeEngine(delay=0)
    engine.menu.accounts.sign_in("claude_code")
    engine.menu.pick("claude_code", "practice-1")
    assert one(engine.send("hello"), NoirDone).where == "cloud"
    at_the_card(engine)
    evts = list(engine.send("never touch pictures", think=True))
    assert (one(evts, NoirDone).by, one(evts, NoirDone).where) == ("", "") and isinstance(evts[-1], AgentCard)
    assert all(e.kind == "step" for e in evts if isinstance(e, Thinking))


def test_cancel_and_unknown_choice():
    engine = FakeEngine(delay=0)
    card = at_the_card(engine)
    assert said(engine.choose(card.id, "Cancel")) == "Okay, I won't create it."
    assert said(engine.choose(card.id, CREATE_IT)) == "That question has already been answered."
    assert types(engine.choose("nope", "x")) == [Error]
    # Called off in words, at any point of the conversation.
    list(engine.send("make an agent"))
    assert said(engine.send("never mind")) == "Okay, I won't create it."
    assert one(engine.startup(), AgentList).agents == ["Contracts helper", "Korean translator", "Home papers"]
    # A button of an earlier card, clicked before anything is said of the new one: the open question again.
    list(engine.send("make an agent"))
    assert one(engine.choose(card.id, CREATE_IT), Question).id == DESIGN


def test_running_an_agent_returns_sources():
    evts = list(FakeEngine(delay=0).send("ask contracts helper who signed"))
    result = next(e for e in evts if isinstance(e, Result))
    assert result.sources


def test_a_message_that_starts_with_a_helpers_name_is_for_that_helper():
    engine = FakeEngine(delay=0)
    # What a helper's page sends from Try this must never start a new helper, whatever its words.
    for name in ("Contracts helper", "Korean translator", "Home papers"):
        evts = list(engine.send(f"{name}: {engine.details(name)['sample']}"))
        assert one(evts, Result).agent == name and Question not in types(evts), name
    assert one(engine.send("contracts helper: who signed?"), Result).sources
    assert "Nothing new has landed in Downloads" in one(engine.send("Home papers: go through the new files"), Result).text
    list(engine.toggle_agent("Home papers"))
    assert "switched off" in said(engine.send("Home papers: go through the new files"))


def test_the_made_up_helpers_are_cards_and_the_lists_read_them_as_the_real_engine_does():
    engine = FakeEngine(delay=0)
    by_name = {agent.name: agent for agent in engine.helpers}
    assert [agent.blueprint for agent in engine.helpers] == [DOCUMENTS_QA, CUSTOM, CUSTOM]
    assert parts.watches(by_name["Home papers"]) and not parts.watches(by_name["Korean translator"])
    lists = one(engine.startup(), AgentList)
    assert lists.switchable == ["Home papers", "Korean translator"] and lists.active == ["Home papers"]
    # The chores' lines: the same keys, and the same sentences, as the real engine gives.
    translator, papers = engine.chore_agents()
    assert translator == {"name": "Korean translator", "kind": "highlight", "on": False,
                          "how": parts.how(by_name["Korean translator"])}
    assert sorted(papers) == ["how", "kind", "left", "name", "now", "on", "since", "why_off"]
    assert (papers["kind"], papers["on"], papers["how"]) == ("files", True, parts.how(by_name["Home papers"]))
    assert papers["why_off"] == ""  # no update ever switched a practice helper off
    assert papers["since"] > 0 and papers["now"] == "" and papers["left"] is None and engine.chore_doing() == ""
    for job in engine.chore_done():
        assert sorted(job) == ["agent", "details", "sort", "text", "undo", "when", "where"] and job["agent"] == "Home papers"
    # Each page is written from the card by the code that writes the real one.
    for agent in engine.helpers:
        assert engine.details(agent.name) == parts.describe(agent)
    # What the made-up helper for highlights leaves out is on its card as data, as the real app saves it.
    assert by_name["Korean translator"].slots["skip_language"] == "Korean"
    assert dict(engine.details("Korean translator")["facts"])["Leaves out"] == "Text that is already in Korean"


def test_a_ready_made_or_shared_helper_is_added_as_the_card_the_real_app_saves():
    engine = FakeEngine(delay=0)
    list(engine.switch_agent("English Translator", True))  # a shared one, from Help me's switch
    list(engine.send("turn on the highlight explainer"))  # a ready-made one, by saying so
    by_name = {agent.name: agent for agent in engine.helpers}
    assert by_name["English Translator"].slots["skip_language"] == "English"
    assert by_name["Highlight Explainer"].slots["skip_language"] == ""
    assert "Leaves out" in dict(engine.details("English Translator")["facts"])
    assert "Leaves out" not in dict(engine.details("Highlight Explainer")["facts"])
    assert engine.details("Nobody") == {}
    # Switched off, it is off in both lists, and has been on since nothing.
    list(engine.toggle_agent("Home papers"))
    assert engine.chore_agents()[1]["on"] is False and engine.chore_agents()[1]["since"] == 0
    assert "Only files that land from now on are handled." in said(engine.toggle_agent("Home papers"))
    assert types(engine.toggle_agent("Contracts helper"))[-1] is Error  # asked in the chat, never switched


def test_a_practice_job_can_be_undone_once():
    engine = FakeEngine(delay=0)
    assert engine.undo_move("practice-2") == 1 and engine.undo_move("practice-2") == 0
    jobs = engine.chore_done()
    assert jobs[1]["undo"] is False and jobs[0]["undo"] is True
    assert (jobs[-1]["text"], jobs[-1]["undo"], jobs[-1]["agent"]) == ("Put 1 file back", False, "")
    assert engine.undo_move("") == 0 and engine.undo_move("not a job") == 0


def test_a_deleted_helper_is_gone_from_every_list():
    engine = FakeEngine(delay=0)
    list(engine.delete_agent("Home papers"))
    lists = one(engine.choose("delete_agent", "Delete it"), AgentList)
    assert lists.agents == ["Contracts helper", "Korean translator"] and lists.active == []
    assert [row["name"] for row in engine.chore_agents()] == ["Korean translator"] and engine.details("Home papers") == {}


def test_events_become_json_ready_dicts():
    card = AgentCard("card", "X", "When you ask in the chat", ["a"], ["b"], ["c"], "model")
    data = events.to_dict(card)
    assert data["type"] == "AgentCard"
    assert data["actions"] == ["Create it", "Change something", "Cancel"]


def test_both_engines_offer_the_same_methods():
    # The contract, then what the windows call outside it (window.py asks for these by name).
    for name in ("startup", "send", "choose", "reset", "close", "new_chat", "open_chat", "delete_chat", "delete_agent",
                 "toggle_agent", "set_agent", "switch_agent", "details", "chore_agents", "chore_done", "chore_doing",
                 "undo_move", "recipes", "add_recipe", "post_agent", "send_files", "follow_up", "ask_again", "activity",
                 "spot_actions", "spot_run", "setup_state", "setup_begin", "measure"):
        assert callable(getattr(FakeEngine, name)), name
        assert callable(getattr(NoirEngine, name)), name
    # Names the engine no longer has are not kept alive here.
    for name in ("organizer_done", "organizer_doing", "organizer_questions", "organizer_answer"):
        assert not hasattr(FakeEngine, name) and not hasattr(NoirEngine, name), name
