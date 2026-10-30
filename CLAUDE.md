# Local AI Concierge (Elaina)

A simple app that sets up local AI for anyone. Elaina checks the computer,
picks a model that fits it, chats with the user, and (next) creates agents for
everyday tasks. Everything runs on the user's machine through Ollama. Users
are not technical: plain words, no jargon, nothing complicated.

Two people work on this, each on their own branch:
- **Engine** (`concierge/`): hardware check, model choice, Elaina, agents.
- **UI** (`concierge/ui/`): a round "AC" bubble at the side of the screen.
  Clicking it opens a compact chat panel; right-click, Open app shows the full
  window, and minimizing that folds it back into the bubble. Just a chat with
  Elaina and her agents. The panel and the full app share one conversation
  (`ChatHub` sends every event to both).

## The rule between UI and engine

The UI talks only to an **Engine** and draws the **events** it returns. It
never calls Ollama, reads hardware or decides anything itself. The contract
is `concierge/events.py`; read it first. Change it only when both people
agree.

```python
engine.startup()             # once when the UI opens: SystemInfo, AgentList, ChatList
engine.send(text, think)     # the user typed something; think: the Think button is on
engine.choose(id, choice)    # the user clicked a button on a Question or AgentCard
engine.new_chat()            # "New chat": keeps the current one in the list, starts empty
engine.open_chat(id)         # reopen a saved conversation from the list
engine.delete_chat(id)       # delete a saved conversation (the UI confirms first)
engine.delete_agent(name)    # Elaina asks to confirm with a Question; choose() deletes
engine.toggle_agent(name)    # switch a switch-on agent (e.g. a highlight translator) on or off
engine.reset()               # new chat without drawing anything (terminal /new)
engine.close()               # UI closing: saves the chat, frees Elaina's graphics memory
```

Every conversation is saved automatically after each message (in
`%LOCALAPPDATA%\LocalAIConcierge\conversations`), including what Elaina
remembers of it, so a reopened chat carries on where it stopped.

Each call returns an iterator of events; draw them as they arrive (replies
stream).

| Event | How the UI shows it |
| --- | --- |
| `SystemInfo` | Header or "about this computer": the hardware lines, recommended model, model in use and device; `note` if set |
| `Thinking` | Elaina working it out, shown faded ("fog") above her answer. `kind` "step": one of her real decisions, a line of its own; "thought": her model's own thinking, streamed, only when Think is on. Fold it into one line ("Thought for 12s") as soon as any other event arrives; clicking reopens it |
| `ElainaText` | Append to Elaina's current message bubble (many small pieces) |
| `ElainaDone` | Her reply is finished; re-enable the input |
| `Question` | Elaina's question; `choices` as buttons, which call `choose(id, choice)`. The user may also type an answer, which goes to `send()` |
| `AgentCard` | A card with name, kind, what it reads, can do, cannot do, runs on, and `actions` as buttons calling `choose(id, action)`. When an existing agent is being changed, the first action is "Save changes" instead of "Create it" |
| `Progress` | One status line ("Reading 23 files..."); each new one replaces the last, cleared by any other event |
| `Result` | An agent's answer, with its `sources` (file path and quote) shown small underneath |
| `AgentList` | The user's agents, for a sidebar or menu, each with a delete button calling `delete_agent(name)`. Agents in `switchable` work outside the chat while switched on: show an on/off switch calling `toggle_agent(name)`; `active` lists the ones on. Sent again whenever it changes |
| `Error` | A friendly error message; the text is already written for the user |
| `ChatList` | Saved conversations, newest first, with `current` marking the open one. Clicking one calls `open_chat(id)`; each has a delete button calling `delete_chat(id)` after a confirm |
| `Transcript` | Replace the whole chat area with these items (`role`: user, elaina, result, error). Empty after New chat or deleting the open chat |
| `IdeaCard` | Elaina's verdict on a helper idea: `title`, each step with its `status` (ready, not_built, not_possible, unclear) and `note`, the `difficulty` line, the `verdict`, and `actions` as buttons calling `choose(id, action)`. `level` is the overall answer, for a colour or icon |

Build the UI against `FakeEngine` (`concierge/fake_engine.py`). It needs no
model and plays scripted flows that produce every event: type anything for a
chat reply, "make an agent" for the full agent setup, "ask ..." to run an
agent, "translate", "screenshot" or "idea" for an idea card, "error" for an
error. Its "Korean translator" agent can be switched on and off. Switch to the real engine with one line:

