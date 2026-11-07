"""The picker between the search and the workers (sources.py): the kind of site from
the yaml, the subject's own site, content farms, relevance, and its model as tie-break."""

from concierge import sources


def test_the_kind_of_site_comes_from_the_yaml_the_subject_or_its_name():
    q = "research what the Hermes agent by Nous Research can do"
    assert sources.tier_of("https://www.nobelprize.org/prizes/physics/2026/", q) == ("primary", "official")
    assert sources.tier_of("https://en.wikipedia.org/wiki/X", q) == ("reference", "reference")
    assert sources.tier_of("https://hermes-agent.nousresearch.com/docs", q) == ("primary", "official")
    assert sources.tier_of("https://python.org/downloads", "what's new in python 3.15") == ("primary", "official")  # listed
    assert sources.tier_of("https://www.perplexity.ai/hub", "how fast is Perplexity Pro Search") == ("primary", "the subject's own site")
    assert sources.tier_of("https://openwebui.com/docs", "Open WebUI web search") == ("primary", "the subject's own site")  # two words run together
    # A topic isn't a name: creatine.my is a seller's site, not creatine's.
    assert sources.tier_of("https://creatine.my/dosage/", "is creatine safe for teenagers") == ("ordinary", "")
    assert sources.tier_of("https://www.perplexity.ai/hub", "how fast is perplexity") == ("ordinary", "")
    assert sources.tier_of("https://www.ollama.com/x", "ollama models") == ("primary", "official")
    assert sources.tier_of("https://hermesatlas.com/guide/", q) == ("ordinary", "")  # about it, not it
    assert sources.tier_of("https://best-cheap-laptops-2026-deals.com/x", "best laptop") == ("farm", "looks made for search engines")
    assert sources.tier_of("https://tilnote.io/pages/1", q) == ("farm", "content farm")
    assert sources.tier_of("https://kkm-mako.com/python", "python 3.15") == ("ordinary", "")


def test_relevance_counts_the_questions_own_words():
    assert sources.relevance("creatine safe for teenagers", "Creatine for teens", "Is creatine safe? Teenagers ask.") == 2
    assert sources.relevance("creatine safe for teenagers", "Cheap laptops", "deals") == 0


ROWS = [
    {"title": "Cheap laptops", "href": "https://best-cheap-laptops-2026-deals.com/x", "body": "deals"},
    {"title": "Hermes 3 models", "href": "https://markaicode.com/vs/hermes/", "body": "Hermes 3 open-weight models"},
    {"title": "Hermes Agent docs", "href": "https://hermes-agent.nousresearch.com/docs", "body": "Hermes Agent by Nous Research: memory, skills"},
    {"title": "What is Hermes agent", "href": "https://www.networksolutions.com/blog/hermes/", "body": "Oct 16, 2026"},
    {"title": "Hermes agent review", "href": "https://hermesatlas.com/guide/", "body": "Hermes Agent is an open-source agent by Nous Research"},
    {"title": "More docs", "href": "https://hermes-agent.nousresearch.com/docs/2", "body": "Hermes Agent tools"},
    {"title": "Third docs page", "href": "https://hermes-agent.nousresearch.com/docs/3", "body": "Hermes Agent cron"},
]


def test_the_best_pages_come_first_two_per_site_and_farms_last():
    q = "research what the Hermes agent by Nous Research can do"
    choices = sources.pick(q, ROWS, wanted=4, judge=lambda question, snippets: {4})
    order = [(c.site, c.picked, c.why_not) for c in choices]
    assert order[0][0] == "hermes-agent.nousresearch.com" and order[1][0] == "hermes-agent.nousresearch.com"
    assert order[2] == ("hermes-agent.nousresearch.com", False, "a third page from the same site")
    assert order[3][0] == "hermesatlas.com" and order[3][1]  # its model's yes lifted it above the rest
    assert [c.site for c in choices if c.picked] == ["hermes-agent.nousresearch.com", "hermes-agent.nousresearch.com",
                                                     "hermesatlas.com", "networksolutions.com"]
    farm = next(c for c in choices if c.tier == "farm")
    assert not farm.picked and farm.score == 0
    # The same rows twice are one choice each.
    assert len(sources.pick(q, ROWS + ROWS, wanted=4)) == len(ROWS)


def test_an_official_page_about_something_else_waits_behind_pages_about_the_question():
    q = "is creatine safe for teenagers"
    rows = [{"title": "FDA home", "href": "https://www.fda.gov/", "body": "Food and Drug Administration news"},
            {"title": "Creatine for teens", "href": "https://www.healthline.com/creatine-teens", "body": "Is creatine safe for teenagers?"},
            {"title": "Creatine dosing", "href": "https://theworkoutmag.com/creatine", "body": "creatine safety for teenagers explained"},
            {"title": "Creatine study", "href": "https://www.frontiersin.org/articles/1", "body": "creatine supplementation in teenagers"}]
    choices = sources.pick(q, rows, wanted=3)
    assert [c.site for c in choices if c.picked] == ["healthline.com", "frontiersin.org", "theworkoutmag.com"]
    fda = next(c for c in choices if c.site == "fda.gov")
    assert not fda.picked and fda.why_not == "nothing about the question in its snippet"
    # With nothing better, it is still read: the second pass fills from the rest.
    choices = sources.pick(q, rows[:1] + [{"title": "Shop", "href": "https://shop.example.com", "body": "deals"}], wanted=3)
    assert [c.site for c in choices if c.picked] == ["fda.gov", "shop.example.com"]


def test_her_model_breaks_ties_through_a_form_and_a_bad_form_changes_nothing():
    asked = []
    judge = sources.judge_with(lambda system, user, schema: asked.append((system, user, schema)) or {"about": [0, 2, 99, "x"]})
    assert judge("q", ["a", "b", "c"]) == {0, 2}
    assert asked[0][2] is sources.JUDGE_SCHEMA and "QUESTION: q" in asked[0][1] and "0. a" in asked[0][1]
    broken = sources.judge_with(lambda s, u, schema: (_ for _ in ()).throw(OSError()))
    choices = sources.pick("hermes agent", ROWS[:3], wanted=2, judge=broken)
    assert all("her model" not in r for c in choices for r in c.reasons)


def test_the_reasons_read_plainly():
    choices = sources.pick("research what the Hermes agent by Nous Research can do", ROWS, wanted=3)
    picked, dropped = sources.said(choices)
    assert picked.startswith("Picked 3 of 7 pages: hermes-agent.nousresearch.com (official), hermes-agent.nousresearch.com (official), ")
    assert "best-cheap-laptops-2026-deals.com (beyond the best 3)" in dropped or "a third page from the same site" in dropped
