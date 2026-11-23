import json
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from concierge.agents import community, parts, starters, store
from concierge.agents.community import PostError, Recipe, clean, install, post_address, recipes
from concierge.agents.recipe import CUSTOM, IN_CHAT, MAX_INSTRUCTION, MECHANICS, WHILE_ON
from concierge.engine import NoirEngine
from concierge.fake_engine import FakeEngine

GOOD = {"name": "Poem Maker", "by": "Dana", "category": "Writing", "about": "Writes a poem.",
        "instruction": "Write a short poem about the text.", "when": IN_CHAT}


class Reply:
    def __init__(self, text="", ok=True, body=None):
        self.text, self.ok, self.body = text, ok, body

    def json(self):
        return self.body


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(community, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(community, "_saved", (0, []))
    return tmp_path


def online(monkeypatch, text="", ok=True):
    monkeypatch.setattr(community.requests, "get", lambda *a, **k: Reply(text, ok))


def offline(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("no internet")

    monkeypatch.setattr(community.requests, "get", fail)


def test_every_agent_that_ships_with_the_app_is_good():
    entries = json.loads(community.INDEX_PATH.read_text(encoding="utf-8"))
    made = [clean(entry) for entry in entries]
    assert all(made) and len({recipe.id for recipe in made}) == len(made)
    for recipe in made:
        assert recipe.category in community.CATEGORIES
        assert not MECHANICS.search(recipe.instruction)  # the job only, never when or where
    # What a recipe leaves out is said by the recipe, as data: nothing works it out from its rule.
    leaving = {recipe.name: recipe.skip_language for recipe in made if recipe.skip_language}
    assert leaving == {"Korean Translator": "Korean", "English Translator": "English"}


def test_a_good_entry_is_kept():
    recipe = clean(GOOD)
    assert recipe.name == "Poem Maker" and recipe.by == "Dana" and recipe.source == community.COMMUNITY


@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": 7}, {"instruction": ""}, {"instruction": "x" * (MAX_INSTRUCTION + 1)},
    {"when": "Every minute"}, {"show": "Send it somewhere"}, {"keep": "Forever"},
])
def test_an_entry_that_isnt_right_is_dropped(change):
    assert clean({**GOOD, **change}) is None


def test_the_language_a_recipe_leaves_out_is_kept_and_one_the_app_cant_tell_is_refused():
    highlight = {**GOOD, "when": WHILE_ON}
    assert clean(highlight).skip_language == ""  # none said: none
    assert clean({**highlight, "skip_language": ""}).skip_language == ""
    for language in parts.WHENS[WHILE_ON].settings[0].choices:
        assert clean({**highlight, "skip_language": language}).skip_language == language
    # A value that is no language the app can tell a text is in: refused, like any setting it doesn't know.
    for wrong in ("Klingon", "Spanish", "korean", "Korean, English", 7, ["Korean"], {"language": "Korean"}):
        assert clean({**highlight, "skip_language": wrong}) is None, wrong
    # It is a setting of a recipe that works on highlights only: asked in the chat, nothing is highlighted.
    assert clean({**GOOD, "skip_language": "Korean"}).skip_language == ""
    assert clean({**GOOD, "skip_language": "Klingon"}) is None


def test_adding_carries_what_a_recipe_leaves_out():
    install(clean({**GOOD, "name": "Leaver", "when": WHILE_ON, "skip_language": "Korean"}))
    assert store.find_agent("Leaver").slots["skip_language"] == "Korean"
    install(clean({**GOOD, "name": "Plain", "when": WHILE_ON}))
    assert store.find_agent("Plain").slots["skip_language"] == ""  # written down: it leaves nothing out
    install(clean({**GOOD, "name": "Asked", "skip_language": "Korean"}))
    assert "skip_language" not in store.find_agent("Asked").slots
    # The two that ship with the app come out as cards that say it, with nothing read from their rules.
    for name, language in (("Korean Translator", "Korean"), ("English Translator", "English")):
        saved = install(community.find(store.slugify(name), online=False))
        assert saved.slots["skip_language"] == language
        assert f"Leaves out text that is already in {language}" in parts.card(saved.slots, "")[2]


