// Activity: every task an agent is doing or has done, so the user never has to
// search through a chat to find out what happened.

ws.activity = (() => {
  const { el, icon, button, pill, sampleTag, emptyNote, ago } = ws.parts;
  const STATUS = {
    running: ["Running", "running"], completed: ["Done", "good"], failed: ["Failed", "bad"], stopped: ["Stopped", "plain"],
  };
  const FILTERS = [["all", "All"], ["running", "Running"], ["completed", "Done"], ["failed", "Failed"]];
  let filter = "all";
  const opened = new Set(); // rows the user clicked open stay open while progress moves

  function details(run) {
    const parts = [];
    if (run.output) parts.push(el("p", "run-output", run.output));
    if (run.error) parts.push(el("p", "run-error", run.error));
    if (run.files && run.files.length) {
      parts.push(el("div", "run-files", ...run.files.map((file) => el("span", "run-file", icon("doc", 14), file))));
    }
    return parts;
  }

  function row(run) {
    const [word, tone] = STATUS[run.status];
    const when = [ago(run.started), run.took].filter(Boolean).join(" · ");
    const more = details(run);
    const open = opened.has(run.id);
    const node = el("article", `run ${run.status}`,
      el("div", `run-mark ${tone}`, icon({ completed: "tick", failed: "warn", stopped: "stop" }[run.status] || "activity", 16)),
      el("div", "run-text",
        el("div", "run-task", run.task),
        el("div", "run-agent", run.agent, " · ", when, run.sample && " ", run.sample && sampleTag())),
      el("div", "run-side", pill(word, tone),
        run.status === "running" && button("Stop", () => ws.store.stopRun(run.id), { glyph: "stop" })),
      run.status === "running" && el("div", "run-bar", progressFill(run)),
      open && more.length > 0 && el("div", "run-more", ...more));
    if (more.length) {
      node.classList.add("can-open");
      node.title = open ? "Click to hide the details" : "Click to see the details";
      node.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        if (open) opened.delete(run.id);
        else opened.add(run.id);
        ws.refresh();
      });
    }
    return node;
  }

  function progressFill(run) {
    const fill = el("span", "run-fill");
    fill.style.width = `${run.progress}%`;
    return fill;
  }

  function nowOn() {
    return ws.store.library().filter((a) => a.on).map((agent) => el("article", "run running",
      el("div", "run-mark running", icon("activity", 16)),
      el("div", "run-text", el("div", "run-task", "Working on what you highlight"), el("div", "run-agent", agent.name)),
      el("div", "run-side", ws.parts.pill("On", "running"), button("Stop", () => ws.actions.toggle(agent), { glyph: "stop" }))));
  }

  function render() {
    const runs = ws.store.state.runs;
    const shown = filter === "all" ? runs : runs.filter((r) => r.status === filter);
    const on = filter === "all" || filter === "running" ? nowOn() : [];
    const chips = el("div", "chips", ...FILTERS.map(([id, label]) => {
      const count = id === "all" ? runs.length : runs.filter((r) => r.status === id).length;
      const chip = el("button", `chip ${filter === id ? "current" : ""}`, `${label} ${count}`);
      chip.type = "button";
      chip.addEventListener("click", () => {
        filter = id;
        ws.refresh();
      });
      return chip;
    }));
    return el("div", "page",
      el("header", "page-head", el("div", "", el("h1", "", "Activity"),
        el("p", "page-sub", "What your agents are doing and what they finished."))),
      chips,
      el("div", "run-list", ...on, ...shown.map(row)),
      !on.length && !shown.length && emptyNote("Nothing here yet."));
  }

  return { render, row };
})();
