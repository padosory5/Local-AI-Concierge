"""Looking things up on the web (research.py): code decides when, the user is asked
once, what comes back goes with the question, and the sources stay with the answer."""

import pytest

from concierge import noir, research, voice
from concierge.agents import store
from concierge.agents.router import Route
from concierge.conversations import ChatBook
from concierge.engine import NoirEngine
from concierge.events import NoirDone, NoirText, Picture, Question, Source, Thinking
from tests.test_chat_path import Ollama


def test_code_knows_which_answers_change():
    for text in ("what's the weather in Seoul today?", "is it going to rain tomorrow", "부산 날씨 어때"):
        assert research.wants_lookup(text) == research.WEATHER, text
    for text in ("latest news about the election", "who is the president of South Korea",
                 "what's the newest version of Python", "how old is Son Heung-min", "오늘 환율 알려줘"):
        assert research.wants_lookup(text) == research.SEARCH, text
    for text in ("show me a picture of Hallasan", "what does a platypus look like"):
        assert research.wants_lookup(text) == research.IMAGES, text
    for text in ("Whats the stock price for samsung electronics right now", "how much is bitcoin worth", "삼성전자 주가"):
        assert research.wants_lookup(text) == research.PRICE, text


def test_a_price_comes_from_the_exchange_feed_not_a_snippet():
    assert research.price_subject("Whats the stock price for samsung electronics right now") == "samsung electronics"
    assert research.price_subject("how much is bitcoin worth today?") == "bitcoin"

    def get(url, **params):
        if url == research.YAHOO_SEARCH:
            assert params["q"] == "samsung electronics"
            return {"quotes": [{"symbol": "005930.KS", "shortname": "SamsungElec", "quoteType": "EQUITY"}]}
        if url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/005930.KS"):
            return {"chart": {"result": [{"meta": {"longName": "Samsung Electronics Co., Ltd.", "currency": "KRW",
                                                   "fullExchangeName": "KSE", "regularMarketPrice": 188700.0,
                                                   "chartPreviousClose": 225000.0, "regularMarketTime": 1793946608,
                                                   "regularMarketDayLow": 179200.0, "regularMarketDayHigh": 196500.0,
                                                   "fiftyTwoWeekLow": 94500.0, "fiftyTwoWeekHigh": 374500.0}}]}}
        raise AssertionError(url)

    found = research.price("Whats the stock price for samsung electronics right now", get=get)
    assert found.text.startswith("Samsung Electronics Co., Ltd. (005930.KS, KSE) last traded at 188,700.0 KRW on ")
    assert "- Previous close 225,000.0 KRW, so -16.1% since then" in found.text
    assert found.sources == [Source("https://finance.yahoo.com/quote/005930.KS", "Yahoo Finance")]

    def coin_get(url, **params):
        if url == research.COINGECKO_SEARCH:
            return {"coins": [{"id": "bitcoin", "name": "Bitcoin", "symbol": "btc"}]}
        if url == research.COINGECKO_PRICE:
            return {"bitcoin": {"usd": 75445, "krw": 102233313, "usd_24h_change": -6.27}}
        raise AssertionError(url)

    found = research.price("how much is bitcoin worth today?", get=coin_get)
    assert found.text == "Bitcoin (BTC) right now: 75,445 USD, 102,233,313 KRW, -6.3% over the last 24 hours (CoinGecko)."
    # A company the feeds don't list falls back to the web search.
    found = research.look_up("stock price of a corner shop", research.PRICE,
                             price=lambda q: (_ for _ in ()).throw(LookupError("nothing listed")),
                             search=lambda q: [{"title": "Shop", "href": "https://shop.example.com", "body": "Open."}],
                             images=lambda q: [], wikipedia=lambda q: None, sent=lambda *a: None, count=lambda: None)
    assert found.kind == research.SEARCH and "1. Shop (shop.example.com): Open." in found.text


def test_what_never_changes_is_never_looked_up():
    for text in ("solve x^2 - 5x + 6 = 0", "why is the sky blue", "what happened in 1066", "explain gravity",
                 "how do I take a screenshot", "translate this into Korean", "what does serendipity mean",
                 "should I learn Python or JavaScript", "hey how are you",
                 "hm its not worth it. forget about it"):  # "worth" alone once sent it to the web
        assert research.wants_lookup(text) is None, text
    assert research.wants_lookup("what is Elon Musk's net worth") == research.SEARCH
    # A question code can't place is put to its model; small talk and timeless things never are.
    assert research.unsure("what's the capital of Korea?")
    assert not research.unsure("explain gravity")
    assert not research.unsure("hey how are you")


