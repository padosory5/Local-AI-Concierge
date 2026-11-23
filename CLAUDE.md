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
| `Result` | An agent's answer, with its `sources` (file path and quote) shown small underneath. From `Try-out`: what a helper still being worked out would do, just before its card |
| `AgentList` | The user's agents, for a sidebar or menu, each with a delete button calling `delete_agent(name)`. Agents in `switchable` work outside the chat while switched on: show an on/off switch calling `toggle_agent(name)`; `active` lists the ones on. Sent again whenever it changes |
| `Error` | A friendly error message; the text is already written for the user |
| `ChatList` | Saved conversations, newest first, with `current` marking the open one. Clicking one calls `open_chat(id)`; each has a delete button calling `delete_chat(id)` after a confirm |
| `Transcript` | Replace the whole chat area with these items (`role`: user, noir, result, error). Empty after New chat or deleting the open chat. A noir item keeps its answer's `by`, `where`, `saved` and `plan_used`, so a reopened chat shows the same dot, its `sources` and `images`, and every item has `when` (ISO), so a reopened chat shows the time, and the day, under each message |
| `IdeaCard` | Noir's verdict on a helper idea: `title`, each step with its `status` (ready, not_built, not_possible, unclear) and `note`, the `difficulty` line, the `verdict`, and `actions` as buttons calling `choose(id, action)`. `level` is the overall answer, for a colour or icon |

Build the UI against `FakeEngine` (`concierge/fake_engine.py`). It needs no
model and plays scripted flows that produce every event: type anything for a
chat reply, "make an agent" for a helper worked out by talking, in the real
order (a question in words, one with buttons, a try-out, the card, then the
files already there), a helper's name and a colon to ask it, "ask ..." to run
an agent, "translate", "screenshot" or "idea" for an idea card, "error" for an
error. Its made-up helpers are cards: "Korean translator" can be switched on
and off, and "Home papers" works on a made-up Downloads. Switch to the real engine with one line:

```python
from concierge.fake_engine import FakeEngine
from concierge.engine import NoirEngine

engine = FakeEngine()      # while building the UI
engine = NoirEngine()    # real Noir: chat, creating agents, running them
```

The real engine produces the same events as the fake one. Its `Question` ids
are `design` (a question in a helper's designing conversation about no setting
in particular), the settings it asks about with buttons (`looks_at`, `show`,
`keep`, `open`, `skip_language`), `duplicate`, `first_pass`, `all_now`,
`carry_on`, `rule_from_move`, `fix_agent`, `delete_agent`,
`pick_agent_to_delete` and `web`, and where nobody can design `folder`,
`name`, `pick_folder`, `change`, `when`, `instruction` and `idea_change`; the
agent card's id is `card` and the idea card's is `idea`; the UI should not
depend on ids beyond passing them back. To try the
real agent flow, ask Noir to make an agent for `examples/sample_docs`
(made-up contracts, a lease and meeting notes). Agents are saved per user in
`%LOCALAPPDATA%\NoirAgents\agents`.

## Agents are cards

An agent (a helper, to the user) is a card (`concierge/agents/parts.py`): WHEN it works, what
it LOOKS AT, the RULE in plain words, and what it does THEN. The rule alone says what a helper
is for: data, worked out with the user in a conversation and read by the built-in model for
every item. The rest are parts from a catalog code owns, each mechanics only (watch a folder,
move a file so it can be undone, show a bubble). Nothing in code, a prompt, a yaml or a test's
product text may know what one helper is for. Every kind used to be written by hand (a
1,300-line file organizer that knew only college courses), so Noir made only what somebody had
built; the user asked for "a new conversation like we never had this conversation".
`tests/test_old_kinds_gone.py` keeps the old kinds and their words out.

The WHENs (`WHENS`) are `WHILE_ON` (text highlighted with the mouse), `IN_CHAT` (its name, a
colon and the text) and `NEW_FILE` (a file lands in a folder); the THENs (`THENS`) `SHOW` (a
bubble, the clipboard or both), `ANSWER`, `MOVE`, `NOTE` and `DOCUMENTS` (a folder's
documents). `FITS`: WHILE_ON with SHOW, IN_CHAT with ANSWER or DOCUMENTS, NEW_FILE with MOVE
or NOTE. Each part has its `about`, its settings (`Setting`: slot, label, type, the question
when it must be known, how the design model fills it; one with a question and no usual value
is `needed`, the rest get `defaults`) and its `facts`, which the design model may tell the
user, each true to the code that runs the part. The settings: `folder`, `looks_at` (inside the
file or its name), `choices` (folder names), `open` (may it make folders), `into` (where they
are kept), `notes`, `show`, `keep`, `skip_language`, the rule (`instruction`, at most
`MAX_RULE`, none for DOCUMENTS) and `name`; `examples` come only from "put X in Y". The texts
are what is saved in the slots, so changing one orphans the agents saved with it. `card`,
`describe` and `how` write every line the user reads about a card, places by name.

`skip_language` (on WHILE_ON, usually none) is what was a translator's special treatment: text
already in that language, or with no letters, is passed over (`parts.leaves_out`, shared by
the runtime and the try-out). Its choices are the languages code can tell
(`translate.TELLABLE`), and nothing reads a rule for "translate". It is the language the
result comes out in: a helper to show what Japanese sentences mean in English was given
Japanese, its try-out did nothing, and once made it turned English into Japanese (21 Nov
2026).

A highlight card runs in `QuickAgents` (`concierge/quick/`): while on, every mouse highlight
in any program goes through its rule (`recipe.run_instruction`) and the result is shown in a
bubble above the text, copied, or both. Highlights are read through UI Automation, or by
pressing Ctrl+C and restoring the clipboard, never in terminals. By default the bubble stays
until the text is no longer highlighted. Windows only, and only while Noir (or the terminal
app) is running. A chat card ("Grammar Fixer: me and him goes") runs its rule on the rest of
the message with the chat's model, only when named: picked by the router's model for a message
that didn't name it, a helper that turns text into one language was handed a request to turn
some into another. `documents_qa` ("Ask my documents") is the one agent not saved as a card,
its runtime being a search index (`agents/runner.py`).

Agents of earlier versions become cards at startup (`parts.migrate`): the file organizer
NEW_FILE and MOVE with its folders, the summary writer NEW_FILE and NOTE, the old highlight
translator a WHILE_ON card. Their rule is code's guess, so the ones for files come back off:
the chat says so once, with the rule (`_say_changed`), and the chores line says "Off: its rule
needs talking through" (`NEEDS_TALKING`) until it is changed or switched on
(`CHANGED_HELPERS`, `CHANGED_TOLD`). `FolderWatch` takes over the old `organizer*.json` once,
so undo history survives. On a copy of the user's own agents (22 Nov 2026) every check passed.

To let Noir build more kinds, add a part: a WHEN or THEN with its settings and facts, its
place in `FITS`, the code that runs it, and its block in `capabilities.yaml` marked `ready`
and in `blocks` in `custom.yaml`, so the idea planner calls such an idea ready.

## Agent ideas

The idea planner (`concierge/agents/planner.py`) breaks an idea into building blocks from
`concierge/agents/capabilities.yaml`, and code decides the verdict from each block's `ai` need
and `status` plus this computer's hardware (bigger models it may need are the `helpers` in
`models.yaml`). With a model that can design it is not the way in: the designing conversation
says honestly what can't be made and keeps it in the ideas list (`planner.save_idea`). Without
one, the router's ideas go to the planner: make it (all blocks ready), save it ("my ideas"),
change it, or drop it. Saved ideas are kept in `%LOCALAPPDATA%\NoirAgents\ideas.json` and
judged again whenever they are listed.

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
and newest by the box, with its questions' buttons working there too (the watch's, through `noticed`; an
earlier question's go dead once something else is said, `retireChoices`) and an agent card drawn whole (reads, can do, can't do, runs on: it
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

## Working a helper out: the designing conversation

