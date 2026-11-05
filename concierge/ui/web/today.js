// The full window around the chat: the first two minutes, Today, Help me, the
// chat and Elaina's room. app.js draws the conversation; this file only chooses
// which view is showing and draws what the engine says.
//
// Help me lists what she can do, each line with its own switch and a small moving
// example, so people can picture it. A switch only asks Python to turn something
// on; lines without one send plain words to Elaina, as if typed, and she decides.
// What Today says comes from Python (TodayBridge in window.py); this page never
// looks at files or decides anything.

window.today = (() => {
  const $ = (id) => document.getElementById(id);
  const ICONS = {
    today: "M-50,-46 H50 V50 H-50 Z M-50,-16 H50 M-24,-62 V-34 M24,-62 V-34",
    plus: "M0,-44 V44 M-44,0 H44",
    panel: "M-52,-44 H52 V44 H-52 Z M-16,-44 V44",
    agents: "M-14,-28 A20,20 0 1 1 -14,-27.9 Z M-50,50 C-50,16 -32,6 -14,6 C4,6 22,16 22,50 M26,-46 A20,20 0 0 1 26,-8 M34,8 C50,14 56,28 56,50",
    clock: "M54,0 A54,54 0 1 1 -54,0 A54,54 0 1 1 54,0 Z M0,-30 V0 L22,16",
    chat: "M-54,-42 H54 V30 H-14 L-36,50 V30 H-54 Z",
    search: "M30,-12 A36,36 0 1 1 -42,-12 A36,36 0 1 1 30,-12 Z M18,16 L50,48",
    pin: "M-6,-54 L48,0 L24,4 L4,24 L0,48 L-48,0 L-24,-4 L-4,-24 Z M-24,24 L-54,54",
    file: "M-38,-56 H14 L38,-30 V56 H-38 Z M14,-56 V-30 H38",
    folder: "M-56,-40 H-16 L-2,-24 H56 V44 H-56 Z",
    picture: "M-56,-42 H56 V42 H-56 Z M-56,24 L-20,-8 L12,20 L28,6 L56,30 M24,-16 A8,8 0 1 1 23.9,-16 Z",
    screen: "M-56,-46 H56 V28 H-56 Z M-22,50 H22 M0,28 V50",
    cube: "M0,-56 L50,-28 V28 L0,56 L-50,28 V-28 Z M-50,-28 L0,0 L50,-28 M0,0 V56",
    back: "M18,-40 L-22,0 L18,40",
    forward: "M-18,-40 L22,0 L-18,40",
    spark: "M0,-58 L12,-12 L58,0 L12,12 L0,58 L-12,12 L-58,0 L-12,-12 Z",
    room: "M-52,-10 L0,-54 L52,-10 V52 H-52 Z M-16,52 V16 H16 V52",
    gear: "M30,0 A30,30 0 1 1 -30,0 A30,30 0 1 1 30,0 Z M0,-58 V-30 M0,30 V58 M-58,0 H-30 M30,0 H58 M-41,-41 L-21,-21 M21,21 L41,41 M41,-41 L21,-21 M-21,21 L-41,41",
  };
  // Each line finishes the sentence "Help me...". `kind` says what its control does:
  // "agent" switches a ready-made highlight agent on and off, "spot" and "notice"
  // switch the Spot and her noticing, "add" adds a ready-made chat agent, "say" sends
  // words to Elaina as if typed, and "soon" is something not built yet, said plainly.
  const TOPICS = [
    { id: "explain", words: "understand what I highlight", kind: "agent", agent: "Highlight Explainer", say: "Turn on the Highlight Explainer", does: "Highlight a word anywhere. A bubble explains it." },
    { id: "spot", words: "write better in any app", kind: "spot", does: "Highlight your writing and tap Ctrl twice. The better version goes right back." },
    { id: "tidy", words: "keep Downloads tidy", kind: "notice", does: "When Downloads gets messy, I ask once, sort it into folders, and you can undo it." },
    { id: "translate", words: "translate what I highlight", kind: "agent", agent: "Korean Translator", does: "Highlight text in another language. A bubble shows it in yours." },
    { id: "grammar", words: "fix my writing", kind: "add", agent: "Grammar Fixer", say: "Install Grammar Fixer", does: "Fixes grammar and spelling, in the chat or from the Spot." },
    { id: "sum", words: "sum things up", kind: "add", agent: "Quick Summarizer", say: "Install Quick Summarizer", does: "Sums up any text in three short points." },
    { id: "files", words: "find things in my files", kind: "say", say: "Make an agent for my documents", does: "Answers questions from a folder of your files, and shows where it found each answer." },
    { id: "notes", words: "take notes from lectures", kind: "soon", does: "When a lecture ends, notes made on this computer. Not built yet." },
    { id: "voice", words: "type with my voice", kind: "soon", does: "Hold a key and talk, and the words are typed. Not built yet." },
    { id: "plan", words: "plan my week", kind: "say", say: "Make a new agent that plans my week", does: "Tell me the idea, and I'll say honestly whether I can make it." },
  ];
  // Who the user is decides which lines start switched on.
  const ROLES = [
    { id: "student", words: "Student", on: ["explain", "spot", "tidy"] },
    { id: "office", words: "Office worker", on: ["spot", "grammar", "tidy"] },
    { id: "parent", words: "Parent", on: ["explain", "translate", "spot"] },
    { id: "shop", words: "Small shop", on: ["spot", "grammar", "sum"] },
    { id: "developer", words: "Developer", on: ["spot", "files"] },
    { id: "someone", words: "Setting this up for someone else", on: ["explain", "translate"], simple: true },
  ];
  // What each kind of job is called on Today: (verb, one, many).
  const DID = {
    explained: ["explained", "thing", "things", "explained where you read them", "explained where you read it"],
    translated: ["translated", "piece", "pieces", "translated in place", "translated in place"],
    polished: ["polished", "piece of writing", "pieces of writing", "pieces of writing polished", "piece of writing polished"],
    summed_up: ["summed up", "text", "texts", "texts summed up", "text summed up"],
    answered: ["answered", "question", "questions", "questions answered", "question answered"],
    helped: ["did", "job with your agents", "jobs with your agents", "jobs done by your agents", "job done by your agents"],
    sorted: ["sorted", "file", "files", "files sorted, all can be undone", "file sorted, it can be undone"],
  };
  const ROOM = ["about", "agents", "helper", "models", "reservations", "privacy", "settings"];
  // How each line looks by how far it is from the middle: how far away in
  // lines of text, how big, and how solid.
  const LOOKS = [[0, 1, 1], [1.21, 0.7, 0.55], [2.09, 0.52, 0.32], [2.79, 0.4, 0.16]];
  const AWAY = [3.2, 0.34, 0];
  const ROLL_SECONDS = 3.8; // while the user hasn't touched it
  const PICK_MS = 330;
  const PLACEHOLDERS = { help: "or just tell me in your own words", chat: "Message Elaina" };

  const LOCALE = "en-US"; // times in English like the rest of the app
  const NARROW = 1100; // below this the side list folds to icons, so the work keeps the room
  const WHATS_ASKED = { sort: "Sort my Downloads", run: "Ask", on: "Turn on", off: "Turn off" };
  const REPEATS = { once: "Once", daily: "Every day", weekly: "Every week" };

  let agents = [];
  let switchable = new Set();
  let active = new Set();
  let opened = null; // the agent on show in the agent view
  let info = {}; // what Python says about her jobs
  let chats = []; // the saved conversations, newest first
  let currentChat = null;
  let pins = new Set();
  let found = new Set(); // chats whose words match the search
  let bookings = [];
  let sideClosed = false; // the user folded the side list on a wide window
  let view = "help";
  let home = "English"; // the computer's own language, for the translator line
  let spotOn = true;
  let welcomed = true;
  let role = "";
  let week = {}; // how many of each kind of job this week
  let started = false; // the first view has been chosen
  let lastRoom = "about";
  let chosenRole = null; // a role picked on Help me, waiting for "Switch these on"
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
    if (name === "room") name = lastRoom;
    if (ROOM.includes(name) && name !== "helper") lastRoom = name;
    view = name;
    document.body.dataset.view = name;
    for (const part of ["welcome", "help", "chat", "today", "about", "agents", "helper", "models", "reservations", "privacy", "settings"]) {
      $(`view-${part}`).hidden = part !== name;
    }
    $("room-tabs").hidden = !ROOM.includes(name);
    document.querySelectorAll("#room-tabs [data-room]").forEach((tab) => tab.classList.toggle("now", tab.dataset.room === (name === "helper" ? "agents" : name)));
    $("empty").hidden = name !== "chat" || $("messages").querySelector(".row") !== null;
    document.body.classList.remove("side-over");
    $("input").dispatchEvent(new Event("input")); // its height depends on the view's font
    $("corner").hidden = ["chat", "agents", "models", "welcome"].includes(name);
    $("input").placeholder = name === "helper" ? `Try ${opened}: type something here` : PLACEHOLDERS[name] || "Ask Elaina anything";
    markSide();
    drawToday();
    if (name === "today") refresh();
    if (name === "privacy") drawPrivacy();
    if (name === "about") drawAbout();
    if (name === "agents") discover.open();
    if (name === "models") modelPage.open();
    if (name === "reservations") {
      if (!$("book-when").value) $("book-when").value = nextHour();
      drawBookings();
    }
    if (name === "help") {
      arrive();
      drawRoles();
      $("input").focus();
    }
    if (name === "welcome") drawWelcome();
    if (name === "chat") $("messages").scrollTop = $("messages").scrollHeight;
  }

  // ------------------------------------------------------------- Help me

  // Whether a line's job is on right now, from what Python last said.
  function isOn(topic) {
    if (topic.kind === "agent") return active.has(agentFor(topic));
    if (topic.kind === "add") return agents.includes(topic.agent);
    if (topic.kind === "spot") return spotOn;
    if (topic.kind === "notice") return info.noticing === true;
    return false;
  }

  function agentFor(topic) {
    // The translator translates into the computer's own language.
    return topic.id === "translate" ? `${home === "English" ? "English" : home} Translator` : topic.agent;
  }

  async function setOn(topic, on) {
    if (topic.kind === "agent" || topic.kind === "add") await pywebview.api.switch_agent(agentFor(topic), on);
    else if (topic.kind === "spot") {
      spotOn = on;
      await pywebview.api.set_spot(on);
    } else if (topic.kind === "notice") {
      await pywebview.api.set_noticing(on);
      await refresh();
    }
    drawWheel();
  }

  // The control at the end of the middle line: a switch, Add, Soon, or nothing.
  function control(topic) {
    const on = isOn(topic);
    if (topic.kind === "soon") return el("span", "wheel-note soon", "Not built yet");
    if (topic.kind === "say") return el("span", "wheel-note", "Ask Elaina");
    if (topic.kind === "add") {
      if (on) return el("span", "wheel-note", "Added");
      return button("wheel-note wheel-add", "Add", (event) => {
        event.stopPropagation();
        setOn(topic, true);
      });
    }
    const toggle = button(`moment-switch ${on ? "on" : ""}`, "", (event) => {
      event.stopPropagation();
      setOn(topic, !on);
    });
    toggle.setAttribute("aria-pressed", String(on));
    toggle.setAttribute("aria-label", `${topic.words}: ${on ? "on" : "off"}`);
    return el("span", "wheel-note", toggle, on ? "On" : "Off");
  }

  // A small moving example of each job, so people can picture it in their own apps.
  function demo(topic) {
    const page = (...parts) => el("div", "demo-page", ...parts);
    const bubble = (words) => el("div", "demo-bubble", el("span", "demo-who", "Elaina"), words);
    const scenes = {
      explain: () => page(el("p", "", "Cells keep their balance through ", el("mark", "", "osmosis"), ", which the next chapter explains."),
                          bubble("Water moving through a thin wall, towards the saltier side.")),
      translate: () => page(el("p", "", el("mark", "", "The library opens at nine on weekdays.")),
                            bubble(home === "English" ? "The library opens at nine on weekdays." : "도서관은 평일 아홉 시에 문을 열어요.")),
      spot: () => page(el("p", "", el("mark", "", "hey can u send me that report asap")),
                       el("div", "demo-spot", el("span", "demo-keys", el("b", "", "Ctrl"), el("b", "", "Ctrl")),
                          el("span", "demo-chip now", "Polish it"), el("span", "demo-chip", "Make it shorter"),
                          el("div", "demo-answer", "Could you send me the report when you have a moment?"))),
      tidy: () => page(el("div", "demo-files", el("span", "", "Downloads"), el("b", "", "34 loose files")),
                       el("div", "demo-arrow", "↓"),
                       el("div", "demo-files after", el("span", "", "Documents 22"), el("span", "", "Pictures 12")),
                       el("div", "demo-undo", "Undo for a week")),
      grammar: () => page(el("p", "", el("mark", "", "me and him goes to school")), bubble("He and I go to school.")),
      sum: () => page(el("p", "demo-long", "A long article about sleep, with study after study, and advice for students..."),
                      bubble("• Sleep 7 to 9 hours\n• Same bedtime daily\n• No screens late")),
      files: () => page(el("p", "", "When does my lease end?"),
                        bubble("On 31 March 2027."), el("div", "demo-source", "lease.pdf · page 2")),
      notes: () => page(el("p", "demo-soon", "A lecture ends, and notes appear in your Documents. Not built yet.")),
      voice: () => page(el("p", "demo-soon", "Hold a key, talk, and your words are typed. Not built yet.")),
      plan: () => page(el("p", "", "Make a new agent that plans my week"),
                       bubble("Here's what that needs, and whether I can make it.")),
    };
    const box = el("div", `demo-box demo-${topic.id}`, scenes[topic.id]());
    return [box, el("p", "demo-does", topic.does)];
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
      row.classList.toggle("lit", isOn(TOPICS[index]));
      row.setAttribute("aria-selected", String(away === 0));
      const old = row.querySelector(".wheel-note");
      if (old) old.remove();
      if (away === 0) row.append(control(TOPICS[index]));
    });
    const topic = TOPICS[at];
    $("demo").replaceChildren(...demo(topic));
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

  // The chosen line fades up into the chat, which takes over from here. A line
  // with a switch flips it instead, and a line not built yet does nothing.
  function pick() {
    const topic = TOPICS[at];
    if (topic.kind === "soon") return;
    if (["agent", "spot", "notice"].includes(topic.kind)) {
      setOn(topic, !isOn(topic));
      return;
    }
    if (topic.kind === "add") {
      if (!isOn(topic)) setOn(topic, true);
      return;
    }
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
      row.prepend(el("span", "wheel-dot"));
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
    document.querySelectorAll(".side-item").forEach((item) => {
      const here = item.dataset.view === (ROOM.includes(view) ? "room" : view);
      item.classList.toggle("now", here);
    });
  }

  // ---------------------------------------------------------------- roles

  function drawRoles() {
    const chips = ROLES.map((one) => button(`role-chip ${one.id === role ? "now" : ""}`, one.words, () => {
      chosenRole = chosenRole && chosenRole.id === one.id ? null : one;
      drawRoles();
    }));
    const parts = [el("span", "roles-lead", "Who are you? I'll switch on what fits."), ...chips];
    if (chosenRole) {
      const names = chosenRole.on.map((id) => TOPICS.find((topic) => topic.id === id).words);
      parts.push(el("div", "role-plan", el("span", "", `For you: ${names.join(", ")}.`),
                    button("solid-button", "Switch these on", () => applyRole(chosenRole)),
                    button("quiet-button", "Not now", () => {
                      chosenRole = null;
                      drawRoles();
                    })));
    }
    $("roles").replaceChildren(...parts);
  }

  async function applyRole(chosen) {
    for (const id of chosen.on) {
      const topic = TOPICS.find((one) => one.id === id);
      if (!isOn(topic)) await setOn(topic, true);
    }
    role = chosen.id;
    chosenRole = null;
    setSimple(Boolean(chosen.simple));
    await pywebview.api.set_welcomed(role);
    drawRoles();
    drawWheel();
  }

  // Set up for someone else: bigger words and only the jobs that are on.
  function setSimple(on) {
    document.body.classList.toggle("simple", on);
    try {
      localStorage.setItem("simple", on ? "yes" : "no");
    } catch {}
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

  // "12:43", "Yesterday" or "Oct 30": enough to find a chat by.
  function whenWas(moment) {
    const then = new Date(moment);
    const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(then).setHours(0, 0, 0, 0)) / 86400000);
    if (days <= 0) return then.toLocaleTimeString(LOCALE, { hour: "numeric", minute: "2-digit" });
    if (days === 1) return "Yesterday";
    return then.toLocaleDateString(LOCALE, { month: "short", day: "numeric" });
  }

  function chatRow(chat) {
    const row = el("li", chat.id === currentChat ? "current" : "");
    const open = button("item-main", "", () => {
      document.body.classList.remove("side-over");
      if (chat.id === currentChat) show("chat");
      else app.openChat(chat.id);
    });
    open.append(el("span", "item-title", chat.title), el("span", "item-when", whenWas(chat.updated)));
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
    $("pinned").replaceChildren(...top.map(chatRow));
    $("pinned").hidden = $("pinned-label").hidden = !top.length;
    const empty = words ? "Nothing found" : "No sessions yet";
    $("chats").replaceChildren(...(rest.length ? rest.map(chatRow) : top.length ? [] : [el("li", "muted", empty)]));
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

  // "This week Elaina explained 34 things, translated 12 pieces and sorted 120 files."
  function weekWords() {
    const done = Object.entries(DID).filter(([kind]) => week[kind]).map(([kind, [verb, one, many]]) => [verb, week[kind], week[kind] === 1 ? one : many]);
    if (!done.length) return null;
    const sentence = el("p", "week-words", "This week Elaina ");
    done.forEach(([verb, count, noun], index) => {
      if (index) sentence.append(index === done.length - 1 ? " and " : ", ");
      sentence.append(`${verb} `, el("em", "", `${count} ${noun}`));
    });
    sentence.append(".");
    return sentence;
  }

  function weekCards() {
    const cards = Object.entries(DID).filter(([kind]) => week[kind]).slice(0, 4)
      .map(([kind, words]) => el("div", "week-card", el("b", "", String(week[kind])), el("span", "", words[week[kind] === 1 ? 4 : 3])));
    return cards.length ? el("div", "week-cards", ...cards) : null;
  }

  function drawToday() {
    const working = active.size + (info.working ? 1 : 0);
    const label = $("working");
    label.hidden = !working || view !== "help"; // it has a place of its own only there
    label.textContent = `${working} working now`;
    const asking = info.noticing === null; // she hasn't been told yet whether she may notice things
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
      parts.push(el("h2", "", "Elaina noticed"));
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
    if (view === "privacy") drawPrivacy();
  }

  // ---------------------------------------------------------- What I see

  const LOOKS_AT = [
    ["The title of the window in front", "So I know when a lecture is playing. Never what's inside the window."],
    ["The names of files in Downloads", "Only names, sizes and dates, never what's in them."],
    ["How long since you last typed or switched windows", "So I ask between tasks. Never what you typed."],
    ["Text you highlight", "Only while a highlight helper is switched on, or when you open me with the keys."],
    ["The names of apps and files on this computer", "Only when you ask me to look around. Names and counts, never what's inside a file."],
    ["Which apps you use most", "From Windows' own count of hours in front, when you ask me to look around. Never what you did in them."],
    ["ChatGPT or Claude downloads you give me", "Only your own messages are kept, and only what you keep about you is remembered."],
  ];
  const NEVER = [
    ["Take pictures of your screen", "Only you can, with the + button."],
    ["Send anything off this computer without you choosing to", "Only when you pick a cloud model, and it's counted below."],
    ["Delete your files", "I only move them, and Undo puts them back for a week."],
    ["Learn from your chats for anyone else", "Everything stays in your own folder on this computer."],
  ];
  const QUESTIONS = { sort: "Sort Downloads", video: "Summarize a lecture" };

  async function drawPrivacy() {
    const data = (await pywebview.api.privacy()) || {};
    if (view !== "privacy") return;
    const on = data.noticing === true;
    const toggle = button(`toggle ${on ? "on" : ""}`, "", () => setNoticing(!on));
    toggle.append(el("span", "track"), on ? "On" : "Off");
    toggle.setAttribute("aria-pressed", String(on));
    const master = el("div", "noticed", el("div", "ask-words", el("b", "", "Notice things for me"),
                      el("span", "", "Off means I never look on my own. I still help whenever you ask.")), toggle);
    const list = (rows, lit) => rows.map(([what, why]) =>
      el("div", "see", el("span", `dot ${lit ? "on" : ""}`), el("span", "", what, el("span", "see-why", why))));
    const answered = Object.entries(data.answers || {}).map(([which, counts]) =>
      el("div", "line", el("span", "what", QUESTIONS[which] || which),
         el("span", "aside", `${counts.yes} yes · ${counts.no} no · ${counts.ignored} not answered`)));
    const sent = data.sent || [];
    const companies = [...new Set(sent.map((item) => item.company))];
    const left = sent.length
      ? `Words left this computer ${sent.length} time${sent.length === 1 ? "" : "s"} in the last 7 days, to ${companies.join(", ")}, when you chose a cloud model.`
      : "Nothing left this computer in the last 7 days.";
    $("view-privacy").replaceChildren(
      el("h1", "", "What I see"),
      el("p", "sub", "Everything I can look at, and what I never do."),
      master,
      el("div", "see-columns",
         el("div", "", el("h2", "", "What I look at"), ...list(LOOKS_AT, true)),
         el("div", "", el("h2", "", "What I never do"), ...list(NEVER, false))),
      el("h2", "", "Leaving this computer"),
      el("div", "nothing", left),
      el("h2", "", "How you answered my questions"),
      ...(answered.length ? answered : [el("div", "nothing", "I haven't asked anything yet.")]),
      el("p", "hint-line", "These counts stay on this computer. They're how I learn which questions aren't worth asking."),
    );
  }

  async function refresh() {
    if (!window.pywebview || !pywebview.api || !pywebview.api.today) return;
    info = (await pywebview.api.today()) || {};
    week = (await pywebview.api.activity()) || {};
    const state = (await pywebview.api.welcome()) || {};
    home = state.home || home;
    spotOn = state.spot !== false;
    welcomed = state.welcomed !== false;
    role = state.role || role;
    if (!started) {
      // The first time, the first two minutes. Then Today, once there's something to show.
      started = true;
      if (!welcomed) show("welcome");
      else if (Object.values(week).some(Boolean) && view === "help") show("today");
    }
    drawWheel();
    drawToday();
    await modelPage.load();
    pins = new Set(await pywebview.api.pinned_chats());
    drawChats();
    await drawBookings();
  }

  // ------------------------------------- getting to know you (portrait.py)

  // How to download your chats from each company, in their own words.
  const EXPORT_STEPS = {
    ChatGPT: [["Open ", "Settings"], ["", "Data controls", ", then ", "Export data"]],
    Claude: [["Open ", "Settings"], ["", "Privacy", ", then ", "Export data"]],
  };
  // What she offers for each kind of help someone asked other AIs for most:
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
  let knowing = null; // what she understood about the user, once asked
  let reading = ""; // what she's doing right now, said while she does it
  let readProblem = "";
  let arrived = ""; // chats she picked up from Downloads by herself
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

  // One way of bringing chats in, then working out what she can. `fetch` gets them,
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

  // Called from Python when chats she was waiting for landed in Downloads and were read.
  function chatsArrived(found) {
    arrived = found.error || `Your ${found.sources.join(" and ")} chats arrived, and I read ${found.read} of them.`;
    if (view === "about") drawAbout();
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

  // Each kind beside what she can do about it, switched on right there.
  // What she can do about something, right there: a switch for a Help me line, Ask
  // for a line that's a request, Ask me something for the chat, or nothing.
  function actionFor(topicId) {
    if (topicId === "chat") return button("line-button", "Ask me something", () => show("chat"));
    const topic = TOPICS.find((one) => one.id === topicId);
    if (topic && ["agent", "spot", "notice", "add"].includes(topic.kind)) {
      return isOn(topic) ? el("span", "kept", "On")
        : button("line-button", "Turn on", async () => {
          await setOn(topic, true);
          drawAbout();
        });
    }
    if (topic && topic.kind === "say") return button("line-button", "Ask Elaina", () => app.say(topic.say));
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

  // What people do most on their computer (signs.activities), beside what she can do about it.
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

  // The two ways of telling her more: looking around, and chats.
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
    if (view !== "about") return;
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
    if (roles.length && role !== roles[0]) {
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

  function steps() {
    const names = ["Your computer", "Try it anywhere", "Get to know you", "Who are you"];
    return el("div", "steps", ...names.map((name, index) =>
      el("span", index + 1 === step ? "now" : "", el("b", "", String(index + 1)), name)));
  }

  function next(to) {
    step = to;
    drawWelcome();
  }

  async function finish(chosen) {
    if (chosen) await applyRole(chosen);
    else await pywebview.api.set_welcomed("");
    welcomed = true;
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
        if (view === "welcome" && step === 1) drawWelcome();
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
                 el("div", "actions", button("solid-button", "Next: try it in any app", () => next(2)), skip));
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
        parts.push(el("p", "sub", facts ? `I found ${facts} thing${facts === 1 ? "" : "s"} about you. Check them any time in Elaina's room, under About you. I only remember the ones you keep.`
                                        : "Nothing stood out, so I won't guess."),
                   el("div", "actions", button("solid-button", "Next", () => next(4))));
      } else {
        parts.push(el("p", "sub", "I can look around this computer: which apps you have and use most, what you work on lately, and the kinds of files you keep. Only names and counts, never what's inside a file, and nothing leaves this computer."),
                   el("div", "actions", button("solid-button", "Look around", () => lookAround(drawWelcome)),
                      button("quiet-button", "I'll do it later", () => next(4))),
                   el("p", "hint-line", "Used ChatGPT or Claude? You can add your chats any time in Elaina's room, under About you."));
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
    if (view === "welcome" && step === 2) drawWelcome();
  }

  // -------------------------------------------------------- reservations

  function nextHour() {
    const soon = new Date(Date.now() + 3600000);
    soon.setMinutes(0, 0, 0);
    return new Date(soon - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }

  function drawBookChoices() {
    const chosen = $("book-what").value;
    const option = (value, words) => {
      const node = el("option", "", words);
      node.value = value;
      return node;
    };
    const options = [option("sort|", WHATS_ASKED.sort)];
    for (const name of agents) {
      if (switchable.has(name)) options.push(option(`on|${name}`, `Turn on ${name}`), option(`off|${name}`, `Turn off ${name}`));
      else options.push(option(`run|${name}`, `Ask ${name}`));
    }
    $("book-what").replaceChildren(...options);
    if (chosen) $("book-what").value = chosen;
    if (!$("book-what").value) $("book-what").value = "sort|";
    $("book-text-row").hidden = !$("book-what").value.startsWith("run|");
  }

  function bookingWords(item) {
    if (item.action === "sort") return WHATS_ASKED.sort;
    if (item.action === "run") return `${item.agent}: ${item.text}`;
    return `${WHATS_ASKED[item.action]} ${item.agent}`;
  }

  async function drawBookings() {
    bookings = (await pywebview.api.reservations()) || [];
    const waiting = bookings.filter((item) => item.active).length;
    $("bookings-count").hidden = !waiting;
    $("bookings-count").textContent = waiting;
    const rows = bookings.map((item) => {
      const when = new Date(item.when).toLocaleString(LOCALE, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      const finished = !item.active && item.repeat === "once";
      const state = item.missed ? "Missed: Elaina was closed" : finished ? "Done" : REPEATS[item.repeat];
      const row = el("div", `booking ${item.active ? "" : "off"}`,
                     el("time", "", when),
                     el("span", "what", bookingWords(item)),
                     el("span", "aside", state));
      if (!finished) {
        const toggle = button(`mini-switch ${item.active ? "on" : ""}`, "", async () => {
          await pywebview.api.switch_reservation(item.id, !item.active);
          drawBookings();
        });
        toggle.title = item.active ? "Pause it" : "Start it again";
        toggle.setAttribute("aria-label", `${bookingWords(item)}: ${item.active ? "on" : "paused"}`);
        row.append(toggle);
      }
      const remove = button("item-delete", "×", async () => {
        await pywebview.api.remove_reservation(item.id);
        drawBookings();
      });
      remove.title = "Remove it";
      remove.setAttribute("aria-label", `Remove: ${bookingWords(item)}`);
      row.append(remove);
      return row;
    });
    $("book-list").replaceChildren(...(rows.length ? rows : [el("div", "nothing", "Nothing booked yet.")]));
  }

  async function book(event) {
    event.preventDefault();
    const [action, agent] = $("book-what").value.split("|");
    const reply = await pywebview.api.add_reservation(agent, action, $("book-text").value, $("book-when").value, $("book-repeat").value);
    $("book-error").textContent = reply.error || "";
    $("book-error").hidden = !reply.error;
    if (!reply.error) {
      $("book-text").value = "";
      $("book-when").value = nextHour();
      drawBookings();
    }
  }

  // ------------------------------------------------------------- wiring

  window.addEventListener("engine-event", ({ detail: event }) => {
    if (event.type === "AgentList") {
      agents = event.agents;
      switchable = new Set(event.switchable || []);
      active = new Set(event.active || []);
      if (view === "agents") discover.agentsChanged();
      if (opened) drawAgent();
      drawBookChoices();
      markSide();
      drawToday();
      drawWheel();
    } else if (event.type === "SystemInfo") {
      $("hardware").replaceChildren(...event.hardware.map((line) => el("li", "", line)));
    } else if (event.type === "ChatList") {
      chats = event.chats;
      currentChat = event.current;
      drawChats();
    } else if (event.type === "ElainaDone" || event.type === "Error") {
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
  $("book").addEventListener("submit", book);
  $("book-what").addEventListener("change", drawBookChoices);
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
  });
  window.addEventListener("resize", placeSide);
  try {
    sideClosed = localStorage.getItem("side") === "closed";
  } catch {}
  placeSide();

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

  return {
    refresh,
    show,
    closeMenus,
    redraw: drawToday,
    spotTried,
    chatsArrived,
    // For discover.js and models.js, which are parts of this page.
    ui: { el, button, icon, dots, miniSwitch, stateOf, openAgent, agentState: () => ({ agents, switchable, active }) },
  };
})();