def test_the_place_in_a_weather_question():
    assert research.place_in("what's the weather in Busan tomorrow?") == "Busan"
    assert research.place_in("Seoul weather today") == "Seoul"
    assert research.place_in("부산 날씨 어때") == "부산"
    assert research.place_in("is it raining right now?") == ""


def test_the_findings_go_together_with_their_sources_and_pictures():
    sent, counted = [], []
    found = research.look_up(
        "who is the president of South Korea", research.SEARCH,
        search=lambda q: [{"title": "President of South Korea", "href": "https://en.wikipedia.org/wiki/President",
                           "body": "The current president is Lee Jae-myung, in office since June 2025."},
                          {"title": "News", "href": "https://www.example.com/news", "body": "Latest on the election."}],
        images=lambda q: [{"image": "https://pics.example.com/lee.jpg", "thumbnail": "https://pics.example.com/t.jpg",
                           "title": "Lee Jae-myung", "url": "https://www.example.com/lee"}],
        wikipedia=lambda q: {"title": "Lee Jae-myung", "extract": "Lee Jae-myung is a South Korean politician.",
                             "fullurl": "https://en.wikipedia.org/wiki/Lee_Jae-myung",
                             "thumbnail": {"source": "https://upload.wikimedia.org/lee.jpg"}},
        sent=lambda *a: sent.append(a), count=lambda: counted.append(1))
    assert found.text.startswith("1. President of South Korea (en.wikipedia.org): The current president is Lee Jae-myung")
    assert "Wikipedia, Lee Jae-myung: Lee Jae-myung is a South Korean politician." in found.text
    assert [s.path for s in found.sources[:2]] == ["https://en.wikipedia.org/wiki/President", "https://www.example.com/news"]
    assert found.sources[2] == Source("https://en.wikipedia.org/wiki/Lee_Jae-myung", "Wikipedia: Lee Jae-myung")
    assert found.images[0].title == "Lee Jae-myung" and found.images[1].thumbnail == "https://pics.example.com/t.jpg"
    assert sent == [("DuckDuckGo", "a web search")] and counted == [1]
    note = research.note(found)
    assert note.startswith("FOUND ON THE WEB just now (") and "don't add anything they don't say" in note
    assert "never say you can't access the web" in note  # it once said it was offline with the findings in hand


def test_the_first_pages_are_read_after_the_search():
    read = []
    found = research.look_up(
        "what's the newest version of python", research.SEARCH,
        search=lambda q: [{"title": "Downloads", "href": "https://www.python.org/downloads/", "body": "Download."},
                          {"title": "A PDF", "href": "https://example.com/paper.pdf", "body": "Paper."},
                          {"title": "News", "href": "https://blog.python.org/", "body": "Released."},
                          {"title": "More", "href": "https://docs.python.org/", "body": "Docs."}],
        images=lambda q: [], wikipedia=lambda q: None,
        read=lambda url: read.append(url) or f"Words of {url}", sent=lambda *a: None, count=lambda: None)
    assert read == ["https://www.python.org/downloads/", "https://blog.python.org/"]  # two pages, never the PDF
    assert "FROM THE PAGE python.org (https://www.python.org/downloads/):\nWords of https://www.python.org/downloads/" in found.text
    assert found.text.index("1. Downloads") < found.text.index("FROM THE PAGE")  # snippets first, then the pages


