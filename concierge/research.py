"""Looking things up on the web, for answers that change.

A small model's knowledge stops at its training date, so a question about today's
weather, a price, the news, who holds an office or the newest version of something
can't be answered from memory. Code decides when the web is needed (`wants_lookup`:
words that mean the answer changes, and words that mean it never does, such as
history, maths and meanings), her model is only asked about a question code can't
place (`model_form`, one word, forced by the schema), and nothing is sent anywhere
until the user has said yes once (`allowed`, kept in research.json next to how many
lookups were made). What comes back goes with the question as plain text, with the
time it was found, so she answers from it and says so, and the sources go under her
answer. Weather comes from Open-Meteo (no key, no account), the rest from
DuckDuckGo through the ddgs package, and a Wikipedia summary when the question is
about a person or thing. Only the question leaves the computer, never a file.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from . import cloud
from .cloud import record_sent
from .events import Picture, Source

SETTINGS = "research.json"
WEB_QUESTION = ("This can change from day to day, so I'd look it up on the web. Only your question goes "
                "out, never your files or anything else here. Shall I?")
YES_LOOK = "Yes, look it up"
NO_LOOK = "No, answer from memory"
WEB = "web"  # the Question's id and the setting's name
WEATHER, SEARCH, IMAGES, PRICE = "weather", "search", "images", "price"
MAX_RESULTS = 6
MAX_IMAGES = 2
SNIPPET_CHARS = 300
EXTRACT_CHARS = 700
# After the search, the first pages are read too: a snippet names the page that has
# the number, the page has it. That is how the other apps get real answers.
MAX_PAGES = 2
PAGE_CHARS = 2000
PAGE_BYTES = 1_500_000
PAGE_TIMEOUT = 6
SKIP_PAGES = re.compile(r"\.(pdf|zip|mp4|mp3)(\?|$)|youtube\.com|youtu\.be|/login|/signin|facebook\.com|x\.com|twitter\.com", re.I)
FINDINGS_CHARS = 7000  # what goes with the question: snippets, then the pages
TIMEOUT = 8
# A Brave Search key makes the search steady (the free path gets "no results" and
# blocks); it's optional, saved in Windows' password store like the model keys.
BRAVE_SEARCH = "https://api.search.brave.com/res/v1/web/search"
SEARCH_KEY = "brave_search"
SEARCH_KEY_PAGE = "https://brave.com/search/api/"
USER_AGENT = "LocalAIConcierge/0.1 (https://github.com/padosory5/elaina-agents)"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
WHERE_AM_I = "https://ipapi.co/json/"  # the city of the internet connection, when no place is named
WIKIPEDIA = "https://{language}.wikipedia.org/w/api.php"
# Prices come from the exchanges' own feeds, not search snippets: the pages a search
# finds have the number, their snippets don't, and she then said she was offline.
YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
COINGECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
COINGECKO_PRICE = "https://api.coingecko.com/api/v3/simple/price"
BROWSER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/130.0 Safari/537.36")  # Yahoo answers a browser, not a script

_I = re.IGNORECASE
# Words that mean the answer is different today from last year, or last week.
CHANGING = re.compile(
    r"\b(today|tonight|tomorrow|yesterday|this (week|weekend|month|year)|right now|currently|current|latest|newest|"
    r"recent|recently|news|headlines?|breaking|happening|update[sd]?|price|prices|cost|costs|how much (is|are|does|do)"
    r"|worth|stock|shares?|market|exchange rate|rate of|bitcoin|crypto|ethereum|score|scores|result|results|won|"
    r"winner|standings|ranking|rankings|rank|schedule|fixture|release date|released|out yet|version|"
    r"opening hours|open (now|today|on)|closed|holiday|when is the next|what day is|what('s| is) the (date|time)|"
    r"who is the (president|prime minister|ceo|leader|mayor|governor|king|queen|chancellor|champion|coach|"
    r"manager|head)|how old is|age of|net worth|population of|election|poll|polls|war in|earthquake|typhoon|"
    r"hurricane|flight|train|traffic|trending|best .{0,40}\b20(2[4-9]|3\d)\b|\b20(2[5-9]|3\d)\b)\b|"
    r"오늘|내일|어제|지금|현재|최근|최신|뉴스|가격|얼마|환율|주가|대통령|나이|몇 살|순위|결과|일정|날짜|몇 시",
    _I)
# Words that mean the answer never changes, so her own knowledge is enough.
TIMELESS = re.compile(
    r"\b(history|historical|ancient|medieval|century|centuries|in \d{3,4}\b|prove|proof|theorem|derive|derivative|"
    r"integral|integrate|equation|solve|calculate|compute|simplify|probability|formula|physics|chemistry|biology|"
    r"gravity|velocity|momentum|photosynthesis|evolution|mean(s|ing)? of|definition|define|what does .{1,30} mean|"
    r"difference between|how does .{1,40} work|why (is|are|do|does)|explain|translate|grammar|spell|synonym|"
    r"poem|story|joke|recipe|how to|how do i|tips? for|advice|should i)\b|"
    r"역사|증명|방정식|풀어|계산|공식|물리|화학|설명|뜻|의미|번역|차이|어떻게",
    _I)
WEATHER_WORDS = re.compile(
    r"\b(weather|temperature|forecast|rain|raining|snow|snowing|umbrella|humid|humidity|windy|how (hot|cold|warm) is it|"
    r"sunny|cloudy)\b|날씨|기온|비 ?(와|올)|눈 ?(와|올)|우산|덥|춥", _I)
IMAGE_WORDS = re.compile(
    r"\b(show me|picture|pictures|photo|photos|image|images|what does .{1,40} look like|look like)\b|사진|이미지|그림|모습",
    _I)
PRICE_WORDS = re.compile(
    r"\b(stock|stocks|share price|shares|ticker|market cap|crypto|cryptocurrency|coin|bitcoin|btc|ethereum|eth|"
    r"solana|dogecoin|xrp)\b|주가|주식|비트코인|코인|시세", _I)
CRYPTO_WORDS = re.compile(r"\b(crypto|cryptocurrency|coin|bitcoin|btc|ethereum|eth|solana|dogecoin|xrp|token)\b"
                          r"|비트코인|코인", _I)
# What's left of a price question once the asking is taken off: the company or coin.
PRICE_FILLER = re.compile(
    r"\b(what'?s|what is|whats|how much is|how much are|tell me|the|a|current|currently|right now|now|today|"
    r"latest|price|prices|stock|stocks|share|shares|of|for|in|is|are|at|worth|trading|value|usd|krw|dollars|won|"
    r"please)\b|[?.!,]|주가|주식|시세|가격|얼마|지금|현재|오늘|알려줘", _I)
# A question that code didn't place, which her model is then asked about.
QUESTION = re.compile(r"\?\s*$|^\s*(what|who|which|when|where|how|is|are|was|were|does|do|did|has|have|can|will)\b"
                      r"|뭐|누구|언제|어디|무엇|나요|까요", _I)
# The place in "weather in Busan tomorrow", "Busan weather", "부산 날씨".
PLACE_AFTER = re.compile(r"\b(?:in|at|for|around|near)\s+([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,3})")
PLACE_BEFORE = re.compile(r"\b([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2})\s+(?:weather|forecast|temperature)", _I)
PLACE_KO = re.compile(r"([가-힣]{2,10}?)(?:의|은|는)?\s*(?:날씨|기온)")
SKY = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle",
       53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain",
       63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
       75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
       85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
       99: "thunderstorm with hail"}


@dataclass
class Findings:
    kind: str
    text: str = ""  # what her model reads, plain lines
    sources: list[Source] = field(default_factory=list)  # path: the address, quote: the page's title
    images: list[Picture] = field(default_factory=list)
    when: str = ""  # when it was found, this computer's clock


# ---------------------------------------------------------------- deciding


def wants_lookup(text: str) -> str | None:
    """What the web is needed for, decided from the words alone: WEATHER, IMAGES,
    SEARCH, or None when her own knowledge will do or code can't tell."""
    if WEATHER_WORDS.search(text) and not TIMELESS.search(text):
        return WEATHER
    if IMAGE_WORDS.search(text):
        return IMAGES
    if PRICE_WORDS.search(text) and re.search(r"price|worth|how much|trading|value|cost|주가|시세|가격|얼마", text, _I):
        return PRICE
    if CHANGING.search(text) and not TIMELESS.search(text):
        return SEARCH
    return None


