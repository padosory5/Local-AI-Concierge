// The drawer, pulled out of the screen's right edge. It has two faces. Quiet, it
// is the chores list: anything it needs answered, the chores it takes care of, and
// what it did, by day, newest first (WatchBridge.chores in window.py, from
// chores.py). Typing folds the list away and the conversation takes the drawer,
// the same one as in the full window, oldest at the top and newest by the box. It
// only draws: everything comes from the same events as the chat.
//
// New messages are added to the conversation, never redrawn, so nothing that is
// already on screen moves or flickers while it answers.

window.app = (() => {
  const $ = (id) => document.getElementById(id);
  const thread = $("thread");

  let api = null;
  let active = []; // agents switched on
  let info = {}; // what Python says about its jobs
  let listing = { chores: [], days: [] }; // the chores list
  let busy = false;
  let bubble = null; // Noir's message that streamed text is added to
  let typing = null; // the dots shown until its answer starts
  let statusKey = "";
  let listKey = "";
  let talking = false; // the conversation has the drawer instead of the list

  function el(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.append(...children);
    return node;
  }

  function button(className, text, onClick) {
    const node = el("button", className, text);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  // ------------------------------------------------------- the conversation

  function follow() {
    thread.scrollTop = thread.scrollHeight;
  }

  function add(row) {
    thread.append(row);
    follow();
    return row;
  }

  function you(text) {
    return add(el("div", "you talk", text));
  }

  function reply(...content) {
    return add(el("div", "reply talk", ...content));
  }

  function showTyping(text = "") {
    if (!typing) typing = add(el("div", "typing talk", el("span", "dots", el("i"), el("i"), el("i")), el("span", "doing")));
    typing.querySelector(".doing").textContent = text;
    follow();
  }

  function hideTyping() {
    if (typing) typing.remove();
    typing = null;
  }

  function finishBubble() {
    if (bubble) {
      bubble.classList.remove("streaming");
      if (!bubble.textContent.trim()) bubble.remove();
    }
    bubble = null;
  }

  function lines(items) {
    const list = el("ul", "card-list");
    for (const item of items || []) list.append(el("li", "", item));
    return list;
  }

  function choices(id, options) {
    const group = el("div", "choices");
    for (const option of options) {
      group.append(button("choice", option, () => {
        if (busy) return;
        thread.querySelectorAll(".choice").forEach((b) => (b.disabled = true));
        talk(() => api.choose(id, option), option);
      }));
    }
    return group;
  }

  function beforeAnswer() {
    hideTyping();
    finishBubble();
  }

  // The list or the conversation. Talking folds the list away with its animation.
  function setTalking(on) {
    talking = on;
    document.body.classList.toggle("talking", on);
    $("back").hidden = !on;
    if (on) follow();
  }

  const draw = {
    AgentList(e) {
      active = e.active || [];
      drawStatus();
      refresh();
    },

    Thinking(e) {
      if (e.kind === "step") showTyping(e.text);
    },

    Progress(e) {
      showTyping(e.text);
    },

    NoirText(e) {
      hideTyping();
      if (!bubble) {
        bubble = reply();
        bubble.classList.add("streaming");
      }
      bubble.append(e.text);
      follow();
    },

    NoirDone() {
      finishBubble();
    },

    Question(e) {
      beforeAnswer();
      const row = reply(e.text);
      if (e.choices && e.choices.length) row.append(choices(e.id, e.choices));
      follow();
    },

    // The whole card, as in the full window: the drawer once showed only the name, so
    // "File organizer" was all there was to judge it by.
    AgentCard(e) {
      beforeAnswer();
      const row = reply(el("div", "from", e.kind), el("div", "strong", e.name));
      row.append(el("div", "card-label", "Reads"), lines(e.reads));
      row.append(el("div", "card-label", "Can do"), lines(e.can_do));
      row.append(el("div", "card-label", "Can't do"), lines(e.cannot_do));
      row.append(el("div", "card-label", "Runs on"), el("div", "card-value", e.runs_on));
      row.append(choices(e.id, e.actions));
      follow();
    },

    IdeaCard(e) {
      beforeAnswer();
      const words = { ready: "Ready", not_built: "Not built yet", not_possible: "Not possible", unclear: "Not sure" };
      const steps = (e.steps || []).map((s) => `${words[s.status] || s.status}: ${s.text}${s.note ? ` (${s.note})` : ""}`);
      const row = reply(el("div", "from", "Your idea"), el("div", "strong", e.title));
      row.append(el("div", "card-label", "What it needs"), lines(steps));
      if (e.difficulty) row.append(el("div", "card-label", "On this computer"), el("div", "card-value", e.difficulty));
      row.append(el("div", "card-value", e.verdict), choices(e.id, e.actions));
      follow();
    },

    Result(e) {
      beforeAnswer();
      reply(el("div", "from", e.agent), e.text);
    },

    Error(e) {
      beforeAnswer();
      reply(e.text).classList.add("problem");
    },

    Transcript(e) {
      beforeAnswer();
      thread.querySelectorAll(".talk").forEach((row) => row.remove());
      for (const item of e.items) {
        if (item.role === "user") you(item.text);
        else if (item.role === "result") draw.Result(item);
        else reply(item.text);
      }
      follow();
    },
  };

  // Called from Python with every event of the conversation.
  function onEvent(event) {
    const handler = draw[event.type];
    if (handler) handler(event);
  }

  function ending() {
    hideTyping();
    finishBubble();
    busy = false;
    drawStatus();
  }

  // Called from Python when the full window starts or finishes a call.
  function mirror(change) {
    if (change.state === "start") {
      busy = true;
      if (change.user) you(change.user);
      if (change.dots) showTyping();
      drawStatus();
    } else {
      ending();
      refresh();
    }
  }

  async function talk(call, words) {
    busy = true;
    setTalking(true);
    you(words);
    showTyping();
    drawStatus();
    try {
      await call();
    } catch (problem) {
      console.error(problem);
      draw.Error({ text: "Something went wrong on my side. Please try again." });
    } finally {
      ending();
      refresh();
      $("text").focus();
    }
  }

  function ask(event) {
    event.preventDefault();
    const text = $("text").value.trim();
    if (!text || !api || busy) return;
    $("text").value = "";
    $("send").hidden = true;
    talk(() => api.send(text, false), text);
  }

  // ----------------------------------------------------------- what's going on

  function summary() {
    if (info.noticed) return "Has a question for you";
    if (busy || info.working) return "Working on it";
    const on = listing.chores.filter((chore) => chore.on).length;
    if (on) return `${on} chore${on === 1 ? "" : "s"} on`;
    return "All quiet";
  }

  // Redrawn only when something in it changed, so it never blinks.
  function drawStatus() {
    $("summary").textContent = summary();
    const key = JSON.stringify([info.noticed, info.working]);
    if (key === statusKey) return;
    statusKey = key;
    const parts = [];
    if (info.noticed) {
      const { id, text } = info.noticed;
      parts.push(el("div", "question", el("span", "", text),
                    button("no", "No", () => api.answer(id, false)),
                    button("yes", "Yes", () => api.answer(id, true))));
    }
    if (info.working) {
      parts.push(el("div", "block", el("div", "what", info.working),
                    el("div", "dots-track", el("div", "working-dots"))));
    }
    $("status").replaceChildren(...parts);
  }

  // The chores list, the way Notes lists things: what it takes care of, then each day's jobs.
  function drawList() {
    const key = JSON.stringify([listing.chores, listing.days]);
    if (key === listKey) return;
    listKey = key;
    const parts = [];
    if (listing.chores.length) {
      parts.push(el("div", "cap", "Handling"));
      for (const chore of listing.chores) {
        const row = el("div", `chore ${chore.on ? "" : "off"}`,
                       el("div", "name", el("i"), chore.name), el("div", "how", chore.how));
        if (chore.last) row.append(el("div", "last", chore.last));
        parts.push(row);
      }
    }
    for (const day of listing.days) {
      parts.push(el("div", "cap", day.day));
      for (const job of day.jobs) {
        const meta = el("div", "meta", el("span", "time", job.time), el("span", "details", job.details || ""));
        if (job.undo) meta.append(button("undo", "Undo", () => api.undo_sorting(job.sort || "").then(refresh)));
        parts.push(el("div", "job", el("div", "what", job.text), meta));
      }
    }
    if (!parts.length) {
      parts.push(el("div", "nothing", "Nothing yet. Tell Noir a chore below, like keeping Downloads tidy, and it shows up here with what it did."));
    }
    $("list").replaceChildren(...parts);
  }

  async function refresh() {
    if (!api) return;
    info = (await api.today()) || {};
    listing = (await api.chores()) || { chores: [], days: [] };
    drawStatus();
    drawList();
  }

  // Called from Python when the drawer comes out.
  function shown() {
    refresh();
    setTalking(busy);
    follow();
    $("text").focus();
  }

  $("ask").addEventListener("submit", ask);
  $("text").addEventListener("input", () => {
    const words = $("text").value.trim();
    $("send").hidden = !words;
    if (words && !talking) setTalking(true);
  });
  $("back").addEventListener("click", () => setTalking(false));
  $("open").addEventListener("click", () => api && api.open_app());
  $("hide").addEventListener("click", () => api && api.hide_drawer());
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !api) return;
    if (talking && !busy && !$("text").value.trim()) setTalking(false);
    else api.hide_drawer();
  });

  // The same small shaded mark as the full window.
  const mark = $("mark").getContext("2d");
  mark.scale(2, 2);
  mark.fillStyle = "#c4b4cc";
  for (let y = 0, row = 0; y < 38; y += 2.6, row++) {
    for (let x = row % 2 ? 1.5 : 0; x < 38; x += 3) {
      if (Math.hypot(x - 18, y - 18) > 16) continue;
      const light = Math.max(0, 0.95 - Math.hypot(x - 13, y - 11) / 22);
      if (light < 0.02) continue;
      mark.beginPath();
      mark.arc(x, y, Math.sqrt(light) * 1.7, 0, 7);
      mark.fill();
    }
  }

  function start() {
    if (api) return;
    api = window.pywebview.api;
    api.startup();
    refresh();
  }

  if (window.pywebview && window.pywebview.api && window.pywebview.api.startup) start();
  else window.addEventListener("pywebviewready", start);

  return { onEvent, mirror, shown, refresh };
})();
