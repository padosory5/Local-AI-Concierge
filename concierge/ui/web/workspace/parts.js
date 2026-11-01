// Small building blocks every workspace screen shares. Like app.js, text
// always goes in as text and never as HTML.

window.ws = window.ws || {};

ws.parts = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  // Drawn on a 24 by 24 grid with round lines, so they match at every size.
  const ICONS = {
    home: "M3 11 12 4l9 7M5.5 9.5V20h13V9.5M10 20v-6h4v6",
    compass: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM15.5 8.5l-2 5-5 2 2-5z",
    agents: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    activity: "M3 12h4l3-8 4 16 3-8h4",
    studio: "M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4",
    plus: "M12 5v14M5 12h14",
    search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
    star: "M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9L3.5 9.7l5.9-.8z",
    play: "M7 5l12 7-12 7z",
    stop: "M7 7h10v10H7z",
    back: "M15 5l-7 7 7 7",
    next: "M9 5l7 7-7 7",
    close: "M6 6l12 12M18 6 6 18",
    history: "M4 12a8 8 0 1 0 2.5-5.8L4 8.5M4 4v4.5h4.5M12 8v4l3 2",
    doc: "M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6",
    folder: "M3 6h6l2 2.5h10V19H3z",
    book: "M12 6c-2-1.5-5-2-8-2v14c3 0 6 .5 8 2 2-1.5 5-2 8-2V4c-3 0-6 .5-8 2zM12 6v14",
    code: "M8 7l-5 5 5 5M16 7l5 5-5 5",
    check: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12l3 3 5-6",
    tick: "M5 12.5l4.5 4.5L19 7",
    cap: "M2 9l10-5 10 5-10 5zM6 11.5V16c2 2 10 2 12 0v-4.5",
    spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
    wand: "M4 20 14 10M14 4l.8 2.2L17 7l-2.2.8L14 10l-.8-2.2L11 7l2.2-.8zM19 12l.6 1.4L21 14l-1.4.6L19 16l-.6-1.4L17 14l1.4-.6z",
    plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
    box: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
    cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    shield: "M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z",
    list: "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
    flask: "M10 3h4M11 3v6L5 19a1.5 1.5 0 0 0 1.3 2h11.4A1.5 1.5 0 0 0 19 19l-6-10V3M8 15h8",
    flow: "M5 4h5v5H5zM14 15h5v5h-5zM7.5 9v3a2 2 0 0 0 2 2h7v1",
    send: "M5 12h14M13 6l6 6-6 6",
    chat: "M4 5h16v11H9l-5 4z",
    warn: "M12 4l9 16H3zM12 10v4M12 17h.01",
    edit: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4",
    copy: "M8 8h12v12H8zM4 16V4h12",
    trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    refresh: "M20 11a8 8 0 0 0-14-4.5L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4.5l2-2.5M20 20v-5h-5",
  };
  const TYPES = { native: "Native", external: "External", community: "Community", imported: "Imported", custom: "Custom" };

  function el(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.append(...children.filter((child) => child !== null && child !== undefined && child !== false));
    return node;
  }

  function icon(name, size = 18) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", size);
    svg.setAttribute("height", size);
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", ICONS[name]);
    svg.append(path);
    return svg;
  }

  function button(label, onClick, { kind = "", glyph, title, disabled } = {}) {
    const node = el("button", `button ${kind}`, glyph && icon(glyph, 16), label);
    node.type = "button";
    node.disabled = Boolean(disabled);
    if (title) node.title = title;
    if (onClick) node.addEventListener("click", onClick);
    return node;
  }

  function iconButton(name, label, onClick, className = "") {
    const node = el("button", `glyph-button ${className}`, icon(name, 16));
    node.type = "button";
    node.title = label;
    node.setAttribute("aria-label", label);
    node.addEventListener("click", onClick);
    return node;
  }

  function pill(text, tone = "") {
    return el("span", `pill ${tone}`, text);
  }

  function sampleTag() {
    const tag = pill("Sample", "sample");
    tag.title = "Sample data for this preview. It doesn't run on your computer yet.";
    return tag;
  }

  function section(title, side, ...children) {
    return el("section", "section", el("div", "section-head", el("h2", "", title), side), ...children);
  }

  function emptyNote(text) {
    return el("p", "empty-note", text);
  }

  function categoryOf(id) {
    return ws.mock.categories.find((c) => c.id === id) || ws.mock.categories[ws.mock.categories.length - 1];
  }

  function glyph(agent) {
    return el("div", `agent-glyph ${agent.type}`, icon(categoryOf(agent.category).icon, 20));
  }

  function compat(agent) {
    const tone = { ok: "good", warn: "warn", no: "bad" }[agent.compat.level];
    return el("span", `compat ${tone}`, icon(agent.compat.level === "ok" ? "tick" : "warn", 14), agent.compat.text);
  }

  function powerSwitch(agent) {
    const node = el("button", `power ${agent.on ? "on" : ""}`, el("span", "power-knob"));
    node.type = "button";
    node.setAttribute("role", "switch");
    node.setAttribute("aria-checked", String(agent.on));
    node.setAttribute("aria-label", `${agent.name} ${agent.on ? "is on" : "is off"}`);
    node.title = agent.on ? "On. Click to switch it off" : "Off. Click to switch it on";
    node.addEventListener("click", () => ws.actions.toggle(agent));
    return node;
  }

  // The one main thing an agent offers right now, the same on every screen.
  function agentControl(agent) {
    const act = ws.actions;
    if (agent.installed) {
      if (agent.switchable) return el("div", "power-row", el("span", "power-word", agent.on ? "On" : "Off"), powerSwitch(agent));
      return button(agent.sample ? "Run" : "Use", () => act.use(agent), { kind: "soft", glyph: "play" });
    }
    if (agent.compat.level === "no") return button("Not available", null, { disabled: true, title: agent.compat.text });
    if (agent.setup) return button("Set up", () => act.install(agent), { kind: "accent" });
    return button(agent.type === "external" ? "Connect" : "Install", () => act.install(agent), { kind: "accent" });
  }

  function star(agent) {
    const node = iconButton("star", agent.favorite ? "Remove from favorites" : "Add to favorites",
                            () => ws.store.toggleFavorite(agent), `star ${agent.favorite ? "on" : ""}`);
    node.setAttribute("aria-pressed", String(agent.favorite));
    return node;
  }

  // Clicking a card opens the agent, except on the controls inside it.
  function opensAgent(node, agent) {
    node.addEventListener("click", (e) => {
      if (!e.target.closest("button, a, input")) ws.go("agent", agent.id);
    });
    node.tabIndex = 0;
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target === node) ws.go("agent", agent.id);
    });
    return node;
  }

  function agentTile(agent) {
    const facts = [agent.runtime, agent.model].filter(Boolean).join(" · ");
    return opensAgent(el("article", "agent-tile",
      el("div", "tile-top", glyph(agent), el("div", "tile-title",
        el("h3", "", agent.name),
        el("div", "tile-tags", pill(TYPES[agent.type]), pill(categoryOf(agent.category).name, "plain"), agent.sample && sampleTag()))),
      el("p", "tile-text", agent.description),
      el("div", "tile-facts", facts),
      el("div", "tile-foot", compat(agent), agentControl(agent))), agent);
  }

  function agentRow(agent) {
    return opensAgent(el("article", "agent-row", glyph(agent),
      el("div", "row-text", el("div", "row-name", agent.name, agent.sample && sampleTag()),
        el("div", "row-sub", agent.description)),
      agentControl(agent)), agent);
  }

  function ago(ms) {
    const minutes = Math.round((Date.now() - ms) / 60000);
    if (minutes < 1) return "Just now";
    if (minutes < 60) return `${minutes} min ago`;
    if (minutes < 1440) return `${Math.round(minutes / 60)} hr ago`;
    return "Yesterday";
  }

  function lasted(ms) {
    const seconds = Math.max(1, Math.round(ms / 1000));
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  }

  return {
    TYPES, el, icon, button, iconButton, pill, sampleTag, section, emptyNote, categoryOf, glyph, compat, agentControl,
    star, agentTile, agentRow, ago, lasted,
  };
})();