def unsure(text: str) -> bool:
    """A question that neither the changing nor the timeless words placed: her model is
    asked whether its answer changes over time."""
    return bool(QUESTION.search(text.strip())) and not TIMELESS.search(text) and not CHANGING.search(text)


def model_form(ollama, model: str):
    """Her small model asked one thing: does the right answer change over time? The
    schema allows one word, so the reply is yes or no and nothing else."""
    schema = {"type": "object", "properties": {"changes": {"enum": ["yes", "no"]}}, "required": ["changes"]}
    note = ("Would the correct answer to this message be different a year from now, or depend on what is "
            "happening now (prices, weather, news, who holds a job, scores, the newest version of something, "
            "what is open or available today)? Answer yes only then. Facts of history, science, maths, "
            "language, how things work, advice and opinions are no.")

    def ask(text: str) -> bool:
        try:
            reply = ollama.chat_json(model, [{"role": "system", "content": note},
                                             {"role": "user", "content": text}], schema, think=False)
        except Exception:
            return False  # if in doubt, her own answer: a lookup she didn't need costs more trust
        return reply.get("changes") == "yes"

    return ask


# ---------------------------------------------------------------- permission


def settings_path() -> Path:
    from .elaina import data_dir

    return data_dir() / SETTINGS


def _read() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def allowed() -> bool | None:
    """Whether the user said she may look things up: None until they've been asked."""
    return _read().get("allowed")