Every request to make or change a helper (the router's `new_agent`, `idea` or `change_agent`,
the planner's Make it, a fix after trouble, a file put somewhere by hand) goes to `Designer`
(`concierge/agents/designer.py`) whenever a model can hold the conversation
(`NoirEngine._new_helper`, `_change`, `_make`). It starts from nothing: what the router made
of the request is dropped and no helper is offered. Standing work on new files, asked for in
words (`router.WATCHES` with `ASKS_TO`, not `ASKS_HOW_IT_IS`), is routed in code: the model
took such a request for chat and offered a web search.

Who designs is the engine's choice at each start (`_design_model`): the plan or key model the
user picked, or the one Auto asks (`talker_form`: note, conversation and schema as one
message, since the plans' apps drop system messages); else the first model on `designers` in
`models.yaml` that is installed and fits beside Noir's own on the graphics card, never on the
processor (`_local_designer`, `local_form`); else nobody. Only a model that passes
`designer_eval` goes on that list, and one picked in the menu doesn't design unless it is
there: in the first probe (10 Nov 2026) qwen3.5:9b switched the agent on with no yes and
qwen3.6:35b-a3b said it would move files nobody had asked about.

Each turn the design model reads a note code builds again (`note_for`): how to talk and
design, the parts, what no helper can do (`NO_HELPER_CAN`), the card so far, what code can see
(`_computer`: how many files of which endings are in the four places, the folders in them by
name, the helpers they have; never a file's name), the last try-out and what was refused. It
fills one form forced by a schema (`schema_for`): what they want, what to change, a WHEN and a
THEN, every setting (a folder is a place from a list plus a name, `field_for`), a text to try,
where things stand (`STILL_ASKING`, `NOTHING_MISSING`, `CALLED_OFF`, `MOVED_ON`,
`CANT_BE_MADE`), what its question asks for, and last its words. A rule is written as the
person would say it, statements about their things and what each kind is not: for 23 made-up
files, 20 right as a model's list of "if" conditions, 22 as plain statements (20 Nov 2026).
Nothing a model reads names a folder, subject or helper as an example: given one, a model
offered it as the user's own, and a smaller one filled it in.

The model talks and proposes; code decides (`_turn`, `_take_form`). A WHEN and a THEN are
taken only when they go together. A folder must exist: looked for everywhere when the place is
wrong, and by the folders it is reached through (`_by_its_steps`); one typed a letter off is
asked about by its real name ("Did you mean Documents\Appliance manuals?", `NEARLY`), never
taken in that turn. The model is told it need never know where a folder is: it asked where a
named one was four turns running. A rule too long or saying how a result is shown goes back
once and is then cut, and a system folder is refused. The name is the model's until there is a
card, then only one the user gave (`NAMES_IT`: "call the folder ..." once named the agent). An
empty value never erases a known one. What the question asks for is not taken from the same
form, nor before a card a place nobody said (a notes file was quietly put in Documents). With
a card up, or a helper being changed, a choice changes only when the turn speaks of it
(`_speaks_of`): told "also leave the pictures alone", a model let the helper make new folders
too (22 Nov 2026). A plain yes changes no known choice. A refused value (`Refused`) goes back
once with the reason; refused twice, code says its own plain line and passes it over unless
the user names it again (`Sketch.ignored`).

With nothing needed missing, nothing refused and nothing asked, the usual values are filled
in, the words said, the try-out run and the card shown (Create it or Save changes, Change
something, Cancel). The first proposal waits for an answer (`Sketch.proposed`), since a card
came under "Which folder should it watch?" for a folder the model had guessed; not when the
first message named every folder (`_said_it_all`), after a plain yes, or for a change. Only
the button, or a whole message that is a plain yes while the card is up and Noir asked nothing
(`CARD_YES`, `AGREES`, `SAVE_YES`), makes anything; "never mind" ends it in code
(`_calls_off`). Code cleans the words: an opening offer, a closing "Shall we begin?"
(`tidy_say`), "Does that look right?" under a card (`CONFIRMS`), talk of a card that won't
come (`CARD_WAITS`); with the card up the model is told so (`CARD_IS_UP`). A plain yes to "a
bubble, the clipboard, or both?" gets "Which one would you like?" once (`WHICH_ONE`): asked
after every yes, a helper was never made (22 Nov 2026). A helper that repeats one they have is
asked about once, in code (`duplicate`).

The try-out is code's (`_try_out`). For new files a local design model leaves memory first and
`FolderWatch.rehearse` runs the card on the newest files in its folder, moving, writing and
recording nothing: "name → folder (read as ...)", "name: stays (why)", or the note. Eight
files took 5.5 seconds with the built-in model to load, 2.6 loaded (20 Nov 2026). After a
change the same files are tried again, each changed one saying what it was. A text helper is
tried on their own text or a sample, called a sample. The model reads its own rule as right,
so code looks at the result: files their message speaks of that come out as before go to the
mender, and code says what is true (`_tried_again`: "still comes out as before", "also comes
out differently"), or that a claimed change wasn't made (`NOT_CHANGED`, `ALREADY_SO`;
`_echoes` for an old change written down again). A text to try, or a question at the card,
leaves the card as it stood: asked "will it touch the stuff thats already in there?", a model
answered well, rewrote the rule too, and three files came out otherwise (22 Nov 2026). A text
try-out plainly in another language puts `skip_language` right (`_comes_out_in`).

Four small forms do jobs the whole form did badly (gemma4:12b). The opening (`OPENING`): a
first message that only names a trouble gets one question about their situation, right for 42
of 45 (20 Nov 2026), where the whole form met "my downloads folder is a mess" with a helper
and a question about folders four times of four. The writer (`WRITE`) writes the draft rule
out once before the card from the conversation alone, taking out what was never said, 3 of 3
(20 Nov 2026); only here, never for a change. The mender (`MEND`) writes the rule again when a
correction didn't take: told to say what a thing is and is not, 8 of 8 files in four rewrites
of four (20 Nov 2026). The aside (`ASIDE`): is the message about something else? 153 of 153
(51 messages, three times each, 22 Nov 2026), where the whole form handed back one aside of
three; the built-in model got 3 of 26 wrong, so only a design model here decides it, and a
plan's says it in the whole form.

Told once, each from a failure: that folders and how a helper decides are the model's to
propose, not to ask of someone who came because they didn't know; that a usual value is not
worth a question; which results go with its WHEN (rough notes were offered a notes file, three
plays of three); that a chat helper is asked by its name and a colon (not "whenever you paste
your notes"). What needs something no part reaches (mail, a website, another program, sending
or buying) is said in its very next words, `CANT_BE_MADE`, and kept in the ideas list: of
fifteen first messages, twice each (20 Nov 2026), every one that can't be made was said so in
one turn, and none that can was refused.

A change to a helper they have is the same conversation (`Designer.edit`), from the saved
card: nothing is saved before Save changes (`EDITING`), and code adds once "X stays as it is
until you press Save changes on the card", as a model wrote "I have updated the helper". A
change only the router's model saw may be handed back on its first turn (`Sketch.unsure`:
"explain why I should update my drivers" shares a word with a rule). A helper deleted
meanwhile is not saved again. Once saved, a helper for files that was off is asked "Switch it
on?", and a renamed one keeps nothing under its old name.

Something else asked in the middle sets the helper aside as it stood (`Designer.aside`), the
engine answers it, and under each answer asks "Carry on with the helper we were working out?"
(`carry_on`), since only the last question's buttons work; Carry on brings back its card and
try-out. Words that sound serious (`safety.crisis`) set it aside too, with no question: left
active, an "ok" would have been a yes to its card.

After "put X in Y", with a model that can design, the engine asks once for that file whether
files like it should always go there (`rule_from_move`); a yes opens `Designer.edit` with what
they did. On 22 made-up files (20 Nov 2026) one example put 3 of 5 like files right, the rule
written again from what they did 4 of 5, and examples that say "leave it" helped nothing, so
only moves become examples.

Trouble ("it's not showing anything", `TROUBLE`, only about a helper: "my wifi isn't working"
is none) gets code's check of the mechanics first (`_diagnose`): highlights where they can't
be read, an old card saved to be asked in the chat, a result copied not shown, switched off,
Ollama out of reach, a highlight it leaves out, nothing highlighted since. If nothing
mechanical is wrong, the report opens `Designer.edit` with code's line on what was checked. A
helper for files is offered Switch it on, or told its record. Code never reads a rule to judge
it.

A plan or key model that designs gets what the user types, folder and helper names and file
counts by ending, never a file's name or contents, as the conversation says when it opens: the
try-out as counts, code's sentences without file names (`_for_turns`: in the one play through
a plan, 22 Nov 2026, one took a file's name to GPT), "a file" for a name in "put X in Y". A
turn through Codex read about 18.7k tokens (22 Nov 2026). What a helper reads and judges never
leaves the computer.

## When nobody can design: the plain way

With no plan or key model and no designer that fits, the plain questions make what they can
(`agents/builder.py`): a documents helper (`create_documents_agent`, which the designer uses
too), and a text helper from the idea planner (`compose`: the built-in model writes the rule,
`recipe.write_recipe`, and words decide the rest in code, `settings_from_words`: "highlight"
means while switched on, "above" or "show" a bubble, "copy" the clipboard). The card shows the
rule before anything is made, which is the check. A text helper is changed setting by setting,
a new job being a rewritten rule (`rewrite_instruction`), which takes `skip_language` off:
kept, "make it Japanese" would go on skipping Korean. A helper for a folder's new files, or an
idea made of such blocks (`FILE_PARTS`), gets `NO_DESIGNER`: that takes a stronger model, a
ChatGPT or Claude plan or a bigger one here.

## The one step the built-in model takes

Every card for files runs one way (`concierge/agents/worker.py`): the built-in model reads the
rule and the beginning of one file (`content_for`, `READ_CHARS`) and fills one small form,
knowing nothing of the conversation; code does the rest. Each note is kept word for word as
measured, the numbers in its comments: changing one means measuring again.

Choosing (`choose`, `CHOOSE_NOTE`) lists the folders by name only, Leave it where it is
(`LEAVE`), Not sure (`UNSURE`) and what the user told it before (`TOLD_BEFORE`); the form is
`what`, then `choice` from those. File names from each folder, tried as a hint, made the 4B
model miss a file it got right from bare names. The last sentence once spoke as the one agent
there used to be ("a bill, a form or a list that only mentions a subject ..."); of five
endings on 24 made-up files, two rules, twice each (20 Nov 2026), "a file that only mentions a
thing is not a file of that thing" got 23 of 24 with a terse rule and 21 with a full one, the
old 21 with both, and every miss was a file moved that should have stayed. When it may make
folders (`open`) the form asks only for a name (`FILE_IT`, `OPEN_PLACES`) and code decides
whether it exists (`parts.same_folder`) or is new (`parts.folder_name`): offered "a new
folder" beside existing ones, a small model always took one that existed. For folders named
after each client, told to use the ones made so far, it put five files, all wrong, into the
first; with no list, twelve went into ten folders; with the list only for spelling, five moved
(25 made-up files, 20 Nov 2026). Still weak, so the designer proposes named folders.

A note (`write_note`) is two small forms: whether the rule asks anything about this file
(`ASK_FIRST`), then the note in its own words, never lines copied out (`WRITE_NOTE`), in a
language code names (`_language`). With one form an English rule gave three of six notes in
Russian and files to leave were written about; with two, 32 of 35 right (20 Nov 2026). A note
that is the rule again, or "None", is no note. A file with nothing readable is left and no
model asked, unless the card goes by names.

## Cards that work on new files: the folder runtime

One machine runs every card whose WHEN is a new file in a folder (`concierge/folderwatch.py`,
`FolderWatch`), on Windows and the Mac: the chores Noir builds. A new one is switched on at
once, with the question whether to go through the files already there (`FIRST_PASS`).

Only what lands after it is switched on counts: what is there then is written down as seen.
What each card has seen, its folders, why each file it left stayed, which were on and `since`
when are kept in `folderwatch_state.json`, read once at start (read at each refresh, it lost
reasons not yet written). A restart changes nothing: a file that landed just before is still
new (once it became old with no record, and "nothing new" was all the user heard), and an
empty record is a record too. The line is drawn again when the folder changes (`switch`,
`refresh`): a changed agent kept the old folder's baseline and filed 28 old downloads ten
seconds after "Only new files from now on", and the first live run, with no line, filed 60.

Each watched folder is looked at every `LOOK_SECONDS` on a thread of its own (one
`os.scandir`). Every file counts but one hidden or Windows' own (`WINDOWS_OWN`,
`SYSTEM_FILES`: a moved desktop.ini renames a folder on screen), a download still arriving
(`UNFINISHED`), a notes file (one was filed with the document it was about) and one kept only
in the cloud (`CLOUD_ONLY`: read, OneDrive fetches it; moved, it leaves the user's other
devices). A file is noticed when first seen (`_noticed`: the circle blinks) and read once its
size and time have stood still for `SETTLE_SECONDS` and nothing holds it open (`_ready`); it
was twenty seconds by the file's own time plus a look every eight, half a minute in which
nothing showed. The model warms meanwhile (`_warm`, once per `WARM_GAP_SECONDS`). One still
growing after `ARRIVING_SECONDS` is a big download, one that can't be opened is in use: the
line says which and the circle rests; after `GIVE_UP_SECONDS` it is left with the reason
(`STILL_CHANGING`, `HELD_OPEN`), or a log some program keeps writing would be "just landed"
for good. A card that writes notes goes before one that moves the file (`_notes_first`), or
the note was never written.

Only a file's beginning is read (`item`, `read_start`): an export.csv of 301 MB took 7.3
seconds and 1.6 GB read whole, and takes 7 milliseconds now (19 Nov 2026). `files.read_pages`
reads text by its bytes (`text_of`), office files from their XML (`office_text`), zips by the
names inside (`archive_listing`), markup without tags. A picture goes to a model that can see
(`seer`: Noir's own when it can, being loaded already, else the vision helper, else any model
with vision), shrunk to `SEE_PIXELS` with `SEE_CONTEXT` of room (a scanned page of 3300 by
2550 was 8,000 tokens against 4,096 and failed silently); a helper is freed when the look ends
(`_release_helper`). `SEE_NOTE` asks for the words in a field of their own: asked only to
describe one, the 4B model named the kind of screenshot and copied nothing; asked for the
words, it copied all 25 lines of six test pictures, half a second each (19 Nov 2026). A
scanned PDF is read through its first page's picture, a program or recording
(`NOTHING_TO_READ`) never opened, and with "Only the file's name" nothing inside is looked at.

One file is in hand at a time, whoever asked (`_work`, a re-entrant lock): the look and a pass
asked for in the chat once took the same file in the same second. A pass lists its files
behind that lock, so the file being read is counted first (else "nothing new has landed" about
it), and ones the look took meanwhile count as `already`. `place`, Undo and forgetting wait
behind it too, and the look checks under it that the card is still on, so one switched off or
deleted takes no file more. A deleted card's state goes with it (`forget`): kept, a new agent
of that name began with the old one's files seen.

Then the worker's form, and code. A move goes under a free name, never deletes or overwrites,
and is logged like Downloads sorting (`tidy.record_moves`, undone with `undo_sort` for
`UNDO_DAYS`). A new folder the rule called for is learned onto the card as saved now, never
the copy in hand (`_learn`: from that copy, a change just made in the chat was written over).
A file already in the chosen folder stays (`ALREADY_THERE`), or it would be renamed at every
look. A note goes at the end of the notes file under "## name · time". A file left keeps why
(`skipped`: "the rule leaves it: <what it was read as>", `NO_TEXT`...), so "why didn't you
move it?" has a true answer. One left because the model couldn't be reached (`NO_MODEL`) is
tried again once Ollama answers (`RETRY_SECONDS`), and at once by a pass: written down as
handled, it never was. A file put back by Undo counts as seen for every card on its folder.

The user must be able to tell it is alive and at what: they downloaded files, saw nothing for
two minutes, and couldn't tell. `status(name)` is one plain line ("x.pdf just landed: reading
it in a moment", "Reading x.pdf now (2 of 5)"), `doing()` the one thing in hand. Each job
keeps its steps (`_note`: "Read it as: ...", "The rule puts it in ...") and is told to the
windows (`moved`, with the record's line in `text`, `stayed`, `working`, `changed`): the
circle blinks and runs its line while anything is in hand (`_in_hand`, worked out from what is
there so it can't drift), and the log by the circle (`move_lines`, `stay_lines`) shows that
line, what was read and decided, and Undo. The windows get `chore_agents` (with `now`,
`since`, `left`, `why_off`), `chore_doing`, `chore_done` and `undo_move`; a chore's line
(`chores._last_line`) is what it does now, else what it did or left last, else "On since 1:10
AM. Nothing new has landed since." Keep Downloads tidy never touches a notes file
(`tidy.notes_files`).

Where Desktop, Documents, Downloads and Pictures really are comes from Windows
(`concierge/places.py`, `known_folder`, SHGetKnownFolderPath): with OneDrive backup on the
Desktop the user sees is `OneDrive/Desktop` (`OneDrive/바탕 화면` on a Korean Windows), and the
first file helper put its folders in `C:/Users/me/Desktop`, which the user never looks at. A
move's record keeps the whole place (`shown_folder`).

Questions about these helpers are answered in code from the card and the records, never by the
chat model, which once said it "couldn't see or move files" right after a move
(`_about_files`), and only when the message is about files or a helper at all
(`_about_the_files`): "where should I go on vacation this summer?" got where the folders are.
Why a file stayed (`WANTS_WHY`) is its kept reason; where it went (`WANTS_WHERE`) the whole
path; what it did (`WANTS_STATUS`) the moves and what stayed. "Go through them" (`WANTS_PASS`,
an order and not a question, which "how do I organize all my recipes?" once was taken for)
takes what landed since it was switched on, or offers Switch it on, since off, every file
counts as new; "go through everything" (`WANTS_EVERYTHING`) counts and asks first (`all_now`);
with nothing new it says what was looked at and why it stayed. "Put x.pdf in Letters"
(`WANTS_PLACE`) moves the file named best, one the card moved included, since people correct
those, and keeps it as an example. "Where did they go?" soon after a job (`FOLLOWS_A_CHORE`)
is about the files, but not by its pronoun alone: "is it going to rain in Seattle tomorrow?"
was answered from the chores. A question about the work (`ABOUT_CHORES`, `HELPER_DOES`) goes
to the chat model with the record in front (`_chores_note`), a plan or key model getting
folders by name and files by kind, for that question only. New work (`ASKS_FOR_WORK`,
`WATCHES`, a place none of them works in, `PLACE_SAID`) is a helper to make: "can you organize
all my desktop files too?" went through Downloads. None of this, nor a message about their own
files (`OWN_THINGS`), goes to the web.

Given up with the hand-written organizer: course codes deciding before the model, run-time
questions about each new kind of file and course folder, folders named by subject. It was one
agent's knowledge in code, and could only sort a student's files. Nothing asks at run time
now: a file the rule doesn't settle stays with its reason, and the user puts it right by
talking or by placing one file.

`python -m concierge.designer_eval` plays it all with the real models: thirteen conversations
through the real engine (`--list`), from a thin request corrected after the try-out to a move
by hand becoming the rule, one in Korean, each a made-up person on a made-up home with its own
data folder. The checks hold whether the design model takes a turn more or fewer: what code
ended up with, what was never done, the fullest form under `ROOM_SHARE` of the room, never
both models in memory. Every word is printed, since several fixes came from reading a play
that passed. On 22 Nov 2026 gemma4:12b passed 175, 174 and 175 of 175 (the miss was the chat
model's own sum), then 177 of 177 after the last fixes, 7.4 to 7.8 seconds a turn. `--plan
codex` plays one through the ChatGPT plan: once, 22 Nov 2026 ("thin", 20 of 20, 14.2 seconds a
turn), before the last fixes.

Known and left: code's lines are English whatever the language; where nobody can design only
documents and text helpers are made; a folder added with + starts a documents helper; the
small model names new folders weakly; the chat model's own side answers; a text helper's rule
sometimes says "leave ... alone" unasked (a note sentence fixed that and broke two other
things, 22 Nov 2026); a chat helper is sometimes offered a notes file. Still weak on 22 Nov:
the mender once wrote against what the user said; the small model sometimes ignores the rule
(a picture moved under "do not move any pictures"); a question about a usual value costs a
turn; "Which one?" is tested only without a model; a new file named like one moved earlier is
never handled, files seen being kept by path.

## What it holds on the graphics card

The user's card has 16 GB and about 2.6 GB of it is the Windows desktop's own. They found the
app holding 15 of the 16. Every figure here was measured with `nvidia-smi` on an RTX 5080,
Ollama's own numbers being unreliable (`python -m concierge measure <tag>`):

| | on the card | to load |
| --- | --- | --- |
| Noir's own model (`noir`, 4B, 4,096 of room) | 3.9 GB | 2.5 s |
| a picture read by its own model | nothing more | — |
| the vision helper `qwen3-vl:8b` at 8,192 | 8.1 GB | 2.5 s |
| the same at 4,096 | 7.4 GB | 2.2 s |
| the design model `gemma4:12b` at 8,192 | 9.2 GB | 5.9 s |

So: its own model leaves the card once nothing has asked it anything for
`noir.IDLE_UNLOAD_SECONDS` (`NoirChat.check_in` simply stops checking in, and Ollama frees it
after `KEEP_ALIVE`; `Ollama.used` notes every call, so a file judged or a Spot job counts as
use just as a chat answer does). It used to stay for as long as the app was open, and the app
sits on the taskbar all day. It is back about three seconds after it is next wanted, and a
file that lands warms it while it settles (`FolderWatch._warm`), so the wait is hidden. A
vision helper is only loaded when its own model can't see, and is freed at the end of that
look rather than five minutes later. The design model and Noir's own are never in memory
together (9.2 + 3.9 + 2.6 would fill the card): Noir's own is unloaded whenever the design
model has to come in, and a local design model leaves before every try-out, which is the
built-in model's work (`DesignModel.done`). In a play of 22 Nov 2026 the whole card showed
10,737 to 11,623 MiB with the design model in, 5,399 to 6,347 with the built-in one, 1,511
before. A local design model reads 8,192 of room (`DESIGN_CONTEXT`): its note alone is about
18,500 characters, and the fullest form of the plays of 22 Nov 2026 held 5,805 tokens. Nothing
here is a guess: when a number changes, measure it again and write what the card said.

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

An agent's page shows what it does and how it's set up, from `parts.describe`
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
asking again for shows up. Agents, the router and forms stay on its model with Auto;
only working a helper out goes to the plan.
Auto asks the plan model picked last (`ModelMenu.auto_target`, `auto_cloud` in the
settings), else a plan's Sonnet, else the first keyed model. `python -m
concierge.auto_eval` checks it with the real model and must stay at 100%.

Only its answers, agents asked in the chat and working a helper out move to the
picked model (`NoirChat.talker`). Deciding what a message is for and filling in forms stay with
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
model involved, and only by its whole name, or by one of its words with nothing
else said: by one word, a request for something that sums up what lands in
Downloads got a helper that answers in the chat. After that it is a card.

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

The window, the chat, agents asked in the chat, the documents agent, helpers for a
folder's new files, web lookups,
research jobs, the Models pages and the plans all run on macOS. What reads other
programs is Windows for now: the Spot, switch-on agents (highlights), its noticing
(Downloads, lectures), the circle, the icon by the clock and the light. Each is
gated in code, never only in the pages' words: `TidyWatch.start` looks at nothing
and `noticing` is False, `BreakSpotter` never spots a break, `NoirEngine.quick`
is None (so `AgentList.switchable` has only helpers for a folder's files, a highlight
helper's switch answers "Windows for now", and the designing conversation offers no
highlight helper, `parts.whens`), `Overlay._ready` makes no Mini, Tray, DoubleTap or EdgePull, and `welcome()["windows"]`
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
can't start is caught before anyone installs it. Over an older version the
program's own files go first (`[InstallDelete]`), and `load_blueprints` passes over
a yaml it doesn't know: two blueprints left behind would have stopped the app. `python packaging/build.py` does it
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
python -m concierge.agents.eval_router   # router accuracy with the real model (47 of 47 on 22 Nov 2026, and 47 of 47 counting only whether a helper is wanted)
python -m concierge.designer_eval        # helpers worked out by talking and then at work: 13 conversations through the real engine with the real models, on made-up homes (every check must pass; 177 of 177 with gemma4:12b on 22 Nov 2026; name a tag to try another model, --only to play some, --list to name them, --plan codex to play one through the ChatGPT plan)
python -m concierge measure <tag>        # what a model really takes on this computer's card, since Ollama's own figure is often wrong
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
| `concierge/catalog.py` | Engine | `CATALOG_PATH`, `GPU_SHARE`, `APPLE_SHARE`, `CPU_SHARE`, `CPU_MAX_GB`, `GPU_HEADROOM_GB`, `RAM_HEADROOM_GB`, `DISK_HEADROOM_GB`, `CPU_HELPER_SHARE`, `ModelEntry`, `HelperModel`, `Recommendation`, `load_catalog`, `load_helpers`, `load_designers`, `helper_room`, `pick_helper`, `find_model`, `memory_budget`, `recommend`; models in `models.yaml` (`models`, `helpers`, `designers`) |
| `concierge/chores.py` | Both | `TIDY`, `AGENT`, `BOOKING`, `MAX_JOBS`, `REPEAT_WORDS`, `ACTION_WORDS`, `listing`, `days`, `day_label`, `ago`, `clock_time` |
| `concierge/quick/drawer.py` | UI | `EDGE_PIXELS`, `OPEN_PIXELS`, `Screen`, `screen_at`, `real_pixels`, `EdgePull` |
| `concierge/places.py` | Both | `KNOWN`, `known_folder` |
| `concierge/folderwatch.py` | Engine | `LOOK_SECONDS`, `SETTLE_SECONDS`, `WARM_GAP_SECONDS`, `ARRIVING_SECONDS`, `GIVE_UP_SECONDS`, `ARRIVING`, `IN_USE`, `STILL_CHANGING`, `HELD_OPEN`, `NOTHING_TO_READ`, `READ_CHARS`, `READ_WHOLE`, `WHOLE_BYTES`, `PIECE_CHARS`, `DONE_KEPT`, `IMAGES`, `MAX_IMAGE_MB`, `SEE_PIXELS`, `SEE_CONTEXT`, `SEE_KEEP_ALIVE`, `SEEN_KEPT`, `SEE_NOTE`, `SEE_SCHEMA`, `NO_TEXT`, `NO_MODEL`, `NO_ANSWER`, `ALREADY_THERE`, `LEFT_BY_RULE`, `NOT_SURE_WHERE`, `NOTHING_ASKED`, `NO_RULE`, `NOTHING_TO_DO`, `NOT_MOVED`, `NOTES_NOT_WRITTEN`, `SKIPPED_KEPT`, `UNFINISHED`, `WINDOWS_OWN`, `RETRY_SECONDS`, `REHEARSE_FILES`, `REHEARSE_OPENED`, `REHEARSE_NOTE_CHARS`, `DECIDED`, `OLD_LOG`, `OLD_DONE`, `OLD_STATE`, `STATE_NAME`, `shrink`, `read_start`, `shown_folder`, `FolderWatch` (`is_on`, `switch`, `forget`, `refresh`, `stop`, `look`, `status`, `doing`, `files`, `new_files`, `count_files`, `run_once`, `place`, `item`, `rehearse`, `seer`, `done_lately`, `last_moves`, `last_skipped`, `undo`; `active`, `made`, `skipped`, `since`, `vision`; told to the windows: `changed`, `moved`, `working`, `stayed`) |
| `concierge/designer_eval.py` | Engine | `ASK_FOR_PLACES`, the made-up homes (`SHOP`, `SHOP_WANTS`, `SHOP_SAYS`, `SHOP_ALSO`, `SHOP_WANTS_TWO`, `SHOP_SAYS_TWO`, `SHOP_LATER`, `HOUSE`, `HOUSE_PAPERS`, `HOUSE_PAPERS_LATER`, `MANUALS`, `KOREAN_HOME`, `KOREAN_WANTS`, `HOBBY_DOWNLOADS`, `HOBBY_PICTURES`), `SAYS_DONE`, `ABOUT_LATER`, `SAYS_STAYS`, `SAYS_CANNOT`, `HANGUL`, `AGREE`, `AGREE_KO`, `LANDS_SECONDS`, `ROOM_SHARE`, `claims_done`, `folder_like`, `as_wanted`, `first_wrong`, `card_in`, `question_in`, `result_in`, `ends_asking`, `words_in`, `card_memory`, `pdf`, `scan`, `write_pdf`, `sheet`, `slides`, `picture`, `photo`, `packed`, `word`, `drop`, `aged`, `Home`, `Run`, `Counted`, `NoWatcher`, `Bubbles`, `RealHome`, `Talk`, `shop_home`, `house_home`, `korean_home`, `hobby_home`, `mover`, the conversations (`thin`, `notes`, `highlight`, `chat`, `documents`, `cannot`, `korean`, `at_once`, `called_off`, `aside`, `change`, `by_hand`, `trouble`), `CONVERSATIONS`, `Plan`, `Play` (`check`, `check_whole`), `main`; command `python -m concierge.designer_eval [tag] [--only name ...] [--plan codex] [--keep] [--forms] [--list]` |
| `concierge/activity.py` | Engine | `ANSWERED`, `EXPLAINED`, `TRANSLATED`, `POLISHED`, `SUMMED_UP`, `HELPED`, `SORTED`, `READ`, `KEPT_DAYS`, `WEEK_DAYS`, `record`, `this_week` |
| `concierge/voice.py` | Engine | `BUDGETS`, `KIND_WORDS`, `SHORTER_SHARE`, `STYLE`, `SMALL_TALK_STYLE`, `POINTS`, `NO_POINTS`, `EXPLAIN_SHAPE`, `EXTRA`, `MATH_STYLE`, `SCIENCE_STYLE`, `DRAWING`, `DRAW_WORDS`, `OPENER`, `QUOTE`, `BOLD_BULLET`, `RULE_ECHO`, `ECHO_START`, `HEADING`, `RULE`, `TABLE_ROW`, `TABLE_LINE`, `SAFE_START`, `FIRST_SENTENCE`, `kind_of`, `guide`, `tidy` |
| `concierge/pictures.py` | Engine | `API`, `USER_AGENT`, `TIMEOUT`, `MAX_PICTURES`, `MAX_LOOKUPS`, `PICTURE_PIXELS`, `NO_PICTURES`, `BOLD`, `PART`, `BETWEEN`, `PLACE_WORDS`, `names_in`, `same_place`, `place`, `worth_asking`, `for_answer` |
| `concierge/safety.py` | Engine | `CRISIS`, `HEALTH`, `MONEY`, `CRISIS_REPLY`, `CRISIS_REPLY_KO`, `HEALTH_NOTE`, `MONEY_NOTE`, `crisis`, `crisis_reply`, `caution` |
| `concierge/noir.py` | Engine | `NOIR_MODEL`, `PERSONA_PATH`, `NUM_CTX`, `HISTORY_CHARS`, `MAX_THOUGHT_CHARS`, `UNLOAD_ON_EXIT`, `KEEP_ALIVE`, `HEARTBEAT_SECONDS`, `IDLE_UNLOAD_SECONDS`, `CLOSING_FILLER`, `ANSWERED_SENTENCES`, `without_closing_filler`, `system_prompt`, `configure`, `needs_configure`, `NoirChat` (`kind`, `draws`, `jobs`), `data_dir`, `load_state`, `save_state` |
| `concierge/ollama.py` | Engine | `DEFAULT_URL`, `DOWNLOAD_PAGE`, `UNREACHABLE`, `OllamaError`, `Ollama` (`last_tokens`: read and written by the last chat; `used`: when each model was last asked something, for `NoirChat.check_in`; `find_program`, `start` for the first run) |
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
| `concierge/engine.py` | Engine | `WANTS_DELETE`, `HELPER_WORDS`, `SWITCH_WORDS`, `WANTS_IDEAS`, `WANTS_WHERE`, `WANTS_STATUS`, `STATUS_ALONE`, `WANTS_PASS`, `ASKS_HOW`, `PRONOUN_OBJECT`, `WANTS_WHY`, `WHERE_WORDS`, `ABOUT_CHORES`, `FOLLOWS_A_CHORE`, `FOLLOW_UP_ASKS`, `CHORE_FRESH_SECONDS`, `FILE_WORDS`, `YOU_HANDLED`, `HELPER_DOES`, `PLACE_SAID`, `ASKS_FOR_WORK`, `OWN_THINGS`, `WANTS_ANSWER`, `NO_WORDS`, `WANTS_PLACE`, `WANTS_EVERYTHING`, `WANTS_ON`, `WANTS_OFF`, `TROUBLE`, `DELETE_AGENT`, `PICK_AGENT_TO_DELETE`, `FIX_AGENT`, `FIX_IT`, `LEAVE_IT`, `SWITCH_IT_ON`, `DELETE_IT`, `KEEP_IT`, `SPOT_KINDS`, `MEASURED_JOBS`, `FOLLOW_UPS`, `FIRST_PASS`, `GO_THROUGH`, `ONLY_NEW`, `ALL_NOW`, `LEAVE_THEM`, `CARRY_ON`, `CARRY_ON_YES`, `DROP_IT`, `RULE_FROM_MOVE`, `CHANGE_THE_RULE`, `JUST_THIS_ONE`, `FILE_PARTS`, `CHANGED_HELPERS`, `CHANGED_TOLD`, `NEEDS_TALKING`, `NoirEngine` (adds `follow_up`, `follow_up_words`, `after_answer`, `pictures`, and `pending_lookup`, `found` for the web; `folderwatch`, `designer`, `builder`, `planner`, and for its own questions `going_through`, `all_asked`, `carry_asked`, `ruling`, `rule_asked`, `rule_refused`, `changed_off`, `changed_over`; outside the contract: `ask_again` for Auto, `setup_state` and `setup_begin` for the first run, `details`, `chore_agents`, `chore_done`, `chore_doing` and `undo_move` for the chores lists; `designs`: whether a helper may be worked out with a model) |
| `concierge/setup.py` | Engine | `OLLAMA`, `MODEL`, `NOIR`, `INSTALLERS`, `SILENT_INSTALL`, `DOWNLOAD_TIMEOUT`, `INSTALL_SECONDS`, `START_SECONDS`, `QUICK_START_SECONDS`, `CHUNK`, `MAC_OPEN`, `SetupError`, `Setup` |
| `concierge/fake_engine.py` | Engine | `FakeEngine` (the engine's `chore_agents`, `chore_done`, `chore_doing` and `undo_move`, over made-up `helpers`), `PracticeOllama`, `PracticeKeys`, `PracticeAccounts`, `PracticeSetup`, `practice_models` |
| `concierge/cli.py` | Engine | `DIM`, `PLAIN`, `main`, `cmd_hardware`, `cmd_recommend`, `cmd_setup`, `cmd_chat`, `cmd_measure`, `cmd_history`, `TerminalScreen`; command `python -m concierge [hardware, recommend, setup, chat, measure, history]`; in the chat `/think` turns thinking on or off |
| `concierge/agents/blueprint.py` | Engine | `BLUEPRINT_DIR`, `Slot`, `Blueprint`, `load_blueprints` (passes over a yaml it doesn't know); templates in `agents/blueprints/*.yaml` (`documents_qa`, and `custom`: what the plain way needs for a card) |
| `concierge/agents/parts.py` | Engine | `CUSTOM`, `WHILE_ON`, `IN_CHAT`, `SAMPLE_TEXT`, `SAMPLE_QUESTION`, `NEW_FILE`, `SHOW`, `ANSWER`, `MOVE`, `NOTE`, `DOCUMENTS`, `INSIDE_FILE`, `NAME_ONLY`, `OPEN_NO`, `OPEN_YES`, `WRITE`, `CHOOSE`, `SEARCH`, `MAX_RULE`, `MAX_CHOICES`, `MAX_EXAMPLES`, `MAX_FOLDER_NAME`, `DOCUMENTS_QA`, `PLACE_NAMES`, `INSIDE`, `NONE`, `SAMPLE_FILES`, `STOPWORDS`, `Setting`, `Part`, `RULE`, `NAME`, `WHENS`, `THENS`, `FITS`, `whens`, `then_of`, `fits`, `settings_for`, `all_settings`, `needed`, `missing`, `defaults`, `mode`, `watches`, `is_switchable`, `choices_of`, `as_given`, `same_name`, `folder_name`, `words_of`, `same_folder`, `skip_language`, `leaves_out`, `destination`, `notes_path`, `short_place`, `shown_place`, `card`, `describe`, `how`, `migrate`; a card's slots `when`, `then`, `instruction`, `folder`, `looks_at`, `choices`, `open`, `into`, `notes`, `show`, `keep`, `skip_language`, `name` |
| `concierge/agents/worker.py` | Engine | `LEAVE`, `UNSURE`, `FILE_IT`, `READ_CHARS`, `MAX_WHAT`, `MAX_NOTE`, `CHOOSE_NOTE`, `OPEN_PLACES`, `NONE_YET`, `OPEN_FOLDER`, `TOLD_BEFORE`, `ASK_FIRST`, `WRITE_IT`, `NOTHING`, `ASK_SCHEMA`, `WRITE_NOTE`, `WRITE_SCHEMA`, `THE_RULES_OWN`, `RULE_AGAIN`, `RULE_AGAIN_WORDS`, `OWN_WORDS`, `NO_NOTE`, `HEADING`, `Item`, `Outcome`, `Ask`, `choose`, `write_note`, `content_for` |
| `concierge/agents/designer.py` | Engine | `STILL_ASKING`, `NOTHING_MISSING`, `CALLED_OFF`, `MOVED_ON`, `CANT_BE_MADE`, `DESIGN`, `NOT_CLEAR`, `NONE_FIT`, `TOLD`, `NOT_TOLD`, `DESIGN_CONTEXT`, `DESIGN_TEMPERATURE`, `DESIGN_KEEP_ALIVE`, `REHEARSE_FILES`, `MAX_TURNS`, `MAX_SAY`, `MAX_WANTS`, `MAX_SAMPLE`, `NOTE_SHOWN`, `SAME_OUTCOME`, `MAX_NAME`, `NEARLY`, `MAX_LOOKED`, `MAX_FOLDERS_TOLD`, `TRY_OUT`, `NOT_KNOWN`, `A_PATH`, `SYSTEM_FOLDER`, `NO_DESIGNER`, `WHEN`, `THEN`, `NAMES_IT`, `NAMES_A_THING`, `SAVE_YES`, `AGREES`, `STANDS_ALONE`, `QUOTED_NAME`, `AND_WORD`, `VOICE`, `HOW_TO_DESIGN`, `OPENING`, `OPENING_SCHEMA`, `PART_OF_THIS`, `SOMETHING_ELSE`, `ASIDE`, `ASIDE_SCHEMA`, `ASIDE_ASKS`, `MEND`, `MEND_SCHEMA`, `WRITE`, `NO_HELPER_CAN`, `EDITING`, `FORM_NOTE`, `CARD_COMES`, `CARD_SAVES`, `CARD_IS_UP`, `CARD_WAITS`, `POINTS_AT_CARD`, `MORE_STATUS`, `OPENING_OFFER`, `CLOSING_NUDGE`, `MORE_HELP`, `CONFIRMS`, `SECOND_QUESTION`, `NO_CHANGE`, `NOT_CHANGED`, `ALREADY_SO`, `CLAIMS_CHANGE`, `PLAIN_WORDS`, `OFFERS_MORE`, `WHICH_ONE`, `ECHOED`, `ECHOED_LOOSELY`, `SHOWN_HOW`, `JSON_ONLY`, `Form`, `DesignerError`, `DesignModel` (`fill`, `waking`, `done`), `local_form`, `talker_form`, `read_form`, `tidy_say`, `field_for`, `schema_for`, `note_for`, `names_in`, `row_line`, `Refused`, `Sketch`, `Designer` (`active`, `available`, `start`, `edit`, `answer`, `choose`, `set_aside`, `carry_on`, `drop`, `take_created`; `handoff`, `aside`, `created`, `edited`, `replaced`) |
| `concierge/quick/agents.py` | Engine | `BUBBLE`, `CLIPBOARD`, `BOTH`, `UNTIL_UNHIGHLIGHT`, `FEW_SECONDS`, `CHECK_SECONDS`, `CHECK_FOR_SECONDS`, `ANSWERED`, `LEFT_OUT`, `NO_MODEL`, `NOTHING_BACK`, `QuickAgents` (`last`: what came of each card's last highlight) |
| `concierge/quick/bubble.py` | Engine | `GAP`, `MAX_WIDTH`, `COLORS`, `GWL_EXSTYLE`, `WS_EX_NOACTIVATE`, `WS_EX_TOOLWINDOW`, `WS_EX_TOPMOST`, `show_seconds`, `Bubble` |
| `concierge/quick/selection.py` | Engine | `DRAG_PIXELS`, `DOUBLE_CLICK_SECONDS`, `MIN_CHARS`, `MAX_CHARS`, `NO_COPY_APPS`, `Rect`, `CF_UNICODETEXT`, `foreground_app`, `SelectionWatcher`, `read_selection`, `highlighted_text`, `save_clipboard`, `restore_clipboard`, `set_clipboard_text` |
| `concierge/quick/glow.py` | Engine | `LILAC`, `GREEN`, `THICKNESS_SHARE`, `RIM_SHARE`, `BRIGHTEST`, `RUN_SECONDS`, `HOLD_SECONDS`, `FADE_SECONDS`, `FRAME_SECONDS`, `LINE_SHARE`, `LINE_BREATH_SECONDS`, `WS_POPUP`, `LIGHT_STYLE`, `light_at`, `pixel`, `reached`, `eased`, `full_screen_in_use`, `work_screen`, `real_pixels`, `Layer`, `pump`, `Glow` |
| `concierge/quick/note.py` | Engine | `COLORS`, `CIRCLE_ROOM`, `BOTTOM_GAP`, `SHOW_SECONDS`, `LOG_SECONDS`, `WRAP_PIXELS`, `CHECK_MS`, `ARRIVE_STEPS`, `ARRIVE_MS`, `ARRIVE_PIXELS`, `SOLID`, `ask`, `tell` |
| `concierge/quick/watching.py` | Engine | `LECTURE_WORDS`, `VIDEO_SITES`, `BROWSERS`, `PLAYERS`, `looks_like_lecture`, `lecture_on_screen` |
| `concierge/quick/tidy.py` | Engine | `MIN_FILES`, `SETTLE_SECONDS`, `FIRST_LOOK_SECONDS`, `LOOK_SECONDS`, `SNOOZE_DAYS`, `IGNORED_DAYS`, `BREAK_SECONDS`, `TYPING_GAP_SECONDS`, `MIN_JOB_SECONDS`, `PRACTICE_FIRST_LOOK_SECONDS`, `PRACTICE_JOB_SECONDS`, `VIDEO_LOOK_SECONDS`, `PRACTICE_VIDEO_SECONDS`, `QUESTION_GAP_SECONDS`, `PRACTICE_QUESTION_GAP_SECONDS`, `UNDO_DAYS`, `LECTURE_NOTES_BUILT`, `CLOUD_ONLY`, `YES`, `NOT_NOW`, `SORT`, `VIDEO`, `VIDEO_QUESTION`, `NO_VIDEO_SUMMARY`, `PRACTICE_LECTURE`, `DONE_KEPT`, `SHELVES`, `OTHER_SHELF`, `UNFINISHED`, `SYSTEM_FILES`, `downloads_dir`, `log_path`, `shelf_for`, `notes_files`, `loose_files`, `free_name`, `sort_plan`, `sort_folder`, `record_moves`, `sorts_on_record`, `last_sort`, `moved_to`, `can_undo`, `undo_sort`, `BreakSpotter`, `TidyWatch` (`leave`) |
| `concierge/quick/spot.py` | Engine | `DOUBLE_TAP_SECONDS`, `TAP_SECONDS`, `MAX_SPOT_CHARS`, `MAX_HELPERS`, `SUM_UP_CHARS`, `SHORTEN_CHARS`, `WRITING`, `READING`, `ERROR`, `CODE`, `NOTHING`, `ERROR_WORDS`, `CODE_SIGNS`, `WRITE_FOR_ME`, `ACTIONS`, `home_language`, `kind_of`, `actions_for`, `job`, `caret_box`, `selection_editable`, `DoubleTap` |
| `concierge/quick/translate.py` | Engine | `LANGUAGES`, `TELLABLE`, `language_in`, `looks_like` |
| `concierge/agents/builder.py` | Engine | `PLACES`, `CANCEL_WORDS`, `YES_WORDS`, `BLOCKED`, `SKIP_WHILE_SEARCHING`, `CARD`, `CHANGE`, `PICK_FOLDER`, `DUPLICATE`, `REPLACE`, `MAKE_ANOTHER`, `CREATE_IT`, `SAVE_CHANGES`, `RENAME`, `CARD_YES`, `MAX_COUNTED`, `Draft`, `AgentBuilder` (`start`, `start_for_folder`, `compose`, `edit`, `answer`, `choose`, `take_created`; `created`, `edited`, `replaced`), `say`, `place_dirs`, `find_folders`, `agent_for_folder`, `is_blocked`, `describe_files`, `files_in`, `create_documents_agent` |
| `concierge/agents/planner.py` | Engine | `BLOCKS_PATH`, `OTHER`, `MAX_STEPS`, `IDEA`, `IDEA_CHANGE`, `KEY_COMBO`, `ASKED_FOR_KEY`, `settle_triggers`, `MAKE_IT`, `SAVE_IDEA`, `CHANGE_IDEA`, `DROP_IDEA`, `HELPER_ROLES`, `ROLE_WORDS`, `Block`, `PlanStep`, `Assessment`, `IdeaDraft`, `IdeaPlanner`, `load_blocks`, `assess`, `clean_detail`, `ideas_path`, `list_ideas`, `save_idea`, `describe_ideas`; building blocks in `agents/capabilities.yaml` |
| `concierge/agents/recipe.py` | Engine | `CUSTOM`, `WHILE_ON`, `IN_CHAT`, `SAMPLE_TEXT`, `SAMPLE_QUESTION`, `describe` and `is_switchable` (passed on from parts), `MAX_INSTRUCTION`, `HIGHLIGHT_WORDS`, `CHAT_WORDS`, `SHOW_WORDS`, `COPY_WORDS`, `STAY_WORDS`, `SHORT_WORDS`, `MECHANICS`, `run_instruction`, `settings_from_words`, `write_recipe`, `rewrite_instruction`, `migrate` |
| `concierge/agents/files.py` | Engine | `TEXT_TYPES`, `SUPPORTED`, `OFFICE_PARTS`, `ARCHIVES`, `MARKUP`, `TEXT_SAMPLE`, `OFFICE_CHARS`, `MAX_LISTED`, `text_of`, `without_tags`, `office_text`, `archive_listing`, `MAX_FILES`, `MAX_FILE_MB`, `PASSAGE_CHARS`, `PASSAGE_OVERLAP`, `Passage`, `ScanResult`, `scan`, `read_pages`, `split`, `passages_of`, `tokens`, `SearchIndex`, `folder_signature` |
| `concierge/agents/router.py` | Engine | `IDEA_OPTION`, `WANTS_CHANGE`, `WANTS_NEW`, `WATCHES`, `ASKS_HOW_IT_IS`, `ASKS_TO`, `Route`, `route`, `wants_change`, `refers_to`, `names_an_agent`; test cases in `agents/router_cases.yaml` |
| `concierge/agents/community.py` | Engine | `REPOSITORY`, `INDEX_PATH`, `INDEX_URL`, `POST_URL`, `TIMEOUT`, `CACHE_SECONDS`, `MAX_NAME`, `MAX_ABOUT`, `MAX_BY`, `READY_MADE`, `COMMUNITY`, `CATEGORIES`, `OTHER_CATEGORY`, `PostError`, `Recipe` (`skip_language`), `clean`, `recipes`, `find`, `install`, `can_post`, `post_address`; shared agents in `agents/community.json` |
| `concierge/agents/starters.py` | Engine | `STARTERS_PATH`, `WANTS_ADD`, `MAX_WORDS`, `Starter` (`about`, `category`, `skip_language`), `load_starters`, `asks_for`, `install`; recipes in `agents/starters.yaml` |
| `concierge/agents/runner.py` | Engine | `TOP_PASSAGES`, `MAX_CONTENTS`, `STOPWORDS`, `run`, `matching_words`, `clean_answer`, `refresh_index`, `best_sentence` |
| `concierge/agents/store.py` | Engine | `Agent`, `agents_dir`, `slugify`, `list_agents`, `find_agent`, `name_taken`, `save`, `load_index`, `delete` |
| `concierge/agents/eval_router.py` | Engine | `CASES`, `MAKES`, `main`; command `python -m concierge.agents.eval_router` |
| `concierge/ui/window.py` | UI | `WEB_DIR`, `TITLE`, `UNEXPECTED_ERROR`, `EDGE_GAP`, `DRAWER_WIDTH`, `DRAWER_GAP`, `MOVE_NOTE_SECONDS`, `STAY_NOTE_SECONDS`, `DRAWER_HEIGHT_SHARE`, `DRAWER_MAX_HEIGHT`, `DRAWER_MIN_HEIGHT`, `DRAWER_SLIDE_STEPS`, `DRAWER_SLIDE_SECONDS`, `DRAWER_FOG`, `DRAWER_LOAD_SECONDS`, `FULL_SHARE`, `FULL_MIN_SIZE`, `SCREEN_SETTLE_SECONDS`, `PICTURES`, `EXPORTS`, `EXPORT_WAIT_HOURS`, `EXPORT_CHECK_SECONDS`, `APP_ID`, `ONE_COPY`, `SPOT_WIDTH`, `SPOT_START_HEIGHT`, `SPOT_MIN_HEIGHT`, `SPOT_GAP`, `SPOT_SETTLE_SECONDS`, `PASTE_SETTLE_SECONDS`, `REMEMBERED`, `Area`, `ChatHub` (adds `restart` after the first run's setup, `latest` for the last list of a kind, `on_chores`, `on_move`, `on_working`, `on_stayed`, which attach to `engine.folderwatch`), `ChatBridge` (a page calls its `startup`, `send`, `choose`, `ask_again`, `new_chat`, `open_chat`, `delete_chat`, `delete_agent`, `toggle_agent`, `reset`), `WatchBridge` (adds `today`, `chores`, `answer`, `undo_sorting`, `set_noticing`, `activity`, `privacy`, `set_web`, `set_search_key`, `open_link`), `TodayBridge` (adds `agent_details`, `quit_app`, `welcome`, `set_welcomed`, `setup_state`, `setup_begin`, `setup_finish`, `measure`, `set_spot`, `switch_agent`, `bring_in_history`, `understand_history`, `what_i_know`, `keep_fact`, `forget_history`, `open_export_page`, `look_around`, `find_downloads`, `send_files`, `pick_files`, `pick_images`, `pick_folder`, `screenshot`, `paste_text`, `follow_up`, `after_answer`, `pictures`, `models`, `pick_model`, `save_key`, `forget_key`, `more_models`, `open_key_page`, `sign_in_account`, `install_account`, `check_accounts`, `use_account`, `usage`, `hide_model`, `add_custom_model`, `remove_custom_model`, `delete_model`, `browse_models`, `get_model`, `cancel_download`, `downloads`, `recipes`, `add_recipe`, `post_agent`, `pinned_chats`, `pin_chat`, `search_chats`, `reservations`, `add_reservation`, `remove_reservation`, `switch_reservation`), `GlassBridge` (adds `open_app`, `hide_drawer`), `SpotBridge` (`run`, `put_back`, `fit`, `close`), `Overlay` (the drawer: `toggle_drawer`, `hide_drawer`, `pull_drawer`, `release_drawer`; `refresh_mini`), `move_lines`, `stay_lines`, `pasted_file`, `full_size`, `centered`, `drawer_bounds`, `drawer_x`, `place_spot`, `work_area`, `first_copy`, `bring_forward`, `main`; command `python -m concierge.ui [--fake] [--debug] [--setup] [--version] [--check]` |
| `concierge/ui/mini.py` | UI | `MINI_SIZE`, `EDGE_GAP`, `DISC_SHARE`, `FRAMES`, `FRAME_SECONDS`, `RESTING`, `BRIGHT`, `FADE_STEP`, `FULL_SCREEN_CHECK_SECONDS`, `IDLE`, `WORKING`, `ASKING`, `BLINK_SECONDS`, `BLINK_DIM`, `LILAC`, `WHITE`, `is_click`, `premultiplied`, `draw_frames`, `Mini` (`blink`) |
| `concierge/ui/tray.py` | UI | `ICON_SIZE`, `INK`, `DOTS`, `tray_picture`, `Tray` |
| `concierge/ui/web/` | UI | `today.html`, `today.css`, `today.js` (full window, global `today.refresh()`, `today.show`, `today.closeMenus`, `today.redraw`, `today.spotTried`, `today.chatsArrived`, `today.ui`), `help.js` (global `helpPage`: Help me and Who are you), `about.js` (global `aboutPage`: About you and the first two minutes), `setup.js` (global `setupPage`: the first run's setup page), `chores.js` (global `choresPage`: the Chores page), `room.js` (global `roomPage`: What I see and Reservations), `discover.js` (global `discover`: the Agents page and parts it shares), `models.js` (global `modelPage`: the model menu and the Models page; `modelPage.loadUsage` and `modelPage.openUsage` for the usage meter), `spot.html`, `spot.css`, `spot.js` (the Spot, global `spot.open`), `glass.html`, `glass.css`, `glass.js` (the drawer, with its own `app.onEvent`, `app.mirror`, `app.shown`, `app.refresh`), `fonts/`, `vendor/` (KaTeX and highlight.js, for maths and code offline), `style.css`, `app.js`; JavaScript globals `app.onEvent(event)`, `app.mirror(state)`, `app.shown()` (called by `ChatHub` and `Overlay`), `app.say`, `app.prefill`, `app.toggleAgent`, `app.deleteAgent`, `app.openChat`, `app.deleteChat`, `app.attach`, `app.setModelName` and `app.addRecipe` (called by today.js, discover.js and models.js); window event `engine-event` |
