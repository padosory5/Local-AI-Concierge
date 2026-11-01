// The full window around the chat: the Help me screen, Today, the agents and
// Settings. app.js draws the conversation; this file only chooses which view is
// showing and draws what the engine says, read from the same events.
//
// Help me only offers ways to start: each line sends plain words to Elaina, as
// if the user had typed them, and she decides what happens. What Today says
// about her jobs comes from Python (TodayBridge in window.py); this page never
// looks at files or decides anything.

window.today = (() => {
  const $ = (id) => document.getElementById(id);
  const ICONS = {
    today: "M-50,-46 H50 V50 H-50 Z M-50,-16 H50 M-24,-62 V-34 M24,-62 V-34",
    plus: "M0,-44 V44 M-44,0 H44",
    gear: "M30,0 A30,30 0 1 1 -30,0 A30,30 0 1 1 30,0 Z M0,-58 V-30 M0,30 V58 M-58,0 H-30 M30,0 H58 M-41,-41 L-21,-21 M21,21 L41,41 M41,-41 L21,-21 M-21,21 L-41,41",
  };
  // Each line finishes the sentence "Help me...". `say` is what goes to Elaina,
  // and `agent` is the ready-made agent it adds, if there is one.
  const TOPICS = [
    { words: "understand what I highlight", say: "Turn on the Highlight Explainer", agent: "Highlight Explainer" },
    { words: "find things in my files", say: "Make an agent for my documents" },
    { words: "sum things up", say: "Install Quick Summarizer", agent: "Quick Summarizer" },
    { words: "sort my files", say: "Make a new agent that sorts my files into folders" },
    { words: "summarize my videos", say: "Make a new agent that summarizes the videos I watch" },
    { words: "summarize my emails", say: "Make a new agent that summarizes my emails" },
    { words: "write code", say: "Make a new agent that writes code for me" },
    { words: "create images", say: "Make a new agent that creates images" },
    { words: "translate into Korean", say: "Make a new agent that translates what I highlight into Korean" },
    { words: "plan my week", say: "Make a new agent that plans my week" },
    { words: "fix my writing", say: "Install Grammar Fixer", agent: "Grammar Fixer" },
  ];
  // How each line looks by how far it is from the middle: how far away in
  // lines of text, how big, and how solid.
  const LOOKS = [[0, 1, 1], [1.21, 0.7, 0.55], [2.09, 0.52, 0.32], [2.79, 0.4, 0.16]];
  const AWAY = [3.2, 0.34, 0];
  const ROLL_SECONDS = 3.8; // while the user hasn't touched it
  const PICK_MS = 330;
  const PLACEHOLDERS = { help: "or just tell me in your own words", chat: "Message Elaina" };

  let agents = [];
  let switchable = new Set();
  let active = new Set();
  let opened = null; // the agent on show in the agent view
  let info = {}; // what Python says about her jobs
  let view = "help";
  let at = 0; // the line in the middle of the wheel
  let touched = false; // once the user has rolled it, it stays where they left it
  let picking = false;
  const rows = [];

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

  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "-70 -70 140 140");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", ICONS[name]);
    svg.append(path);
    return svg;
  }

  // Round print dots on a slanted grid, bigger where the shade is lighter.
  function dots(canvas, width, height, step, shade) {
    const c = canvas.getContext("2d");
    c.scale(canvas.width / width, canvas.height / height);
    c.fillStyle = "#c4b4cc";
    for (let y = 0, row = 0; y < height + step; y += step * 0.866, row++) {
      for (let x = row % 2 ? step / 2 : 0; x < width + step; x += step) {
        const v = shade(x, y);
        if (v < 0.02) continue;
        c.beginPath();
        c.arc(x, y, Math.sqrt(v) * step * 0.6, 0, 7);
        c.fill();
      }
    }
  }

  // ------------------------------------------------------------ the views

  function show(name) {
    view = name;
    document.body.dataset.view = name;
    for (const part of ["help", "chat", "today", "helper", "settings"]) $(`view-${part}`).hidden = part !== name;
    $("corner").hidden = name === "chat";
    $("input").placeholder = name === "helper" ? `Try ${opened}: type something here` : PLACEHOLDERS[name] || "Ask Elaina anything";
    markSide();
    drawToday();
    if (name === "today") refresh();
    if (name === "help") {
      arrive();
      $("input").focus();
    }
    if (name === "chat") $("messages").scrollTop = $("messages").scrollHeight;
  }

  // ------------------------------------------------------------- Help me

  function note(topic) {
    if (!topic.agent) return "";
    if (active.has(topic.agent)) return "On in every app";
    return agents.includes(topic.agent) ? "Ready" : "";
  }

  function distance(index) {
    const count = TOPICS.length;
    return ((index - at + count + Math.floor(count / 2)) % count) - Math.floor(count / 2);
  }

  function drawWheel() {
    rows.forEach((row, index) => {
      const away = distance(index);
      const [lines, size, solid] = LOOKS[Math.abs(away)] || AWAY;
      row.style.transform = `translateY(calc(${Math.sign(away) * lines} * var(--size))) scale(${size})`;
      row.style.opacity = solid;
      row.style.pointerEvents = solid ? "auto" : "none";
      row.tabIndex = away === 0 ? 0 : -1;
      row.classList.toggle("center", away === 0);
      row.setAttribute("aria-selected", String(away === 0));
      const words = away === 0 ? note(TOPICS[index]) : "";
      const old = row.querySelector(".wheel-note");
      if (old) old.remove();
      if (words) row.append(el("span", "wheel-note", words));
    });
  }

  function roll(by) {
    at = (at + by + TOPICS.length) % TOPICS.length;
    drawWheel();
  }

  function arrive() {
    const wheel = $("wheel");
    wheel.classList.add("arriving");
    requestAnimationFrame(() => requestAnimationFrame(() => wheel.classList.remove("arriving")));
  }

  // The chosen line fades up into the chat, which takes over from here.
  function pick() {
    if (picking) return;
    picking = true;
    touched = true;
    $("wheel").classList.add("leaving");
    setTimeout(() => {
      picking = false;
      $("wheel").classList.remove("leaving");
      app.say(TOPICS[at].say);
    }, PICK_MS);
  }

  function makeWheel() {
    TOPICS.forEach((topic, index) => {
      const row = button("wheel-row", topic.words, () => {
        touched = true;
        if (distance(index) === 0) pick();
        else roll(distance(index));
      });
      row.setAttribute("role", "option");
      rows.push(row);
    });
    $("wheel").append(...rows);
    let lastRoll = 0;
    $("view-help").addEventListener("wheel", (event) => {
      event.preventDefault();
      touched = true;
      if (Date.now() - lastRoll < 130) return; // one line per notch, however fast the wheel spins
      lastRoll = Date.now();
      roll(Math.sign(event.deltaY));
    }, { passive: false });
    $("wheel").addEventListener("mouseenter", () => (touched = true));
    drawWheel();

    const stillness = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!stillness) {
      setInterval(() => {
        if (view === "help" && !touched && !$("input").value && !picking) roll(1);
      }, ROLL_SECONDS * 1000);
    }
  }

  // ---------------------------------------------------------- side list

  function markSide() {
    document.querySelectorAll(".side-item, .agent-row").forEach((item) => {
      const here = view === "helper" ? item.dataset.helper === opened : item.dataset.view === view;
      item.classList.toggle("now", here);
    });
  }

  function stateOf(name) {
    if (!switchable.has(name)) return "Ask it in the chat";
    return active.has(name) ? "On in every app" : "Off";
  }

  function miniSwitch(name) {
    const on = active.has(name);
    const toggle = button(`mini-switch ${on ? "on" : ""}`, "", () => app.toggleAgent(name));
    toggle.setAttribute("aria-label", `${name}: ${on ? "on" : "off"}`);
    toggle.setAttribute("aria-pressed", String(on));
    toggle.title = on ? "Switch it off" : "Switch it on";
    return toggle;
  }

  function drawAgents() {
    const rows = agents.map((name) => {
      const on = active.has(name);
      const row = el("div", `agent-row ${on ? "on" : ""}`);
      row.dataset.helper = name;
      const open = button("open", "", () => openAgent(name));
      open.append(el("span", `dot ${on ? "on" : ""}`),
                  el("span", "words", el("span", "name", name), el("span", "state", stateOf(name))));
      row.append(open);
      if (switchable.has(name)) row.append(miniSwitch(name));
      return row;
    });
    $("helpers").replaceChildren(...(rows.length ? rows : [el("div", "nothing side-empty", "No agents yet")]));

    // The ready-made ones they don't have yet, one click away.
    const more = TOPICS.filter((topic) => topic.agent && !agents.includes(topic.agent)).map((topic) => {
      const row = button("suggest", "", () => app.say(topic.say));
      row.append(el("span", "plus", "+"), el("span", "name", topic.agent));
      return row;
    });
    $("suggested").replaceChildren(...more);
    $("suggested-label").hidden = !more.length;
    markSide();
  }

  function openAgent(name) {
    opened = name;
    drawAgent();
    show("helper");
  }

  async function drawAgent() {
    const name = opened;
    if (!agents.includes(name)) {
      opened = null;
      if (view === "helper") show("help");
      return;
    }
    const details = (await pywebview.api.agent_details(name)) || {};
    if (name !== opened) return; // they've moved on to another agent

    const on = active.has(name);
    const canSwitch = switchable.has(name);
    const mark = el("canvas", "agent-mark");
    mark.width = mark.height = 144;
    dots(mark, 72, 72, 5.2, (x, y) => (Math.hypot(x - 36, y - 36) < 32 ? Math.max(0, (on ? 1.05 : 0.7) - Math.hypot(x - 26, y - 23) / 44) : 0));
    const state = canSwitch ? (on ? "On. Highlight text in any app." : "Off. Switch it on to use it in any app.") : "Ask it in the chat.";
    const head = el("div", `agent-head ${on ? "on" : ""}`, mark,
                    el("div", "agent-titles", el("h1", "agent-name", name),
                       el("div", "agent-state", el("span", `dot ${on ? "on" : ""}`), state)));
    if (canSwitch) {
      const toggle = button(`toggle ${on ? "on" : ""}`, "", () => app.toggleAgent(name));
      toggle.setAttribute("aria-pressed", String(on));
      toggle.append(el("span", "track"), on ? "On" : "Off");
      head.append(toggle);
    }

    const parts = [head];
    if (details.does) parts.push(el("p", "agent-does", details.does));
    if (details.facts) {
      parts.push(el("div", "facts", ...details.facts.map(([label, value]) =>
        el("div", "fact", el("div", "label", label), el("div", "value", value)))));
    }
    if (details.sample) {
      const sample = button("try", "", () => app.say(`${name}: ${details.sample}`));
      sample.append(el("span", "sample", `"${details.sample}"`), el("span", "go", "Try this"));
      parts.push(el("h2", "", "Try it"), sample, el("p", "hint", "Or type your own in the box below."));
    }
    parts.push(el("div", "actions",
                  button("line-button", "Change it", () => app.prefill(`Change ${name} so that `)),
                  button("line-button danger", "Delete", () => app.deleteAgent(name))));
    $("view-helper").replaceChildren(...parts);
  }

  // --------------------------------------------------------------- Today

  function clockTime(seconds) {
    return new Date(seconds * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function drawToday() {
    const working = active.size + (info.working ? 1 : 0);
    const label = $("working");
    label.hidden = !working || view !== "help"; // it has a place of its own only there
    label.textContent = `${working} working now`;
    $("today-count").hidden = !info.noticed;
    $("today-count").textContent = "1";
    const summary = working === 0 ? "Nothing is running right now." : working === 1 ? "1 agent is working." : `${working} agents are working.`;
    const parts = [el("h1", "", "Today"), el("p", "sub", `${summary} Everything stays on this computer.`)];

    if (working) {
      parts.push(el("h2", "", "Working now"));
      if (info.working) {
        parts.push(el("div", "job", el("span", "what", info.working),
                      el("div", "dots-track", el("div", "working-dots"))));
      }
      for (const name of agents.filter((a) => active.has(a))) {
        parts.push(el("div", "line", el("span", "what", name), el("span", "aside", "On in every app")));
      }
    }

    if (info.noticed) {
      const { id, text } = info.noticed;
      parts.push(el("h2", "", "Elaina noticed"));
      const box = el("div", "noticed", text);
      box.append(button("quiet-button say-no", "No", () => pywebview.api.answer(id, false)),
                 button("solid-button", "Yes", () => pywebview.api.answer(id, true)));
      parts.push(box);
    }

    parts.push(el("h2", "", "Done today"));
    if (info.done && info.done.length) {
      info.done.forEach((job, index) => {
        const row = el("div", "line", el("time", "", clockTime(job.when)), el("span", "what", job.text));
        if (job.undo && index === 0 && info.can_undo) {
          const undo = button("quiet-button", "Undo", () => pywebview.api.undo_sorting());
          undo.style.marginLeft = "auto";
          row.append(undo);
        }
        parts.push(row);
      });
    } else {
      parts.push(el("div", "nothing", "Nothing yet today."));
    }
    $("view-today").replaceChildren(...parts);
  }

  async function refresh() {
    if (!window.pywebview || !pywebview.api || !pywebview.api.today) return;
    info = (await pywebview.api.today()) || {};
    drawToday();
  }

  // ------------------------------------------------------------- wiring

  window.addEventListener("engine-event", ({ detail: event }) => {
    if (event.type === "AgentList") {
      agents = event.agents;
      switchable = new Set(event.switchable || []);
      active = new Set(event.active || []);
      drawAgents();
      if (opened) drawAgent();
      drawToday();
      drawWheel();
    } else if (event.type === "SystemInfo") {
      $("hardware").replaceChildren(...event.hardware.map((line) => el("li", "", line)));
      $("side-model").textContent = `${event.in_use.replace(/\s*\(.*\)$/, "")} on this computer`;
    }
  });

  // Anything said in the chat turns the window into the chat. An empty chat,
  // after New chat, goes back to Help me.
  new MutationObserver(() => {
    const talking = $("messages").querySelector(".row") !== null;
    if (talking && view !== "chat") show("chat");
    else if (!talking && view === "chat") show("help");
    drawToday();
  }).observe($("messages"), { childList: true });

  document.querySelectorAll("[data-icon]").forEach((item) => item.prepend(icon(item.dataset.icon)));
  document.querySelectorAll(".side [data-view]").forEach((item) => {
    item.addEventListener("click", () => {
      opened = null;
      show(item.dataset.view);
    });
  });
  $("start").addEventListener("click", () => {
    opened = null;
    if ($("messages").querySelector(".row")) $("new-chat").click();
    else show("help");
  });
  $("working").addEventListener("click", () => show("today"));

  // On an agent's page, what's typed goes to that agent. This runs before
  // app.js sends it, so Elaina sees the agent's name as if the user had typed it.
  function aimAtAgent() {
    const box = $("input");
    if (view === "helper" && opened && box.value.trim() && !box.value.startsWith(`${opened}:`) && !box.value.startsWith("Change ")) {
      box.value = `${opened}: ${box.value.trim()}`;
    }
  }
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) aimAtAgent();
  });
  $("composer").addEventListener("submit", aimAtAgent);
  $("quit").addEventListener("click", () => pywebview.api.quit_app());

  $("input").addEventListener("input", () => {
    // Typing rolls the wheel to the closest thing it offers.
    const text = $("input").value.trim().toLowerCase();
    const found = text ? TOPICS.findIndex((topic) => topic.words.toLowerCase().includes(text)) : -1;
    if (found >= 0) {
      touched = true;
      at = found;
      drawWheel();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (view !== "help") return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      touched = true;
      roll(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && !event.isComposing && !$("input").value.trim()) {
      event.preventDefault();
      pick();
    }
  });

  dots($("mark"), 26, 26, 2.2, (x, y) => (Math.hypot(x - 13, y - 13) < 12 ? Math.max(0, 0.95 - Math.hypot(x - 9, y - 8) / 16) : 0));
  dots($("corner"), 260, 170, 7, (x, y) => Math.max(0, 1 - Math.hypot(270 - x, y + 10) / 150) ** 1.6);

  window.addEventListener("page-shown", refresh);
  window.addEventListener("pywebviewready", refresh);
  makeWheel();
  drawToday();
  show("help");

  return { refresh };
})();
