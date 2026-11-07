// Two tabs of Noir's room that are only lists: What I see (everything it can
// look at, and what it never does) and Reservations (booking an agent for later,
// reservations.py through TodayBridge). Both only draw what Python says.

window.roomPage = (() => {
  const $ = (id) => document.getElementById(id);
  const { el, button, show, setNoticing, state, LOCALE } = today.ui;

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
    ["Send anything off this computer without you choosing to", "Only when you pick a cloud model, turn on photos of places or let me look things up on the web, and it's counted below."],
    ["Delete your files", "I only move them, and Undo puts them back for a week."],
    ["Learn from your chats for anyone else", "Everything stays in your own folder on this computer."],
  ];
  const QUESTIONS = { sort: "Sort Downloads", video: "Summarize a lecture" };

  async function drawPrivacy() {
    const data = (await pywebview.api.privacy()) || {};
    if (state().view !== "privacy") return;
    const on = data.noticing === true;
    const toggle = button(`toggle ${on ? "on" : ""}`, "", () => setNoticing(!on));
    toggle.append(el("span", "track"), on ? "On" : "Off");
    toggle.setAttribute("aria-pressed", String(on));
    // Its noticing reads the window in front and Downloads through Windows; a Mac has no switch yet.
    const master = el("div", "noticed", el("div", "ask-words", el("b", "", "Notice things for me"),
                      el("span", "", "Off means I never look on my own. I still help whenever you ask.")),
                      state().windows ? toggle : el("span", "aside", "Windows for now"));
    const list = (rows, lit) => rows.map(([what, why]) =>
      el("div", "see", el("span", `dot ${lit ? "on" : ""}`), el("span", "", what, el("span", "see-why", why))));
    const answered = Object.entries(data.answers || {}).map(([which, counts]) =>
      el("div", "line", el("span", "what", QUESTIONS[which] || which),
         el("span", "aside", `${counts.yes} yes · ${counts.no} no · ${counts.ignored} not answered`)));
    const sent = data.sent || [];
    const companies = [...new Set(sent.map((item) => item.company))];
    const left = sent.length
      ? `Words left this computer ${sent.length} time${sent.length === 1 ? "" : "s"} in the last 7 days, to ${companies.join(", ")}, each time because you chose it.`
      : "Nothing left this computer in the last 7 days.";
    // Photos of places: the page keeps the choice (app.js), so it's read and set here.
    let photos = null;
    try {
      photos = localStorage.getItem("photos");
    } catch {}
    const photoToggle = button(`toggle ${photos === "on" ? "on" : ""}`, "", () => {
      try {
        localStorage.setItem("photos", photos === "on" ? "off" : "on");
      } catch {}
      drawPrivacy();
    });
    photoToggle.append(el("span", "track"), photos === "on" ? "On" : "Off");
    photoToggle.setAttribute("aria-pressed", String(photos === "on"));
    const photoRow = el("div", "noticed", el("div", "ask-words", el("b", "", "Photos of places"),
                        el("span", "", "When my answer names a place, I show its photo from Wikipedia. Only the place's name is looked up, never what you typed.")), photoToggle);
    // Looking things up on the web: the engine keeps the choice (research.py), with
    // how many times it was used, so it's read and set through Python.
    const webOn = data.web === true;
    const webToggle = button(`toggle ${webOn ? "on" : ""}`, "", async () => {
      await pywebview.api.set_web(!webOn);
      drawPrivacy();
    });
    webToggle.append(el("span", "track"), webOn ? "On" : "Off");
    webToggle.setAttribute("aria-pressed", String(webOn));
    const looked = data.lookups ? ` Looked up ${data.lookups} time${data.lookups === 1 ? "" : "s"} so far.` : "";
    const webRow = el("div", "noticed", el("div", "ask-words", el("b", "", "Looking things up on the web"),
                      el("span", "", `For answers that change, like the weather, prices, the news or who holds a job. Only your question goes out, never your files.${looked}`)), webToggle);
    // An optional search key: the free search path is flaky, a key makes it steady. The
    // key goes to Python and into Windows' password store; the page only learns if one is saved.
    const keyWords = el("div", "ask-words", el("b", "", "Search key (optional)"),
                        el("span", "", data.search_key
                          ? "A Brave Search key is saved, so searches go through Brave."
                          : "Without one, searches use the free path, which sometimes finds nothing. A free Brave Search key fixes that."));
    const keyRow = el("div", "noticed key-row", keyWords);
    if (data.search_key) {
      keyRow.append(button("quiet-button", "Remove", async () => {
        await pywebview.api.set_search_key("");
        drawPrivacy();
      }));
    } else {
      const keyInput = el("input", "cloud-key small-key");
      keyInput.type = "password";
      keyInput.placeholder = "Paste the key";
      keyInput.setAttribute("aria-label", "Brave Search key");
      const save = button("quiet-button", "Save", async () => {
        if (!keyInput.value.trim()) return;
        await pywebview.api.set_search_key(keyInput.value);
        drawPrivacy();
      });
      const get = el("a", "key-link", "Get a free key");
      get.href = data.search_key_page || "https://brave.com/search/api/";
      get.addEventListener("click", (event) => {
        event.preventDefault();
        pywebview.api.open_link(get.href);
      });
      keyWords.append(get);
      keyRow.append(keyInput, save);
    }
    $("view-privacy").replaceChildren(
      el("h1", "", "What I see"),
      el("p", "sub", "Everything I can look at, and what I never do."),
      master,
      el("div", "see-columns",
         el("div", "", el("h2", "", "What I look at"), ...list(LOOKS_AT, true)),
         el("div", "", el("h2", "", "What I never do"), ...list(NEVER, false))),
      el("h2", "", "Leaving this computer"),
      el("div", "nothing", left),
      webRow,
      keyRow,
      photoRow,
      el("h2", "", "How you answered my questions"),
      ...(answered.length ? answered : [el("div", "nothing", "I haven't asked anything yet.")]),
      el("p", "hint-line", "These counts stay on this computer. They're how I learn which questions aren't worth asking."),
    );
  }

  // -------------------------------------------------------- reservations

  const WHATS_ASKED = { sort: "Sort my Downloads", run: "Ask", on: "Turn on", off: "Turn off" };
  const REPEATS = { once: "Once", daily: "Every day", weekly: "Every week" };
  let bookings = [];

  function nextHour() {
    const soon = new Date(Date.now() + 3600000);
    soon.setMinutes(0, 0, 0);
    return new Date(soon - soon.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }

  function drawBookChoices() {
    const { agents, switchable } = state();
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
      const state_ = item.missed ? "Missed: Noir was closed" : finished ? "Done" : REPEATS[item.repeat];
      const row = el("div", `booking ${item.active ? "" : "off"}`,
                     el("time", "", when),
                     el("span", "what", bookingWords(item)),
                     el("span", "aside", state_));
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

  // The tab opens with the next full hour filled in, so booking is one click.
  function openBookings() {
    if (!$("book-when").value) $("book-when").value = nextHour();
    drawBookings();
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

  $("book").addEventListener("submit", book);
  $("book-what").addEventListener("change", drawBookChoices);

  return { drawPrivacy, drawBookings, drawBookChoices, openBookings };
})();
