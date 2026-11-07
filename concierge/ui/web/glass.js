// The card from minimized Noir. Above: what it needs answered and what's
// running. Below: the conversation, oldest at the top and newest by the box, the
// same one as in the full window. It only draws. Everything comes from the same
// events as the chat, plus what Python says about its jobs (WatchBridge in
// window.py).
//
// New messages are added to the conversation, never redrawn, so nothing that is
// already on screen moves or flickers while it answers.

window.app = (() => {
  const $ = (id) => document.getElementById(id);
  const thread = $("thread");
  const FIRST_NOTES = 3; // finished jobs shown when the card first opens
  // Talking, the card only grows through these heights. Following every new line
  // would make it twitch; a few calm steps keep it close to what it has to show.
  const STEPS = [300, 430, 560];

  let api = null;
  let active = []; // agents switched on
  let info = {}; // what Python says about its jobs
  let busy = false;
  let bubble = null; // Noir's message that streamed text is added to
  let typing = null; // the dots shown until its answer starts
  let statusKey = "";
  let fitted = "";
  let chatHeight = 0; // the step it has reached in this conversation
  const seen = new Set(); // finished jobs already in the conversation

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

  function clockTime(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  // ------------------------------------------------------- the conversation

  function follow() {
    thread.scrollTop = thread.scrollHeight;
  }

  function add(row) {
    thread.append(row);
    settle();
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

  const draw = {
    AgentList(e) {
      active = e.active || [];
      drawStatus();
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
      settle();
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

    AgentCard(e) {
      beforeAnswer();
      reply(el("div", "from", e.kind), el("div", "strong", e.name), choices(e.id, e.actions));
    },

    IdeaCard(e) {
      beforeAnswer();
      reply(el("div", "from", "Your idea"), el("div", "strong", e.title), e.verdict, choices(e.id, e.actions));
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
      settle();
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
    settle();
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
    }
  }

  async function talk(call, words) {
    busy = true;
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
    if (active.length) return `${active.length} agent${active.length === 1 ? " is" : "s are"} on`;
    return "All quiet";
  }

  // Redrawn only when something in it changed, so it never blinks.
  function drawStatus() {
    $("summary").textContent = summary();
    const key = JSON.stringify([info.noticed, info.working, active]);
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
    if (active.length) parts.push(el("div", "on-agents", ...active.map((name) => el("span", "on-agent", name))));
    $("status").replaceChildren(...parts);
    settle();
  }

  // Finished jobs join the conversation as small notes, once each.
  function addNotes() {
    const fresh = (info.done || []).filter((job) => !seen.has(`${job.when}${job.text}`));
    const firstTime = seen.size === 0;
    for (const job of fresh) seen.add(`${job.when}${job.text}`);
    for (const job of (firstTime ? fresh.slice(0, FIRST_NOTES) : fresh).reverse()) {
      const row = el("div", "note", el("span", "text", job.text), el("time", "", clockTime(job.when)));
      if (job.undo) row.append(button("undo", "Undo", () => api.undo_sorting()));
      add(row);
    }
    thread.querySelectorAll(".undo").forEach((undo) => (undo.hidden = !info.can_undo));
  }

  async function refresh() {
    if (!api) return;
    info = (await api.today()) || {};
    drawStatus();
    addNotes();
    settle();
  }

  function neededToTalk() {
    const first = thread.firstElementChild;
    const last = thread.lastElementChild;
    const words = last.offsetTop + last.offsetHeight - first.offsetTop;
    const around = $("card").offsetHeight - thread.clientHeight;
    return words + around + 26;
  }

  // Quiet, the card is as tall as what it says. Talking, it rises a step at a
  // time, never shrinks, and the conversation scrolls inside it.
  function settle() {
    const talking = thread.querySelector(".talk") !== null;
    document.body.classList.toggle("talking", talking);
    if (!talking) chatHeight = 0;
    else chatHeight = Math.max(chatHeight, STEPS.find((step) => step >= neededToTalk()) || STEPS[STEPS.length - 1]);
    const height = talking ? chatHeight : Math.ceil($("card").getBoundingClientRect().height);
    const key = `${talking} ${height}`;
    if (api && key !== fitted) {
      fitted = key;
      api.fit_glass(height, talking);
    }
  }

  function shown() {
    refresh();
    follow();
    $("text").focus();
  }

  $("ask").addEventListener("submit", ask);
  $("text").addEventListener("input", () => ($("send").hidden = !$("text").value.trim()));
  $("open").addEventListener("click", () => api && api.open_app());
  $("hide").addEventListener("click", () => api && api.hide_glass());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && api) api.hide_glass();
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
  drawStatus();

  return { onEvent, mirror, shown, refresh };
})();
