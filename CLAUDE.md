# Local AI Concierge (Elaina)

A simple app that sets up local AI for anyone. Elaina checks the computer,
picks a model that fits it, chats with the user, and (next) creates agents for
everyday tasks. Everything runs on the user's machine through Ollama. Users
are not technical: plain words, no jargon, nothing complicated.

Two people work on this, each on their own branch:
- **Engine** (`concierge/`): hardware check, model choice, Elaina, agents.
- **UI** (`concierge/ui/`): the chat window. Just a chat with Elaina and her agents.

## The rule between UI and engine

The UI talks only to an **Engine** and draws the **events** it returns. It
never calls Ollama, reads hardware or decides anything itself. The contract
is `concierge/events.py`; read it first. Change it only when both people
agree.

```python
engine.startup()             # once when the UI opens: SystemInfo, AgentList
engine.send(text)            # the user typed something
engine.choose(id, choice)    # the user clicked a button on a Question or AgentCard
engine.reset()               # new conversation
engine.close()               # UI closing: frees Elaina's graphics memory
```

Each call returns an iterator of events; draw them as they arrive (replies
stream).

| Event | How the UI shows it |
| --- | --- |
| `SystemInfo` | Header or "about this computer": the hardware lines, recommended model, model in use and device; `note` if set |
| `ElainaText` | Append to Elaina's current message bubble (many small pieces) |
| `ElainaDone` | Her reply is finished; re-enable the input |
| `Question` | Elaina's question; `choices` as buttons, which call `choose(id, choice)`. The user may also type an answer, which goes to `send()` |
| `AgentCard` | A card with name, kind, what it reads, can do, cannot do, runs on, and `actions` as buttons calling `choose(id, action)` |
| `Progress` | One status line ("Reading 23 files..."); each new one replaces the last, cleared by any other event |
| `Result` | An agent's answer, with its `sources` (file path and quote) shown small underneath |
| `AgentList` | The user's agents, for a sidebar or menu. Sent again whenever it changes |
| `Error` | A friendly error message; the text is already written for the user |

Build the UI against `FakeEngine` (`concierge/fake_engine.py`). It needs no
model and plays scripted flows that produce every event: type anything for a
chat reply, "make an agent" for the full agent setup, "ask ..." to run an
agent, "error" for an error. Switch to the real engine with one line:

```python
from concierge.fake_engine import FakeEngine
from concierge.engine import ElainaEngine

engine = FakeEngine()      # while building the UI
engine = ElainaEngine()    # real Elaina (chat only until agents land)
```

The UI technology is the UI developer's choice. A UI not written in Python
(web, Electron, Tauri) should run a small local server around the engine and
send `events.to_dict(event)` as JSON; every event has a `"type"` field with
its class name.

## Setup and commands

Python 3.11 and Ollama. From the repo root:

```bash
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m concierge          # terminal version: hardware, model, setup, chat
python -m concierge.ui       # chat window with the real Elaina
python -m concierge.ui --fake # chat window with FakeEngine, no model needed
pytest                       # all tests; none need Ollama
```

## Conventions

- One branch per feature, merged by pull request. `git pull` after a merge.
- New package: add it to `requirements.txt` in the same commit.
- Reliability lives in code, not prompts. Small models (1 to 4B) fill forms
  and phrase things; code decides, checks and enforces.
- Never guess hardware or memory figures. Ollama's own memory numbers are
  often wrong; measure the card (`python -m concierge measure <tag>`).
- Talk to Ollama at `127.0.0.1`, never `localhost` (IPv6 delay on Windows).
- Comments explain why, in plain sentences, like the existing code.

## Names in use

Both people work with Claude, so this list keeps us (and our Claudes) from
picking the same name twice or building something that already exists.
Before adding a module, class, function, constant, command or event that
other code can see, check this list. When you add, rename or remove one,
update the list in the same commit. Private helpers (leading `_`) and
variables inside a function do not need listing.

