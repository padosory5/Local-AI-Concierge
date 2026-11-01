// Discover: finding agents by task. Agents, workflow templates, models and
// integrations are different things, so each has its own tab and its own card.

ws.discover = (() => {
  const { el, icon, button, pill, sampleTag, section, agentTile, emptyNote, categoryOf, TYPES } = ws.parts;
  const TABS = [["agents", "Agents"], ["workflows", "Workflow templates"], ["models", "Models"], ["integrations", "Integrations"]];
  const SHELVES = [["featured", "Featured"], ["popular", "Popular"], ["recent", "Recently added"], ["community", "From the community"]];
  const WIDE_TYPES = ["all", "native", "external", "community"];
  const filters = { tab: "agents", query: "", category: "all", type: "all", status: "all" };
  let results = null;
  let arrivedWith = null;

  function chip(label, current, onClick) {
    const node = el("button", `chip ${current ? "current" : ""}`, label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function select(label, value, options, onChange) {
    const node = el("select", "picker");
    node.setAttribute("aria-label", label);
    for (const [id, text] of options) {
      const option = el("option", "", text);
      option.value = id;
      node.append(option);
    }
    node.value = value;
    node.addEventListener("change", () => onChange(node.value));
    return node;
  }

  // Agents in the catalog: not the user's own or ones added this session.
  function catalog() {
    return ws.store.agents().filter((a) => !a.id.includes(":"));
  }

  function matches(agent) {
    const words = `${agent.name} ${agent.description} ${categoryOf(agent.category).name}`.toLowerCase();
    return words.includes(filters.query.toLowerCase())
      && (filters.category === "all" || agent.category === filters.category)
      && (filters.type === "all" || agent.type === filters.type)
      && (filters.status === "all" || agent.installed === (filters.status === "installed"));
  }

  function isFiltered() {
    return filters.query || filters.category !== "all" || filters.type !== "all" || filters.status !== "all";
  }

  function agentResults() {
    if (isFiltered()) {
      const found = catalog().filter(matches);
      if (!found.length) {
        return [emptyNote("No agent does that yet."),
                button("Create it with Elaina", () => ws.addAgent.open("create"), { kind: "accent", glyph: "wand" })];
      }
      return [el("div", "tile-grid", ...found.map(agentTile))];
    }
    return SHELVES.map(([id, title]) => section(title, null, el("div", "tile-grid",
      ...catalog().filter((a) => a.shelves && a.shelves.includes(id)).map(agentTile))));
  }

  function plainCard(glyph, name, tags, text, foot) {
    return el("article", "agent-tile static",
      el("div", "tile-top", el("div", "agent-glyph", icon(glyph, 20)), el("div", "tile-title", el("h3", "", name),
        el("div", "tile-tags", ...tags, sampleTag()))),
      el("p", "tile-text", text),
      foot && el("div", "tile-facts", foot));
  }

  function typedResults() {
    const query = filters.query.toLowerCase();
    const found = (items) => items.filter((item) => `${item.name} ${item.blurb}`.toLowerCase().includes(query));
    const cards = {
      workflows: () => found(ws.mock.workflows).map((w) => plainCard("flow", w.name, [pill(categoryOf(w.category).name, "plain")],
                                                                      w.blurb, `Uses: ${w.uses.join(", ")}`)),
      models: () => found(ws.mock.models).map((m) => plainCard("cpu", m.name, [pill(m.size, "plain")], m.blurb, m.fit)),
      integrations: () => found(ws.mock.integrations).map((i) => plainCard("plug", i.name, [pill(i.kind, "plain")], i.blurb)),
    }[filters.tab]();
    return cards.length ? [el("div", "tile-grid", ...cards)] : [emptyNote("Nothing matches that.")];
  }

  function fill() {
    results.replaceChildren(...(filters.tab === "agents" ? agentResults() : typedResults()));
  }

  function agentFilters() {
    const categories = [["all", "All tasks"], ...ws.mock.categories.filter((c) => c.id !== "custom").map((c) => [c.id, c.name])];
    return el("div", "filters",
      el("div", "chips", ...categories.map(([id, label]) => chip(label, filters.category === id, () => {
        filters.category = id;
        ws.refresh.full();
      }))),
      el("div", "pickers",
        select("Agent type", filters.type, WIDE_TYPES.map((id) => [id, id === "all" ? "Any type" : TYPES[id]]), (value) => {
          filters.type = value;
          fill();
        }),
        select("Installed or not", filters.status, [["all", "Installed or not"], ["installed", "Installed"], ["available", "Not installed"]], (value) => {
          filters.status = value;
          fill();
        })));
  }

  function render(param) {
    // Only on arrival: after that the user's own filter choices win.
    if (param && param !== arrivedWith) Object.assign(filters, { tab: "agents", query: "", category: param.category });
    arrivedWith = param;
    const search = el("input");
    search.type = "search";
    search.value = filters.query;
    search.placeholder = "Search by what you want to do";
    search.setAttribute("aria-label", "Search");
    search.addEventListener("input", () => {
      filters.query = search.value;
      fill();
    });
    results = el("div", "results");
    fill();
    return el("div", "page",
      el("header", "page-head", el("div", "", el("h1", "", "Discover"),
        el("p", "page-sub", "Find a ready-made agent, or see what you can connect."))),
      el("div", "search-box", icon("search", 18), search),
      el("div", "tabs", ...TABS.map(([id, label]) => {
        const tab = el("button", `tab ${filters.tab === id ? "current" : ""}`, label);
        tab.type = "button";
        tab.addEventListener("click", () => {
          filters.tab = id;
          ws.refresh.full();
        });
        return tab;
      })),
      filters.tab === "agents" && agentFilters(),
      results);
  }

  return { render, refresh: fill };
})();
