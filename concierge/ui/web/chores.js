// Chores, in the main window: the same list the drawer shows (WatchBridge.chores,
// from chores.py), with the switches and Remove the drawer leaves out, and a line to
// tell Noir a chore, which goes to the chat as if typed. This file only draws.

window.choresPage = (() => {
  const $ = (id) => document.getElementById(id);
  const { el, button, state, setNoticing } = today.ui;

  async function switchChore(chore, on) {
    if (chore.kind === "tidy") await setNoticing(on);
    else if (chore.kind === "agent") app.toggleAgent(chore.name);
    else if (chore.kind === "booking") {
      await pywebview.api.switch_reservation(chore.id.split(":")[1], on);
      await draw();
    }
  }

  async function removeChore(chore) {
    if (chore.kind === "agent") app.deleteAgent(chore.name);
    else if (chore.kind === "booking") {
      await pywebview.api.remove_reservation(chore.id.split(":")[1]);
      await draw();
    }
  }

  function choreRow(chore) {
    const toggle = button(`toggle ${chore.on ? "on" : ""}`, "", () => switchChore(chore, !chore.on));
    toggle.append(el("span", "track"), chore.on ? "On" : "Off");
    toggle.setAttribute("aria-pressed", String(chore.on));
    const words = el("div", "chore-words", el("div", "chore-name", chore.name), el("div", "chore-how", chore.how));
    if (chore.last) words.append(el("div", "chore-last", chore.last));
    const side = el("div", "chore-side", toggle);
    if (chore.kind !== "tidy") side.append(button("quiet-button chore-remove", "Remove", () => removeChore(chore)));
    return el("div", `chore-row ${chore.on ? "" : "off"}`, words, side);
  }

  function jobRow(job, canUndo) {
    const meta = el("div", "job-meta", el("span", "job-time", job.time), el("span", "job-details", job.details || ""));
    if (job.undo) meta.append(button("quiet-button", "Undo", () => pywebview.api.undo_sorting(job.sort || "").then(draw)));
    return el("div", "job-row", el("div", "job-what", job.text), meta);
  }

  async function draw() {
    if (state().view !== "chores") return;
    const listing = (await pywebview.api.chores()) || { chores: [], days: [] };
    const info = (await pywebview.api.today()) || {};
    const parts = [el("h1", "", "Chores"),
                   el("p", "sub", "Small things Noir takes care of on its own, on this computer. Every one can be switched off, and what it moves can be undone for a week.")];
    const line = el("input", "chore-ask");
    // The example must be a chore a helper can be made for: the one before asked for
    // files to be renamed, which no helper does.
    line.placeholder = "Tell Noir a chore, like: put every new download in a folder by what it's about";
    line.setAttribute("aria-label", "Tell Noir a chore");
    line.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && line.value.trim()) {
        app.say(line.value.trim());
        line.value = "";
      }
    });
    parts.push(el("div", "chore-askbox", el("span", "chore-plus", "+"), line));
    parts.push(el("h2", "", "Handling"));
    if (listing.chores.length) parts.push(el("div", "chore-list", ...listing.chores.map(choreRow)));
    else parts.push(el("div", "nothing", "Nothing yet."));
    for (const day of listing.days) {
      parts.push(el("h2", "", day.day), el("div", "job-list", ...day.jobs.map((job) => jobRow(job, info.can_undo))));
    }
    if (!listing.days.length) parts.push(el("h2", "", "Done"), el("div", "nothing", "Nothing done yet."));
    parts.push(el("p", "chore-hint", state().windows
      ? "The same list comes out of the right edge of the screen, over whatever you're doing: hold Ctrl, press the mouse at the edge and pull left. Esc puts it back."
      : "On Windows the same list comes out of the right edge of the screen with Ctrl and the mouse."));
    $("view-chores").replaceChildren(...parts);
  }

  return { draw };
})();