```python
from concierge.fake_engine import FakeEngine
from concierge.engine import ElainaEngine

engine = FakeEngine()      # while building the UI
engine = ElainaEngine()    # real Elaina: chat, creating agents, running them
```

The real engine produces the same events as the fake one. Its `Question` ids
are `folder`, `name`, `pick_folder`, `change`, `duplicate`, `language`,
`show`, `idea_change`, `delete_agent`, `pick_agent_to_delete`, `target_language` and `fix_agent`, the agent card's id is `card` and
the idea card's is `idea`; the UI should not depend on ids beyond passing
them back. To try the
real agent flow, ask Elaina to make an agent for `examples/sample_docs`
(made-up contracts, a lease and meeting notes). Agents are saved per user in
`%LOCALAPPDATA%\LocalAIConcierge\agents`.

## Agent types

Most agents have no kind of their own: they are **made from parts**. The
idea planner breaks the user's request into building blocks; when every
block exists, Elaina writes one instruction for what the agent does with
the text ("Explain this English word in simple Korean."), and the shared
template `agents/blueprints/custom.yaml` holds the rest: when it works
(while switched on, or when asked in the chat), how it shows the result
(bubble, clipboard, both) and how long the result stays. One runner does
every such agent's job (`agents/recipe.run_instruction`), so a translator, a
word explainer and a grammar fixer are the same machine with different
instructions. Elaina only fills the template; she never writes code.

- Switch-on agents (`concierge/quick/`): while on, every mouse highlight in
  any program goes through the instruction and the result is shown in a
  bubble above the text, copied, or both. Highlights are read through UI
  Automation, or by pressing Ctrl+C and restoring the clipboard, never in
  terminals. By default the bubble stays until the text is no longer
  highlighted. Windows only, and only while Elaina's window (or the terminal
  app) is open.
- Chat agents: "Grammar Fixer: me and him goes" runs the instruction on the
  rest of the message and answers in the chat.
- `documents_qa` ("Ask my documents") is the one agent with a blueprint of its
  own, because it needs a search index rather than an instruction.

Agents of the retired "Highlight translator" blueprint are turned into
agents made from parts when the app starts (`recipe.migrate`).