def test_what_the_agents_page_says_of_a_ready_made_agent_is_data_beside_its_recipe():
    assert not hasattr(community, "STARTER_DETAILS")
    for starter in starters.load_starters():
        assert starter.about and starter.category in community.CATEGORIES, starter.name
        assert starter.skip_language in ("", *parts.WHENS[WHILE_ON].settings[0].choices)
    ready = {recipe.name: recipe for recipe in recipes(online=False) if recipe.source == community.READY_MADE}
    explainer = ready["Highlight Explainer"]
    assert (explainer.about, explainer.category) == ("Explains what you highlight, in simple words.", "Study")
    assert (ready["Grammar Fixer"].category, ready["Quick Summarizer"].category) == ("Writing", "Everyday")
    assert all(recipe.about != recipe.instruction for recipe in ready.values())


def test_a_ready_made_agent_without_those_lines_still_shows(monkeypatch):
    bare = starters.Starter("Bare one", ("bare one",), "Say it in fewer words.", WHILE_ON)
    leaves = starters.Starter("Leaver", ("leaver",), "Say it in fewer words.", WHILE_ON, "Shortens.", "Nowhere", "Korean")
    monkeypatch.setattr(community, "load_starters", lambda: (bare, leaves))
    first, second = community._starters()
    assert (first.about, first.category, first.skip_language) == ("Say it in fewer words.", community.OTHER_CATEGORY, "")
    assert (second.about, second.category, second.skip_language) == ("Shortens.", community.OTHER_CATEGORY, "Korean")
    assert starters.install(leaves).slots["skip_language"] == "Korean"
    assert starters.install(bare).slots["skip_language"] == ""
    chat = starters.install(starters.Starter("Chat one", ("chat one",), "Say it in fewer words.", IN_CHAT))
    assert "skip_language" not in chat.slots


def test_something_that_isnt_an_entry_is_dropped():
    assert clean("hello") is None and clean(None) is None


def test_only_known_settings_are_kept():
    recipe = clean({**GOOD, "folder": "C:/secrets", "run": "format c:", "source": "Hacker"})
    assert not hasattr(recipe, "folder") and not hasattr(recipe, "run")
    assert recipe.source == community.COMMUNITY  # nobody can claim to be ready-made by accident


def test_long_or_broken_words_are_tidied():
    recipe = clean({**GOOD, "about": "a\n\x00b" + "c" * 500, "by": "", "category": "Nonsense"})
    assert "\n" not in recipe.about and len(recipe.about) <= community.MAX_ABOUT
    assert recipe.by == "Someone" and recipe.category == community.OTHER_CATEGORY


def test_the_list_from_the_internet_is_used_and_kept(monkeypatch, own_folder):
    online(monkeypatch, json.dumps([GOOD]))
    assert "Poem Maker" in [recipe.name for recipe in recipes()]
    assert (own_folder / "community.json").exists()


def test_with_no_internet_the_last_list_seen_is_used(monkeypatch, own_folder):
    (own_folder / "community.json").write_text(json.dumps([GOOD]), encoding="utf-8")
    offline(monkeypatch)
    assert "Poem Maker" in [recipe.name for recipe in recipes()]


def test_with_nothing_else_the_list_from_the_app_is_used(monkeypatch):
    online(monkeypatch, ok=False)
    assert "Email Polisher" in [recipe.name for recipe in recipes()]


def test_a_broken_list_from_the_internet_is_ignored(monkeypatch):
    online(monkeypatch, "<html>not json</html>")
    assert "Email Polisher" in [recipe.name for recipe in recipes()]


def test_ready_made_agents_come_first_and_cant_be_replaced(monkeypatch):
    online(monkeypatch, json.dumps([{**GOOD, "name": "Grammar Fixer", "instruction": "Something else."}]))
    found = recipes()
    fixers = [recipe for recipe in found if recipe.name == "Grammar Fixer"]
    assert len(fixers) == 1 and fixers[0].source == community.READY_MADE
    assert found[0].source == community.READY_MADE


def test_the_practice_app_never_goes_online(monkeypatch):
    offline(monkeypatch)
    monkeypatch.setattr(community.requests, "get", lambda *a, **k: pytest.fail("went online"))
    assert recipes(online=False)


def test_adding_makes_an_ordinary_agent():
    agent = install(clean({**GOOD, "when": WHILE_ON}))
    saved = store.find_agent("Poem Maker")
    assert saved.blueprint == CUSTOM and saved.slots["instruction"] == GOOD["instruction"]
    assert saved.slots["when"] == WHILE_ON and agent.name == "Poem Maker"


def test_adding_never_replaces_what_the_user_has():
    store.save(store.Agent("Poem Maker", CUSTOM, {"instruction": "My own words."}))
    install(clean(GOOD))
    assert store.find_agent("Poem Maker").slots["instruction"] == "My own words."


