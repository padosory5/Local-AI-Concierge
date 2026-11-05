import pytest

from concierge import portrait
from concierge.elaina import ElainaChat
from concierge.engine import ElainaEngine
from concierge.fake_engine import FakeEngine
from concierge.history import CHATGPT, CLAUDE, PastChat


@pytest.fixture(autouse=True)
def kept_apart(tmp_path, monkeypatch):
    from concierge import history

    monkeypatch.setattr(portrait, "portrait_path", lambda: tmp_path / "portrait.json")
    monkeypatch.setattr(history, "history_path", lambda: tmp_path / "history.json")


class Model:
    """Answers each kind of question the way it's told to, and remembers what it was shown."""

    def __init__(self, kinds=(), facts=(), yes=lambda fact: True):
        self.kinds, self.facts, self.yes = list(kinds), list(facts), yes
        self.schemas = []

    def chat_json(self, model, messages, schema, think=None, keep_alive=None):
        self.schemas.append(schema)
        if "facts" in schema["properties"]:
            return {"facts": self.facts}
        numbers = list(schema["properties"])
        if schema["properties"]["1"]["enum"] == ["yes", "no"]:
            asked = messages[-1]["content"]
            return {n: "yes" if self.yes(asked.split(f"{n}. ")[1].split("Fact: ")[1].split("\n")[0]) else "no"
                    for n in numbers}
        return {n: self.kinds[int(n) - 1] if int(n) <= len(self.kinds) else "nonsense" for n in numbers}


def chat(*asked, title="", when=1_700_000_000.0, source=CHATGPT):
    return PastChat(source, title or asked[0][:20], title or asked[0][:20], when, list(asked))


def test_kinds_are_counted_by_code_from_a_fixed_list():
    model = Model(kinds=["writing", "coding", "writing", "made-up"])
    chats = [chat(f"chat {n}") for n in range(4)]
    kinds = portrait.sort_kinds(model, "elaina", chats)
    assert [(k["id"], k["count"]) for k in kinds] == [("writing", 2), ("coding", 1), ("other", 1)]
    assert model.schemas[0]["properties"]["1"]["enum"] == list(portrait.KINDS)  # the model can't invent one
    assert kinds[0]["topic"] == "spot"  # writing points to the Spot on Help me


def suggestion(fact, quote, line=1, about="work"):
    return {"about": about, "fact": fact, "quote": quote, "line": line}


LINE = [("I work part-time at a cafe in Sinchon on weekends.", chat("x"))]


def test_a_fact_is_kept_only_when_its_words_are_really_in_the_line():
    assert portrait.checked(suggestion("Works part-time at a cafe", "I work part-time at a cafe"), LINE)
    assert not portrait.checked(suggestion("Works part-time at a cafe", "I own a cafe"), LINE)
    assert not portrait.checked(suggestion("Works at a cafe", "part-time at a cafe", line=2), LINE)


def test_a_fact_that_has_nothing_to_do_with_its_quote_is_dropped():
    line = [("I use C# and the new input system.", chat("x"))]
    assert not portrait.checked(suggestion("Studies computer science", "I use C# and the new input system", about="study"), line)
    assert portrait.checked(suggestion("Uses C#", "I use C#", about="tool"), line)


def test_a_language_is_never_worked_out_from_how_a_line_is_written():
    line = [("저는 서울에 살고 있어요.", chat("x"))]
    assert not portrait.checked(suggestion("Speaks Korean", "저는 서울에 살고 있어요", about="language"), line)
    assert portrait.checked(suggestion("Lives in Seoul", "서울에 살고 있어요", about="place"), line)


def test_what_isnt_hers_to_work_out_never_becomes_a_fact():
    line = [("I work at a bank and my salary is low.", chat("x"))]
    assert not portrait.checked(suggestion("Works at a bank", "I work at a bank"), line)
    snippets = portrait.self_snippets([chat("I have a bad headache, which medicine?"), chat("I'm a nurse in Busan.")])
    assert [text for text, _ in snippets] == ["I'm a nurse in Busan."]