def allow(on: bool) -> None:
    _write({**_read(), "allowed": bool(on)})


def lookups() -> int:
    return int(_read().get("lookups", 0))


def _count() -> None:
    _write({**_read(), "lookups": lookups() + 1})


# ---------------------------------------------------------------- looking up


def place_in(text: str) -> str:
    """The place a weather question names, or nothing."""
    for pattern in (PLACE_KO, PLACE_AFTER, PLACE_BEFORE):
        if found := pattern.search(text):
            name = found.group(1).strip(" ,.?!")
            if name.lower() not in {"the", "it", "today", "tomorrow", "tonight", "now"}:
                return name
    return ""


def _get(url: str, **params) -> dict:
    agent = BROWSER_AGENT if "yahoo.com" in url else USER_AGENT
    reply = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": agent})
    reply.raise_for_status()
    return reply.json()


def price_subject(question: str) -> str:
    """The company or coin a price question is about: "Samsung Electronics", "bitcoin"."""
    return re.sub(r"\s+", " ", PRICE_FILLER.sub(" ", question)).strip()


def price(question: str, get=_get) -> Findings:
    """What a share or coin trades at right now: CoinGecko for a coin, Yahoo Finance
    for a listed company, each with the change since the last close."""
    subject = price_subject(question)
    if not subject:
        raise LookupError("no company or coin named")
    when = datetime.now().isoformat(timespec="minutes")
    if CRYPTO_WORDS.search(question):
        coins = get(COINGECKO_SEARCH, query=subject).get("coins") or []
        if coins:
            coin = coins[0]
            data = get(COINGECKO_PRICE, ids=coin["id"], vs_currencies="usd,krw", include_24hr_change="true")
            now = data.get(coin["id"], {})
            if now.get("usd") is not None:
                change = now.get("usd_24h_change")
                won = f", {now['krw']:,.0f} KRW" if now.get("krw") else ""
                moved = f", {change:+.1f}% over the last 24 hours" if change is not None else ""
                text = f"{coin['name']} ({coin['symbol'].upper()}) right now: {now['usd']:,} USD{won}{moved} (CoinGecko)."
                return Findings(PRICE, text, [Source(f"https://www.coingecko.com/en/coins/{coin['id']}", "CoinGecko")],
                                when=when)
    quotes = [q for q in get(YAHOO_SEARCH, q=subject, quotesCount=6, newsCount=0).get("quotes") or []
              if q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "MUTUALFUND")]
    if not quotes:
        raise LookupError(f"nothing listed as {subject}")
    quote = quotes[0]
    result = get(YAHOO_CHART.format(symbol=quote["symbol"]), range="5d", interval="1d")["chart"]["result"][0]
    meta = result.get("meta", {})
    last = meta.get("regularMarketPrice")
    if last is None:
        raise LookupError("no price in the feed")
    before = meta.get("previousClose") or meta.get("chartPreviousClose")
    currency = meta.get("currency", "")
    name = meta.get("longName") or meta.get("shortName") or quote.get("shortname") or quote["symbol"]
    at = datetime.fromtimestamp(meta["regularMarketTime"]).strftime("%A %Y-%m-%d %H:%M") if meta.get(
        "regularMarketTime") else when
    lines = [f"{name} ({quote['symbol']}, {meta.get('fullExchangeName') or meta.get('exchangeName', '')}) last traded "
             f"at {last:,} {currency} on {at}, this computer's time."]
    if before:
        lines.append(f"- Previous close {before:,} {currency}, so {100 * (last - before) / before:+.1f}% since then")
    if meta.get("regularMarketDayLow") and meta.get("regularMarketDayHigh"):
        lines.append(f"- Today's range {meta['regularMarketDayLow']:,} to {meta['regularMarketDayHigh']:,} {currency}")
    if meta.get("fiftyTwoWeekLow") and meta.get("fiftyTwoWeekHigh"):
        lines.append(f"- 52-week range {meta['fiftyTwoWeekLow']:,} to {meta['fiftyTwoWeekHigh']:,} {currency}")
    lines.append("(Yahoo Finance; prices can be delayed by some minutes.)")
    return Findings(PRICE, "\n".join(lines), [Source(f"https://finance.yahoo.com/quote/{quote['symbol']}",
                                                      "Yahoo Finance")], when=when)