| File | Side | Names |
| --- | --- | --- |
| `concierge/hardware.py` | Engine | `GB`, `MIN_USABLE_VRAM_GB`, `GPU`, `HardwareReport`, `detect`, `parse_nvidia_smi`, `describe` |
| `concierge/catalog.py` | Engine | `CATALOG_PATH`, `GPU_SHARE`, `APPLE_SHARE`, `CPU_SHARE`, `CPU_MAX_GB`, `GPU_HEADROOM_GB`, `RAM_HEADROOM_GB`, `DISK_HEADROOM_GB`, `ModelEntry`, `Recommendation`, `load_catalog`, `find_model`, `memory_budget`, `recommend` |
| `concierge/elaina.py` | Engine | `ELAINA_MODEL`, `PERSONA_PATH`, `NUM_CTX`, `HISTORY_CHARS`, `UNLOAD_ON_EXIT`, `KEEP_ALIVE`, `HEARTBEAT_SECONDS`, `system_prompt`, `configure`, `needs_configure`, `ElainaChat`, `data_dir`, `load_state`, `save_state` |
| `concierge/ollama.py` | Engine | `DEFAULT_URL`, `DOWNLOAD_PAGE`, `OllamaError`, `Ollama` |
| `concierge/events.py` | Both (contract) | `SystemInfo`, `ElainaText`, `ElainaDone`, `Question`, `AgentCard`, `Progress`, `Source`, `Result`, `AgentList`, `Error`, `Event`, `to_dict`, `Engine` |
| `concierge/engine.py` | Engine | `ElainaEngine` |
| `concierge/fake_engine.py` | Engine | `FakeEngine` |
| `concierge/cli.py` | Engine | `main`, `cmd_hardware`, `cmd_recommend`, `cmd_setup`, `cmd_chat`, `cmd_measure`, `TerminalScreen`; command `python -m concierge [hardware, recommend, setup, chat, measure]` |
| `concierge/agents/blueprint.py` | Engine | `BLUEPRINT_DIR`, `Slot`, `Blueprint`, `load_blueprints`; templates in `agents/blueprints/*.yaml` (`documents_qa`) |
| `concierge/agents/builder.py` | Engine | `PLACES`, `CANCEL_WORDS`, `YES_WORDS`, `BLOCKED`, `SKIP_WHILE_SEARCHING`, `Draft`, `AgentBuilder`, `say`, `place_dirs`, `find_folders`, `is_blocked`, `describe_files` |
| `concierge/agents/files.py` | Engine | `TEXT_TYPES`, `SUPPORTED`, `MAX_FILES`, `MAX_FILE_MB`, `PASSAGE_CHARS`, `PASSAGE_OVERLAP`, `Passage`, `ScanResult`, `scan`, `read_pages`, `split`, `passages_of`, `tokens`, `SearchIndex`, `folder_signature` |
| `concierge/agents/router.py` | Engine | `WANTS_NEW`, `Route`, `route`; test cases in `agents/router_cases.yaml` |
| `concierge/agents/runner.py` | Engine | `TOP_PASSAGES`, `MAX_CONTENTS`, `STOPWORDS`, `run`, `matching_words`, `clean_answer`, `refresh_index`, `best_sentence` |
| `concierge/agents/store.py` | Engine | `Agent`, `agents_dir`, `slugify`, `list_agents`, `find_agent`, `name_taken`, `save`, `load_index`, `delete` |
| `concierge/agents/eval_router.py` | Engine | `CASES`, `main`; command `python -m concierge.agents.eval_router` |
| `concierge/ui/window.py` | UI | `WEB_DIR`, `TITLE`, `UNEXPECTED_ERROR`, `ChatBridge` (the page calls its `startup`, `send`, `choose`, `reset`), `open_window`, `main`; command `python -m concierge.ui [--fake] [--debug]` |
| `concierge/ui/web/` | UI | `index.html`, `style.css`, `app.js`; JavaScript global `app.onEvent(event)`, which `ChatBridge` calls with `events.to_dict(event)` |
