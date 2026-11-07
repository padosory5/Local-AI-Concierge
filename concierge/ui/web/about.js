// Getting to know the user: About you in Noir's room, and the first two minutes
// (view-welcome), which share what it found out (portrait.py through TodayBridge).
// Everything here only draws what Python says; the facts, the hours and the roles
// are worked out there.

window.aboutPage = (() => {
  const $ = (id) => document.getElementById(id);
  const { el, button, show, whenWas, LOCALE, state } = today.ui;
  const { TOPICS, ROLES, isOn, setOn, applyRole } = helpPage;

  // How to download your chats from each company, in their own words.
  const EXPORT_STEPS = {
    ChatGPT: [["Open ", "Settings"], ["", "Data controls", ", then ", "Export data"]],
    Claude: [["Open ", "Settings"], ["", "Privacy", ", then ", "Export data"]],
  };
  // What it offers for each kind of help someone asked other AIs for most:
  // [words in bold, the rest]. Kinds not here get no offer.
  const OFFERS = {
    writing: ["I can do this right where you write:", " highlight it and tap Ctrl twice."],
    coding: ["Highlight an error or some code", " and tap Ctrl twice: I explain it."],
    explaining: ["Highlight anything you're reading,", " and I explain it in simple words."],
    studying: ["Highlight anything you're reading,", " and I explain it in simple words."],
    translating: ["A bubble shows the translation", " as you highlight."],
    summarizing: ["I sum things up", " in three short points."],
    documents: ["Ask me about a folder of your files,", " and I show where each answer is."],
    planning: ["Tell me an idea,", " and I'll say honestly whether I can make it."],
  };
  const ROLE_NAMES = { developer: "a developer", student: "a student", office: "an office worker" };
  // What people do most on their computer (signs.activities), beside what it can do about it.
  const DOING = {
    ai: ["AI tools", "I'm an AI too, right here:", " free, private and with no limits.", "chat"],
    browsing: ["Browsing the web", "Highlight anything you read on a page,", " and a bubble explains it.", "explain"],
    coding: ["Writing code", "Highlight an error or some code", " and tap Ctrl twice: I explain it.", "spot"],
    chatting: ["Chatting", "Polish or translate a message before you send it:", " tap Ctrl twice.", "spot"],
    documents: ["Documents", "Ask me about a folder of your files,", " and I show where each answer is.", "files"],
    design: ["Design", "", "", ""],
    music: ["Music", "", "", ""],
    video: ["Videos", "I stay out of the way", " while you watch.", ""],
    games: ["Games", "I step out of the way", " while you play.", ""],
  };

  let knowing = null; // what it understood about the user, once asked
  let reading = ""; // what it's doing right now, said while it does it
  let readProblem = "";
  let arrived = ""; // chats it picked up from Downloads by itself
  let forgetting = false; // "Forget all of this" was clicked once

  function exportCards() {
    return el("div", "export-cards", ...Object.entries(EXPORT_STEPS).map(([source, lines]) =>
      el("div", "export-card", el("h3", "", source),
         el("ol", "", ...lines.map((parts) => el("li", "", ...parts.map((part, n) => (n % 2 ? el("b", "", part) : part)))),
            el("li", "", "Click the links in the email")),
         button("line-button", `Open ${source}'s settings`, () => pywebview.api.open_export_page(source)))));
  }

  function promises() {
    return el("div", "promise-list", ...["Read on this computer", "Only your own messages are kept",
      "Never sent to any AI company", "Forget it all any time"].map((words) => el("span", "", words)));
  }

  function readingNow() {
    return [el("p", "sub", reading), el("div", "dots-track", el("div", "working-dots"))];
  }

  // The roles this computer clearly points to, strongest first (signs.role_words).
  function looksLike(made) {
    const roles = (made.computer && made.computer.roles) || {};
    return Object.entries(roles).filter(([role, score]) => score >= 2 && ROLE_NAMES[role])
      .sort((a, b) => b[1] - a[1]).slice(0, 2).map(([role]) => role);
  }

  function knows(made) {
    return Boolean(made && (made.made || made.computer));
  }

  // One way of bringing chats in, then working out what it can. `fetch` gets them,
  // `waiting` is said meanwhile ("" when a file picker is showing), `after` redraws.
  async function readChats(after, waiting, fetch) {
    readProblem = "";
    arrived = "";
    reading = waiting;
    if (waiting) after();
    const brought = (await fetch()) || {};
    if (brought.cancelled || brought.error) {
      reading = "";
      readProblem = brought.error || "";
      after();
      return;
    }
    reading = `Read ${brought.read} chat${brought.read === 1 ? "" : "s"} from ${brought.sources.join(" and ")}. Now working out what you ask for most, and what you've said about yourself...`;
    after();
    const made = (await pywebview.api.understand_history()) || {};
    reading = "";
    if (made.error) readProblem = made.error;
    else knowing = made;
    after();
  }

  async function lookAround(after) {
    readProblem = "";
    reading = "Looking around this computer: the apps you have and the kinds of files you keep...";
    after();
    const made = (await pywebview.api.look_around()) || {};
    reading = "";
    if (made.error) readProblem = made.error;
    else knowing = made;
    after();
  }

  // Called from Python when chats it was waiting for landed in Downloads and were read.
  function chatsArrived(found) {
    arrived = found.error || `Your ${found.sources.join(" and ")} chats arrived, and I read ${found.read} of them.`;
    if (state().view === "about") drawAbout();
  }

  function knownSentence(made) {
    const total = Object.values(made.chats || {}).reduce((sum, count) => sum + count, 0);
    const since = made.first ? new Date(made.first * 1000).toLocaleDateString(LOCALE, { month: "long", year: "numeric" }) : "";
    const language = Object.keys(made.languages || {})[0];
    const tail = [since && ` since ${since}`, made.busiest && `, mostly ${made.busiest}`,
                  language && language !== "Other" && `, mostly in ${language}`].filter(Boolean).join("");
    return el("h1", "known-sentence", "You've had ", el("em", "", `${total} chat${total === 1 ? "" : "s"}`),
              ` with ${Object.keys(made.chats || {}).join(" and ")}${tail}.`);
  }

  function rolesSentence(made) {
    const roles = looksLike(made);
    if (!roles.length) return null;
    return el("h1", "known-sentence", "From this computer, you look like ",
              el("em", "", roles.map((role) => ROLE_NAMES[role]).join(" and ")), ".");
  }

  function topKinds(made, count) {
    return (made.kinds || []).filter((kind) => !["other", "personal"].includes(kind.id)).slice(0, count);
  }

  // What it can do about something, right there: a switch for a Help me line, Ask
  // for a line that's a request, Ask me something for the chat, or nothing.
  function actionFor(topicId) {
    if (topicId === "chat") return button("line-button", "Ask me something", () => show("chat"));
    const topic = TOPICS.find((one) => one.id === topicId);
    if (topic && ["agent", "spot", "notice"].includes(topic.kind) && !state().windows) {
      return el("span", "kept", "Windows for now");
    }
    if (topic && ["agent", "spot", "notice", "add"].includes(topic.kind)) {
      return isOn(topic) ? el("span", "kept", "On")
        : button("line-button", "Turn on", async () => {
          await setOn(topic, true);
          drawAbout();
        });
    }
    if (topic && topic.kind === "say") return button("line-button", "Ask Noir", () => app.say(topic.say));
    return el("span");
  }

  function offerRow(name, amount, share, offer, action) {
    const bar = el("div", "ask-bar");
    bar.style.width = `${Math.max(8, Math.round(share * 100))}%`;
    return el("div", "ask-row", el("div", "ask-name", el("b", "", name), bar),
              el("div", "ask-offer", amount, ...(offer && offer[0] ? [el("b", "", offer[0]), offer[1]] : [])), action);
  }

  function kindRow(kind, most) {
    const offer = OFFERS[kind.id] || ["", "Ask me in the chat any time."];
    return offerRow(kind.words, `${kind.count} chat${kind.count === 1 ? "" : "s"}. `, kind.count / most,
                    offer[0] ? offer : null, actionFor(kind.topic));
  }

  function doingRow(kind, hours, most) {
    const [name, bold, rest, topic] = DOING[kind] || [kind, "", "", ""];
    return offerRow(name, `${hours} hour${hours === 1 ? "" : "s"}. `, hours / most, bold ? [bold, rest] : null, actionFor(topic));
  }

  function listed(words) {
    return words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
  }

  function doingSentence(made) {
    const doing = Object.keys((made.computer && made.computer.activities) || {}).slice(0, 3);
    if (!doing.length) return null;
    const phrase = (kind) => {
      const name = DOING[kind] ? DOING[kind][0] : kind;
      return /^[A-Z]{2}/.test(name) ? name : name.toLowerCase(); // "AI tools" stays as it is
    };
    return el("h1", "known-sentence", "You spend most of your computer time on ", el("em", "", listed(doing.map(phrase))), ".");
  }

  function factRow(fact) {
    const where = fact.source === "This computer" ? "this computer" : `${fact.source} · seen in ${fact.seen} chat${fact.seen === 1 ? "" : "s"}`;
    const keep = async (kept) => {
      knowing = (await pywebview.api.keep_fact(fact.id, kept)) || knowing;
      drawAbout();
    };
    const choice = fact.kept === null || fact.kept === undefined
      ? el("div", "fact-buttons", button("line-button", "Keep", () => keep(true)), button("quiet-button", "Not right", () => keep(false)))
      : el("div", "fact-buttons", el("span", "kept", fact.kept ? "Kept" : "Not kept"),
           button("quiet-button", fact.kept ? "Drop it" : "Keep it", () => keep(!fact.kept)));
    const quote = fact.source === "This computer" ? fact.quote : `"${fact.quote}"`;
    return el("div", `fact-row ${fact.kept === false ? "dropped" : ""}`,
              el("div", "", el("b", "", fact.fact), el("small", "", `${quote} · ${where}`)), choice);
  }

  function lookedWhen(seconds) {
    const day = whenWas(seconds * 1000);
    return /:/.test(day) ? `today at ${day}` : day === "Yesterday" ? "yesterday" : `on ${day}`;
  }

  // The two ways of telling it more: looking around, and chats.
  function tellMore(made) {
    const looked = made && made.computer && made.computer.looked;
    const lookCard = el("div", "tell-card",
      el("h3", "", "This computer"),
      el("p", "", "Which apps you have and use most, what you work on lately, and the kinds of files you keep. Only names and counts, never what's inside a file."),
      looked ? el("div", "tell-buttons", el("span", "kept", `Looked ${lookedWhen(looked)}`),
                  button("quiet-button", "Look again", () => lookAround(drawAbout)))
             : button("solid-button", "Look around", () => lookAround(drawAbout)));
    const chatCard = el("div", "tell-card wide",
      el("h3", "", "Your ChatGPT and Claude chats"), el("span", "optional", "Optional"),
      el("p", "", "For more, ask each company for your chats. They email you links: click them, and I pick the files up from your Downloads myself."),
      exportCards(),
      el("div", "tell-buttons",
         button("line-button", "Find it in my Downloads", () => readChats(drawAbout, "Looking in your Downloads...", () => pywebview.api.find_downloads())),
         button("quiet-button", "Choose the zip", () => readChats(drawAbout, "", () => pywebview.api.bring_in_history()))),
      promises());
    return [el("h2", "", knows(made) ? "Tell me more" : "Two ways to tell me about you"), el("div", "tell-cards", lookCard, chatCard)];
  }

  async function drawAbout() {
    if (!reading) knowing = (await pywebview.api.what_i_know()) || {};
    if (state().view !== "about") return;
    const parts = [];
    if (arrived) parts.push(el("p", "arrived", arrived));
    if (readProblem) parts.push(el("p", "read-problem", readProblem));
    if (reading) {
      $("view-about").replaceChildren(el("div", "knowing", el("h1", "", "Getting to know you..."), ...parts, ...readingNow()));
      return;
    }
    if (!knows(knowing)) {
      parts.unshift(el("h1", "", "I don't know you yet."),
                    el("p", "sub", "Tell me a little, and I'll fit what I do to you. Everything stays on this computer."));
      parts.push(...tellMore(knowing));
      $("view-about").replaceChildren(el("div", "knowing", ...parts));
      return;
    }
    const roles = looksLike(knowing);
    const doing = (knowing.computer && knowing.computer.activities) || {};
    // The computer comes first; chats, when there are any, add to it.
    parts.unshift(doingSentence(knowing) || (knowing.made ? knownSentence(knowing) : rolesSentence(knowing))
                  || el("h1", "", "Here's what I could tell."));
    const said = [roles.length && `From this computer, you look like ${listed(roles.map((r) => ROLE_NAMES[r]))}.`,
                  knowing.made && doingSentence(knowing) && knownSentence(knowing).textContent].filter(Boolean);
    if (said.length) parts.push(el("p", "sub", said.join(" ")));
    if (roles.length && state().role !== roles[0]) {
      const fits = ROLES.find((one) => one.id === roles[0]);
      if (fits) parts.push(el("div", "actions", button("line-button", `Switch on what fits ${ROLE_NAMES[roles[0]]}`, async () => {
        await applyRole(fits);
        show("about");
      })));
    }
    const doingNow = Object.entries(doing).filter(([, hours]) => hours >= 0.5).slice(0, 5);
    if (doingNow.length) {
      const most = Math.max(...doingNow.map(([, hours]) => hours));
      parts.push(el("h2", "", "What you do most on this computer"), ...doingNow.map(([kind, hours]) => doingRow(kind, hours, most)),
                 el("p", "hint-line", "Hours in front, by Windows' own count of programs opened from Start or the taskbar."));
    }
    const kinds = topKinds(knowing, 5);
    if (kinds.length) {
      const most = Math.max(1, ...kinds.map((kind) => kind.count));
      parts.push(el("h2", "", "What you ask other AIs for most"), ...kinds.map((kind) => kindRow(kind, most)));
    }
    const facts = knowing.facts || [];
    parts.push(el("h2", "", "What I think I know about you"),
               ...(facts.length ? facts.map(factRow) : [el("div", "nothing", "Nothing yet, so I won't guess.")]));
    parts.push(...tellMore(knowing));
    const forget = button("quiet-button", forgetting ? "Forget it all? Click again" : "Forget all of this", async () => {
      if (!forgetting) {
        forgetting = true;
        drawAbout();
        return;
      }
      forgetting = false;
      await pywebview.api.forget_history();
      knowing = null;
      drawAbout();
    });
    parts.push(el("div", "knowing-foot",
                  el("span", "", "Only what you keep is remembered. It stays on this computer, and never goes to a cloud model, even one you picked."),
                  el("span", "knowing-buttons", forget)));
    $("view-about").replaceChildren(el("div", "knowing", ...parts));
  }

  // ------------------------------------------------- the first two minutes

  let step = 1;
  let measured = null;
  let tried = false;

  // Step 2 is the Spot, which a Mac doesn't have yet, so there the steps go 1, 3, 4 and are numbered 1, 2, 3.
  function steps() {
    const names = [[1, "Your computer"], [2, "Try it anywhere"], [3, "Get to know you"], [4, "Who are you"]]
      .filter(([which]) => which !== 2 || state().windows);
    return el("div", "steps", ...names.map(([which, name], index) =>
      el("span", which === step ? "now" : "", el("b", "", String(index + 1)), name)));
  }

  function next(to) {
    step = to;
    drawWelcome();
  }

  async function finish(chosen) {
    if (chosen) await applyRole(chosen);
    else await pywebview.api.set_welcomed("");
    show("help");
  }

  async function drawWelcome() {
    const skip = button("quiet-button", "Skip", () => finish(null));
    const parts = [steps()];
    if (step === 1) {
      parts.push(el("h1", "welcome-title", "Your computer can run its own AI."));
      if (!measured) {
        parts.push(el("p", "sub", "Measuring what it can do, on this computer, right now..."),
                   el("div", "dots-track", el("div", "working-dots")));
        $("view-welcome").replaceChildren(...parts);
        measured = (await pywebview.api.measure()) || {};
        if (state().view === "welcome" && step === 1) drawWelcome();
        return;
      }
      if (measured.error) {
        parts.push(el("p", "sub", measured.error));
      } else {
        parts.push(el("p", "sub", `${measured.device} · measured just now, on this computer`));
        const cells = measured.results.map((job) => el("div", "week-card", el("b", "", `${job.seconds} s`), el("span", "", job.what)));
        if (measured.words_per_second) cells.push(el("div", "week-card", el("b", "", `${measured.words_per_second}`), el("span", "", "words a second")));
        parts.push(el("div", "week-cards", ...cells));
      }
      parts.push(el("p", "promise", "No subscription · No limits · Works without internet · Nothing leaves this computer"),
                 el("div", "actions", state().windows
                   ? button("solid-button", "Next: try it in any app", () => next(2))
                   : button("solid-button", "Next", () => next(3)), skip));
    } else if (step === 2) {
      parts.push(el("h1", "welcome-title", tried ? "That's it. It works in every app." : "Try it in any app."));
      if (!tried) {
        parts.push(el("p", "sub", "Go to another window, like a web page or a document. Highlight a sentence, then tap Ctrl twice."),
                   el("div", "big-keys", el("span", "", "Ctrl"), el("span", "", "Ctrl")),
                   el("p", "hint-line", "I'll wait here. Nothing you highlight leaves this computer."));
      } else {
        parts.push(el("p", "sub", "Whatever you highlight, I offer what fits, and the answer goes straight back where you were."));
      }
      parts.push(el("div", "actions", button(tried ? "solid-button" : "line-button", tried ? "Next" : "I'll try it later", () => next(3)), skip));
    } else if (step === 3) {
      parts.push(el("h1", "welcome-title", "Want me to get to know you?"));
      if (readProblem) parts.push(el("p", "read-problem", readProblem));
      if (reading) {
        parts.push(...readingNow());
      } else if (knows(knowing)) {
        const facts = (knowing.facts || []).length;
        const headline = doingSentence(knowing) || (looksLike(knowing).length && rolesSentence(knowing));
        if (headline) parts.push(headline);
        if (doingSentence(knowing) && looksLike(knowing).length) parts.push(el("p", "sub", rolesSentence(knowing).textContent));
        parts.push(el("p", "sub", facts ? `I found ${facts} thing${facts === 1 ? "" : "s"} about you. Check them any time in Settings, under About you. I only remember the ones you keep.`
                                        : "Nothing stood out, so I won't guess."),
                   el("div", "actions", button("solid-button", "Next", () => next(4))));
      } else {
        parts.push(el("p", "sub", "I can look around this computer: which apps you have and use most, what you work on lately, and the kinds of files you keep. Only names and counts, never what's inside a file, and nothing leaves this computer."),
                   el("div", "actions", button("solid-button", "Look around", () => lookAround(drawWelcome)),
                      button("quiet-button", "I'll do it later", () => next(4))),
                   el("p", "hint-line", "Used ChatGPT or Claude? You can add your chats any time in Settings, under About you."));
      }
    } else {
      parts.push(el("h1", "welcome-title", "Who are you?"),
                 el("p", "sub", "I'll switch on the jobs that fit. You can change any of them on Help me."));
      // What looking around found comes first, marked, but they still choose.
      const suggested = knowing ? looksLike(knowing) : [];
      const ordered = [...ROLES].sort((a, b) => suggested.includes(b.id) - suggested.includes(a.id));
      parts.push(el("div", "role-list", ...ordered.map((one) => {
        const names = one.on.map((id) => TOPICS.find((topic) => topic.id === id).words).join(", ");
        const card = button(`role-card ${suggested.includes(one.id) ? "suggested" : ""}`, "", () => finish(one));
        card.append(el("b", "", one.words, suggested.includes(one.id) ? el("span", "role-tag", "Looks like you") : ""),
                    el("span", "", names));
        return card;
      })));
      parts.push(el("div", "actions", button("quiet-button", "Start without these", () => finish(null))));
    }
    $("view-welcome").replaceChildren(...parts);
  }

  // Called from Python when the Spot opens anywhere.
  function spotTried() {
    tried = true;
    if (state().view === "welcome" && step === 2) drawWelcome();
  }

  return { draw: drawAbout, drawWelcome, chatsArrived, spotTried };
})();
