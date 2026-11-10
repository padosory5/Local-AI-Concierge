# Noir Agents

A simple app that sets up local AI for anyone. Noir checks the computer,
picks a model that fits it, chats with the user, and (next) creates agents for
everyday tasks. Everything runs on the user's machine through Ollama, unless the
user picks a cloud model they pay for. Users are not technical: plain words, no
jargon, nothing complicated.

The product is Noir Agents, Noir for short, and the voice in it is Noir too. Until
7 November 2026 it was Elaina and the app was Local AI Concierge, which is still
the repository folder's name. `data_dir` takes over the old `LocalAIConcierge`
folder once, with everything in it; saved chats whose items say `elaina` still
open; the password store keeps its old name so saved keys stay; and its Ollama
model is `noir` now, built by the setup page on the first start (the old `elaina`
model can go with `ollama rm elaina`).

Noir is a name, not a person. The pages and messages say it and its, never she or
her, and nothing is "Noir's" the way a person owns things: the side list says
Settings, not Noir's room, and the model is the built-in model. In the chat the app
speaks as I, like any assistant, and the persona says so.

Two people work on this, each on their own branch:
- **Engine** (`concierge/`): hardware check, model choice, Noir, agents.
- **UI** (`concierge/ui/`): the app opens as a full window. Minimizing it keeps it
  on the taskbar and folds Noir into a small circle in the corner; clicking the
  circle opens a small window with its agents' work and messages. Both windows
  share one conversation (`ChatHub` sends every event to both).

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
engine.delete_agent(name)    # Noir asks to confirm with a Question; choose() deletes
engine.toggle_agent(name)    # switch a switch-on agent (e.g. a highlight translator) on or off
engine.reset()               # new chat without drawing anything (terminal /new)
engine.close()               # UI closing: saves the chat, frees Noir's graphics memory
```

Every conversation is saved automatically after each message (in
`%LOCALAPPDATA%\NoirAgents\conversations`), including what Noir
remembers of it, so a reopened chat carries on where it stopped.

Each call returns an iterator of events; draw them as they arrive (replies
stream).

| Event | How the UI shows it |
| --- | --- |
| `SystemInfo` | Header or "about this computer": the hardware lines, recommended model, model in use and device; `note` if set |
| `Thinking` | Noir working it out, shown faded ("fog") above its answer. `kind` "step": one of its real decisions, a line of its own; "thought": its model's own thinking, streamed, only when Think is on. Fold it into one line ("Thought for 12s") as soon as any other event arrives; clicking reopens it |
| `NoirText` | Append to Noir's current message bubble (many small pieces) |
| `NoirDone` | Its reply is finished; re-enable the input. With Auto, `by` names the model that wrote it (show it under the reply), and `instead` is the plan model to offer as "Ask … instead", calling `ask_again()`; both empty otherwise. Every chat answer also has `where` ("here" or "cloud": a blue dot, or yellow turning red with `plan_used`, the plan's fullest window after it) and `saved` (tokens Auto kept off the plan, shown as "Saved about 29k tokens"); empty for set phrases. An answer looked up on the web (research.py) names its `sources` (path: address, quote: title), shown as small links under it, and may bring `images` (`Picture`: url, thumbnail, title, source) shown under its words |
| `Question` | Noir's question; `choices` as buttons, which call `choose(id, choice)`. The user may also type an answer, which goes to `send()` |
| `AgentCard` | A card with name, kind, what it reads, can do, cannot do, runs on, and `actions` as buttons calling `choose(id, action)`. When an existing agent is being changed, the first action is "Save changes" instead of "Create it" |
| `Progress` | One status line ("Reading 23 files..."); each new one replaces the last, cleared by any other event |
| `Result` | An agent's answer, with its `sources` (file path and quote) shown small underneath |
| `AgentList` | The user's agents, for a sidebar or menu, each with a delete button calling `delete_agent(name)`. Agents in `switchable` work outside the chat while switched on: show an on/off switch calling `toggle_agent(name)`; `active` lists the ones on. Sent again whenever it changes |
| `Error` | A friendly error message; the text is already written for the user |
| `ChatList` | Saved conversations, newest first, with `current` marking the open one. Clicking one calls `open_chat(id)`; each has a delete button calling `delete_chat(id)` after a confirm |
| `Transcript` | Replace the whole chat area with these items (`role`: user, noir, result, error). Empty after New chat or deleting the open chat. A noir item keeps its answer's `by`, `where`, `saved` and `plan_used`, so a reopened chat shows the same dot, its `sources` and `images`, and every item has `when` (ISO), so a reopened chat shows the time, and the day, under each message |
| `IdeaCard` | Noir's verdict on a helper idea: `title`, each step with its `status` (ready, not_built, not_possible, unclear) and `note`, the `difficulty` line, the `verdict`, and `actions` as buttons calling `choose(id, action)`. `level` is the overall answer, for a colour or icon |

Build the UI against `FakeEngine` (`concierge/fake_engine.py`). It needs no
model and plays scripted flows that produce every event: type anything for a
chat reply, "make an agent" for the full agent setup, "ask ..." to run an
agent, "translate", "screenshot" or "idea" for an idea card, "error" for an
error. Its "Korean translator" agent can be switched on and off. Switch to the real engine with one line:

```python
from concierge.fake_engine import FakeEngine
from concierge.engine import NoirEngine

