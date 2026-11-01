// Studio: the full controls for people who want them. Kept apart from the
// guided screens, in the same app. Each box says whether it's real yet.

ws.studio = (() => {
  const { el, icon, button, pill, sampleTag } = ws.parts;
  const LATER = "Not built yet";

  function box(glyph, title, tag, ...children) {
    return el("section", "studio-box",
      el("div", "studio-head", el("span", "offer-glyph", icon(glyph, 18)), el("h2", "", title), tag),
      ...children);
  }

  function lines(rows) {
    return el("ul", "studio-lines", ...rows.map(([name, state]) => el("li", "", el("span", "", name), el("span", "muted", state))));
  }

  function laterNote(text) {
    return el("p", "studio-text", text);
  }

  function render() {
    const { system, names } = ws.store.state;
    const later = pill(LATER, "plain");
    return el("div", "page",
      el("header", "page-head", el("div", "", el("h1", "", "Studio"),
        el("p", "page-sub", "Full control over models, tools and connections. You never need this to use Elaina."))),
      el("div", "studio-grid",
        box("cpu", "This computer", pill("Live", "good"),
          system ? el("ul", "studio-lines plain", ...system.hardware.map((line) => el("li", "", line)))
                 : laterNote("Checking your computer...")),
        box("box", "Models", pill("Live", "good"),
          lines([["In use", system ? system.in_use : "..."], ["Best fit", (system && system.recommended) || "None yet"],
                 ["Running on", system ? system.device : "..."]]),
          system && system.note && el("p", "studio-text", system.note)),
        box("activity", "Runtimes", sampleTag(),
          lines(ws.mock.runtimes.map((r) => [r.name, r.state]))),
        box("agents", "Agents", pill("Live", "good"),
          laterNote(`${names.length} of your own on this computer.`),
          el("div", "action-row",
            button("My Agents", () => ws.go("agents")),
            button("Build from scratch", () => ws.addAgent.open("scratch")))),
        box("plug", "Tools and MCP", sampleTag(),
          lines(ws.mock.integrations.map((i) => [i.name, i.kind]))),
        box("flow", "External frameworks", sampleTag(),
          laterNote("Bring in Hermes or your own agents and manage them here."),
          el("div", "action-row", button("Connect", () => ws.addAgent.open("connect")))),
        box("studio", "Advanced model settings", later,
          laterNote("Context size, temperature and how long a model stays loaded.")),
        box("list", "Run logs", later,
          laterNote("Every step an agent took, for when something goes wrong.")),
        box("flask", "Testing", later,
          laterNote("Try an agent on the same examples after each change.")),
        box("shield", "Permissions", later,
          laterNote("What each agent may read and change, all in one list.")),
        box("wand", "Workflows", later,
          laterNote("Chain agents together, so one's result goes to the next."))));
  }

  return { render };
})();
