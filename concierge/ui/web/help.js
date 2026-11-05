// Help me: the rolling list of what she can do, each line with its own switch and a
// small moving example, so people can picture it, and "Who are you?" under it. A
// switch only asks Python to turn something on; a line without one sends plain words
// to Elaina, as if typed, and she decides. This file only draws, from what today.js
// knows (today.ui.state()).

window.helpPage = (() => {
  const $ = (id) => document.getElementById(id);
  const { el, button, state, setRole, setSpot } = today.ui;

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
  // How each line looks by how far it is from the middle: how far away in
  // lines of text, how big, and how solid.
  const LOOKS = [[0, 1, 1], [1.21, 0.7, 0.55], [2.09, 0.52, 0.32], [2.79, 0.4, 0.16]];
  const AWAY = [3.2, 0.34, 0];
  const ROLL_SECONDS = 3.8; // while the user hasn't touched it
  const PICK_MS = 330;

  let at = 0; // the line in the middle of the wheel
  let touched = false; // once the user has rolled it, it stays where they left it
  let picking = false;
  let chosenRole = null; // a role picked on Help me, waiting for "Switch these on"
  const rows = [];

  // Whether a line's job is on right now, from what Python last said.
  function isOn(topic) {
    const { agents, active, spotOn, info } = state();
    if (topic.kind === "agent") return active.has(agentFor(topic));
    if (topic.kind === "add") return agents.includes(topic.agent);
    if (topic.kind === "spot") return spotOn;
    if (topic.kind === "notice") return info.noticing === true;
    return false;
  }

  function agentFor(topic) {
    // The translator translates into the computer's own language.
    const { home } = state();
    return topic.id === "translate" ? `${home === "English" ? "English" : home} Translator` : topic.agent;
  }

  async function setOn(topic, on) {
    if (topic.kind === "agent" || topic.kind === "add") await pywebview.api.switch_agent(agentFor(topic), on);
    else if (topic.kind === "spot") {
      setSpot(on);
      await pywebview.api.set_spot(on);
    } else if (topic.kind === "notice") {
      await pywebview.api.set_noticing(on);
      await today.refresh();
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
    const { home } = state();
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
        if (state().view === "help" && !touched && !$("input").value && !picking) roll(1);
      }, ROLL_SECONDS * 1000);
    }
  }

  // ---------------------------------------------------------------- roles

  function drawRoles() {
    const { role } = state();
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
    setRole(chosen.id);
    chosenRole = null;
    setSimple(Boolean(chosen.simple));
    await pywebview.api.set_welcomed(chosen.id);
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

  // ------------------------------------------------------------- wiring

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
    if (state().view !== "help") return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      touched = true;
      roll(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Enter" && !event.isComposing && !$("input").value.trim()) {
      event.preventDefault();
      pick();
    }
  });

  return { TOPICS, ROLES, isOn, setOn, applyRole, draw: drawWheel, drawRoles, arrive, make: makeWheel };
})();