Agents are changed by talking: "make the translation stay until I
unhighlight it" opens the existing agent with the change applied and shows
its card with Save changes (`AgentBuilder.edit`). Settings are found in code;
a change to what it does ("make it Japanese", "shorter") is a rewritten
instruction (`recipe.rewrite_instruction`). Code recognises a change request
(`router.wants_change`) and which agent it is about, by name or by words from
its name and instruction (`router.refers_to`). Words decide settings in code
(`recipe.settings_from_words`): "highlight" means it works while switched on,
"above"/"show" a bubble, "copy"/"clipboard" the clipboard; the model may only
change a setting the message talks about, and an instruction is only ever the
job ("Translate the text into Korean."), never when or where. A translator
whose language the user did not say asks for it. A problem report ("it's not
showing anything") gets a diagnosis from the agent's settings and a fix to
click (`ElainaEngine._diagnose`), not a blind change. Asking for an agent that
repeats one the user has first asks whether to use or change it.

To let Elaina build more kinds of agents, build a block (a trigger such as
shortcut keys or new screenshots, an input, an output), mark it `ready` in
`capabilities.yaml`, add it to `blocks` in `custom.yaml`, and teach
`QuickAgents`/the engine to run it.

## Agent ideas

When the user describes a helper they would like ("translate what I highlight
when I press Ctrl+F1"), the router sends it to the idea planner
(`concierge/agents/planner.py`). Elaina's model breaks the idea into building
blocks from `concierge/agents/capabilities.yaml`, and code decides the
verdict from each block's `ai` need and `status` plus this computer's
hardware (bigger models it may need are the `helpers` in `models.yaml`). The
user can make it (all blocks ready), save it to their ideas list ("my ideas"),
change it, or drop it. Saved ideas are kept in
`%LOCALAPPDATA%\LocalAIConcierge\ideas.json` and judged again whenever they
are listed. When you build a block, set its `status` to `ready` in
`capabilities.yaml`.

## UI technology

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
python -m concierge.ui       # the bubble overlay with the real Elaina
python -m concierge.ui --fake # the bubble overlay with FakeEngine, no model needed
pytest                       # all tests; none need Ollama
python -m concierge.agents.eval_router   # router accuracy with the real model (must stay 100%)
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
| `concierge/catalog.py` | Engine | `CATALOG_PATH`, `GPU_SHARE`, `APPLE_SHARE`, `CPU_SHARE`, `CPU_MAX_GB`, `GPU_HEADROOM_GB`, `RAM_HEADROOM_GB`, `DISK_HEADROOM_GB`, `CPU_HELPER_SHARE`, `ModelEntry`, `HelperModel`, `Recommendation`, `load_catalog`, `load_helpers`, `helper_room`, `pick_helper`, `find_model`, `memory_budget`, `recommend`; models in `models.yaml` (`models`, `helpers`) |
| `concierge/elaina.py` | Engine | `ELAINA_MODEL`, `PERSONA_PATH`, `NUM_CTX`, `HISTORY_CHARS`, `UNLOAD_ON_EXIT`, `KEEP_ALIVE`, `HEARTBEAT_SECONDS`, `CLOSING_FILLER`, `without_closing_filler`, `system_prompt`, `configure`, `needs_configure`, `ElainaChat`, `data_dir`, `load_state`, `save_state` |
| `concierge/ollama.py` | Engine | `DEFAULT_URL`, `DOWNLOAD_PAGE`, `OllamaError`, `Ollama` |
| `concierge/conversations.py` | Engine | `TITLE_CHARS`, `Conversation`, `ChatBook`, `title_from` |
| `concierge/events.py` | Both (contract) | `Thinking`, `SystemInfo`, `ElainaText`, `ElainaDone`, `Question`, `AgentCard`, `Progress`, `Source`, `Result`, `AgentList`, `Error`, `IdeaStep`, `IdeaCard`, `ChatSummary`, `ChatList`, `TranscriptItem`, `Transcript`, `Event`, `to_dict`, `Engine` |
| `concierge/engine.py` | Engine | `TROUBLE`, `FIX_AGENT`, `FIX_IT`, `LEAVE_IT`, `WANTS_DELETE`, `WANTS_IDEAS`, `WANTS_ON`, `WANTS_OFF`, `DELETE_AGENT`, `PICK_AGENT_TO_DELETE`, `DELETE_IT`, `KEEP_IT`, `ElainaEngine` |
| `concierge/fake_engine.py` | Engine | `FakeEngine` |
| `concierge/cli.py` | Engine | `DIM`, `PLAIN`, `main`, `cmd_hardware`, `cmd_recommend`, `cmd_setup`, `cmd_chat`, `cmd_measure`, `TerminalScreen`; command `python -m concierge [hardware, recommend, setup, chat, measure]`; in the chat `/think` turns thinking on or off |
| `concierge/agents/blueprint.py` | Engine | `BLUEPRINT_DIR`, `Slot`, `Blueprint`, `load_blueprints`; templates in `agents/blueprints/*.yaml` (`documents_qa`, and `custom`: the shared template for agents made from parts) |
| `concierge/quick/agents.py` | Engine | `BUBBLE`, `CLIPBOARD`, `BOTH`, `UNTIL_UNHIGHLIGHT`, `FEW_SECONDS`, `CHECK_SECONDS`, `CHECK_FOR_SECONDS`, `QuickAgents` |
| `concierge/quick/bubble.py` | Engine | `GAP`, `MAX_WIDTH`, `COLORS`, `GWL_EXSTYLE`, `WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `WS_EX_TOPMOST`, `show_seconds`, `Bubble` |
| `concierge/quick/selection.py` | Engine | `DRAG_PIXELS`, `DOUBLE_CLICK_SECONDS`, `MIN_CHARS`, `MAX_CHARS`, `NO_COPY_APPS`, `Rect`, `CF_UNICODETEXT`, `foreground_app`, `SelectionWatcher`, `read_selection`, `highlighted_text`, `save_clipboard`, `restore_clipboard`, `set_clipboard_text` |
| `concierge/quick/translate.py` | Engine | `LANGUAGES`, `language_in`, `looks_like` |
| `concierge/agents/builder.py` | Engine | `PLACES`, `CANCEL_WORDS`, `YES_WORDS`, `BLOCKED`, `SKIP_WHILE_SEARCHING`, `CARD`, `CHANGE`, `PICK_FOLDER`, `DUPLICATE`, `REPLACE`, `MAKE_ANOTHER`, `CREATE_IT`, `SAVE_CHANGES`, `RENAME`, `TARGET_LANGUAGE`, `LANGUAGE_CHOICES`, `custom_card`, `Draft`, `AgentBuilder`, `say`, `place_dirs`, `find_folders`, `agent_for_folder`, `is_blocked`, `describe_files` |
| `concierge/agents/planner.py` | Engine | `BLOCKS_PATH`, `OTHER`, `MAX_STEPS`, `IDEA`, `IDEA_CHANGE`, `KEY_COMBO`, `ASKED_FOR_KEY`, `settle_triggers`, `MAKE_IT`, `SAVE_IDEA`, `CHANGE_IDEA`, `DROP_IDEA`, `HELPER_ROLES`, `ROLE_WORDS`, `Block`, `PlanStep`, `Assessment`, `IdeaDraft`, `IdeaPlanner`, `load_blocks`, `assess`, `clean_detail`, `ideas_path`, `list_ideas`, `save_idea`, `describe_ideas`; building blocks in `agents/capabilities.yaml` |
| `concierge/agents/recipe.py` | Engine | `CUSTOM`, `WHILE_ON`, `IN_CHAT`, `MAX_INSTRUCTION`, `HIGHLIGHT_WORDS`, `CHAT_WORDS`, `SHOW_WORDS`, `COPY_WORDS`, `STAY_WORDS`, `SHORT_WORDS`, `MECHANICS`, `run_instruction`, `target_language`, `settings_from_words`, `needs_language`, `with_language`, `write_recipe`, `rewrite_instruction`, `is_switchable`, `migrate` |
| `concierge/agents/files.py` | Engine | `TEXT_TYPES`, `SUPPORTED`, `MAX_FILES`, `MAX_FILE_MB`, `PASSAGE_CHARS`, `PASSAGE_OVERLAP`, `Passage`, `ScanResult`, `scan`, `read_pages`, `split`, `passages_of`, `tokens`, `SearchIndex`, `folder_signature` |
| `concierge/agents/router.py` | Engine | `IDEA_OPTION`, `WANTS_CHANGE`, `WANTS_NEW`, `Route`, `route`, `wants_change`, `refers_to`, `names_an_agent`; test cases in `agents/router_cases.yaml` |
| `concierge/agents/runner.py` | Engine | `TOP_PASSAGES`, `MAX_CONTENTS`, `STOPWORDS`, `run`, `matching_words`, `clean_answer`, `refresh_index`, `best_sentence` |
| `concierge/agents/store.py` | Engine | `Agent`, `agents_dir`, `slugify`, `list_agents`, `find_agent`, `name_taken`, `save`, `load_index`, `delete` |
| `concierge/agents/eval_router.py` | Engine | `CASES`, `main`; command `python -m concierge.agents.eval_router` |
| `concierge/ui/window.py` | UI | `WEB_DIR`, `TITLE`, `UNEXPECTED_ERROR`, `BUBBLE_SIZE`, `MENU_SIZE`, `EDGE_GAP`, `PANEL_WIDTH_SHARE`, `PANEL_MIN_WIDTH`, `PANEL_MAX_WIDTH`, `PANEL_RATIO`, `PANEL_MAX_HEIGHT_SHARE`, `FULL_SIZE`, `REMEMBERED`, `Area`, `ChatHub`, `ChatBridge` (a chat page calls its `startup`, `send`, `choose`, `new_chat`, `open_chat`, `delete_chat`, `delete_agent`, `toggle_agent`, `reset`), `PanelBridge` (adds `open_app`, `hide_panel`), `BubbleBridge` (`toggle_panel`, `menu`, `moved`, `open_app`, `quit`), `Overlay`, `bubble_home`, `panel_size`, `place_panel`, `place_menu`, `work_area`, `main`; command `python -m concierge.ui [--fake] [--debug]` |
| `concierge/ui/web/` | UI | `index.html` (full app), `panel.html` (compact chat), `bubble.html` (the round bubble and its menu), `style.css`, `app.js`; JavaScript globals `app.onEvent(event)`, `app.mirror(state)`, `app.shown()` (called by `ChatHub` and `Overlay`) and `bubble.setMenu(grow)` |