def weather(place: str, get=_get) -> Findings:
    """Now and the next two days where the user asked, from Open-Meteo. Without a
    place, the city of the internet connection, and the answer says so."""
    guessed = not place
    if guessed:
        here = get(WHERE_AM_I)
        place = f"{here.get('city', '')}, {here.get('country_name', '')}".strip(", ")
        if not place:
            raise LookupError("no place")
    found = get(GEOCODE, name=place, count=1, language="en").get("results") or []
    if not found:
        raise LookupError(f"no place called {place}")
    spot = found[0]
    where = ", ".join(part for part in (spot.get("name"), spot.get("admin1"), spot.get("country")) if part)
    data = get(FORECAST, latitude=spot["latitude"], longitude=spot["longitude"],
               current="temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
               daily="weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
               timezone="auto", forecast_days=3)
    now, daily = data.get("current", {}), data.get("daily", {})
    lines = [f"Weather in {where}, local time {now.get('time', '')}:"]
    if guessed:  # the user named no place, and an internet connection can sit in another city
        lines.insert(0, f"No place was named, so this is for {where}, the city of the user's internet connection, "
                        "which may be wrong. Say which city this is for, and that they can name another.")
    lines += [
             f"- Right now: {now.get('temperature_2m')}°C ({SKY.get(now.get('weather_code'), 'unknown sky')}), "
             f"feels like {now.get('apparent_temperature')}°C, wind {now.get('wind_speed_10m')} km/h, "
             f"humidity {now.get('relative_humidity_2m')}%"]
    for i, label in enumerate(("Today", "Tomorrow", "The day after")):
        try:
            # The weekday is spelled out: left to work it out, her model called a Saturday Tuesday.
            day = datetime.fromisoformat(daily["time"][i]).strftime("%A %Y-%m-%d")
            lines.append(f"- {label} ({day}): high {daily['temperature_2m_max'][i]}°C, low "
                         f"{daily['temperature_2m_min'][i]}°C, {SKY.get(daily['weather_code'][i], 'unknown sky')}, "
                         f"chance of rain {daily['precipitation_probability_max'][i]}%")
        except (KeyError, IndexError, TypeError):
            break
    return Findings(WEATHER, "\n".join(lines), [Source("https://open-meteo.com", "Open-Meteo")],
                    when=now.get("time", ""))


def _site(url: str) -> str:
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0])


# Tried in turn: each engine alone answered "no results" to a question another one
# answered a second later, so one try is never enough.
SEARCH_ENGINES = ("auto", "bing", "duckduckgo", "auto")


def search_key() -> str:
    return cloud.saved_key(SEARCH_KEY)


def set_search_key(key: str) -> None:
    """Save a Brave Search key, or forget it when empty."""
    if key.strip():
        cloud.save_key(SEARCH_KEY, key)
    else:
        cloud.forget_key(SEARCH_KEY)