def test_the_user_is_never_the_subject_of_a_shown_fact():
    fact = portrait.checked(suggestion("The user works part-time at a cafe", "I work part-time at a cafe"), LINE)
    assert fact["fact"] == "Works part-time at a cafe"


def test_only_facts_the_second_look_says_yes_to_survive():
    found = [(portrait.checked(suggestion("Works part-time at a cafe", "I work part-time at a cafe"), LINE), LINE[0][0]),
             (portrait.checked(suggestion("Works as a barista manager", "I work part-time at a cafe"), LINE), LINE[0][0])]
    model = Model(yes=lambda fact: "manager" not in fact)
    assert [fact["fact"] for fact in portrait.confirmed(model, "elaina", found)] == ["Works part-time at a cafe"]


def test_the_same_fact_from_two_chats_becomes_one_and_keeps_the_fuller_words():
    short = portrait.checked(suggestion("Works at a cafe", "I work part-time at a cafe"), LINE)
    longer = portrait.checked(suggestion("Works part-time at a cafe in Sinchon", "I work part-time at a cafe in Sinchon"), LINE)
    other = portrait.checked(suggestion("Likes making music", "I like making music", about="interest"),
                             [("I like making music.", chat("x"))])
    merged = portrait.merge([short, longer, other])
    assert merged[0]["fact"] == "Works part-time at a cafe in Sinchon" and merged[0]["seen"] == 2
    assert len(merged) == 2


def test_a_task_is_not_the_person_talking_about_themselves():
    chats = [chat("So then if I have to integrate sin(at+b), what do I do?"),
             chat("Takes pet data represented as a list of dictionaries."),
             chat("I have an exam in December.")]
    assert [text for text, _ in portrait.self_snippets(chats)] == ["I have an exam in December."]


def test_a_request_is_never_shown_as_a_fact_about_someone():
    line = [("can u layout the courses that I have to take", chat("x"))]
    assert not portrait.checked(suggestion("Requests course layouts", "layout the courses", about="study"), line)


def test_one_line_gives_at_most_two_facts():
    line = "I'm building an AI operating system with agents and scheduling."
    model = Model(facts=[suggestion("Builds an AI operating system", "building an AI operating system", about="goal"),
                         suggestion("Builds agents", "agents", about="goal"),
                         suggestion("Builds scheduling", "scheduling", about="goal")])
    facts = portrait.find_facts(model, "elaina", [chat(line)])
    assert len(facts) == 2


def test_one_line_per_chat_newest_first():
    chats = [chat("I'm a student.", "I'm also tired.", when=1), chat("I use Excel daily.", when=2)]
    assert [text for text, _ in portrait.self_snippets(chats)] == ["I use Excel daily.", "I'm a student."]


def test_languages_are_told_apart_by_code():
    assert portrait.language_of("Can you make this email polite?") == "English"
    assert portrait.language_of("이 문장 번역해 줘") == "Korean"
    assert portrait.language_of("Peux-tu traduire ce texte") == "Other"


def test_understanding_again_never_asks_twice_about_the_same_fact():
    chats = [chat("I work part-time at a cafe in Sinchon on weekends.")]
    model = Model(kinds=["writing"], facts=[suggestion("Works part-time at a cafe", "I work part-time at a cafe")])
    made = portrait.understand(model, "elaina", chats)
    portrait.keep(made["facts"][0]["id"], False)
    again = portrait.understand(model, "elaina", chats)
    assert again["facts"][0]["kept"] is False
    assert again["chats"] == {CHATGPT: 1} and again["languages"] == {"English": 1}


