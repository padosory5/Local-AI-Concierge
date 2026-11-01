// Home: what the user sees first. It answers "what can this do?" without
// anyone having to ask, and the chat is one choice on it rather than the page.

ws.home = (() => {
  const { el, icon, button, section, agentRow, agentTile, emptyNote } = ws.parts;
  // Each sends real words to Elaina, so they all work today.
  const STARTS = [
    { label: "Explain what I highlight", say: "Turn on the Highlight Explainer" },
    { label: "Fix my grammar", say: "Install Grammar Fixer" },
    { label: "Ask about my documents", say: "Make an agent for my documents" },
  ];
  let draft = "";
  let boxes = null;

  function greeting() {
    const hour = new Date().getHours();
    return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  }

  function hero() {
    const input = el("input");
    input.type = "text";
    input.value = draft;
    input.placeholder = "Describe a task, or pick one below";
    input.setAttribute("aria-label", "What do you want to get done?");
    input.addEventListener("input", () => (draft = input.value));
    const form = el("form", "ask-box", input, el("button", "ask-send", icon("send", 18)));
    form.lastChild.setAttribute("aria-label", "Ask Elaina");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = draft.trim();
      if (!text) return;
      draft = "";
      input.value = "";
      ws.ask(text);
    });
    const starts = STARTS.map(({ label, say }) => {
      const chip = el("button", "chip", label);
      chip.type = "button";
      chip.addEventListener("click", () => ws.ask(say));
      return chip;
    });
    return el("section", "hero",
      el("div", "hero-greet", el("div", "avatar", "E"), `${greeting()}, I'm Elaina.`),
      el("h1", "", "What do you want to get done?"),
      form,
      el("div", "chips", ...starts));
  }

  function categories() {
    const tiles = ws.mock.categories.map((category) => {
      const tile = el("button", "category", icon(category.icon, 20),
                      el("span", "category-name", category.name), el("span", "category-blurb", category.blurb));
      tile.type = "button";
      tile.addEventListener("click", () => {
        if (category.id === "custom") ws.addAgent.open("create");
        else ws.go("discover", { category: category.id });
      });
      return tile;
    });
    return section("Browse by task", null, el("div", "category-grid", ...tiles));
  }

  function fill() {
    const library = ws.store.library();
    const recent = library.slice(0, 3);
    const favorites = library.filter((a) => a.favorite).slice(0, 3);
    const runs = ws.store.state.runs.slice(0, 3);
    const fresh = ws.store.agents().filter((a) => !a.installed && a.shelves && a.shelves.includes("featured")).slice(0, 3);
    boxes.recent.replaceChildren(...(recent.length ? recent.map(agentRow) : [emptyNote("Agents you add show up here.")]));
    boxes.favorites.replaceChildren(...(favorites.length ? favorites.map(agentRow)
      : [emptyNote("Click the star on an agent to keep it here.")]));
    boxes.runs.replaceChildren(...(runs.length ? runs.map(ws.activity.row) : [emptyNote("Nothing has run yet.")]));
    boxes.fresh.replaceChildren(...(fresh.length ? fresh.map(agentTile) : [emptyNote("You've added them all.")]));
  }

  function render() {
    boxes = {
      recent: el("div", "stack"), favorites: el("div", "stack"), runs: el("div", "run-list"), fresh: el("div", "tile-grid"),
    };
    const page = el("div", "page",
      hero(),
      categories(),
      el("div", "two-up",
        section("Recently used", button("My Agents", () => ws.go("agents"), { kind: "link" }), boxes.recent),
        section("Favorites", null, boxes.favorites)),
      section("Running and recent", button("Activity", () => ws.go("activity"), { kind: "link" }), boxes.runs),
      section("New to try", button("Discover", () => ws.go("discover"), { kind: "link" }), boxes.fresh),
      section("Need something else?", null, el("div", "two-up tight",
        offer("wand", "Create with Elaina", "Describe the job in your own words.", () => ws.addAgent.open("create")),
        offer("plug", "Connect an agent", "Already use Hermes or your own tools? Bring them in.", () => ws.addAgent.open("connect")))));
    fill();
    return page;
  }

  function offer(glyph, title, text, onClick) {
    const node = el("button", "offer", el("span", "offer-glyph", icon(glyph, 20)),
                    el("span", "offer-text", el("span", "offer-title", title), el("span", "offer-blurb", text)));
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  return { render, refresh: fill };
})();
