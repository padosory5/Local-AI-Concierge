"""Finding models on Hugging Face that can run on this computer.

Only models in the GGUF format can run through Ollama, and Ollama fetches them
itself from `hf.co/<owner>/<name>:<size>`, so all this does is read Hugging Face's
public list and work out what each one would really download. No account is
needed. Models that ask for an account (gated ones) are left out, because Ollama
couldn't fetch them.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

import requests

API = "https://huggingface.co/api/models"
TIMEOUT = 15
LIST_LIMIT = 24
SIZE_WORKERS = 6
CACHE_SECONDS = 600
GB = 1_000_000_000
SORTS = {"downloads": "downloads", "likes": "likes", "new": "createdAt"}
VISION = "image-text-to-text"
# Which version of a model to fetch when a repository has several. Q4_K_M is what
# most people use: a good balance of size and quality.
PREFERRED = ("Q4_K_M", "Q4_K_S", "Q5_K_M", "Q4_0", "Q3_K_L", "Q3_K_M", "Q6_K", "Q8_0")
QUANTIZATION = re.compile(r"(?<![A-Za-z0-9])(I?Q\d+(?:_[A-Z0-9]+)*|BF16|F16)(?![A-Za-z0-9])", re.IGNORECASE)
PART = re.compile(r"-\d{5}-of-\d{5}", re.IGNORECASE)


class HubError(RuntimeError):
    """Written for the user."""


@dataclass
class HubModel:
    id: str  # owner/name
    author: str
    name: str
    downloads: int
    likes: int
    tag: str  # what Ollama fetches
    size_gb: float
    family: str
    license: str
    vision: bool


def _get(url: str, params: dict | None = None):
    try:
        reply = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise HubError("I couldn't reach Hugging Face. Check your internet connection.") from exc
    if not reply.ok:
        raise HubError("Hugging Face had a problem. Please try again in a moment.")
    return reply.json()


def best_file(files: list[dict]) -> tuple[str, int]:
    """The version to fetch and its size in bytes, from a repository's files.
    A big model can be split into parts, which together make one version.
    Empty if there's nothing that can be run on its own."""
    sizes: dict[str, int] = {}
    for file in files:
        name = file.get("rfilename", "").rsplit("/", 1)[-1]
        if not name.lower().endswith(".gguf") or name.lower().startswith("mmproj"):
            continue  # an mmproj file only adds sight to a model
        found = QUANTIZATION.search(PART.sub("", name))
        if found and file.get("size"):
            quantization = found.group(1).upper()
            sizes[quantization] = sizes.get(quantization, 0) + file["size"]
    if not sizes:
        return "", 0
    choice = next((q for q in PREFERRED if q in sizes), min(sizes, key=sizes.get))
    return choice, sizes[choice]


def _details(row: dict) -> HubModel | None:
    try:
        info = _get(f"{API}/{row['id']}", {"blobs": "true"})
    except HubError:
        return None  # one that can't be read shouldn't lose the others
    files = info.get("siblings") or []
    quantization, size = best_file(files)
    if not size or info.get("gated") or info.get("disabled"):
        return None
    author, _, name = row["id"].partition("/")
    return HubModel(
        id=row["id"],
        author=author,
        name=re.sub(r"[-_]gguf$", "", name, flags=re.IGNORECASE),
        downloads=row.get("downloads", 0),
        likes=row.get("likes", 0),
        tag=f"hf.co/{row['id']}:{quantization}",
        size_gb=round(size / GB, 1),
        family=(info.get("gguf") or {}).get("architecture", ""),
        license=str((info.get("cardData") or {}).get("license") or ""),
        vision=any(file.get("rfilename", "").lower().startswith("mmproj") for file in files),
    )


_cache: dict[tuple, tuple[float, list[dict]]] = {}


def browse(words: str = "", sort: str = "downloads", kind: str = "") -> list[dict]:
    """The models to show, most wanted first, each with what it would download."""
    key = (words.strip().lower(), sort, kind)
    when, saved = _cache.get(key, (0, []))
    if time.monotonic() - when < CACHE_SECONDS:
        return saved
    params = {"filter": "gguf", "pipeline_tag": VISION if kind == "vision" else "text-generation",
              "sort": SORTS.get(sort, "downloads"), "direction": -1, "limit": LIST_LIMIT}
    if words.strip():
        params["search"] = words.strip()
    if kind == "code" and not words.strip():
        params["search"] = "code"
    rows = _get(API, params)
    with ThreadPoolExecutor(SIZE_WORKERS) as pool:
        found = [asdict(model) for model in pool.map(_details, rows) if model]
    _cache[key] = (time.monotonic(), found)
    return found


def tag_from(text: str) -> str:
    """What Ollama should fetch for a name or a Hugging Face link. Empty if it can't be either."""
    text = text.strip()
    text = re.sub(r"^https?://(www\.)?(huggingface\.co|hf\.co)/", "hf.co/", text).split("?")[0].rstrip("/")
    return text if re.fullmatch(r"[\w.\-]+(/[\w.\-]+)*(:[\w.\-]+)?", text) else ""
