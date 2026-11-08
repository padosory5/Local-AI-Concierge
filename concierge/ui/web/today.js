// The full window around the chat: which view is showing, the side list with the
// sessions, the agent page, Today, and the state every page reads. app.js draws the
// conversation. The other pages are files of their own, loaded after this one and
// drawing from what it knows (today.ui.state()): help.js (Help me and Who are you),
// about.js (About you and the first two minutes), room.js (What I see and
// Reservations), discover.js (Agents) and models.js (the model menu and Models).
//
// What Today says comes from Python (TodayBridge in window.py); this page never
// looks at files or decides anything.

window.today = (() => {
  const $ = (id) => document.getElementById(id);
  const ICONS = {
    today: "M-52,-40 H52 V52 H-52 Z M-52,-10 H52 M-26,-58 V-24 M26,-58 V-24",
    plus: "M0,-48 V48 M-48,0 H48",
    chores: "M-52,-46 H52 V46 H-52 Z M-30,-16 H30 M-30,0 H30 M-30,16 H30",
    panel: "M-52,-44 H52 V44 H-52 Z M-16,-44 V44 M-44,-20 H-24 M-44,0 H-24",
    agents: "M-14,-28 A20,20 0 1 1 -14,-27.9 Z M-50,50 C-50,16 -32,6 -14,6 C4,6 22,16 22,50 M26,-46 A20,20 0 0 1 26,-8 M34,8 C50,14 56,28 56,50",
    clock: "M54,0 A54,54 0 1 1 -54,0 A54,54 0 1 1 54,0 Z M0,-30 V0 L22,16",
    chat: "M-54,-44 H54 V28 H-12 L-36,52 V28 H-54 Z",
    search: "M-54,-54 H12 V12 H-54 Z M12,12 L54,54",
    pin: "M-32,-56 H32 V-40 L18,-30 V4 L40,24 V36 H-40 V24 L-18,4 V-30 L-32,-40 Z M0,36 V62",
    file: "M-38,-56 H14 L38,-30 V56 H-38 Z M14,-56 V-30 H38",
    folder: "M-56,-40 H-16 L-2,-24 H56 V44 H-56 Z",
    picture: "M-56,-42 H56 V42 H-56 Z M-56,24 L-20,-8 L12,20 L28,6 L56,30 M24,-16 A8,8 0 1 1 23.9,-16 Z",
    screen: "M-56,-46 H56 V28 H-56 Z M-22,50 H22 M0,28 V50",
    cube: "M0,-56 L50,-28 V28 L0,56 L-50,28 V-28 Z M-50,-28 L0,0 L50,-28 M0,0 V56",
    back: "M18,-40 L-22,0 L18,40",
    forward: "M-18,-40 L22,0 L-18,40",
    spark: "M0,-58 V-18 M0,18 V58 M-58,0 H-18 M18,0 H58 M-14,-14 H14 V14 H-14 Z",
    room: "M-54,-4 L0,-54 L54,-4 V54 H-54 Z M-14,54 V12 H14 V54",
    gear: "M30,0 A30,30 0 1 1 -30,0 A30,30 0 1 1 30,0 Z M0,-58 V-30 M0,30 V58 M-58,0 H-30 M30,0 H58 M-41,-41 L-21,-21 M21,21 L41,41 M41,-41 L21,-21 M-21,21 L-41,41",
  };
  // What each kind of job is called on Today: (verb, one, many).
  const DID = {
    explained: ["explained", "thing", "things", "explained where you read them", "explained where you read it"],
    translated: ["translated", "piece", "pieces", "translated in place", "translated in place"],
    polished: ["polished", "piece of writing", "pieces of writing", "pieces of writing polished", "piece of writing polished"],
    summed_up: ["summed up", "text", "texts", "texts summed up", "text summed up"],
    answered: ["answered", "question", "questions", "questions answered", "question answered"],
    helped: ["did", "job with your agents", "jobs with your agents", "jobs done by your agents", "job done by your agents"],
    sorted: ["sorted", "file", "files", "files sorted, all can be undone", "file sorted, it can be undone"],
    saved: ["saved", "token", "tokens", "tokens kept off your cloud model", "token kept off your cloud model"],
  };
  const ROOM = ["about", "agents", "helper", "models", "reservations", "privacy", "settings"];
  const PLACEHOLDERS = { help: "or just tell me in your own words", chat: "Message Noir" };

  const LOCALE = "en-US"; // times in English like the rest of the app
  const NARROW = 1100; // below this the side list folds to icons, so the work keeps the room

  let agents = [];
  let switchable = new Set();
  let active = new Set();
  let opened = null; // the agent on show in the agent view
  let info = {}; // what Python says about its jobs
  let chats = []; // the saved conversations, newest first
  let currentChat = null;
  let pins = new Set();
  let found = new Set(); // chats whose words match the search
  let sideClosed = false; // the user folded the side list on a wide window
  let view = "help";
  let home = "English"; // the computer's own language, for the translator line
  let spotOn = true;
  let windows = true; // the Spot, highlight agents and its noticing exist only on Windows for now
  let welcomed = true;
  let role = "";
  let week = {}; // how many of each kind of job this week
  let started = false; // the first view has been chosen
  let lastRoom = "about";

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
    if (name === "room") name = lastRoom;
    if (ROOM.includes(name) && name !== "helper") lastRoom = name;
    view = name;
    document.body.dataset.view = name;
    for (const part of ["setup", "welcome", "help", "chat", "today", "chores", "about", "agents", "helper", "models", "reservations", "privacy", "settings"]) {
      $(`view-${part}`).hidden = part !== name;
    }
    $("room-tabs").hidden = !ROOM.includes(name);
    document.querySelectorAll("#room-tabs [data-room]").forEach((tab) => tab.classList.toggle("now", tab.dataset.room === (name === "helper" ? "agents" : name)));
    $("empty").hidden = name !== "chat" || $("messages").querySelector(".row") !== null;
    document.body.classList.remove("side-over");
    $("input").dispatchEvent(new Event("input")); // its height depends on the view's font
    $("corner").hidden = ["chat", "agents", "models", "welcome", "setup"].includes(name);
    $("input").placeholder = name === "helper" ? `Try ${opened}: type something here` : PLACEHOLDERS[name] || "Ask Noir anything";
    markSide();
    drawToday();
    if (name === "today") refresh();
    if (name === "chores") choresPage.draw();
    if (name === "privacy") roomPage.drawPrivacy();
    if (name === "about") aboutPage.draw();
    if (name === "agents") discover.open();
    if (name === "models") modelPage.open();
    if (name === "reservations") roomPage.openBookings();
    if (name === "help") {
      helpPage.arrive();
      helpPage.drawRoles();
      $("input").focus();
    }
    if (name === "welcome") aboutPage.drawWelcome();
    if (name === "chat") $("messages").scrollTop = $("messages").scrollHeight;
  }

  // ---------------------------------------------------------- side list

  function markSide() {
    document.querySelectorAll(".side-item").forEach((item) => {
      // New chat opens Help me, so it is the row lit while Help me is open.
      const here = item.id === "start" ? view === "help" : item.dataset.view === (ROOM.includes(view) ? "room" : view);
      item.classList.toggle("now", here);
    });
  }

  // Half a screen is enough to read: the list folds to icons by itself on a
  // narrow window, and opens over the page when asked.
  function placeSide() {
    const narrow = window.innerWidth < NARROW;
    document.body.classList.toggle("rail", narrow || sideClosed);
    if (!narrow) document.body.classList.remove("side-over");
  }

  function toggleSide() {
    if (window.innerWidth < NARROW) {
      document.body.classList.toggle("side-over");
      return;
    }
    sideClosed = !sideClosed;
    try {
      localStorage.setItem("side", sideClosed ? "closed" : "open");
    } catch {}
    placeSide();
  }

  // ------------------------------------------------------------ sessions

  function daysAgo(moment) {
    return Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(moment).setHours(0, 0, 0, 0)) / 86400000);
  }

  // "12:43", "Yesterday" or "Oct 30": enough to find a chat by.
  function whenWas(moment) {
    const then = new Date(moment);
    const days = daysAgo(moment);
    if (days <= 0) return then.toLocaleTimeString(LOCALE, { hour: "numeric", minute: "2-digit" });
    if (days === 1) return "Yesterday";
    return then.toLocaleDateString(LOCALE, { month: "short", day: "numeric" });
  }

  // Which group of the list a chat falls into, by its last message.
  function groupOf(moment) {
    const days = daysAgo(moment);
    return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days < 7 ? "Earlier this week" : "Older";
  }

  function chatRow(chat) {
    const row = el("li", chat.id === currentChat ? "current" : "");
    const open = button("item-main", "", () => {
      document.body.classList.remove("side-over");
      if (chat.id === currentChat) show("chat");
      else app.openChat(chat.id);
    });
    open.append(el("span", "item-title", chat.title), el("span", "item-lead"), el("span", "item-when", whenWas(chat.updated)));
    open.title = `${chat.title}\nLast message ${new Date(chat.updated).toLocaleString(LOCALE)}`;
    const pinned = pins.has(chat.id);
    const pin = button(`item-pin ${pinned ? "on" : ""}`, "", async () => {
      pins = new Set(await pywebview.api.pin_chat(chat.id, !pinned));
      drawChats();
    });
    pin.append(icon("pin"));
    pin.title = pinned ? "Unpin" : "Pin";
    pin.setAttribute("aria-label", `${pinned ? "Unpin" : "Pin"} ${chat.title}`);
    // Deleting can't be undone, so the first click only asks.
    const remove = button("item-delete", "×", () => {
      if (remove.classList.contains("confirm")) {
        app.deleteChat(chat.id);
        return;
      }
      remove.classList.add("confirm");
      remove.textContent = "Delete?";
      setTimeout(() => {
        remove.classList.remove("confirm");
        remove.textContent = "×";
      }, 3000);
    });
    remove.title = "Delete this chat";
    remove.setAttribute("aria-label", `Delete chat: ${chat.title}`);
    row.append(open, pin, remove);
    return row;
  }

  function drawChats() {
    const words = $("chat-search").value.trim().toLowerCase();
    const shown = chats.filter((chat) => !words || chat.title.toLowerCase().includes(words) || found.has(chat.id));
    const top = shown.filter((chat) => pins.has(chat.id));
    const rest = shown.filter((chat) => !pins.has(chat.id));
    $("pinned").replaceChildren(...(top.length ? top.map(chatRow) : [el("li", "muted", "Pin a chat to keep it here")]));
    const groups = [];
    for (const chat of rest) {
      const name = groupOf(chat.updated);
      let group = groups.find((one) => one.name === name);
      if (!group) groups.push((group = { name, chats: [] }));
      group.chats.push(chat);
    }
    const parts = groups.flatMap((group) => [el("div", "side-label", group.name), el("ul", "chats", ...group.chats.map(chatRow))]);
    if (!parts.length) parts.push(el("div", "side-label", "Sessions"), el("ul", "chats", el("li", "muted", words ? "Nothing found" : "No sessions yet")));
    $("chats").replaceChildren(...parts);
  }

  // Titles match as the user types; the words inside chats follow a moment later.
  let searching = 0;
  function search() {
    drawChats();
    clearTimeout(searching);
    const words = $("chat-search").value.trim();
    searching = setTimeout(async () => {
      found = new Set(words ? await pywebview.api.search_chats(words) : []);
      drawChats();
    }, 220);
  }

  // ----------------------------------------------------------- the + button

  function closeMenus() {
    for (const [menu, opener] of [["add-menu", "add"], ["model-menu", "model"]]) {
      $(menu).hidden = true;
      $(opener).setAttribute("aria-expanded", "false");
    }
  }

  function privacy() {
    return window.modelPage ? modelPage.privacy() : "Everything stays on this computer.";
  }

  function toggleMenu(menu, opener) {
    const opening = $(menu).hidden;
    closeMenus();
    $(menu).hidden = !opening;
    $(opener).setAttribute("aria-expanded", String(opening));
  }

  async function add(kind) {
    closeMenus();
    const calls = { files: "pick_files", folder: "pick_folder", images: "pick_images", screenshot: "screenshot" };
    app.attach((await pywebview.api[calls[kind]]()) || []);
  }

  // ------------------------------------------------------- an agent's page

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
    return new Date(seconds * 1000).toLocaleTimeString(LOCALE, { hour: "numeric", minute: "2-digit" });
  }

  // "This week Noir explained 34 things, translated 12 pieces and sorted 120 files."
  function weekWords() {
    const done = Object.entries(DID).filter(([kind]) => week[kind]).map(([kind, [verb, one, many]]) => [verb, week[kind], week[kind] === 1 ? one : many]);
    if (!done.length) return null;
    const sentence = el("p", "week-words", "This week Noir ");
    done.forEach(([verb, count, noun], index) => {
      if (index) sentence.append(index === done.length - 1 ? " and " : ", ");
      sentence.append(`${verb} `, el("em", "", `${amount(verb, count)} ${noun}`));
    });
    sentence.append(".");
    return sentence;
  }

  // Tokens are an estimate and run into the thousands, so they read "about 12,400".
  function amount(verb, count) {
    return verb === "saved" ? `about ${count.toLocaleString("en-US")}` : String(count);
  }

  function weekCards() {
    const cards = Object.entries(DID).filter(([kind]) => week[kind]).slice(0, 4)
      .map(([kind, words]) => el("div", "week-card", el("b", "", week[kind].toLocaleString("en-US")), el("span", "", words[week[kind] === 1 ? 4 : 3])));
    return cards.length ? el("div", "week-cards", ...cards) : null;
  }

  function drawToday() {
    const working = active.size + (info.working ? 1 : 0);
    const label = $("working");
    label.hidden = !working || view !== "help"; // it has a place of its own only there
    label.textContent = `${working} working now`;
    const asking = info.noticing === null && windows; // it hasn't been told yet whether it may notice things
    $("today-count").hidden = !info.noticed && !asking;
    $("today-count").textContent = "1";
    const summary = working === 0 ? "Nothing is running right now." : working === 1 ? "1 agent is working." : `${working} agents are working.`;
    $("agents-on").hidden = !active.size;
    $("agents-on").textContent = active.size;
    const parts = [el("h1", "", "Today")];
    const words = weekWords();
    if (words) parts.push(words, weekCards());
    else parts.push(el("p", "week-words quiet", "Nothing yet this week. Highlight something in any app and tap Ctrl twice."));
    parts.push(el("p", "sub", `${summary} ${privacy()}`));

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

    if (asking) {
      parts.push(el("h2", "", "Before I start"));
      const words = el("div", "ask-words", el("b", "", "Can I notice things that could help?"),
                       el("span", "", "Like a messy Downloads folder. I only look at window titles and file names, never what's inside them, and I ask before I do anything."));
      const box = el("div", "noticed consent", words);
      box.append(button("quiet-button", "What I see", () => show("privacy")),
                 button("quiet-button say-no", "Not now", () => setNoticing(false)),
                 button("solid-button", "Yes", () => setNoticing(true)));
      parts.push(box);
    }

    if (info.noticed) {
      const { id, text, plan } = info.noticed;
      parts.push(el("h2", "", "Noir noticed"));
      const words = el("div", "ask-words", el("b", "", text));
      if (plan && plan.length) words.append(el("span", "", `Into ${plan.map((part) => `${part.shelf} ${part.count}`).join(" · ")}. Nothing is deleted, and you can undo it for a week.`));
      const box = el("div", "noticed", words);
      box.append(button("quiet-button say-no", "No", () => pywebview.api.answer(id, false)),
                 button("solid-button", "Yes", () => pywebview.api.answer(id, true)));
      parts.push(box);
    }

    parts.push(el("h2", "", "Done today"));
    if (info.done && info.done.length) {
      info.done.forEach((job) => {
        const what = el("span", "what", job.text);
        if (job.details) what.append(el("span", "line-details", job.details));
        const row = el("div", "line", el("time", "", clockTime(job.when)), what);
        if (job.undo) {
          const undo = button("quiet-button", "Undo", () => pywebview.api.undo_sorting(job.sort || ""));
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

  async function setNoticing(on) {
    await pywebview.api.set_noticing(on);
    await refresh();
    if (view === "privacy") roomPage.drawPrivacy();
  }

  async function refresh() {
    if (!window.pywebview || !pywebview.api || !pywebview.api.today) return;
    info = (await pywebview.api.today()) || {};
    week = (await pywebview.api.activity()) || {};
    const welcome = (await pywebview.api.welcome()) || {};
    home = welcome.home || home;
    spotOn = welcome.spot !== false;
    windows = welcome.windows !== false;
    if (welcome.version) $("version").textContent = `Noir ${welcome.version}`;
    welcomed = welcome.welcomed !== false;
    role = welcome.role || role;
    if (!started) {
      // Before anything else, the setup page while Ollama, its model or it is missing
      // (setup.js). The first time after that, the first two minutes. Then Today, once
      // there's something to show.
      started = true;
      const setup = (await pywebview.api.setup_state()) || {};
      if (setup.needed) {
        show("setup");
        setupPage.open(setup);
      } else if (!welcomed) show("welcome");
      else if (Object.values(week).some(Boolean) && view === "help") show("today");
    }
    helpPage.draw();
    drawToday();
    await modelPage.load();
    pins = new Set(await pywebview.api.pinned_chats());
    drawChats();
    await roomPage.drawBookings();
  }

  // ------------------------------------------------------------- wiring

  window.addEventListener("engine-event", ({ detail: event }) => {
    if (event.type === "AgentList") {
      agents = event.agents;
      switchable = new Set(event.switchable || []);
      active = new Set(event.active || []);
      if (view === "agents") discover.agentsChanged();
      if (opened) drawAgent();
      roomPage.drawBookChoices();
      markSide();
      drawToday();
      helpPage.draw();
    } else if (event.type === "SystemInfo") {
      $("hardware").replaceChildren(...event.hardware.map((line) => el("li", "", line)));
    } else if (event.type === "ChatList") {
      chats = event.chats;
      currentChat = event.current;
      drawChats();
    } else if (event.type === "NoirDone" || event.type === "Error") {
      modelPage.loadUsage(); // an answer from a plan or key just used some of it
    }
  });
  $("usage").addEventListener("click", () => modelPage.openUsage());

  // Anything said in the chat turns the window into the chat. A chat emptied by
  // New chat goes back to Help me; opening Chat on purpose stays there.
  let hadRows = false;
  new MutationObserver(() => {
    const talking = $("messages").querySelector(".row") !== null;
    if (talking && view !== "chat" && view !== "welcome") show("chat");
    else if (!talking && hadRows && view === "chat") show("help");
    hadRows = talking;
    $("empty").hidden = view !== "chat" || talking;
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
    show("help");
  });
  $("working").addEventListener("click", () => show("today"));
  document.querySelectorAll("#room-tabs [data-room]").forEach((tab) => {
    tab.addEventListener("click", () => {
      opened = null;
      show(tab.dataset.room);
    });
  });
  try {
    document.body.classList.toggle("simple", localStorage.getItem("simple") === "yes");
  } catch {}
  $("side-toggle").addEventListener("click", toggleSide);
  $("sessions-open").addEventListener("click", toggleSide);
  $("chat-search").addEventListener("input", search);
  $("add").addEventListener("click", () => toggleMenu("add-menu", "add"));
  $("model").addEventListener("click", () => {
    modelPage.drawMenu();
    toggleMenu("model-menu", "model");
  });
  $("manage-models").addEventListener("click", () => modelPage.open("api"));
  $("open-privacy").addEventListener("click", () => show("privacy"));
  document.querySelectorAll("[data-add]").forEach((item) => {
    item.addEventListener("click", () => add(item.dataset.add));
  });
  document.addEventListener("click", (event) => {
    // The path, because a click can redraw the menu it was in.
    if (!event.composedPath().some((part) => part.matches && part.matches("#add, #model, .pop"))) closeMenus();
    if (!event.target.closest(".side")) document.body.classList.remove("side-over");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
    if (event.ctrlKey && !event.altKey && (event.key === "n" || event.key === "N")) {
      event.preventDefault();
      $("start").click();
    }
  });
  window.addEventListener("resize", placeSide);
  try {
    sideClosed = localStorage.getItem("side") === "closed";
  } catch {}
  placeSide();

  // On an agent's page, what's typed goes to that agent. This runs before
  // app.js sends it, so Noir sees the agent's name as if the user had typed it.
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

  dots($("corner"), 260, 170, 7, (x, y) => Math.max(0, 1 - Math.hypot(270 - x, y + 10) / 150) ** 1.6);

  window.addEventListener("page-shown", refresh);
  window.addEventListener("pywebviewready", refresh);
  // The other pages' scripts load after this one, so the first drawing waits for them.
  document.addEventListener("DOMContentLoaded", () => {
    helpPage.make();
    drawToday();
    show("help");
  });

  return {
    refresh,
    show,
    closeMenus,
    redraw: drawToday,
    spotTried: () => aboutPage.spotTried(),
    chatsArrived: (found) => aboutPage.chatsArrived(found),
    // For the other pages, which are parts of this window and draw from what it knows.
    ui: {
      el,
      button,
      icon,
      dots,
      miniSwitch,
      stateOf,
      openAgent,
      show,
      whenWas,
      setNoticing,
      LOCALE,
      agentState: () => ({ agents, switchable, active }),
      state: () => ({ agents, switchable, active, info, home, spotOn, windows, role, view, welcomed }),
      setRole: (id) => {
        role = id;
      },
      setSpot: (on) => {
        spotOn = on;
      },
    },
  };
})();