def test_a_page_is_cut_to_its_words():
    html = ("<html><head><title>Downloads</title><style>p{color:red}</style><script>var x=1;</script></head>"
            "<body><nav>Menu Home</nav><h1>Python 3.15.2</h1><p>The latest &amp; greatest.</p>"
            "<div>Second   line</div><span>|</span><footer>Legal</footer></body></html>")
    assert research.page_text(html) == "Downloads\nPython 3.15.2\nThe latest & greatest.\nSecond line"

    class Reply:
        ok = True
        encoding = "utf-8"
        headers = {"content-type": "text/html; charset=utf-8"}

        class raw:
            @staticmethod
            def read(size, decode_content=True):
                return html.encode()

    assert research.read_page("https://example.com/page", get=lambda *a, **k: Reply()).startswith("Downloads\nPython 3.15.2")
    assert research.read_page("https://example.com/paper.pdf", get=lambda *a, **k: Reply()) == ""
    Reply.headers = {"content-type": "application/octet-stream"}
    assert research.read_page("https://example.com/file", get=lambda *a, **k: Reply()) == ""
    assert research.read_page("https://example.com/x", get=lambda *a, **k: (_ for _ in ()).throw(OSError())) == ""


def test_a_brave_key_is_used_first_and_the_free_path_is_the_fallback():
    def brave(question, key, get=None):
        assert key == "secret"
        return [{"title": "Brave hit", "href": "https://brave.example.com", "body": "Found."}]

    assert research.search("anything", key="secret", brave=brave)[0]["title"] == "Brave hit"
    with_failure = research.search("anything", key="secret", brave=lambda q, k: (_ for _ in ()).throw(OSError()))
    assert isinstance(with_failure, list)  # the free path answered (or found nothing), never an error from the key


def test_nothing_found_is_an_error_not_an_empty_answer():
    with pytest.raises(LookupError):
        research.look_up("latest news", research.SEARCH, search=lambda q: [], images=lambda q: [],
                         wikipedia=lambda q: None, sent=lambda *a: None, count=lambda: None)


def test_weather_is_read_plainly_from_open_meteo():
    def get(url, **params):
        if url == research.GEOCODE:
            assert params["name"] == "Busan"
            return {"results": [{"name": "Busan", "admin1": "Busan", "country": "South Korea", "latitude": 35.1,
                                 "longitude": 129.0}]}
        return {"current": {"time": "2026-11-06T16:30", "temperature_2m": 12.5, "apparent_temperature": 11.0,
                            "weather_code": 2, "wind_speed_10m": 9.0, "relative_humidity_2m": 40},
                "daily": {"time": ["2026-11-06", "2026-11-07"], "weather_code": [2, 61],
                          "temperature_2m_max": [15.0, 13.0], "temperature_2m_min": [8.0, 7.0],
                          "precipitation_probability_max": [5, 70]}}

    found = research.weather("Busan", get=get)
    assert found.text.startswith("Weather in Busan, Busan, South Korea, local time 2026-11-06T16:30:")
    assert "- Right now: 12.5°C (partly cloudy), feels like 11.0°C, wind 9.0 km/h, humidity 40%" in found.text
    assert "- Tomorrow (Saturday 2026-11-07): high 13.0°C, low 7.0°C, light rain, chance of rain 70%" in found.text
    assert found.sources == [Source("https://open-meteo.com", "Open-Meteo")]


