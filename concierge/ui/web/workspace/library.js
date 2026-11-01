// My Agents, and the page for one agent. Agents don't all offer the same
// things, so the page says plainly when something isn't available rather
// than showing an empty control.

ws.library = (() => {
  const { el, button, agentTile, emptyNote } = ws.parts;
  const FILTERS = [["all", "All"], ["on", "On now"], ["native", "Native"], ["imported", "Imported"],
                   ["external", "Connected"], ["community", "Community"], ["custom", "Made by you"]];
  let filter = "all";

  function render() {
    const library = ws.store.library();
    const shown = library.filter((a) => filter === "all" || (filter === "on" ? a.on : a.type === filter));
    const chips = FILTERS.map(([id, label]) => {
      const chip = el("button", `chip ${filter === id ? "current" : ""}`, label);
      chip.type = "button";
      chip.addEventListener("click", () => {
        filter = id;
        ws.refresh();
      });
      return chip;
    });
    return el("div", "page",
      el("header", "page-head",
        el("div", "", el("h1", "", "My Agents"), el("p", "page-sub", "Everything you've added, in one place.")),
        button("Add agent", () => ws.addAgent.open(), { kind: "accent", glyph: "plus" })),
      el("div", "chips", ...chips),
      shown.length ? el("div", "tile-grid", ...shown.map(agentTile)) : emptyNote("No agents here yet."));
  }

  return { render };
})();

ws.agentPage = (() => {
  const { el, icon, button, pill, sampleTag, emptyNote, glyph, compat, agentControl, star, categoryOf, TYPES } = ws.parts;

  function box(title, ...children) {
    return el("section", "fact-box", el("h2", "", title), ...children);
  }

  function pairs(rows) {
    const list = el("dl", "pairs");
    for (const [key, value] of rows) list.append(el("dt", "", key), el("dd", "", value));
    return list;
  }

  // Why a section has nothing to show: its framework doesn't offer it, or
  // the engine doesn't send it to the UI yet.
  function missing(agent, section) {
    if (agent.unsupported && agent.unsupported.includes(section)) {
      return el("p", "not-offered", `${agent.framework} doesn't share this with Elaina.`);
    }
    return el("p", "not-offered", "Not shown yet. Ask Elaina about this agent in the chat.");
  }

  function permissions(agent) {
    if (!agent.permissions) return missing(agent, "permissions");
    return el("ul", "permission-list", ...agent.permissions.map((p) => el("li", p.allowed ? "yes" : "no",
      icon(p.allowed ? "tick" : "close", 15), `${p.allowed ? "Can" : "Can't"}: ${p.label}`)));
  }

  function availability(agent) {
    if (!agent.installed) return "Not installed";
    if (agent.switchable) return agent.on ? "On now" : "Off";
    return "Ready";
  }

  function actions(agent) {
    const later = { disabled: true, title: "Not built yet" };
    const real = agent.real;
    const canDisable = real && agent.switchable && agent.on;
    return el("div", "action-row",
      button("Edit", () => ws.actions.change(agent), { glyph: "edit", ...(real ? {} : later) }),
      button("Duplicate", () => {
        ws.store.addExtra({ ...agent, id: `copy:${agent.id}:${Date.now()}`, name: `${agent.name} copy`, favorite: false });
        ws.toast(`Made a copy of ${agent.name}.`);
      }, { glyph: "copy", ...(agent.sample ? {} : later) }),
      button("Update", null, { glyph: "refresh", ...later }),
      button("Disable", () => ws.actions.toggle(agent), { glyph: "stop", ...(canDisable ? {} : later) }),
      button("Remove", () => ws.actions.remove(agent), { kind: "danger", glyph: "trash" }));
  }

  function render(id) {
    const agent = ws.store.find(id);
    if (!agent) return ws.library.render();
    const runs = ws.store.runsOf(agent.name);
    return el("div", "page",
      button("My Agents", () => ws.go("agents"), { kind: "link back", glyph: "back" }),
      el("header", "detail-head", glyph(agent),
        el("div", "detail-title",
          el("h1", "", agent.name),
          el("div", "tile-tags", pill(TYPES[agent.type]), pill(categoryOf(agent.category).name, "plain"), agent.sample && sampleTag())),
        star(agent),
        agentControl(agent)),
      el("p", "detail-text", agent.description),
      agent.installed && actions(agent),
      el("div", "fact-grid",
        box("What it's for", el("p", "", agent.purpose || agent.description)),
        box("Runs on", pairs([["Runtime", agent.runtime], ["Model", agent.model || "Elaina's model"], ["Status", availability(agent)]]),
            compat(agent)),
        box("Tools and connections", agent.tools ? el("div", "tag-list", ...agent.tools.map((t) => pill(t, "plain"))) : missing(agent, "tools")),
        box("Permissions", permissions(agent)),
        box("Settings", agent.config ? (agent.config.length ? pairs(agent.config) : emptyNote("Nothing to set.")) : missing(agent, "config")),
        box("History", runs.length ? el("div", "run-list", ...runs.slice(0, 3).map(ws.activity.row)) : emptyNote("It hasn't run yet."))));
  }

  return { render };
})();