engine = FakeEngine()      # while building the UI
engine = NoirEngine()    # real Noir: chat, creating agents, running them
```

The real engine produces the same events as the fake one. Its `Question` ids
are `folder`, `name`, `pick_folder`, `change`, `duplicate`, `language`,
`show`, `idea_change`, `delete_agent`, `pick_agent_to_delete`, `target_language`, `fix_agent` and `conduct` (a question in a setup that is talked through, about no setting in particular), the agent card's id is `card` and
the idea card's is `idea`; the UI should not depend on ids beyond passing
them back. To try the
real agent flow, ask Noir to make an agent for `examples/sample_docs`
(made-up contracts, a lease and meeting notes). Agents are saved per user in
`%LOCALAPPDATA%\NoirAgents\agents`.

## Agent types

Most agents have no kind of their own: they are **made from parts**. The
idea planner breaks the user's request into building blocks; when every
block exists, Noir writes one instruction for what the agent does with
the text ("Explain this English word in simple Korean."), and the shared
template `agents/blueprints/custom.yaml` holds the rest: when it works
(while switched on, or when asked in the chat), how it shows the result
(bubble, clipboard, both) and how long the result stays. One runner does
every such agent's job (`agents/recipe.run_instruction`), so a translator, a
word explainer and a grammar fixer are the same machine with different
instructions. Noir only fills the template; it never writes code.

- Switch-on agents (`concierge/quick/`): while on, every mouse highlight in
  any program goes through the instruction and the result is shown in a
  bubble above the text, copied, or both. Highlights are read through UI
  Automation, or by pressing Ctrl+C and restoring the clipboard, never in
  terminals. By default the bubble stays until the text is no longer
  highlighted. Windows only, and only while Noir (or the terminal app) is
  running.
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
click (`NoirEngine._diagnose`), not a blind change. Asking for an agent that
repeats one the user has first asks whether to use or change it.

To let Noir build more kinds of agents, build a block (a trigger such as
shortcut keys or new screenshots, an input, an output), mark it `ready` in
`capabilities.yaml`, add it to `blocks` in `custom.yaml`, and teach
`QuickAgents`/the engine to run it.

## Agent ideas

When the user describes a helper they would like ("translate what I highlight
when I press Ctrl+F1"), the router sends it to the idea planner
(`concierge/agents/planner.py`). Noir's model breaks the idea into building
blocks from `concierge/agents/capabilities.yaml`, and code decides the
verdict from each block's `ai` need and `status` plus this computer's
hardware (bigger models it may need are the `helpers` in `models.yaml`). The
user can make it (all blocks ready), save it to their ideas list ("my ideas"),
change it, or drop it. Saved ideas are kept in
`%LOCALAPPDATA%\NoirAgents\ideas.json` and judged again whenever they
are listed. When you build a block, set its `status` to `ready` in
`capabilities.yaml`.

## Minimized Noir

Noir helps inside the user's work: no split screen and no chat at the side.
Minimized, it is a small circle (`concierge/ui/mini.py`) that shows its state
without words: print dots drifting while it waits, a line going round while a
job runs, rings opening out of it while it has a question. It steps out of
the way during games, videos and slideshows, and hides while the full window is
open. Its pictures are drawn once with soft edges and shown one after another.

## The drawer

Beside the user's work there is a drawer (`glass.html`, `glass.js`, `glass.css`):
hold Ctrl, press the mouse at the very right edge of the screen and pull left, and
it comes out of the edge following the hand (`quick/drawer.py`, `EdgePull`, through
the same mouse and keyboard hooks as the Spot; `EDGE_PIXELS` is how close to the edge
the press must be, `OPEN_PIXELS` how far it must be pulled to stay out, else it
slides back). Clicking the circle brings it out too. Pushing it back is Ctrl and a
press on it dragged right, Esc, or its close button. It is as tall as the screen's
work area less `DRAWER_GAP`, `DRAWER_WIDTH` wide, flush with the edge
(`drawer_bounds`, `drawer_x` in `window.py`, in the screen's real pixels, since the
mouse speaks in them; `Overlay.pull_drawer` only notes where the hand is and a
thread of its own moves the window, because the hooks must return at once). It is
see-through with the desktop blurred behind it: the window is made transparent and
Windows' frosted glass is asked for (`_prepare_drawer`, `DRAWER_FOG`), so the page's
dark is only a tint; without the frost the page would be black, which is why the
window is made off the screen's edge and hidden once its page is in.

It has two faces. Quiet, it is the chores list, the way the Notes app lists things:
any question waiting for an answer, then "Handling" (every chore, on or off, with
what it does and the last thing it did), then each day's jobs, newest day first,
with Undo (`WatchBridge.chores`, from `chores.py`: `listing` puts together what
`TidyWatch`, the last `AgentList` (`ChatHub.latest`) and the bookings already know;
a chore is anything that runs without being asked in the chat). Below is one line,
"Tell Noir a chore, or ask". Typing folds the list away (`body.talking`) and the
conversation takes the drawer, the same one as the full window, oldest at the top
and newest by the box, with its questions' buttons working there too (the watch's and an organizer's, through
the same `noticed`) and an agent card drawn whole (reads, can do, can't do, runs on: it
once showed only the name); "‹ Chores"
goes back. Messages are added, never redrawn, so nothing flickers.

The main window has the same list as a page, Chores in the side list
(`chores.js`, `choresPage`): the switches and Remove the drawer leaves out, Undo on
each job, a line that sends a chore to the chat as if typed, and a sentence on how
to pull the drawer out.

`concierge/quick/tidy.py` is what it notices itself. `TidyWatch` looks at two
things: 30 or more loose files in Downloads, and a lecture in the window in
front (`quick/watching.py`, from the window's title only, two looks in a row).
It notices nothing until the user says yes once (Today asks, and Settings › What
I see has the switch; `TidyWatch.noticing`, kept in `tidy_settings.json`).

It asks at a break between tasks (`BreakSpotter`: a window switch in the last
`BREAK_SECONDS` and no typing), never just because typing stopped, since a pause
is usually someone thinking. That was the research's clearest warning. Questions
are hours apart (`QUESTION_GAP_SECONDS`), take turns, and wait while the full
window is open or a job runs. One short question with Yes and No appears in
`quick/note.py`, next to the circle. "No" keeps it quiet about it for a week,
and the same question waits in both windows until it's answered. Every yes, no
and ignored question is counted on the computer (`questions.json`, shown on What
I see), so questions people keep refusing can be found and dropped.

The lecture question is only asked in the practice run (`LECTURE_NOTES_BUILT`):
a Yes that does nothing spends an interruption on nothing.

When a job the user said yes to starts, a soft lilac light runs once around the
screen they are working on (`quick/glow.py`, Engine side like the highlight
bubble, so `events.py` did not change), and a thin line stays at the right edge
while it runs. When it is done, the same light runs in green. A job that fails
shows no green. Clicks and typing pass through the light, and during games,
videos and slideshows there is none.

Sorting is plain code with no model: it moves files into folders by kind, never
deletes or overwrites, and never touches files kept only in the cloud
(`CLOUD_ONLY`). The question comes with where everything would go
(`sort_plan`), the finished job says where it all went (`moved_to`), and every
sort can be undone on its own for a week (`sorts.json`, `UNDO_DAYS`). Summarizing a video is **not
built**: Yes only says so, plainly, with no light. `python -m concierge.ui
--fake` is a practice run where both questions come soon after minimizing, the
jobs only wait, and no files are looked at or moved.

## How an agent is made, and how Noir talks about it

An agent is a blueprint (`agents/blueprints/*.yaml`: which building blocks from
`capabilities.yaml` it is made of, and which slots it needs) filled in through a
conversation, then run by the code those blocks map to. Code drives the conversation:
it reads what the first message already says (`AgentBuilder._prefill`, `watched_from`,
`destination_from`, `courses_in`), asks only for what is still empty, shows one card and
creates the agent on Create it; the model fills forms forced by a schema (which folder,
what the agent does) and never decides. Two kinds watch a folder (`organizer.WATCHED_KINDS`,
run by `Organizer` on one thread, summaries before moves): the file organizer
(`organizer.yaml`) and the summary writer (`summarizer.yaml`: a few lines about each new
document into a notes file, `notes_path`, `NOTES_DEFAULT`, `SUMMARY_NOTE`; `save_file` is a
ready block now, and `recipe.describe` knows both). A request for either is routed in code
before the model (`router.WATCHES` with `SUMS_UP` or `SORTS`: "when a pdf lands in my
downloads, write me a short summary in a notes file" once went to chat and a web search),
and a request for new work is never taken for a question about a chore or for a web
lookup (`engine.ASKS_FOR_WORK`).

A helper for files whose kind the words don't say is asked about, never guessed
(`router.KIND_WORDS`, `FILES`, `WANTS_HELPER`, `kinds_named`; route `ask_kind`,
`NoirEngine._ask_kind`, `WHICH_KIND`, `KIND_SHORT`, `SOMETHING_ELSE_KIND`): "can you create
an agent that can handle my files" once became Ask my documents, and now Noir asks what it
should do with the files, with the kinds as buttons, an existing helper of those kinds to
use instead, and Something else (the idea planner); a short answer typed instead of a click
is joined to the request and routed again. One kind named by its words is that kind, in
code, and a kind the model picked that the words contradict is overruled. During a setup
an answer typed for a question not asked yet ("just keep them inside that folder" while
the folder is still being chosen, "decide as you go" to the folder question) is filled in
where it fits (`AgentBuilder._answer_any_slot`, `BY_CONTENT_WORDS`, `BY_NAME_WORDS`) and
the open question is asked again, instead of the setup being dropped and the chat model
answering about passwords; a click on a card not yet shown re-asks the open question. A
short question with a pronoun soon after an organizer did something ("where did they go?")
is about the files (`FOLLOWS_A_CHORE`, `CHORE_FRESH_SECONDS`, `chore_spoken_at`), never a
web lookup. Other local-first apps (Open WebUI, AnythingLLM, Jan, LM Studio) set helpers up
in forms and switch them on; their models only ever answer, never decide, which is why
their conversations feel smooth. Here code decides and asks, and the model is only ever
offered a choice it can refuse with "ask instead".

Noir says what code decided in its own words (`agents/talk.py`, `phrase`): code writes the
plain line (the offer, a slot's question, "it's on", "okay", a kind or course question) and
the model rewords it at `TEMPERATURE`; the rewording must keep every fact word for word
(names, paths, numbers, codes, file names, listed by the caller or found in the line by
`facts_in`), keep `KEPT_SHARE` of the line's own words (`words_of`), stay short and plain
(`JARGON`) and still ask what the line asked (`ASKING_WORDS`), or the plain line is used; a
line longer than `MAX_PLAIN` is a record and is never reworded, because a 4B model turned
"left alone, as you said" into "since it's not a .png". Without a model (the tests, the
practice run) the plain line is used, so tests see fixed text. No question in a blueprint
carries an example that could look like the user's own life: the user saw "Physics 122,
Calculus, History" in one and took it for his data.

## Setups talked through: the conductor

In the plain setup above nobody is in the conversation: code asks the blueprint's questions
in order and the 4B model rewords one line at a time without seeing the chat. In the user's
own setup on 9 Nov "Inside that folder is simplest" came back as "inside the Sorted Folders
folder", a folder that doesn't exist, and passed every check. So a blueprint that says how
it works (`facts` in its yaml: the organizer and the summary writer; each line must stay
true to the code) is talked through instead, when there is a model fit to do it
(`agents/conductor.py`). Each turn that model, the conductor, reads how to talk and how to
conduct (`VOICE`, `HOW_TO_CONDUCT`), the blueprint's facts, each setting with its question
and how to fill it, the draft as code has checked it (`AgentBuilder._known`: places by
name, never a whole path), what code can see (`_facts`: the places, how many files of
which endings are in the folder and never their names, the agents already made) and the
setup's own conversation (`Draft.turns`), and fills one form forced by a schema
(`schema_for`): a value for every setting, where things stand (`STILL_ASKING`,
`NOTHING_MISSING`, `CALLED_OFF`, `MOVED_ON`), which setting its question is about, and
last its words. A folder is a place from a list plus a name (`field_for`, `PLACE_NAMES`,
`INSIDE`), so a model can't misspell a place or make up a path. Nothing in that note is an
example of a folder's name: given "like College", one model offered it to the user as if
it were theirs and a smaller one filled it in as the answer.

The model talks and proposes; code decides (`AgentBuilder._conduct`, `_take_form`). Every
value is checked: the folder to watch must exist (`_form_folder`, looked for everywhere
when the place the model gave is wrong), a new folder needs a place (`_form_place`), a name
is only taken if the user gave the agent one (`NAMES_IT`: "can you call the folder School"
once named the agent School), an empty value never erases a known one. What code
refuses (`Refused`) goes back to the model once with the reason and what to do about it
(for a folder that isn't there: say so and ask, and use the name nowhere else; hinted
instead that it might be where the sorted folders go, the model made a mistyped "my Scool
folder" into a new destination nobody had asked for); refused twice, code says its own
plain line, what was known stays as it was, and that value is passed over from then on unless
the user names it again (`Draft.ignored`: without that, a 9B model answered three
different messages with "I can't find a folder called College"). "Nothing missing" with
something missing is asked again, and the card is shown by code as soon as nothing needed
is missing (`needed`: a setting with a question and no usual value), whatever the model
says of where things stand: let hold the card back to ask once more, it asked about a
setting that has a usual value. Only a turn in which code refused something waits with
the card: asked for a folder that isn't there, the model said so, asked which folder to
watch, and guessed Downloads for the draft, and a card for Downloads showed under its
question. Nothing the model says makes an agent: only the card's
button, or a whole message that is a plain yes while the card is up (`CARD_YES`; "ok but
put them in Documents" is a change), and not even that when Noir has just asked something,
since the yes then answers the question. In the first probe (10 Nov: the model given the conversation
but no guard) three of four local models switched the agent on with no yes or said they
would move a bank statement, which is why. A click on a question's button sets that
setting in code and is said to the model like anything typed; Change something on the card
asks in words. An opening offer that says nothing ("I can certainly help you with that.")
is taken off in code (`OPENING_OFFER`: told not to, the model still wrote it), and so is a
closing offer or "Shall we begin?" (`tidy_say`, with `noir.CLOSING_FILLER` and
`CLOSING_NUDGE`); once the card is up the model is
told so (`CARD_IS_UP`), or every answer ends by pointing at its button. A conductor that fails (`ConductorError`: Ollama stopped, the plan signed out,
a form that can't be read) leaves the plain questions, from wherever the draft is. The
lines code writes after a talked-through setup ("File organizer is ready.", "It's on ...")
are said as written, not reworded (`AgentBuilder.conducted`).

Who conducts is the engine's choice at each start (`NoirEngine._conductor`): a plan or key
model the user picked, or the one Auto sends hard questions to (`talker_form`: the note,
the conversation and the schema as one message, since the plans' apps drop system
messages, and the JSON read out of the reply by `read_form`); else the first model on the
`conductors` list in `models.yaml` that is installed and fits beside Noir's own on the
graphics card (`_local_conductor`, `local_form`; loaded for the setup, freed when it ends,
`Conductor.done`); else nobody, and the plain questions are asked. A local model picked
in the menu doesn't conduct unless it is on that list. Only a model that passes `python -m
concierge.conductor_eval <tag>` goes on it: seven scripted setups through the real engine
on a made-up home (the user's own with its typos, an answer out of order, a worry about
old files and a question about bank statements; one message that says everything, then
two changes at the card; never mind; a question about something else; a folder that isn't
there; the summary writer; one in Korean), checking what code ended up with and what was
never done, and printing every word to be read, since no check can judge the words (several
of the fixes above came from reading a run that had passed every check). On 10 Nov 2026
Gemma 4 12B passed 50 of 50 in each of its last three runs, about 45 seconds a run; Qwen
3.5 9B failed three to seven checks in each of four runs and the 4B three to five (they put the
destination in the folder to watch, dropped a change said at the card, and answered
Korean in English), so size alone puts nobody on the list. The plan path
(`talker_form`) is covered by tests with a pretend model only: no real setup has been run
through a plan yet, where each turn costs what any answer does (about 29k tokens through
Claude Code). `organizer_eval` switches the conductor off (`NoirEngine.conducts`), since it
is about what the organizer does and must run the same on every computer.

## Chores Noir builds: the file organizer

A chore is anything that runs without being asked in the chat; the first one Noir
builds for people is the file organizer (`agents/blueprints/organizer.yaml`,
`concierge/organizer.py`). "Organize my school files by what's inside them" reaches
it through the router (a kind of agent of its own, `switchable`, `watches: true`) or
through the idea planner (its blocks `new_file`, `folder_files`, `classify` and
`move_files` are all ready now). The setup is the discussion: which folder to watch
(Downloads is where most things land), how to tell files apart (`by`: what's inside
each file, which means the built-in model reads the first pages on this computer, or
the file's name, quicker but only as good as the names), and which folders
(`groups`: the user's list, or Decide as you go, where it names folders by what it
finds and reuses them). What the first message already says isn't asked again
(`AgentBuilder._prefill` reads "inside" and "by name", and `watched_from` reads "from
Downloads" as the folder to watch, in code: asked as a free question, the model once took
"a folder on my desktop called College", the destination, for it; a folder that is the
destination is refused with a question), the card comes from the
slots (`organizer_card`), and Create it saves the agent and hands it to the engine
(`AgentBuilder.take_created`, `NoirEngine._building`), which switches it on and asks
whether to go through the documents already there (`ORGANIZE_NOW`, `GO_THROUGH`,
`ONLY_NEW`; `_organize_now` runs `Organizer.run_once` with Progress and a Result).

Only what lands after it is switched on counts: everything in the folder at that
moment is written down as old (`Organizer._seen`), so "only new files from now on" means
it. What it has seen, and why each file it left stayed, is kept in `organizer_state.json`
(`seen`, `SEEN_KEPT`, `skipped`), so a restart changes nothing: a file that landed a
moment before one is still new, and "why didn't you move it" still has its answer; the
first version wrote the folder down as old again at every start, and output.pdf, landed
just before a restart, became old with no record, so "nothing new" was all the user heard.
A file whose job broke is recorded with that reason (`look`), never lost in silence. The first live run had no such line and filed
60 old downloads, CVs and immigration forms among them, into two folders. The line is
drawn again whenever the watched folder changes (`switch`, `refresh`): an agent changed
from watching College to Downloads once kept College's empty baseline and filed 28 old
downloads ten seconds after "Only new files from now on". While on,
`Organizer` looks at each watched folder every `LOOK_SECONDS` on a thread of its own:
any file at all (every kind is a candidate, since a practice5.py for CSE 163 once sat
unread while only documents counted; `files.read_pages` reads documents, code and any text
by looking at its bytes (`text_of`), spreadsheets, slides and OpenDocument files from the
XML in their zip (`OFFICE_PARTS`, `office_text`, no spreadsheet library), zips and tars
by the names inside (`archive_listing`), markup without its tags (`without_tags`), a
notebook by its cells, and the organizer reads a picture through the installed vision
model (`Organizer.seer`: the catalog's vision helper, else any model Ollama says has
vision; `SEE_NOTE`) and a scanned PDF through its first page's picture, the picture shrunk
to `SEE_PIXELS` on its longer side and the model given `SEE_CONTEXT` of room (`shrink`: a
scanned page of 3300 by 2550 was 8,000 tokens against a room of 4,096, the call failed
without a word and output.pdf, six photographed pages of a MATH 207 midterm, counted as
unreadable); a program or a video gives nothing and is judged by its name alone) that has
sat still for `SETTLE_SECONDS` (a download
still arriving is left alone, `.crdownload` and the like too) is read (`READ_CHARS`
of its text, `files.read_pages`). With folders the user named, the built-in model
fills one form forced by a schema: what kind of document it is ("course material" or
"something else"; a tuition statement, a CV and an I-20 form once went into PHYS122
because they named the course, so only the first kind ever moves) and which of those
folders, "another course" or "not sure", the folders listed by name only: a few file
names already in each, tried as a hint, made the 4B model call hw2_pandas.py "something
else", and bare names got five of five right. A course code in the file decides before
the model (`course_codes`, `folder_codes`, `COURSE_CODE`: letters in CAPS and a number, so
"Kane 130" is not one): a code that names one of the folders is that folder; a code none
of them is becomes a question ("phys121_ch3_notes.pdf looks like a new course, PHYS 121.
Make a folder for it, called PHYS121?", `_ask_subject`), since the model saw "physics" in
PHYS 121 notes and filed them under the only physics folder; material with no code that
the model calls "another course" is named by the subject form (`_topic`) and asked about
the same way. A yes makes the folder (the name the user typed, else the one offered), adds
it to the organizer's folders (`_add_folder`, saved with the agent) and files what was
held; a no leaves that course alone (`SUBJECT_WAITING`, `SUBJECT_REFUSED`); both are kept
in `subjects` and the question waits across restarts. In the chat a short name typed while
such a question waits is the folder's name (`_names_a_folder`, `_question_for_name`: the
question whose course the name echoes, else the newest). Deciding as
it goes, the model only says what the document is about, as a subject or course name
("Physics 122", never "Physics 122 Lab 3"), and whether it is sure; code matches those
words to the folders made so far (`closest`, by shared telling words, `STOPWORDS`
left out) or makes a new one (`folder_name`). The model is never asked to choose
between a folder it made and "a new folder": a 4B model took the existing folder every
time, and a club guide became the home of every lab handout. Code does everything
else: the file moves under a free name into the watched folder or the place the user
named (the `into` slot: "inside my desktop calling it College" is read by
`destination_from`, course codes like "phys122 and cse163" by `courses_in`, both
filled in from the first message), the move is written to the same log as Downloads
sorting (`tidy.record_moves`, so `undo_sort` and `can_undo` work unchanged, for
`UNDO_DAYS`), and the job joins the organizer's own done list (`organizer_done.json`),
which the chores list merges with the watch's. The user sees the organizer at work on the circle
and beside it. While a file is read and judged (`Organizer.working`, `ChatHub.on_working`,
`Overlay._working`) the circle blinks once (`Mini.blink`, `BLINK_SECONDS`, `BLINK_DIM`: it
dims for a moment and comes back) and runs its line, then goes back to what it showed.
Each job keeps its steps as it goes (`_note`, `_steps`: "Noticed output.pdf in Downloads",
"A scanned page: read it through qwen3-vl:8b", "It's about Math 207, a new folder", "Put it
in 바탕 화면\Math 207"), and a file moved while watching is told to the window with them
(`Organizer.moved`, `ChatHub.on_move`, `Overlay._moved`): the small log by the circle, the
same window as its questions (`quick/note.py`, `tell`, `LOG_SECONDS`), shows what happened
on its first line and what was read and decided in small lines under it, with Undo and OK
for `MOVE_NOTE_SECONDS`; a file read and left is told the same way with why it stayed
(`Organizer.stayed`, `ChatHub.on_stayed`, `Overlay._stayed`, `STAY_NOTE_SECONDS`), one note
at a time, never during a game, a video or a slideshow, Windows for now. The decision step
also goes into the job's line in the chores list. A pass asked for in the chat tells the
chat instead. A summary writer's notes file is never a file to sort (`files`
skips it: it once got filed under PHYS122 for the lab it summarised), and its note says
where the summary went. A file the model isn't sure about stays
and isn't asked about again; nothing leaves the computer, which is why the judging is
always the built-in model's job (the card says so; pictures go through the vision helper
when one is installed, else by name). Documents and code (`KINDS_AUTO`) move as soon as
they read as material. Any other kind (a spreadsheet, slides, a picture, a zip...) is held
back the first time one reads as material and the user is asked once, for the kind
(`Organizer.asking`, `_ask_kind`, `questions`, `answer`; `kinds` keeps each yes or no per
organizer in `organizer_state.json`, and a question waits across restarts): "hw3_data.xlsx
looks like CSE163 material. Sort .xlsx files like it from now on?" A yes moves the files
held back and every such file from then on; a no leaves that kind alone (`KIND_WAITING`
and `KIND_REFUSED` are the reasons they keep). The question reaches the user everywhere
the watch's do: `WatchBridge.today` puts it in `noticed` for the drawer and Today when the
watch has none, `WatchBridge.answer` routes a `kind:` id to `NoirEngine.organizer_answer`,
a note by the circle asks it (`ChatHub.on_ask`, `Overlay._asked`, `ASK_NOTE_SECONDS`), the
circle shows rings while it waits (`Overlay.refresh_mini`), and a plain yes or no in the
chat answers it (`_plain_answer`, `NO_WORDS`). The facts note tells the chat model the
question and whether a vision model is installed. What was on comes back when the app starts (`organizer_state.json`,
`Organizer.refresh`); it runs on the Mac too.

With an organizer, questions about it are answered in code, never by the chat model,
which once said it "couldn't see or move files" right after a move. "Where did you put
it", "where's the folder" and "which folder is the physics lab in now?" (`WANTS_WHERE`,
or `WHERE_WORDS` with a file it moved or left named by a word of its name, `_mentions`):
`_say_where`, from `Organizer.last_moves` (read from the move log, so a pass's files
count) and the agent's settings, always as the whole path, which the user asked for
after a folder went to a Desktop they never see; a file that stayed is said to have
stayed, and why. "Why didn't you move the receipt?" (`WANTS_WHY`, `_say_why`): every
file it read and left keeps its reason (`Organizer.skipped`, `verdict`, `last_skipped`),
as a short label such as "not material for any of the folders". "What did you do"
(`WANTS_STATUS`, `_say_status`): the moves and what stayed, grouped by reason.
"Organize it", "I just downloaded a file", "move the files" (`WANTS_ORGANIZE`,
`_organize_now` over what landed since it was switched on; "go through everything",
`WANTS_EVERYTHING`, and the first pass the user is asked about go over all of it; a file
the message names is looked at again whatever was decided before, `run_once(only=...)`),
and the result says why what stayed did. When nothing is new, the answer says what was
looked at already and why it stayed, and asks the questions still waiting right there in
the chat with buttons (`_nothing_new`, `_pending_questions`, answered through
`_handle_choice` by their `kind:` or `subject:` id), instead of "wait 20 seconds", which
once was all the user heard about a file that had been judged. "Put output.pdf in math"
(`WANTS_PLACE`, `_place`, `Organizer.place`) moves the file where the user says, makes the
folder if need be, and teaches the organizer: that course's code and that kind of file go
there from now on. A question about the chore itself ("is it still
on?", "can you also sort pictures?", "why did nothing happen?": `ABOUT_CHORES` with
`WANTS_ANSWER`) goes to the chat model with a note of facts in front (`_chores_note`,
`_answer_about_chores`): with a plan or key model set up (Auto, or one picked in the
menu) that model gets the record and the question, so the user talks through what went
wrong with the better model, which is the orchestrator they expect; else its own model
answers from the same record (`NoirChat.jobs`, like `about`). Routing, forms and the
judging of files stay on the small model and in code, since through Claude Code even one
question reads about 29k tokens. The note holds: what each organizer watches, where its folders are, the last
moves and the files that stayed with their paths and reasons, and what kinds of file it
moves. Such a question never goes to the web (`_lookup_kind`: "pictures" once sent it
to an image search), the idea planner or the builder (the router once began a second
organizer for Pictures), and one the router still hands to the organizer is answered
the same way (`_run_agent`), not run as a pass. `python -m concierge.organizer_eval`
plays all of this with the real model on a made-up home, in a temporary folder with a
temporary data folder, and must pass every check; it is how each live failure was
reproduced before it was fixed.

Where Desktop, Documents, Downloads and Pictures really are comes from Windows
(`concierge/places.py`, `known_folder`, SHGetKnownFolderPath): with OneDrive backup on
the Desktop the user sees is `OneDrive/Desktop` (`OneDrive/바탕 화면` on a Korean
Windows), and the first organizer put its College folder in `C:/Users/me/Desktop`,
which the user never looks at. `destination_from`, `place_dirs` and `downloads_dir`
all ask it. A move's record keeps the whole place (`where`), and the done line says
`College/PHYS122` (`shown_folder`) when the folders live somewhere else. The
chores list gets its agents from `NoirEngine.chore_agents` (name, kind, on, how) and
the organizer's jobs from `organizer_done`; `undo_move` puts one back, which
`WatchBridge.undo_sorting` tries before the watch's own undo; `ChatHub.on_chores`
lets the window redraw when an organizer did something.

## The Spot

Tapping Ctrl twice in any program (`quick/spot.py`, `DoubleTap`) opens a small
card right under what's highlighted (`spot.html`, `spot.js`, `SpotBridge`,
`Overlay.open_spot`). Code decides the buttons from the text (`actions_for`):
your own writing gets Polish it and Make it shorter, something you're reading
gets Explain simply and Sum it up, an error gets What this error means, code
gets Explain this code. Translate is offered when the text isn't in the
computer's own language. The user's own chat agents come after those, and
there's a line to type anything. With nothing highlighted, what's typed is the
request and the answer is typed at the cursor.

The answer goes back where it came from (`Overlay.put_back`): in place of the
highlight, on a new line under it (Shift+Enter, so a chat message isn't sent),
at the cursor, or onto the clipboard. The user's own clipboard is put back
afterwards. Where the text can't be typed into (`selection_editable`: UI Automation, then
whether the window shows a text cursor, `caret_box`), Copy is the first button.
Short text isn't offered Sum it up or Make it shorter (`SUM_UP_CHARS`,
`SHORTEN_CHARS`): one sentence summed up came back as three bullet points. Ctrl used with another key, or held, never opens it.

The Spot always runs on its own model, whatever the model menu says: it can be
opened over anything in any program, so what it reads never goes to a cloud
model.

## Safety

`concierge/safety.py`: words about ending one's life or hurting oneself get a
fixed, kind reply with numbers to call (109 in Korea, 988 in the US), in the
language the person wrote in, before anything else runs, setups included. The
model never improvises there. Answers about health or money get a plain note to
check with a person. Ollama stopping halfway is `OllamaError(UNREACHABLE)`, shown
in plain words like any other problem.

## Noir's way of answering

Every answer reads the same whichever model writes it: hers, Claude or GPT through
the user's plan, or one with a key (`concierge/voice.py`). The answer comes first in
one or two plain sentences, then a few short points only if they help, at most one
tip, and no greeting, headings, tables or closing offer. Two halves, because a
model's habits win over a polite request. Code picks the kind of question
(`kind_of`: small_talk, fact, chat, explain, decide, how-to, code, plan, math, science) and its
word and point budget (`BUDGETS`), so the shape of an answer follows the question: a fact is one
or two sentences, an explanation is prose (`EXPLAIN_SHAPE`, never a forced list), steps and
options are lists, maths is worked through step by step with every formula in LaTeX between
$...$ and the result between $$...$$ (`MATH_STYLE`), and science gets the answer, the why and
the key equation (`SCIENCE_STYLE`). A model that draws well (a plan or key model,
`NoirChat.draws`) may add a drawing as SVG in a ```svg block (`DRAWING`); its own 4B model's
drawings came out black on black and off the edge, so it only draws when asked to
(`DRAW_WORDS`). Small talk ("hello", "thanks!", "hey how are you doing today?") gets a note
of its own (`SMALL_TALK_STYLE`): told to answer first with no greeting, its model listed what it
can do, or answered the last question again, and it says nothing about this computer, its model
or what it knows about the user, because "how are you" once came back as advice about memory.
Plain chat gets no points at all: offered "up to 2", a 4B model made two up every time. A
message of three words or fewer ("what?", "why?") is a follow-up to the last answer, so it is
chat, not something to explain with points. Its persona keeps the facts about this computer for
when the user asks about it or about Noir, never to bring up on its own; the app rebuilds its
model at startup whenever that prompt changed with the program (`needs_configure`), so a fix
to its words reaches the app without running setup. A whole line that only echoes the note ("No special conditions are
needed for this answer.", `RULE_ECHO`) is dropped by `tidy`, and `guide` goes with that one question only, so its memory of
the chat keeps just the words. Then `tidy` shapes every reply as it streams: it
drops "Great question!", turns headings into bold lines, tables into short lines,
takes out horizontal lines and quote marks and closes up gaps, never touching code.
`without_closing_filler` drops a closing offer, and a question tacked on after a whole
answer (`ANSWERED_SENTENCES`); a question it needs to ask stays. Every model treats
"up to six points" as six, so the caps are low. The budgets were set against the same
seven questions asked of its own model, GPT through Codex and Claude through Claude
Code.

Under its newest answer, on a row of its own below the facts line, one pill: Shorter,
only under an answer of 30 words or more. It skips the router and sets the answer's kind in
code (`FOLLOW_UPS`). The engine also answers More detail and "Ask X instead" (`ask_again`),
but the window no longer shows them: the user found them unnecessary. Keys are drawn as keys (`keys` in `app.js`). A photo of a
place it names goes beside its line (`pictures.py`: Wikipedia pages with map
coordinates whose title is the name it wrote). Nothing is looked up until the user says
yes once, under the first plan that names places or on What I see, and each lookup is
counted there.

## Looking things up on the web

A small model's knowledge stops at its training date, so `concierge/research.py` looks
things up for answers that change. Code decides from the words (`wants_lookup`): weather
words go to Open-Meteo (no key; the place from the question, or else the city of the
internet connection, and the answer says it's a guess; weekdays spelled out, since its
model called a Saturday Tuesday), a share or coin price to Yahoo Finance or CoinGecko
(`price`: the pages a search finds have the number but their snippets don't, and it then
said it was offline), "show me a picture" to an image search, and changing words (today, latest, price, news, who is the president, a year
from 2025 on, 오늘, 환율...) to a web search; timeless words (history, prove, explain,
physics, how do I, translate...) never go anywhere. A question neither list places is
put to its own model as one word, yes or no (`model_form`, forced by the schema; 16 of
16 right in the check), and doubt means no lookup. Nothing leaves the computer until the
user says yes once: the first time, it asks with a Question (id `web`), and What I see
has the switch and the count (`research.json`); every lookup is also counted under
"Leaving this computer" through `cloud.record_sent`. The search goes through a Brave
Search key when one is saved (optional, on What I see, kept in Windows' password store
like the model keys; the free path finds nothing now and then), else the `ddgs` package
with engines tried in turn (`SEARCH_ENGINES`). After the search the first two pages are
read as well (`read_page`, `MAX_PAGES`, never a PDF or a video) and go with the snippets,
because a snippet names the page that has the number while the page has it: that is how
the other apps get real answers. A who/what question not about the latest anything also
gets the first lines of its Wikipedia page and that page's picture. What was found goes with the question as
plain text headed "FOUND ON THE WEB just now (time)" that also tells it that it is not offline
for this answer, so it answers from it and says so,
and the sources and pictures ride on the `NoirDone` and into the saved chat. A lookup
that fails says so in its thinking and it answers from memory. With Auto, pages' worth of
findings count as a document and go to the plan model, which reads long text far better
than its 4B model; the weather or a price is short and stays here. Under a looked-up
answer the window says "As of 12:16 AM, from open-meteo.com", because such an answer
goes stale. The Spot and
agents never look anything up.

## Research jobs

"Research X", "look into", "write me a report on" (`researcher.RESEARCH_WORDS`) is more
than one lookup, and it is the first piece of the shape the product is heading for:
the plan model as reviewer, its own model as the workers, code in between. Its own
model turns the request into 2 to 4 searches as a form forced by the schema
(`plan`, `PLAN_SCHEMA`: its queries were as good as Claude's in the first live run,
in a sixth of the time and for none of the plan). The note tells it today's date and
code puts this year into any query that names an older one when the question named
none (`fresh_queries`): its model's sense of "now" stops at its training, and it
searched "Seattle housing 2024" in November 2026. Code runs all the searches at once
(`gather`, `SEARCH_WAIT`; one after another they were a third of the job, and a search
the burst refused is tried once more alone only when fewer than `ENOUGH_SEARCHES`
answered), then a picker chooses which results are worth reading (`concierge/sources.py`,
the judge every other app puts between the search and the model): the kind of site
from `sources.yaml` (official, reference, content farm; promoting, never banning), the
subject's own site counted as official (only for a proper name in the question, since
creatine.my is a seller's site and not creatine's), a name that looks made for search
engines as a farm, how many of the question's words the snippet holds, a date for a
current question, and its own model's yes or no over all the snippets in one form as
the tie-break. Pages about the question come first whatever their kind (an fda.gov
page about something else once outranked every page that was about it), with the rest
filling in only when fewer than three were. The best six are read at once, at most two from one site (`PAGES_PER_SITE`:
three pages from one supplement site made a brief lean on it), with two spare picks
swapped in for a page that turns out thin once read (`SPARE_PAGES`, `MIN_PAGE_CHARS`: a
blocked page once gave a worker 140 tokens of nothing). Every pick and drop is said in
its thinking with its reason, and each summary goes to the reviewer marked with its
kind, which is told to trust the higher kind where pages disagree; its own model reads each page and writes up to
six lines of what it says about the question, one page per call (`summarise`), the
part that eats the most tokens and the kind of job a 4B model does well; then the
plan model merges the summaries into one brief, checks them against each other,
names each point's site and ends with what wasn't found (`merge`). With Auto that is
the plan's fast model (`ModelMenu.fast_talker`: Sonnet on a Claude plan), since a
merge needs care more than depth and Opus took 15 of the first job's 37 seconds; a
model the user picked on purpose is used as it is. Every step is said in its
thinking with its tokens (`NoirEngine._research_job`), and the end counts what the
plan was charged (the apps report read and written exactly, `usage` keeps the last
answer) against what it would have been charged doing every step itself: each local
step as one plan call, its model's tokens plus the app's measured per-call overhead
(`usage.saved_estimate`, the same count as the Saved line), so it's "about", since the
plan's tokenizer counts a little differently. The saving goes on the `NoirDone` and
into the week's total, and the brief carries its sources. The plan's apps drop system
messages (`accounts.transcript`), so the notes ride in front of the question. A brief
about health or money gets the same plain note as any answer. Without a plan, its own
model does every step and the thinking says so.

Measured against the others: Perplexity answers a plain question in 3 to 8 seconds
and a Pro Search (several queries, then a synthesis) in 15 to 30, and the deep-research
modes of every company take minutes. Noir's job takes 19 to 30 seconds, half of it
the plan's app starting and writing; its Ollama serves one request at a time (four at
once took as long as four in a row), so the workers can't run side by side, and an
API key would save the app's start-up but not the writing. Five varied questions in
the check (a Nobel prize, a supplement's safety, a housing market, a software agent,
Korea's minimum wage in Korean) came back right wherever the pages were, with
disagreements between sources named and what wasn't found said. It needs the same web
permission as a lookup. Next in that shape: a last pass that puts the brief in the
user's own words, from their kept writing.

## The full window

`today.html` opens with the app. The side list is a plain contents column with no
brand on top: Today, New chat (Ctrl N, in bold; it opens Help me, which has no row of
its own) and Settings, each with
a small hairline icon (`ICONS` in `today.js`, viewBox -70..70, square corners), then
"/ search sessions", Pinned (a hint while nothing is pinned, the pin on each row's
hover), the sessions grouped Today, Yesterday, Earlier this week and Older
(`groupOf`), each title joined to its time by dotted leaders (`.item-lead`), and a
foot line naming the model answering. Labels, times, the search and the foot are in
the mono stack (`--mono` in `today.css`: Cascadia or Consolas, so it works offline),
and the same small mono caps label Today's sections, the room tabs and the welcome
steps, so every page reads as one design. Settings has tabs (`#room-tabs`):
About you, Agents, Models, Reservations, What I see and General, so a beginner only
meets the first four items.

The very first time, it opens on the first two minutes (`view-welcome`): it
times three real jobs on this computer (`Engine.measure`, never guessed), then
waits for the user to try the Spot in another window (`today.spotTried`, called
when the Spot opens), offers to look around this computer to get to know them, then
asks who they are, with what looking around found first. After that it opens on Today once
there's something to show this week, and on Help me otherwise. What was chosen is
kept in `window.json` (`Overlay.settings`; in memory in the practice run).

Help me is the rolling list (`TOPICS` in `today.js`), each line finishing "Help
me...". A line can be a switch (a ready-made highlight agent, the Spot, its
noticing), Add (a ready-made chat agent), a request sent to Noir as if typed, or
"Not built yet". The middle line's control works right on it, and a small moving
example of it happening shows beside the list, so people can picture it. Under
it, "Who are you?" (`ROLES`) offers which lines to switch on, and "Setting this
up for someone else" makes every word bigger. Switches go through
`Engine.switch_agent`, which adds and switches agents with nothing said in the
chat. Picking a line that sends words, or typing, turns the window into an
ordinary chat. New chat comes back to Help me; clicking the open session in the
side list goes back to its chat.

Today starts with what it did this week (`concierge/activity.py`: only the kind
of job and when, never the words, kept a month), then what's running, what it
noticed and what was done today.

An agent's page shows what it does and how it's set up, from `recipe.describe`
through `Engine.details(name)` and `TodayBridge.agent_details`, outside
`events.py` because it's only read when the page opens. What's typed on that
page goes to that agent.

`app.js` draws the chat and passes every event on as an `engine-event`;
`today.js` chooses the view, keeps what every page reads (`today.ui.state()`) and
draws Today and the side list from those events; `help.js`, `about.js` and `room.js`
draw their pages from it. The window acts through `app.say`,
`app.prefill`, `app.toggleAgent`, `app.deleteAgent`, `app.openChat`,
`app.deleteChat`, `app.attach`, `app.setModelName` and `app.addRecipe`. What the windows show
about its jobs comes from `TidyWatch.today()` through `WatchBridge`, outside
`events.py`, because those jobs aren't part of a conversation. Fonts are in
`web/fonts/`, because the app must work with no internet.

The chat sits in one centred column (`--column` in `today.css`), so the two sides
of a conversation stay close on a wide window. Below 1100 pixels the side list
folds to icons and opens over the page when asked, and below 760 "Help me" goes
above its wheel, so half a screen stays readable. The title bar stays Windows'
own, or snapping would stop working; `_blend_title` gives it the page's black.
Minimize and X both leave the window on the taskbar; Quit is in Settings and on
the clock icon. Only one copy runs at a time (`first_copy`): starting it again
brings the running one forward (`bring_forward`), the practice run included,
because two copies would both answer Ctrl tapped twice.

Its answers are drawn by `rich` and `inline` in `app.js`, still never as HTML from the
model's words: maths between $...$, $$...$$, \(...\) or \[...\] through KaTeX, code blocks
through highlight.js with the language and Copy on a line above, both shipped in
`web/vendor/` so they work offline (only the woff2 fonts, 740 KB in all); a ```svg block
is a drawing, cleaned of scripts, links and anything fetched, on a white card; links
open in the user's own browser (`open_link`), bold, italics and `code` as themselves,
and emoji through Segoe UI Emoji. "$5 and $10" stays money: single dollars are maths only
when what's between them looks like it. The user's own messages are drawn the same way,
and a question copied from a page or a book, whose code comes as plain lines with no
fences, gets them from `fenced` (runs of lines that look like code), so its code shows in
boxes too. Under every message is its time, and under hers
who wrote it, how long it took and Copy; a reopened chat shows the same times with the
day (`TranscriptItem.when`), and an answer from the web its sources and pictures.

Think is on by default, and the user asked to see its working it out. A switch beside the
box turns it off, remembered in the page. Its thinking is cut at `MAX_THOUGHT_CHARS` (about
5 seconds on an RTX 5080, measured) and the answer then written without it, because the 4B
model mostly thinks about the answer rules until stopped; small talk never thinks, since a
greeting took the longest of all. The first message after the app opens says that its model
is loading into memory (`NoirEngine._waking`), so the window never sits silent. Under each reply is the time, the model, how long it took and Copy, and
replies keep their lists, bold and code (`rich` in `app.js`, built as elements, never
as HTML).

The model menu sits beside the text box, not under it, and the box is left out of the
Agents and Models pages because those are for looking around.

Sessions can be pinned and searched, by title at once and by what was said a moment
later (`ChatBook.pin`, `ChatBook.search`). Agents and Models have pages of their own
in the side list.

## Cloud models

The menu beside the chat box (`concierge/models.py`, `ModelMenu`, `web/models.js`) is
one plain list, kept simple on purpose: On this computer (everything in Ollama), then
the user's plans (Your ChatGPT plan, Your Claude plan: each model by name once signed
in, or one Sign in row), then models from a company only if the user added its API key.
The Models page's Accounts tab looks like other AI apps' account pages: Connect an
account, a Run models locally card, Connected accounts with a badge (× only stops Noir
using one, `ModelMenu.use_account`; it never signs anyone out of Codex or Claude Code),
then the others, each opening its own sign-in when clicked. API keys are optional,
behind Have an API key instead? on a page of their own: the companies in
`cloud_models.yaml`, plus custom ones at any address that talks the way OpenAI's does. With a key saved, More models asks the company for the rest. Keys go in Windows'
password store through `keyring`, are never in a file, and pages only ever learn
whether one is saved. Noir's persona goes along as the system prompt.

The easy way in is a plan the user already pays for (`concierge/accounts.py`,
"Your plans" at the top of the API tab): ChatGPT through Codex, Claude through Claude
Code, the companies' own apps. They press Sign in, the app's own sign-in opens
ChatGPT's or Anthropic's page in the browser (`codex login`, `claude auth login
--claudeai`: plain `claude` first asks setup questions in a terminal people couldn't
use), whether they're signed in comes from the apps themselves (`codex login status`,
`claude auth status --json`), and
after that each answer comes from their plan, with no key. This is the way the
companies allow: Anthropic doesn't let other apps offer Claude sign-in, but people may
use the unmodified Claude Code with their own plan, so Noir never sees a login or a
token. It runs the app they installed (`AppModel`: `codex exec --json -s read-only
--ephemeral`, `claude -p --output-format stream-json --disallowedTools ...`) in an
empty folder where it can't change anything, sends the conversation as one question
(`transcript`) and reads the answer back. Codex's own model list (`codex debug
models`) fills the menu; Claude Code takes the same model names as Anthropic's list in the yaml. An app
that isn't installed gets Get Claude Code (Anthropic's installer, in a window) or
OpenAI's page; signed out, it falls back to its own model. Each answer takes a few
seconds more than with a key, because the app starts each time. The practice app has
`PracticeAccounts`.

How much is used (`concierge/usage.py`): a meter beside the model button (`#usage`,
`drawUsage` in `models.js`) shows the fullest window of the plan answering now, and
turns amber from `NEARLY_FULL`. Clicking it opens that plan on the Accounts page,
where each connected plan shows its windows like `/usage` in Claude Code (Next 5
hours, This week, each with when it starts again), then the tokens its answers used
today and this week, and the last answer. The model menu shows thin bars under the
plan's name. The limits are the plan's own numbers, never estimated: Claude Code
sends a `rate_limit_event` with every answer (`claude_limits`); Codex's are read only
if it reports them (`codex_limits`), otherwise only tokens show. Tokens come from
Claude Code's `result`, Codex's `turn.completed`, and for API keys from the streamed
reply (`cloud.tokens_in`; only OpenAI itself is asked for them with `stream_options`,
since other services might refuse it). A key has no plan limits, only tokens: what's
left is credit on the company's website. Only numbers are kept (`usage.json`, per
day for `KEPT_DAYS`), never words; the practice app counts in memory
(`usage.in_memory`). Most of what Claude Code reads per answer (about 29k tokens) is
its own instructions, sent each time, and the Accounts page says so.

Each chat answer says who wrote it (`whoAnswered` in `app.js`): a dot at the start of
the line under it, blue for this computer, yellow from a plan or key, turning red as
the plan fills (`--hue` from `plan_used`; a key has no plan, so it stays yellow). The
dot is kept with the saved conversation (`TranscriptItem.where` and the rest), so it's
there after reopening; chats saved before this have none. An answer Auto kept here
also says "Saved about 29k tokens": what its model read and wrote (`Ollama.last_tokens`,
Ollama's own count) plus the least the plan's app has ever read for one answer
(`least_read`, measured from real answers, so nothing is added before there is one),
in `usage.saved_estimate`. Those add up per day (`usage.record_saved`), and the
Accounts page shows a blue Saved this week bar under the plan's own bars
(`savedMeter` in `models.js`): what share of this week's tokens stayed here. Today's
week sentence adds the same total, "and saved about 12,400 tokens" (`Engine.activity`).

## Auto

Auto, the first row of the model menu once a plan or key is set up, saves the user's
plan (`concierge/auto.py`): each chat message is answered by its own model or sent to
the plan, decided on this computer. Never by the plan's model: through Claude Code
even "hi" reads about 29k tokens, so asking it would cost as much as answering. Code
places clear messages by their words (`kind_by_code`: pasted code, a proof, an essay,
a plan, a comparison go to the plan; greetings, quick facts, translating or fixing a
short text, small suggestions stay), the same on every computer. Only an unclear one
goes to its small model, which fills in one word from `KINDS` (`model_form`, forced by
the schema), and code turns that into here or the plan. With the real model the
examples in `auto_cases.yaml` are 50/50; its model judging alone got 41/47 ("good
morning" went to the plan), which is why code goes first.

The computer matters through what its model can answer, not how it judges:
`STAY_HERE` keeps more kinds here for a bigger model (`strength`, from the size in the
tag; unknown counts as small). Code, maths and comparisons always go to the plan. A
plan's fullest window past `NEARLY_OUT` keeps more here, past `USED_UP` everything.
Doubt goes to the plan (a wasted question costs a little; a bad answer costs trust), a
short "why?" stays with whoever answered before, and a plan that refuses before
writing a word (signed out, used up) means it answers itself. It says where each
message goes and why in its thinking (`say`), the reply's line names the model
(`NoirDone.by`), and an answer kept here carries "Ask Claude Sonnet 5.5 instead"
(`NoirDone.instead`, `Engine.ask_again`, `ChatBridge.ask_again`), which asks the
same question of the plan and replaces its answer in its memory; the window doesn't
draw that button any more, though the engine still offers it. Each kind kept here
and each ask-again is counted (`auto.json`, `record`, `counts`), so a kind people keep
asking again for shows up. Agents, the router and forms stay on its model with Auto.
Auto asks the plan model picked last (`ModelMenu.auto_target`, `auto_cloud` in the
settings), else a plan's Sonnet, else the first keyed model. `python -m
concierge.auto_eval` checks it with the real model and must stay at 100%.

Only its answers and agents asked in the chat move to the picked model
(`NoirChat.talker`). Deciding what a message is for and filling in forms stay with
its own small model, and so do switch-on agents, because those see whatever the user
highlights in any program. The documents agent stays too. The windows say so
whenever a model off the computer is chosen. Names in the yaml come from OpenRouter's
public list and may need changing; a wrong one shows "doesn't have that model".

The Models page has three tabs. Discover reads Hugging Face's public list
(`concierge/huggingface.py`) for GGUF models, the only kind Ollama can run, and works
out what each would download; Ollama fetches them itself from `hf.co/...`. Whether
one fits comes from the real file size against `helper_room` and the free disk, and
those come first. A model can be huge, so the first click on one only says how big. On
this computer and API edit what the menu shows (hiding removes nothing), delete local
models (never Noir's own) and add custom ones. A deleted model or a removed key
falls back to its own model, so it never stops talking.

The calls for this are outside `events.py`, like `details`: the bridge reaches them
through `ChatHub.menu`, and `FakeEngine` gives `ModelMenu` a `PracticeOllama`,
`PracticeKeys` and `practice_models`, so the practice app fetches, deletes and stores nothing.

## Sharing agents

The Agents page has Discover and Your agents (`web/discover.js`, shared with the
Models page). An agent made from parts is only words, never code, so it's safe to
share (`concierge/agents/community.py`, `community.json`). Agents that read a folder
can't be posted, because they're made of someone's own files.

The list everyone sees is `community.json` in the public repository
`padosory5/noir-agents`, kept apart because this project's code is private. There's
no server. Post an agent opens GitHub's new issue page in the browser, filled in, and
the user presses Submit, which needs a free GitHub account. Someone reads the issue
and adds the entry to that file by hand, so nothing goes live unchecked. The app reads
the list from the internet, then its last copy, then the one it shipped with, and
checks every entry with `community.clean`, which keeps only known settings. Until the
repository exists, `community.can_post` says so and nobody is sent to a dead page.

## The + button

Files, a folder, pictures or a screenshot (`concierge/attachments.py`, `send_files`).
Something added is the point of the message, so it skips the router and goes
straight to it. A file's words go into its memory of the conversation, cut to what
a small model can read, so the user can ask about it again. Pictures only go with
their own message, because they're too big to keep. A model that can't see pictures
says so; it never pretends. A folder starts a documents agent for it. What couldn't
be read is named in its thinking.

A long paste (1,500 characters or 20 lines) becomes a "Pasted text" card above the
box, the way other AI apps do it (`paste_text`, `pasted_file`), and goes to it like
any added file. Clicking the card puts the words back in the box.

## Getting to know the user

Noir can learn who someone is from their past chats with ChatGPT and Claude
(`concierge/history.py`, `concierge/portrait.py`). Those chats live on the companies'
servers, so nothing is automatic: the user asks each company once for a download
(Settings, then Export data) and gets a zip by email. It never signs in as them and
never reads their screen. `history.read_export` takes the zip, the unpacked folder or
its `conversations.json`, follows only the branch of a ChatGPT chat the user last saw
(edited drafts are side branches), and keeps only the user's own messages, cut short,
in `history.json`.

`portrait.understand` then works out what it can. Code counts the chats, the time of
day, the language (`language_of`) and the kinds of help asked for. Its model only sorts
each chat into one of `KINDS` (forced by the schema) and suggests facts, each with the
line number and the exact words it came from. Code drops a fact whose words aren't in
that line, that shares no word with its quote, that names a language its quote doesn't,
or that touches `SENSITIVE` matters (health, money, beliefs, politics, family,
relationships). Then a second, separate look (`confirmed`) shows the model each fact
beside its line and takes only "yes": suggesting and checking are different jobs, and
the second one caught every wrong fact in testing. The user keeps or drops each fact
(`portrait.keep`); only kept ones, plus what they ask for most, go into
`portrait.about_you`, which `NoirChat` sends with its persona (a system message there
replaces the one built into its model), and only to its own model, never a cloud one.

Real chats taught two more rules. Lines where someone sets a task ("I have to
integrate...", "represented as a list") aren't about them, so `SELF_WORDS` leaves them
out; a "fact" that's really a request ("Requests course layouts") is dropped by
`ASKING`, and the second look only says yes to lasting things (work, studies, home,
interests, tools, goals). One line gives at most `FACTS_PER_LINE` facts, or a single
line about a project became four.

Looking around this computer comes first (`concierge/signs.py`); chats are optional
extra. It reads the apps with a Start menu or desktop shortcut it knows
(`KNOWN_APPS`), which apps are used most from Windows' own count of hours in front
(UserAssist in the registry, read only: `app_use`, named the way people know them by
`app_name`, grouped into `ACTIVITIES`), the kinds and counts of files in the user's
own folders and which kinds changed in the last `RECENT_DAYS`, and folders with code
(a `.git` inside). Never AppData, hidden folders, links, anything inside a file, or
what was done inside an app. Windows only counts programs opened from Start or the
taskbar, so a program started from a terminal shows few hours; files changed lately
make up for that. Apps that touch `SENSITIVE` matters are left out. It's plain code
with no model, bounded by `MAX_ENTRIES` and `MAX_SECONDS` (under a second here), and
every guess says what it came from ("Unity Hub is installed", "5.2 hours in front, by
Windows' own count"). Only the summary is kept, in `portrait.json` beside the chats'
facts (`portrait.add_computer`), and the roles it points to put the matching "Who are
you?" card first.

Chat downloads arrive as links in an email. It can't read anyone's email, and the
links need the user signed in, so it never fetches them: when the user opens a
company's export page from it, it watches Downloads for `EXPORT_WAIT_HOURS`
(`Overlay.expect_exports`) and reads each export that lands there by itself
(`history.find_exports`, never the same file twice). Find it in my Downloads does the
same at once, and Choose the zip takes one by hand.

In the windows, step 3 of the first two minutes ("Get to know you") only offers Look
around. About you, the first tab of Settings, leads with what they do most on
this computer, each activity beside what it can do about it with Turn on right
there, then what they ask other AIs for most (from chats), each fact with what it
came from and Keep or Not right, then Tell me more (look around, and the chats,
marked Optional) and Forget all of this. The engine's calls are outside `events.py`,
like `measure`: `bring_in_history`, `understand_history`, `what_i_know`, `keep_fact`,
`forget_history`, `look_around`, `bring_in_downloads`, reached through `TodayBridge`,
which opens a company's export page from `EXPORT_PAGES` only.
`FakeEngine` gives a made-up portrait and reads nothing. `python -m concierge history ZIP`
does the same in the terminal (`--forget` forgets everything).

## Reservations

Booking an agent for later (`concierge/reservations.py`, `Overlay._run_booking`):
ask an agent something, switch one on or off, or sort Downloads, once, every day or
every week. They run only while the app is open, minimized or not. Something that
came due while it was closed is never run late: a one-time booking shows as missed
and a repeating one waits for its next time, because moving files hours later could
surprise someone. Bookings are saved in the data folder, or in memory with `--fake`.

## Ready-made agents

`concierge/agents/starters.yaml` holds tested recipes (Highlight Explainer,
Grammar Fixer, Quick Summarizer). "Turn on the highlight explainer" or "install
Grammar Fixer" adds one straight away and switches it on if asked
(`starters.asks_for`, `NoirEngine._add_starter`), decided in code with no
model involved. After that it is an ordinary agent made from parts.

## UI technology

The UI technology is the UI developer's choice. A UI not written in Python
(web, Electron, Tauri) should run a small local server around the engine and
send `events.to_dict(event)` as JSON; every event has a `"type"` field with
its class name.

## The first run

The window sets everything up itself (`concierge/setup.py`, `setup.js`): when
Ollama, its model or it is missing, `setup_state()["needed"]` is true and
`today.js` opens the setup page before anything else. It shows this computer, the
three steps with what each will do and how big it is (Ollama's own installer from
ollama.com, about 0.7 GB on Windows and 0.25 GB on a Mac; the model that fits from
`catalog.recommend`, with its download size and the memory it will use; Noir built
from it), and one button. `Setup.begin` runs the missing steps in order on a thread
of its own: the installer is fetched with its bytes shown, run quietly on Windows
(Inno Setup's switches, no admin prompt since it installs per user) or copied into
Applications on a Mac (`hdiutil` and `ditto`, with the image opened for the user if
that fails), Ollama is started (`Ollama.start`: its own app where there is one, which
`Ollama.find_program` finds where the installer puts it, since an app opened from the
Start menu or Finder never sees a PATH changed after it opened), the model is pulled
with a bar, and `noir.configure` builds it. Every step is checked, never assumed,
and a step that fails says what to do in plain words; Try again carries on where it
stopped, because Ollama keeps the part of a model it has. A computer nothing fits is
told why and can take the smallest model anyway. When nothing is missing the page
starts it again (`ChatHub.restart`) and goes on to the first two minutes. Other apps
either bundle their own engine (Jan, LM Studio, Msty: big installers, an engine that
only changes with the app) or send people to install Ollama themselves (Open WebUI,
AnythingLLM); this is the middle way, and nothing of Ollama's is bundled. `python -m
concierge.ui --fake --setup` plays the page with nothing fetched (`PracticeSetup`).

## Other systems (the Mac)

The window, the chat, agents asked in the chat, the documents agent, web lookups,
research jobs, the Models pages and the plans all run on macOS. What reads other
programs is Windows for now: the Spot, switch-on agents (highlights), its noticing
(Downloads, lectures), the circle, the icon by the clock and the light. Each is
gated in code, never only in the pages' words: `TidyWatch.start` looks at nothing
and `noticing` is False, `BreakSpotter` never spots a break, `NoirEngine.quick`
is None (so `AgentList.switchable` is empty and a switch answers "Windows for
now"), `Overlay._ready` makes no Mini, Tray, DoubleTap or EdgePull, and `welcome()["windows"]`
tells the pages, which show "Windows for now" on those lines and leave the Spot
step out of the first two minutes. A Mac window minimizes to the Dock, and Quit is
in Settings. The modules that talk to Windows (`quick/bubble.py`, `glow.py`,
`note.py`, `selection.py`) take their handles under `if sys.platform == "win32":`,
so they import anywhere; `home_language` asks the Mac for its first language.
`tests/test_platforms.py` keeps it so: it reads every module as a tree and fails on
Windows reached at import time outside such a block, and imports everything in a
fresh Python that says it is a Mac. `pynput` and `pystray` are Windows-only
requirements until the Spot and the icon come to the Mac.

## Versions and packaging

V0.1 was the app for the two of us; V0.2 is the app anyone can install, on
Windows and the Mac. The version lives in `concierge/__init__.py` (`__version__`)
and `pyproject.toml`, and a test keeps them the same. `packaging/` has the
recipe: `noir.py` is what the packaged app runs (its printing goes to
`noir.log` in the data folder, since a windowed app has no terminal),
`noir.spec` is PyInstaller's (one folder, not one file, which would unpack itself
at every start; every non-Python file under `concierge/` goes where `__file__`
expects it), `make_icons.py` draws its icon from the tray's disc, `noir.iss` is
the Windows installer (Inno Setup, like Ollama's: per user, no admin prompt, the
data folder never touched), and `build.py` runs them in order and then starts the
built app with `--check`, which loads every part and opens nothing, so a build that
can't start is caught before anyone installs it. `python packaging/build.py` does it
on this computer; `.github/workflows/release.yml` does it on GitHub's Windows and
Mac (Apple Silicon) runners when a `v*` tag is pushed and attaches
`Noir-Setup-<version>.exe` and `Noir-<version>.dmg` to the release. Both are
unsigned for now (Windows: More info, Run anyway; Mac: right-click, Open), which a
certificate and notarization would end. Other apps bundle their engine; Noir's
installer is small because Ollama is fetched on the first run (see The first run).

## Setup and commands

Python 3.11 and Ollama. From the repo root:

```bash
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m concierge          # terminal version: hardware, model, setup, chat
python -m concierge.ui       # the app with the real Noir
python -m concierge.ui --fake # FakeEngine and practice suggestions, no model needed, no files moved
python -m concierge.ui --fake --setup  # the first run's setup page, fetching nothing
python -m concierge.ui --check  # load every part, open nothing (what a build is checked with)
python packaging/build.py     # the installer (Windows) or disk image (Mac) for this system
pytest                       # all tests; none need Ollama
python -m concierge.agents.eval_router   # router accuracy with the real model (45 of 47 on 9 Nov 2026: "manuals in Downloads" went to an existing agent, a browser-translation idea to the translator; neither touched by the code rules)
python -m concierge.organizer_eval       # the file organizer end to end with the real model, on a made-up home (every check must pass)
python -m concierge.conductor_eval       # setups talked through, with the conductor this computer would use, on a made-up home (every check must pass; name a tag to try another model)
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
| `concierge/__init__.py` | Both | `__version__` |
| `packaging/` | Both | `noir.py` (what the packaged app runs), `noir.spec`, `make_icons.py` (`ICO_SIZES`, `ICNS_SIZES`, `make`), `noir.iss`, `build.py` (`DIST`, `INNO`, `main`, `built_program`, `check`, `windows_installer`, `mac_image`, `run`); workflow `.github/workflows/release.yml` |
| `concierge/hardware.py` | Engine | `GB`, `MIN_USABLE_VRAM_GB`, `GPU`, `HardwareReport`, `detect`, `parse_nvidia_smi`, `describe` |
| `concierge/catalog.py` | Engine | `CATALOG_PATH`, `GPU_SHARE`, `APPLE_SHARE`, `CPU_SHARE`, `CPU_MAX_GB`, `GPU_HEADROOM_GB`, `RAM_HEADROOM_GB`, `DISK_HEADROOM_GB`, `CPU_HELPER_SHARE`, `ModelEntry`, `HelperModel`, `Recommendation`, `load_catalog`, `load_helpers`, `load_conductors`, `helper_room`, `pick_helper`, `find_model`, `memory_budget`, `recommend`; models in `models.yaml` (`models`, `helpers`, `conductors`) |
| `concierge/chores.py` | Both | `TIDY`, `AGENT`, `BOOKING`, `MAX_JOBS`, `REPEAT_WORDS`, `ACTION_WORDS`, `listing`, `days`, `day_label`, `ago` |
| `concierge/quick/drawer.py` | UI | `EDGE_PIXELS`, `OPEN_PIXELS`, `Screen`, `screen_at`, `real_pixels`, `EdgePull` |
| `concierge/places.py` | Both | `KNOWN`, `known_folder` |
| `concierge/organizer.py` | Engine | `ORGANIZER`, `LOOK_SECONDS`, `SETTLE_SECONDS`, `READ_CHARS`, `MAX_FOLDER_NAME`, `DONE_KEPT`, `CONTENT`, `BY_NAME`, `DECIDE`, `DOCUMENTS`, `CODE`, `KINDS_AUTO`, `IMAGES`, `MAX_IMAGE_MB`, `SEE_NOTE`, `SEE_SCHEMA`, `KIND_WAITING`, `KIND_REFUSED`, `SUBJECT_WAITING`, `SUBJECT_REFUSED`, `ANOTHER`, `SUMMARIZER`, `WATCHED_KINDS`, `THREE_LINES`, `ONE_PARAGRAPH`, `NOTES_DEFAULT`, `SUMMARY_NOTE`, `SUMMARY_SCHEMA`, `NO_SUMMARY`, `COURSE_CODE`, `FOLDER_CODE`, `NOT_SURE`, `UNFINISHED`, `DECIDE_WORDS`, `SAME_PLACE`, `PLACES`, `CALLED`, `PATH`, `COURSE`, `STOPWORDS`, `TOPIC_NOTE`, `PICK_NOTE`, `SUBJECT`, `SOMETHING_ELSE`, `NO_TEXT`, `NOT_MATERIAL`, `NOT_SURE_WHICH`, `UNSURE_TOPIC`, `SKIPPED_KEPT`, `WATCHED`, `SEE_PIXELS`, `SEE_CONTEXT`, `SEEN_KEPT`, `how`, `organizer_card`, `summarizer_card`, `notes_path`, `shrink`, `course_codes`, `folder_codes`, `spoken_code`, `groups_from`, `courses_in`, `watched_from`, `destination_from`, `shown_folder`, `folder_name`, `words_of`, `closest`, `Organizer` (`verdict`, `skipped`, `last_skipped`, `moved`, `asked`, `working`, `stayed`, `kinds`, `subjects`, `asking`, `questions`, `answer`, `seer`, `place`); blueprint `agents/blueprints/organizer.yaml` |
| `concierge/organizer_eval.py` | Engine | `REQUEST`, `OLD`, `NEW`, `STAYS`, `pdf`, `word`, `drop`, `Run`, `main`; command `python -m concierge.organizer_eval [--keep]` |
| `concierge/conductor_eval.py` | Engine | `SAYS_DONE`, `ABOUT_LATER`, `claims_done`, `SAYS_STAYS`, `CANT_FIND`, `HANGUL`, `Trial`, `main`; command `python -m concierge.conductor_eval [tag ...] [--keep]` |
| `concierge/activity.py` | Engine | `ANSWERED`, `EXPLAINED`, `TRANSLATED`, `POLISHED`, `SUMMED_UP`, `HELPED`, `SORTED`, `READ`, `KEPT_DAYS`, `WEEK_DAYS`, `record`, `this_week` |
| `concierge/voice.py` | Engine | `BUDGETS`, `KIND_WORDS`, `SHORTER_SHARE`, `STYLE`, `SMALL_TALK_STYLE`, `POINTS`, `NO_POINTS`, `EXPLAIN_SHAPE`, `EXTRA`, `MATH_STYLE`, `SCIENCE_STYLE`, `DRAWING`, `DRAW_WORDS`, `OPENER`, `QUOTE`, `BOLD_BULLET`, `RULE_ECHO`, `ECHO_START`, `HEADING`, `RULE`, `TABLE_ROW`, `TABLE_LINE`, `SAFE_START`, `FIRST_SENTENCE`, `kind_of`, `guide`, `tidy` |
| `concierge/pictures.py` | Engine | `API`, `USER_AGENT`, `TIMEOUT`, `MAX_PICTURES`, `MAX_LOOKUPS`, `PICTURE_PIXELS`, `NO_PICTURES`, `BOLD`, `PART`, `BETWEEN`, `PLACE_WORDS`, `names_in`, `same_place`, `place`, `worth_asking`, `for_answer` |
| `concierge/safety.py` | Engine | `CRISIS`, `HEALTH`, `MONEY`, `CRISIS_REPLY`, `CRISIS_REPLY_KO`, `HEALTH_NOTE`, `MONEY_NOTE`, `crisis`, `crisis_reply`, `caution` |
| `concierge/noir.py` | Engine | `NOIR_MODEL`, `PERSONA_PATH`, `NUM_CTX`, `HISTORY_CHARS`, `MAX_THOUGHT_CHARS`, `UNLOAD_ON_EXIT`, `KEEP_ALIVE`, `HEARTBEAT_SECONDS`, `CLOSING_FILLER`, `ANSWERED_SENTENCES`, `without_closing_filler`, `system_prompt`, `configure`, `needs_configure`, `NoirChat` (`kind`, `draws`, `jobs`), `data_dir`, `load_state`, `save_state` |
| `concierge/ollama.py` | Engine | `DEFAULT_URL`, `DOWNLOAD_PAGE`, `UNREACHABLE`, `OllamaError`, `Ollama` (`last_tokens`: read and written by the last chat; `find_program`, `start` for the first run) |
| `concierge/conversations.py` | Engine | `TITLE_CHARS`, `Conversation`, `ChatBook`, `title_from` |
| `concierge/models.py` | Engine | `LOCAL`, `CUSTOM`, `LOOPBACK`, `GB`, `FITS`, `SLOW`, `NO_DISK`, `LocalModel`, `ModelMenu` (Auto adds `auto_target`, `plan_used`, `fast_talker`; the meter `usage`), `nice_name` |
| `concierge/huggingface.py` | Engine | `API`, `TIMEOUT`, `LIST_LIMIT`, `SIZE_WORKERS`, `CACHE_SECONDS`, `GB`, `SORTS`, `VISION`, `PREFERRED`, `QUANTIZATION`, `PART`, `HubError`, `HubModel`, `best_file`, `browse`, `tag_from` |
| `concierge/cloud.py` | Engine | `CATALOG_PATH`, `KEY_STORE`, `MAX_REPLY_TOKENS`, `LIST_TIMEOUT`, `REPLY_TIMEOUT`, `MORE_MODELS`, `ANTHROPIC_VERSION`, `SENT_KEPT`, `NOT_FOR_CHAT`, `CloudError`, `CloudOption`, `Provider`, `CloudModel`, `load_providers`, `saved_key`, `save_key`, `forget_key`, `request_for`, `text_in`, `record_sent`, `sent_recently`, `key_refused`, `tokens_in`, `live_models`, `overview`, `find_option`; companies and models in `cloud_models.yaml` |
| `concierge/accounts.py` | Engine | `CODEX`, `CLAUDE_CODE`, `APPS`, `CLAUDE_INSTALL`, `CLAUDE_NO_TOOLS`, `ANSWER_TIMEOUT`, `STATUS_SECONDS`, `NO_WINDOW`, `NEW_WINDOW`, `Accounts`, `AppModel`, `transcript` |
| `concierge/auto.py` | Engine | `HERE`, `CLOUD`, `AUTO`, `KINDS`, `SMALL`, `MEDIUM`, `LARGE`, `STAY_HERE`, `MEDIUM_FROM_B`, `LARGE_FROM_B`, `NEARLY_OUT`, `USED_UP`, `LONG_CHARS`, `FOLLOW_UP_WORDS`, `QUICK_WORDS`, `CASES_PATH`, `SMALL_TALK`, `JOKE`, `CODE`, `MATH`, `WRITING`, `WRITING_ACT`, `PLANNING`, `ANALYSIS`, `EXPLAIN`, `DEEP`, `REWRITE`, `QUICK`, `SUGGESTION`, `REFERS_BACK`, `WORDS`, `HERE_WORDS`, `CLOUD_WORDS`, `Decision`, `strength`, `bigger`, `kind_by_code`, `decide`, `say`, `model_form`, `record`, `counts`, `load_cases`; examples in `auto_cases.yaml` |
| `concierge/auto_eval.py` | Engine | `SMALL_MODEL`, `main`; command `python -m concierge.auto_eval [model]` |
| `concierge/usage.py` | Engine | `KEPT_DAYS`, `WINDOWS`, `NEARLY_FULL`, `usage_path`, `in_memory`, `record_tokens`, `record_limits`, `record_saved`, `saved_estimate`, `summary`, `forget`, `claude_limits`, `claude_tokens`, `codex_limits`, `codex_tokens` |
| `concierge/attachments.py` | Engine | `IMAGE_TYPES`, `MAX_CHARS_PER_FILE`, `MAX_CHARS`, `MAX_IMAGE_MB`, `NOTHING_SAID`, `Attached`, `read_attachments` |
| `concierge/history.py` | Engine | `CHATGPT`, `CLAUDE`, `EXPORT_PAGES`, `MAX_MESSAGE_CHARS`, `MAX_EXPORT_MB`, `CONVERSATIONS`, `HistoryError`, `PastChat`, `history_path`, `is_export`, `read_export`, `bring_in`, `brought_in`, `forget`, `read_files_path`, `find_exports` |
| `concierge/signs.py` | Engine | `KNOWN_APPS`, `NOT_APPS`, `FILE_KINDS`, `RECENT_GROUPS`, `RECENT_DAYS`, `USER_ASSIST`, `MAX_APPS_KEPT`, `MIN_HOURS`, `ACTIVITIES`, `GAME_FOLDERS`, `PLAIN_FOLDERS`, `NOT_ACTIVITIES`, `FRIENDLY`, `CODE`, `STUDY_NAMES`, `WORK_NAMES`, `SKIP_DIRS`, `MAX_ENTRIES`, `MAX_SECONDS`, `MAX_DEPTH`, `MAX_PROJECTS_KEPT`, `REPARSE_POINT`, `THIS_COMPUTER`, `look_around`, `app_use`, `app_name`, `activity_of`, `activities`, `installed_apps`, `facts_from`, `role_words` |
| `concierge/portrait.py` | Engine | `KINDS`, `KIND_MEANINGS`, `ABOUT`, `MAX_SORTED`, `SORT_BATCH`, `SORT_PREVIEW_CHARS`, `MAX_SNIPPETS`, `SNIPPET_CHARS`, `FACT_BATCH`, `MAX_FACTS`, `FACTS_PER_LINE`, `QUOTE_MIN_CHARS`, `FACT_MAX_CHARS`, `SELF_WORDS`, `SENSITIVE`, `SUBJECT`, `ASKING`, `PARTS_OF_DAY`, `SCRIPTS`, `ENGLISH_WORDS`, `portrait_path`, `load`, `forget`, `understand`, `add_computer`, `keep`, `about_you`, `busiest_part_of_day`, `languages_used`, `language_of`, `sort_kinds`, `find_facts`, `confirmed`, `self_snippets`, `checked`, `merge` |
| `concierge/reservations.py` | Engine | `SORT`, `RUN`, `TURN_ON`, `TURN_OFF`, `ONCE`, `DAILY`, `WEEKLY`, `CHECK_SECONDS`, `STEPS`, `ReservationError`, `Reservation`, `Reservations` |
| `concierge/events.py` | Both (contract) | `Thinking`, `SystemInfo`, `NoirText`, `NoirDone`, `Question`, `AgentCard`, `Progress`, `Source`, `Picture`, `Result`, `AgentList`, `Error`, `IdeaStep`, `IdeaCard`, `ChatSummary`, `ChatList`, `TranscriptItem`, `Transcript`, `Event`, `to_dict`, `Engine` |
| `concierge/research.py` | Engine | `SETTINGS`, `WEB_QUESTION`, `YES_LOOK`, `NO_LOOK`, `WEB`, `WEATHER`, `SEARCH`, `IMAGES`, `PRICE`, `MAX_RESULTS`, `MAX_IMAGES`, `SNIPPET_CHARS`, `EXTRACT_CHARS`, `FINDINGS_CHARS`, `TIMEOUT`, `USER_AGENT`, `GEOCODE`, `FORECAST`, `WHERE_AM_I`, `WIKIPEDIA`, `MAX_PAGES`, `PAGE_CHARS`, `PAGE_BYTES`, `PAGE_TIMEOUT`, `SKIP_PAGES`, `BRAVE_SEARCH`, `SEARCH_KEY`, `SEARCH_KEY_PAGE`, `TAGS_TO_DROP`, `TAG`, `BLOCK_END`, `YAHOO_SEARCH`, `YAHOO_CHART`, `COINGECKO_SEARCH`, `COINGECKO_PRICE`, `BROWSER_AGENT`, `CHANGING`, `TIMELESS`, `WEATHER_WORDS`, `IMAGE_WORDS`, `PRICE_WORDS`, `CRYPTO_WORDS`, `PRICE_FILLER`, `QUESTION`, `PLACE_AFTER`, `PLACE_BEFORE`, `PLACE_KO`, `SKY`, `SEARCH_ENGINES`, `Findings`, `wants_lookup`, `unsure`, `model_form`, `settings_path`, `allowed`, `allow`, `lookups`, `place_in`, `weather`, `price_subject`, `price`, `search_key`, `set_search_key`, `brave`, `search`, `page_text`, `read_page`, `images`, `wikipedia`, `look_up`, `note` |
| `concierge/sources.py` | Engine | `TIERS_PATH`, `PRIMARY`, `REFERENCE`, `ORDINARY`, `FARM`, `TIER_WORDS`, `TIER_POINTS`, `SUBJECT_POINTS`, `MODEL_POINTS`, `FRESH_POINTS`, `MIN_SNIPPET_MATCH`, `CURRENT_WORDS`, `STOPWORDS`, `FARM_LOOKS`, `JUDGE_NOTE`, `JUDGE_SCHEMA`, `Choice`, `load_tiers`, `site_of`, `words_of`, `tier_of`, `relevance`, `pick`, `judge_with`, `said`; tiers in `sources.yaml` |
| `concierge/researcher.py` | Engine | `RESEARCH`, `RESEARCH_WORDS`, `MAX_QUERIES`, `PAGES_PER_QUERY`, `MAX_PAGES`, `SUMMARY_LINES`, `SINGLE_ASK_WRITTEN`, `SEARCH_WAIT`, `ENOUGH_SEARCHES`, `PAGES_PER_SITE`, `SPARE_PAGES`, `MIN_PAGE_CHARS`, `PLAN_NOTE`, `PLAN_SCHEMA`, `STALE_YEAR`, `WORKER_NOTE`, `MERGE_NOTE`, `Page`, `Account`, `wants_research`, `fresh_queries`, `plan`, `gather`, `summarise`, `merge`, `plan_tokens_after`, `last_plan_answer`, `settle`, `account_lines`, `when_now`, `sources_of` |
| `concierge/engine.py` | Engine | `SPOT_KINDS`, `MEASURED_JOBS`, `TROUBLE`, `FIX_AGENT`, `FIX_IT`, `LEAVE_IT`, `WANTS_DELETE`, `WANTS_IDEAS`, `WANTS_ON`, `WANTS_OFF`, `DELETE_AGENT`, `PICK_AGENT_TO_DELETE`, `DELETE_IT`, `KEEP_IT`, `FOLLOW_UPS`, `ORGANIZE_NOW`, `GO_THROUGH`, `ONLY_NEW`, `WANTS_WHERE`, `WANTS_STATUS`, `WANTS_ORGANIZE`, `WANTS_PLACE`, `WANTS_EVERYTHING`, `WANTS_WHY`, `WHERE_WORDS`, `WANTS_ANSWER`, `ABOUT_CHORES`, `ASKS_FOR_WORK`, `FOLLOWS_A_CHORE`, `CHORE_FRESH_SECONDS`, `NO_WORDS`, `WHICH_KIND`, `SOMETHING_ELSE_KIND`, `KIND_SHORT`, `NoirEngine` (adds `follow_up`, `follow_up_words`, `after_answer`, `pictures`, and `pending_lookup`, `found` for the web; outside the contract: `ask_again` for Auto, `setup_state` and `setup_begin` for the first run, `chore_agents`, `organizer_done`, `undo_move`, `organizer_questions` and `organizer_answer` for the chores list; `conducts`: whether a setup may be talked through) |
| `concierge/setup.py` | Engine | `OLLAMA`, `MODEL`, `NOIR`, `INSTALLERS`, `SILENT_INSTALL`, `DOWNLOAD_TIMEOUT`, `INSTALL_SECONDS`, `START_SECONDS`, `QUICK_START_SECONDS`, `CHUNK`, `MAC_OPEN`, `SetupError`, `Setup` |
| `concierge/fake_engine.py` | Engine | `FakeEngine`, `PracticeOllama`, `PracticeKeys`, `PracticeAccounts`, `PracticeSetup`, `practice_models` |
| `concierge/cli.py` | Engine | `DIM`, `PLAIN`, `main`, `cmd_hardware`, `cmd_recommend`, `cmd_setup`, `cmd_chat`, `cmd_measure`, `cmd_history`, `TerminalScreen`; command `python -m concierge [hardware, recommend, setup, chat, measure, history]`; in the chat `/think` turns thinking on or off |
| `concierge/agents/blueprint.py` | Engine | `BLUEPRINT_DIR`, `Slot`, `Blueprint`, `load_blueprints`; templates in `agents/blueprints/*.yaml` (`documents_qa`, `organizer`, `summarizer`, and `custom`: the shared template for agents made from parts) |
| `concierge/agents/conductor.py` | Engine | `STILL_ASKING`, `NOTHING_MISSING`, `CALLED_OFF`, `MOVED_ON`, `CONDUCT`, `PLACE_NAMES`, `INSIDE`, `PLACE_SLOTS`, `CONDUCT_CONTEXT`, `CONDUCT_TEMPERATURE`, `CONDUCT_KEEP_ALIVE`, `MAX_TURNS`, `MAX_SAY`, `VOICE`, `HOW_TO_CONDUCT`, `FORM_NOTE`, `MORE_STATUS`, `CARD_COMES`, `CARD_IS_UP`, `OPENING_OFFER`, `CLOSING_NUDGE`, `JSON_ONLY`, `Form`, `ConductorError`, `Turn`, `Conductor` (`turn`, `waking`, `done`), `tidy_say`, `field_for`, `schema_for`, `needed`, `note_for`, `local_form`, `talker_form`, `read_form` |
| `concierge/agents/talk.py` | Engine | `MAX_CHARS`, `MAX_PLAIN`, `TEMPERATURE`, `KEPT_SHARE`, `ASKING_WORDS`, `PHRASE_NOTE`, `QUESTION_NOTE`, `JARGON`, `UNQUOTED`, `FACT_IN_LINE`, `STOPWORDS`, `phrase`, `facts_in`, `words_of` |
| `concierge/quick/agents.py` | Engine | `BUBBLE`, `CLIPBOARD`, `BOTH`, `UNTIL_UNHIGHLIGHT`, `FEW_SECONDS`, `CHECK_SECONDS`, `CHECK_FOR_SECONDS`, `QuickAgents` |
| `concierge/quick/bubble.py` | Engine | `GAP`, `MAX_WIDTH`, `COLORS`, `GWL_EXSTYLE`, `WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `WS_EX_TOPMOST`, `show_seconds`, `Bubble` |
| `concierge/quick/selection.py` | Engine | `DRAG_PIXELS`, `DOUBLE_CLICK_SECONDS`, `MIN_CHARS`, `MAX_CHARS`, `NO_COPY_APPS`, `Rect`, `CF_UNICODETEXT`, `foreground_app`, `SelectionWatcher`, `read_selection`, `highlighted_text`, `save_clipboard`, `restore_clipboard`, `set_clipboard_text` |
| `concierge/quick/glow.py` | Engine | `LILAC`, `GREEN`, `THICKNESS_SHARE`, `RIM_SHARE`, `BRIGHTEST`, `RUN_SECONDS`, `HOLD_SECONDS`, `FADE_SECONDS`, `FRAME_SECONDS`, `LINE_SHARE`, `LINE_BREATH_SECONDS`, `WS_POPUP`, `LIGHT_STYLE`, `light_at`, `pixel`, `reached`, `eased`, `full_screen_in_use`, `work_screen`, `real_pixels`, `Layer`, `pump`, `Glow` |
| `concierge/quick/note.py` | Engine | `COLORS`, `CIRCLE_ROOM`, `BOTTOM_GAP`, `SHOW_SECONDS`, `LOG_SECONDS`, `WRAP_PIXELS`, `CHECK_MS`, `ARRIVE_STEPS`, `ARRIVE_MS`, `ARRIVE_PIXELS`, `SOLID`, `ask`, `tell` |
| `concierge/quick/watching.py` | Engine | `LECTURE_WORDS`, `VIDEO_SITES`, `BROWSERS`, `PLAYERS`, `looks_like_lecture`, `lecture_on_screen` |
| `concierge/quick/tidy.py` | Engine | `MIN_FILES`, `SETTLE_SECONDS`, `FIRST_LOOK_SECONDS`, `LOOK_SECONDS`, `SNOOZE_DAYS`, `IGNORED_DAYS`, `BREAK_SECONDS`, `TYPING_GAP_SECONDS`, `MIN_JOB_SECONDS`, `PRACTICE_FIRST_LOOK_SECONDS`, `PRACTICE_JOB_SECONDS`, `VIDEO_LOOK_SECONDS`, `PRACTICE_VIDEO_SECONDS`, `QUESTION_GAP_SECONDS`, `PRACTICE_QUESTION_GAP_SECONDS`, `UNDO_DAYS`, `LECTURE_NOTES_BUILT`, `CLOUD_ONLY`, `YES`, `NOT_NOW`, `SORT`, `VIDEO`, `VIDEO_QUESTION`, `NO_VIDEO_SUMMARY`, `PRACTICE_LECTURE`, `DONE_KEPT`, `SHELVES`, `OTHER_SHELF`, `UNFINISHED`, `SYSTEM_FILES`, `downloads_dir`, `log_path`, `shelf_for`, `loose_files`, `free_name`, `sort_plan`, `sort_folder`, `record_moves`, `sorts_on_record`, `last_sort`, `moved_to`, `can_undo`, `undo_sort`, `BreakSpotter`, `TidyWatch` |
| `concierge/quick/spot.py` | Engine | `DOUBLE_TAP_SECONDS`, `TAP_SECONDS`, `MAX_SPOT_CHARS`, `MAX_HELPERS`, `SUM_UP_CHARS`, `SHORTEN_CHARS`, `WRITING`, `READING`, `ERROR`, `CODE`, `NOTHING`, `ERROR_WORDS`, `CODE_SIGNS`, `WRITE_FOR_ME`, `ACTIONS`, `home_language`, `kind_of`, `actions_for`, `job`, `caret_box`, `selection_editable`, `DoubleTap` |
| `concierge/quick/translate.py` | Engine | `LANGUAGES`, `language_in`, `looks_like` |
| `concierge/agents/builder.py` | Engine | `PLACES`, `CANCEL_WORDS`, `YES_WORDS`, `BY_CONTENT_WORDS`, `BY_NAME_WORDS`, `BLOCKED`, `SKIP_WHILE_SEARCHING`, `CARD`, `CHANGE`, `PICK_FOLDER`, `DUPLICATE`, `REPLACE`, `MAKE_ANOTHER`, `CREATE_IT`, `SAVE_CHANGES`, `RENAME`, `TARGET_LANGUAGE`, `LANGUAGE_CHOICES`, `CARD_YES`, `NAMES_IT`, `NOT_KNOWN`, `A_PATH`, `MAX_COUNTED`, `SYSTEM_FOLDER`, `custom_card`, `Refused`, `Draft`, `AgentBuilder` (`take_created`; `conductor` and `conducted` for a setup talked through), `say`, `place_dirs`, `find_folders`, `agent_for_folder`, `is_blocked`, `describe_files`, `short_place`, `files_in` |
| `concierge/agents/planner.py` | Engine | `BLOCKS_PATH`, `OTHER`, `MAX_STEPS`, `IDEA`, `IDEA_CHANGE`, `KEY_COMBO`, `ASKED_FOR_KEY`, `settle_triggers`, `MAKE_IT`, `SAVE_IDEA`, `CHANGE_IDEA`, `DROP_IDEA`, `HELPER_ROLES`, `ROLE_WORDS`, `Block`, `PlanStep`, `Assessment`, `IdeaDraft`, `IdeaPlanner`, `load_blocks`, `assess`, `clean_detail`, `ideas_path`, `list_ideas`, `save_idea`, `describe_ideas`; building blocks in `agents/capabilities.yaml` |
| `concierge/agents/recipe.py` | Engine | `CUSTOM`, `WHILE_ON`, `IN_CHAT`, `MAX_INSTRUCTION`, `HIGHLIGHT_WORDS`, `CHAT_WORDS`, `SHOW_WORDS`, `COPY_WORDS`, `STAY_WORDS`, `SHORT_WORDS`, `SAMPLE_TEXT`, `SAMPLE_QUESTION`, `MECHANICS`, `describe`, `run_instruction`, `target_language`, `settings_from_words`, `needs_language`, `with_language`, `write_recipe`, `rewrite_instruction`, `is_switchable`, `migrate` |
| `concierge/agents/files.py` | Engine | `TEXT_TYPES`, `SUPPORTED`, `OFFICE_PARTS`, `ARCHIVES`, `MARKUP`, `TEXT_SAMPLE`, `OFFICE_CHARS`, `MAX_LISTED`, `text_of`, `without_tags`, `office_text`, `archive_listing`, `MAX_FILES`, `MAX_FILE_MB`, `PASSAGE_CHARS`, `PASSAGE_OVERLAP`, `Passage`, `ScanResult`, `scan`, `read_pages`, `split`, `passages_of`, `tokens`, `SearchIndex`, `folder_signature` |
| `concierge/agents/router.py` | Engine | `IDEA_OPTION`, `WANTS_CHANGE`, `WANTS_NEW`, `WATCHES`, `SUMS_UP`, `SORTS`, `KIND_WORDS`, `FILES`, `WANTS_HELPER`, `kinds_named`, `Route`, `route`, `wants_change`, `refers_to`, `names_an_agent`; test cases in `agents/router_cases.yaml` |
| `concierge/agents/community.py` | Engine | `REPOSITORY`, `INDEX_PATH`, `INDEX_URL`, `POST_URL`, `TIMEOUT`, `CACHE_SECONDS`, `MAX_NAME`, `MAX_ABOUT`, `MAX_BY`, `READY_MADE`, `COMMUNITY`, `CATEGORIES`, `OTHER_CATEGORY`, `STARTER_DETAILS`, `PostError`, `Recipe`, `clean`, `recipes`, `find`, `install`, `can_post`, `post_address`; shared agents in `agents/community.json` |
| `concierge/agents/starters.py` | Engine | `STARTERS_PATH`, `WANTS_ADD`, `MAX_WORDS`, `Starter`, `load_starters`, `asks_for`, `install`; recipes in `agents/starters.yaml` |
| `concierge/agents/runner.py` | Engine | `TOP_PASSAGES`, `MAX_CONTENTS`, `STOPWORDS`, `run`, `matching_words`, `clean_answer`, `refresh_index`, `best_sentence` |
| `concierge/agents/store.py` | Engine | `Agent`, `agents_dir`, `slugify`, `list_agents`, `find_agent`, `name_taken`, `save`, `load_index`, `delete` |
| `concierge/agents/eval_router.py` | Engine | `CASES`, `main`; command `python -m concierge.agents.eval_router` |
| `concierge/ui/window.py` | UI | `WEB_DIR`, `TITLE`, `UNEXPECTED_ERROR`, `EDGE_GAP`, `DRAWER_WIDTH`, `DRAWER_GAP`, `MOVE_NOTE_SECONDS`, `STAY_NOTE_SECONDS`, `ASK_NOTE_SECONDS`, `DRAWER_MIN_HEIGHT`, `DRAWER_SLIDE_STEPS`, `DRAWER_SLIDE_SECONDS`, `DRAWER_FOG`, `DRAWER_LOAD_SECONDS`, `FULL_SHARE`, `FULL_MIN_SIZE`, `SCREEN_SETTLE_SECONDS`, `PICTURES`, `EXPORTS`, `EXPORT_WAIT_HOURS`, `EXPORT_CHECK_SECONDS`, `APP_ID`, `ONE_COPY`, `SPOT_WIDTH`, `SPOT_START_HEIGHT`, `SPOT_MIN_HEIGHT`, `SPOT_GAP`, `SPOT_SETTLE_SECONDS`, `PASTE_SETTLE_SECONDS`, `REMEMBERED`, `Area`, `ChatHub` (adds `restart` after the first run's setup, `latest` for the last list of a kind, `on_chores`, `on_move`, `on_ask`, `on_working`, `on_stayed`), `ChatBridge` (a page calls its `startup`, `send`, `choose`, `ask_again`, `new_chat`, `open_chat`, `delete_chat`, `delete_agent`, `toggle_agent`, `reset`), `WatchBridge` (adds `today`, `chores`, `answer`, `undo_sorting`, `set_noticing`, `activity`, `privacy`, `set_web`, `set_search_key`, `open_link`), `TodayBridge` (adds `agent_details`, `quit_app`, `welcome`, `set_welcomed`, `setup_state`, `setup_begin`, `setup_finish`, `measure`, `set_spot`, `switch_agent`, `bring_in_history`, `understand_history`, `what_i_know`, `keep_fact`, `forget_history`, `open_export_page`, `look_around`, `find_downloads`, `send_files`, `pick_files`, `pick_images`, `pick_folder`, `screenshot`, `paste_text`, `follow_up`, `after_answer`, `pictures`, `models`, `pick_model`, `save_key`, `forget_key`, `more_models`, `open_key_page`, `sign_in_account`, `install_account`, `check_accounts`, `use_account`, `usage`, `hide_model`, `add_custom_model`, `remove_custom_model`, `delete_model`, `browse_models`, `get_model`, `cancel_download`, `downloads`, `recipes`, `add_recipe`, `post_agent`, `pinned_chats`, `pin_chat`, `search_chats`, `reservations`, `add_reservation`, `remove_reservation`, `switch_reservation`), `GlassBridge` (adds `open_app`, `hide_drawer`), `SpotBridge` (`run`, `put_back`, `fit`, `close`), `Overlay` (the drawer: `toggle_drawer`, `hide_drawer`, `pull_drawer`, `release_drawer`; `refresh_mini`), `pasted_file`, `full_size`, `centered`, `drawer_bounds`, `drawer_x`, `place_spot`, `work_area`, `first_copy`, `bring_forward`, `main`; command `python -m concierge.ui [--fake] [--debug] [--setup] [--version] [--check]` |
| `concierge/ui/mini.py` | UI | `MINI_SIZE`, `EDGE_GAP`, `DISC_SHARE`, `FRAMES`, `FRAME_SECONDS`, `RESTING`, `BRIGHT`, `FADE_STEP`, `FULL_SCREEN_CHECK_SECONDS`, `IDLE`, `WORKING`, `ASKING`, `BLINK_SECONDS`, `BLINK_DIM`, `LILAC`, `WHITE`, `is_click`, `premultiplied`, `draw_frames`, `Mini` (`blink`) |
| `concierge/ui/tray.py` | UI | `ICON_SIZE`, `INK`, `DOTS`, `tray_picture`, `Tray` |
| `concierge/ui/web/` | UI | `today.html`, `today.css`, `today.js` (full window, global `today.refresh()`, `today.show`, `today.closeMenus`, `today.redraw`, `today.spotTried`, `today.chatsArrived`, `today.ui`), `help.js` (global `helpPage`: Help me and Who are you), `about.js` (global `aboutPage`: About you and the first two minutes), `setup.js` (global `setupPage`: the first run's setup page), `chores.js` (global `choresPage`: the Chores page), `room.js` (global `roomPage`: What I see and Reservations), `discover.js` (global `discover`: the Agents page and parts it shares), `models.js` (global `modelPage`: the model menu and the Models page; `modelPage.loadUsage` and `modelPage.openUsage` for the usage meter), `spot.html`, `spot.css`, `spot.js` (the Spot, global `spot.open`), `glass.html`, `glass.css`, `glass.js` (the drawer, with its own `app.onEvent`, `app.mirror`, `app.shown`, `app.refresh`), `fonts/`, `vendor/` (KaTeX and highlight.js, for maths and code offline), `style.css`, `app.js`; JavaScript globals `app.onEvent(event)`, `app.mirror(state)`, `app.shown()` (called by `ChatHub` and `Overlay`), `app.say`, `app.prefill`, `app.toggleAgent`, `app.deleteAgent`, `app.openChat`, `app.deleteChat`, `app.attach`, `app.setModelName` and `app.addRecipe` (called by today.js, discover.js and models.js); window event `engine-event` |