def agent(**slots):
    return store.Agent("Poem Maker", CUSTOM, {"instruction": "Write a poem.", "when": IN_CHAT, **slots})


def test_posting_fills_in_a_github_page():
    address = post_address(agent(), "Writes poems.", "Writing", "Dana")
    assert address.startswith(community.POST_URL)
    page = parse_qs(urlsplit(address).query)
    assert page["title"] == ["New agent: Poem Maker"]
    posted = json.loads(page["body"][0].split("```json")[1].split("```")[0])
    assert posted["instruction"] == "Write a poem." and posted["by"] == "Dana"
    assert clean(posted)  # what's posted can be read back
    assert "skip_language" not in posted  # it leaves nothing out, so there is nothing to say
    # One that leaves a language out says so in what is posted, and it reads back the same.
    leaves = agent(when=WHILE_ON, skip_language="Korean")
    page = parse_qs(urlsplit(post_address(leaves, "Writes poems.", "Writing")).query)
    posted = json.loads(page["body"][0].split("```json")[1].split("```")[0])
    assert posted["skip_language"] == "Korean" and clean(posted).skip_language == "Korean"


def test_posting_shares_the_recipe_and_nothing_else():
    made = agent(folder="C:/Users/me/Secret", private="my notes")
    made.contents = ["taxes.pdf"]
    address = post_address(made, "Writes poems.", "Writing")
    for word in ("Secret", "private", "taxes"):
        assert word not in address


def test_an_agent_that_reads_folders_cant_be_posted():
    with pytest.raises(PostError, match="own files"):
        post_address(store.Agent("Files", "documents_qa", {"folder": "C:/Users/me"}), "Reads.", "Work")


def test_an_agent_that_works_on_a_folder_cant_be_posted():
    from concierge.agents import parts

    watcher = store.Agent("Paper sorter", CUSTOM, {"when": parts.NEW_FILE, "then": parts.MOVE, "folder": "C:/Users/me/Downloads",
                                                   "instruction": "Put letters in Letters.", "choices": "Letters"})
    with pytest.raises(PostError, match="own files"):
        post_address(watcher, "Sorts papers.", "Work")
    # And nothing from outside is ever let near a folder: only the two WHENs that work on text are taken.
    assert clean({**GOOD, "when": parts.NEW_FILE}) is None


def test_a_rule_too_long_to_share_says_so():
    # A rule worked out by talking can be twice as long as a shared one may be.
    long = "Explain it. " * 40
    assert community.MAX_INSTRUCTION < len(long.strip())
    with pytest.raises(PostError, match="too long to share"):
        post_address(agent(instruction=long), "Explains.", "Study")


def test_a_post_needs_a_line_about_it():
    with pytest.raises(PostError, match="one line"):
        post_address(agent(), "  ", "Writing")


def test_posting_is_only_offered_once_the_shared_place_exists(monkeypatch):
    monkeypatch.setattr(community.requests, "get", lambda *a, **k: Reply(ok=False))
    assert community.can_post() is False
    monkeypatch.setattr(community.requests, "get", lambda *a, **k: Reply(body={"has_issues": True}))
    assert community.can_post() is True
    offline(monkeypatch)
    assert community.can_post() is False


def test_the_engine_says_when_posting_isnt_open(monkeypatch):
    store.save(agent())
    monkeypatch.setattr(community, "can_post", lambda: False)
    reply = NoirEngine(object()).post_agent("Poem Maker", "Writes poems.", "Writing")
    assert "isn't open yet" in reply["error"] and "address" not in reply


def test_the_engine_hands_back_the_page_to_open(monkeypatch):
    store.save(agent())
    monkeypatch.setattr(community, "can_post", lambda: True)
    assert NoirEngine(object()).post_agent("Poem Maker", "Writes poems.", "Writing")["address"].startswith(community.POST_URL)


def test_the_practice_app_never_posts():
    assert "practice" in FakeEngine(delay=0).post_agent("Korean translator", "x", "Work")["error"]


def test_adding_from_the_practice_app():
    fake = FakeEngine(delay=0)
    recipe: Recipe = next(item for item in community.recipes(online=False) if item.when == WHILE_ON)
    events = list(fake.add_recipe(recipe.id))
    assert recipe.name in events[-1].agents and recipe.name in events[-1].switchable
    assert next(item for item in fake.recipes()["recipes"] if item["id"] == recipe.id)["added"] is True