def test_permission_is_remembered_and_lookups_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(noir, "data_dir", lambda: tmp_path)
    assert research.allowed() is None
    research.allow(True)
    assert research.allowed() is True and research.lookups() == 0
    research._count()
    assert research.lookups() == 1
    research.allow(False)
    assert research.allowed() is False and research.lookups() == 1


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "agents_dir", lambda: tmp_path / "agents")
    monkeypatch.setattr(noir, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("concierge.engine.route", lambda *args, **kwargs: Route("chat"))
    monkeypatch.setattr(research, "model_form", lambda ollama, model: lambda text: False)
    made = NoirEngine(Ollama())
    made.book = ChatBook(None)
    made.chat = noir.NoirChat(made.ollama)
    from concierge.agents.builder import AgentBuilder
    from concierge.agents.planner import IdeaPlanner
    made.builder = AgentBuilder(made.ollama, "noir", None, made.blueprints)
    made.planner = IdeaPlanner(made.ollama, "noir", None, lambda: None, made.blueprints)
    return made


FOUND = research.Findings(research.SEARCH, "1. Coin site (coins.example.com): Bitcoin is $75,000 today.",
                          [Source("https://coins.example.com/btc", "Bitcoin price")],
                          [Picture("https://coins.example.com/btc.png", "", "Bitcoin", "https://coins.example.com")],
                          "2026-11-06T16:30")


def test_she_asks_once_before_the_first_lookup_and_then_answers_from_the_web(engine, monkeypatch):
    looked = []
    monkeypatch.setattr(research, "look_up", lambda text, kind: looked.append((text, kind)) or FOUND)
    events = list(engine.send("what's the newest version of python?"))
    question = next(e for e in events if isinstance(e, Question))
    assert question.id == research.WEB and question.choices == [research.YES_LOOK, research.NO_LOOK]
    assert looked == [] and not any(isinstance(e, NoirText) for e in events)

    events = list(engine.choose(research.WEB, research.YES_LOOK))
    assert research.allowed() is True and looked == [("what's the newest version of python?", research.SEARCH)]
    assert any(isinstance(e, Thinking) and "looking this up on the web" in e.text for e in events)
    assert "".join(e.text for e in events if isinstance(e, NoirText)) == "Tokyo."
    done = next(e for e in events if isinstance(e, NoirDone))
    assert done.sources == FOUND.sources and done.images == FOUND.images
    # Its model read the findings along with the question, and remembers them.
    asked = engine.chat.history[-2]["content"]
    assert asked.startswith("FOUND ON THE WEB just now (2026-11-06 16:30") and asked.endswith("what's the newest version of python?")
    # The next lookup needs no question.
    events = list(engine.send("and the weather in Seoul?"))
    assert not any(isinstance(e, Question) for e in events) and looked[-1][1] == research.WEATHER


def test_no_means_she_answers_from_memory_and_says_so(engine, monkeypatch):
    monkeypatch.setattr(research, "look_up", lambda text, kind: (_ for _ in ()).throw(AssertionError("looked up")))
    list(engine.send("latest news today"))
    events = list(engine.choose(research.WEB, research.NO_LOOK))
    assert research.allowed() is False
    assert any(isinstance(e, Thinking) and "from memory" in e.text for e in events)
    assert "".join(e.text for e in events if isinstance(e, NoirText)) == "Tokyo."
    assert next(e for e in events if isinstance(e, NoirDone)).sources == []


def test_when_the_web_fails_she_still_answers(engine, monkeypatch):
    research.allow(True)
    monkeypatch.setattr(research, "look_up", lambda text, kind: (_ for _ in ()).throw(LookupError("nothing came back")))
    events = list(engine.send("who is the president of south korea now"))
    assert any(isinstance(e, Thinking) and "may be out of date" in e.text for e in events)
    assert "".join(e.text for e in events if isinstance(e, NoirText)) == "Tokyo."


def test_the_saved_chat_keeps_the_time_sources_and_pictures(engine, monkeypatch):
    research.allow(True)
    monkeypatch.setattr(research, "look_up", lambda text, kind: FOUND)
    list(engine.send("bitcoin price now"))
    items = engine.book.transcript().items
    assert items[0].role == "user" and items[0].when[:4] == "2026" or items[0].when
    assert items[1].sources == FOUND.sources and items[1].images == FOUND.images and items[1].when


def test_math_and_science_get_their_own_shape():
    assert voice.kind_of("solve x^2 - 5x + 6 = 0") == "math"
    assert voice.kind_of("what's the derivative of sin(x)*x^2") == "math"
    assert voice.kind_of("how do I solve 2x + 3 = 11") == "math"  # working it out, not a how-to
    assert voice.kind_of("a 2 kg box on a 30 degree slope with no friction, what's its acceleration?") == "science"
    assert voice.kind_of("why does ice float?") == "explain"
    assert voice.kind_of("What's the capital of Australia?") == "fact"
    assert "LaTeX between $...$" in voice.guide("solve x^2 = 4") and "numbered step" in voice.guide("solve x^2 = 4")
    assert "explain why" in voice.guide("what is the acceleration of a falling ball")
    explain = voice.guide("explain how a transformer works")
    assert "paragraphs" in explain and "up to" not in explain  # prose, never a forced list


def test_only_a_model_that_draws_well_is_asked_to_draw_unless_the_user_asks():
    question = "what forces act on a box on a slope?"
    assert "```svg" not in voice.guide(question)
    assert "```svg" in voice.guide(question, draws=True)
    assert "```svg" in voice.guide("draw the forces on a box on a slope")
    assert "```svg" not in voice.guide("solve x^2 = 4", draws=True)  # the working is the drawing