def test_only_kept_facts_reach_her_and_personal_matters_never_do():
    made = {"facts": [{"fact": "Works at a cafe", "kept": True}, {"fact": "Lives in Seoul", "kept": None},
                      {"fact": "Likes jazz", "kept": False}],
            "kinds": [{"id": "personal", "words": "Personal matters"}, {"id": "writing", "words": "Writing and polishing messages"}],
            "languages": {"Korean": 9, "English": 2}}
    about = portrait.about_you(made)
    assert "Works at a cafe" in about and "Seoul" not in about and "jazz" not in about
    assert "Personal" not in about and "writing" in about and "Korean" in about
    assert portrait.about_you({}) == ""


class Ollama:
    def __init__(self, system="I am Elaina."):
        self.system, self.sent = system, None

    def capabilities(self, name):
        return []

    def show(self, name):
        return {"system": self.system}

    def chat(self, model, messages, think=None, options=None, keep_alive=None):
        self.sent = messages
        return iter(["Hello"])


def test_what_she_knows_goes_only_to_her_own_model_with_her_persona():
    own = Ollama()
    chat_ = ElainaChat(own)
    chat_.about = "WHAT YOU KNOW ABOUT THE USER\n- Works at a cafe"
    list(chat_.send("hi"))
    assert own.sent[0] == {"role": "system", "content": "I am Elaina.\n\nWHAT YOU KNOW ABOUT THE USER\n- Works at a cafe"}
    cloud = Ollama()
    chat_.talker = cloud  # a cloud model was picked in the menu
    list(chat_.send("hi again"))
    assert all(message["role"] != "system" for message in cloud.sent)
    chat_.close()


def test_without_her_persona_nothing_about_the_user_is_sent():
    own = Ollama(system="")
    chat_ = ElainaChat(own)
    chat_.about = "WHAT YOU KNOW ABOUT THE USER\n- Works at a cafe"
    list(chat_.send("hi"))
    assert all(message["role"] != "system" for message in own.sent)
    chat_.close()


def test_the_engine_says_plainly_when_theres_nothing_to_read(tmp_path, monkeypatch):
    from concierge.agents import store

    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    engine = ElainaEngine(Ollama())
    assert "error" in engine.understand_history()
    (tmp_path / "notes.txt").write_text("hello")
    assert "ChatGPT or Claude" in engine.bring_in_history(str(tmp_path / "notes.txt"))["error"]


def test_the_practice_app_shows_a_portrait_without_reading_anything():
    fake = FakeEngine(delay=0)
    assert fake.bring_in_history("anything.zip")["sources"] == [CHATGPT, CLAUDE]
    made = fake.understand_history()
    fake.keep_fact(made["facts"][0]["id"], True)
    assert fake.what_i_know()["facts"][0]["kept"] is True
    fake.forget_history()
    assert fake.what_i_know() == {}


def test_what_the_computer_says_and_what_chats_say_live_side_by_side():
    from concierge.signs import THIS_COMPUTER

    computer = [{"id": "c1", "about": "tool", "fact": "Makes things in Unity", "quote": "Unity Hub is installed",
                 "source": THIS_COMPUTER, "title": "", "when": 1.0, "seen": 1, "kept": None}]
    portrait.add_computer({"looked": 1.0, "roles": {"developer": 4}}, computer)
    portrait.keep("c1", True)
    chats = [chat("I work part-time at a cafe in Sinchon on weekends.")]
    model = Model(kinds=["writing"], facts=[suggestion("Works part-time at a cafe", "I work part-time at a cafe")])
    made = portrait.understand(model, "elaina", chats)
    assert [fact["source"] for fact in made["facts"]] == [CHATGPT, THIS_COMPUTER]
    assert made["facts"][1]["kept"] is True and made["computer"]["roles"] == {"developer": 4}
    again = portrait.add_computer({"looked": 2.0, "roles": {}}, [dict(computer[0], kept=None)])
    assert [fact["source"] for fact in again["facts"]] == [CHATGPT, THIS_COMPUTER]
    assert again["facts"][1]["kept"] is True  # looking again doesn't ask again