def brave(question: str, key: str, get=requests.get) -> list[dict]:
    """Brave's results in the same shape as the free search's."""
    reply = get(BRAVE_SEARCH, params={"q": question, "count": MAX_RESULTS}, timeout=TIMEOUT,
                headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": USER_AGENT})
    reply.raise_for_status()
    return [{"title": row.get("title", ""), "href": row.get("url", ""), "body": row.get("description", "")}
            for row in reply.json().get("web", {}).get("results", [])]


def search(question: str, key: str | None = None, brave=brave) -> list[dict]:
    key = search_key() if key is None else key
    if key:
        try:
            if rows := brave(question, key):
                return rows
        except Exception:
            pass  # the key's quota or the service: the free path is still there
    from ddgs import DDGS

    failed = None
    for engine in SEARCH_ENGINES:
        try:
            if rows := DDGS().text(question, max_results=MAX_RESULTS, backend=engine):
                return rows
        except Exception as exc:
            failed = exc
    if failed:
        raise failed
    return []


TAGS_TO_DROP = re.compile(r"<(script|style|noscript|svg|nav|footer|header|aside)\b.*?</\1\s*>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
BLOCK_END = re.compile(r"</(p|div|li|h[1-6]|tr|br|section|article|td|th|dd|dt|title|head)\s*>|<br\s*/?>", re.I)


def page_text(html_text: str) -> str:
    """The words of a web page, without its markup, menus and scripts."""
    import html as entities

    text = TAGS_TO_DROP.sub(" ", html_text)
    text = BLOCK_END.sub("\n", text)
    text = TAG.sub(" ", text)
    text = entities.unescape(text)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if len(line) > 1)


def read_page(url: str, get=requests.get) -> str:
    """The start of a page's words, or nothing: a page that won't open or isn't a web
    page (a PDF, a video) must not stop the answer."""
    if SKIP_PAGES.search(url):
        return ""
    try:
        reply = get(url, timeout=PAGE_TIMEOUT, headers={"User-Agent": BROWSER_AGENT}, stream=True)
        if not reply.ok or "html" not in reply.headers.get("content-type", "").lower():
            return ""
        body = reply.raw.read(PAGE_BYTES, decode_content=True)
        encoding = reply.encoding or "utf-8"
        return page_text(body.decode(encoding, errors="replace"))[:PAGE_CHARS]
    except Exception:
        return ""


def images(question: str) -> list[dict]:
    from ddgs import DDGS

    return DDGS().images(question, max_results=MAX_IMAGES) or []


def wikipedia(question: str, get=_get) -> dict | None:
    """The start of the Wikipedia page a question is about, if one matches well."""
    language = "ko" if re.search(r"[가-힣]", question) else "en"
    subject = re.sub(r"^\s*(who|what|which|where|when|how old|how big|how tall)\s+(is|are|was|were)\s+(the\s+)?", "",
                     question, flags=_I).strip(" ?.!")
    if not subject:
        return None
    pages = get(WIKIPEDIA.format(language=language), action="query", format="json", formatversion=2,
                generator="search", gsrsearch=subject, gsrlimit=1, prop="extracts|pageimages|info", exintro=1,
                explaintext=1, exchars=EXTRACT_CHARS, piprop="thumbnail", pithumbsize=320,
                inprop="url").get("query", {}).get("pages", [])
    return pages[0] if pages else None


def _wants_wikipedia(question: str) -> bool:
    """A question about a person or thing, where the page's first lines help. Not
    about the latest anything: the page's history then drowned out the news."""
    return bool(re.match(r"\s*(who|what|which|how old|how big|how tall)\b", question, _I)) and not re.search(
        r"\b(latest|newest|current|currently|today|now|recent|price|news|version|release)\b", question, _I)


def look_up(question: str, kind: str, search=search, images=images, weather=weather, wikipedia=wikipedia,
            price=price, read=read_page, sent=record_sent, count=_count) -> Findings:
    """What the web says, in one piece of plain text her model can read, with the
    sources and any pictures. Raises LookupError when nothing came back."""
    when = datetime.now().isoformat(timespec="minutes")
    if kind == WEATHER:
        sent("Open-Meteo", "the weather")
        count()
        found = weather(place_in(question))
        found.when = found.when or when
        return found
    if kind == PRICE:
        sent("Yahoo Finance or CoinGecko", "a price")
        count()
        try:
            return price(question)
        except (LookupError, requests.RequestException, KeyError, ValueError, TypeError):
            kind = SEARCH  # not listed, or the feed is down: the web search may still say
    sent("Brave Search" if search_key() else "DuckDuckGo", "a web search")
    count()
    found = Findings(kind, when=when)
    parts: dict[str, object] = {}

    def run(name, call):
        try:
            parts[name] = call()
        except Exception as exc:  # one source failing must not lose the others
            parts[name] = exc

    jobs = []
    if kind == IMAGES or _wants_wikipedia(question):
        jobs.append(threading.Thread(target=run, args=("images", lambda: images(question))))
    if kind == SEARCH:
        jobs.append(threading.Thread(target=run, args=("search", lambda: search(question))))
        if _wants_wikipedia(question):
            jobs.append(threading.Thread(target=run, args=("wikipedia", lambda: wikipedia(question))))
    for job in jobs:
        job.start()
    for job in jobs:
        job.join(TIMEOUT + 4)

    lines = []
    results = parts.get("search")
    pages: dict[str, str] = {}
    if isinstance(results, list):  # the search comes first: it's the newest
        urls = [row.get("href") for row in results[:MAX_RESULTS] if row.get("href")]
        to_read = [url for url in urls if not SKIP_PAGES.search(url)][:MAX_PAGES]
        readers = [threading.Thread(target=lambda u=url: pages.__setitem__(u, read(u))) for url in to_read]
        for reader in readers:
            reader.start()
        for number, row in enumerate(results[:MAX_RESULTS], 1):
            title, url, body = (row.get("title") or "").strip(), row.get("href") or "", (row.get("body") or "").strip()
            if not url:
                continue
            lines.append(f"{number}. {title} ({_site(url)}): {body[:SNIPPET_CHARS]}")
            found.sources.append(Source(url, title or _site(url)))
        for reader in readers:
            reader.join(PAGE_TIMEOUT + 2)
        for url in to_read:
            if words := pages.get(url, "").strip():
                lines.append(f"\nFROM THE PAGE {_site(url)} ({url}):\n{words}")
    page = parts.get("wikipedia")
    if isinstance(page, dict) and page.get("extract"):
        lines.append(f"Wikipedia, {page['title']}: {page['extract'].strip()}")
        found.sources.append(Source(page.get("fullurl") or f"https://en.wikipedia.org/wiki/{page['title']}",
                                    f"Wikipedia: {page['title']}"))
        if page.get("thumbnail", {}).get("source"):
            found.images.append(Picture(page["thumbnail"]["source"], page["thumbnail"]["source"], page["title"],
                                        found.sources[-1].path))
    pictures = parts.get("images")
    if isinstance(pictures, list):
        for row in pictures[:MAX_IMAGES]:
            if row.get("image") and len(found.images) < MAX_IMAGES:
                found.images.append(Picture(row["image"], row.get("thumbnail") or row["image"],
                                            (row.get("title") or "")[:120], row.get("url") or row["image"]))
    if not lines and not found.images:
        raise LookupError("nothing came back")
    found.text = "\n".join(lines)[:FINDINGS_CHARS]
    return found


def note(found: Findings) -> str:
    """The findings as they go with the question, so she answers from them."""
    if found.kind == IMAGES and not found.text:
        titles = "; ".join(picture.title for picture in found.images if picture.title)
        return ("PICTURES FOUND ON THE WEB by the app, shown right under your answer (so don't say you can't show "
                f"images). Their titles: {titles or 'none'}. In one or two sentences, say what the pictures show "
                "and one thing worth knowing about it.")
    head = (f"FOUND ON THE WEB just now ({found.when.replace('T', ' ')}, this computer's clock) by the app, for you: "
            "you are NOT offline for this answer, so never say you can't access the web or live data. Answer from "
            "these lines, say it's as of now, and don't add anything they don't say. If they don't hold the answer "
            "(for example pages that have the number but no snippet of it), say the search didn't show it and "
            "name the site that would. Name a source only by its site's name.")
    return f"{head}\n\n{found.text}"
