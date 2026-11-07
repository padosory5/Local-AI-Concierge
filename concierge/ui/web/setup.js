// The first run's setup page (view-setup): Ollama, a model that fits, then Noir,
// from one button. It only draws what Python says (setup_state, from setup.py) and
// asks again every second while a step runs. Once nothing is missing it starts it
// again (setup_finish) and goes on to the first two minutes.

window.setupPage = (() => {
  const $ = (id) => document.getElementById(id);
  const { el, button, state, show } = today.ui;
  const ASK_MS = 900;
  let data = null;
  let timer = null;

  async function open(known) {
    data = known || (await pywebview.api.setup_state()) || {};
    draw();
    if (data.working) later();
  }

  function later() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      data = (await pywebview.api.setup_state()) || {};
      draw();
      if (data.working) later();
      else if (!data.needed) finish();
    }, ASK_MS);
  }

  async function begin(smallest) {
    data = (await pywebview.api.setup_begin(Boolean(smallest))) || data;
    draw();
    later();
  }

  async function finish() {
    clearTimeout(timer);
    await pywebview.api.setup_finish();
    show(state().welcomed ? "help" : "welcome");
  }

  const gb = (bytes) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

  // While a step runs: a bar with the bytes when they're known, moving dots otherwise.
  function bar() {
    const p = data.progress;
    if (!p) return el("div", "dots-track", el("div", "working-dots"));
    const fill = el("div", "setup-fill");
    fill.style.width = `${p.total ? Math.min(100, (100 * p.done) / p.total) : 0}%`;
    return el("div", "setup-progress", el("div", "setup-bar", fill),
              el("span", "setup-bytes", p.total ? `${gb(p.done)} of ${gb(p.total)}` : gb(p.done)));
  }

  // One row per step: what it is, what will happen or has happened, and a bar while it runs.
  function row(number, title, what, status, running, done) {
    const words = el("div", "setup-words", el("div", "setup-title", title), el("div", "setup-what", what));
    const side = running ? el("div", "setup-running", el("span", "", data.note), bar())
      : el("span", `setup-status ${done ? "done" : ""}`, status);
    return el("div", `setup-step ${running ? "running" : ""} ${done ? "done" : ""}`, el("b", "", String(number)), words, side);
  }

  function draw() {
    if (!data) return;
    const model = data.model;
    const parts = [
      el("h1", "welcome-title", !data.needed ? "Ready." : data.working ? "Setting up..." : "Your own AI, set up in one step."),
      el("p", "sub", "Noir runs on this computer, on a model that fits it. Nothing you say leaves it."),
      el("ul", "setup-computer", ...(data.hardware || []).map((line) => el("li", "", line))),
    ];
    const ollamaStatus = data.ollama === "running" ? "Installed and running"
      : data.ollama === "stopped" ? "Installed, will be started"
      : data.can_install ? `Will be downloaded from ollama.com (about ${data.ollama_gb} GB)` : "Not installed";
    const modelWhat = model
      ? `${model.name} · ${model.download_gb} GB to download · uses about ${model.memory_gb} GB of ${data.device}`
      : data.reason || "";
    parts.push(el("div", "setup-steps",
      row(1, "Ollama", "The free program that runs AI models on this computer.", ollamaStatus,
          data.step === "ollama", data.ollama === "running"),
      row(2, "A model for this computer", modelWhat, model ? (model.have ? "Downloaded" : "Will be downloaded") : "None fits",
          data.step === "model", Boolean(model && model.have)),
      row(3, "Noir", "Built from the model, with how it talks and what it knows about this computer.",
          data.noir ? "Ready" : "Will be built", data.step === "noir", Boolean(data.noir))));
    if (data.waiting) parts.push(el("p", "setup-waiting", data.waiting));
    if (data.error) parts.push(el("p", "setup-error", data.error));

    const actions = el("div", "actions");
    if (!data.needed) actions.append(button("solid-button", "Start", finish));
    else if (data.working) actions.append(el("span", "setup-patience", "This can take a few minutes. You can leave it running."));
    else {
      if (model || data.ollama !== "running") {
        actions.append(button("solid-button", data.error ? "Try again" : "Set up Noir", () => begin(false)));
      }
      if (!model && data.ollama === "running") {
        actions.append(button("line-button", "Use the smallest model anyway", () => begin(true)));
      }
      if (!data.can_install && data.ollama === "missing") {
        actions.append(button("line-button", "Get Ollama from ollama.com", () => pywebview.api.open_link(data.download_page)));
      }
    }
    parts.push(actions);
    $("view-setup").replaceChildren(...parts);
  }

  return { open };
})();
