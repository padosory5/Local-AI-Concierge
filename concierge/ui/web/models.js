// Models: the menu by the chat box and the Models page. The menu keeps models on
// this computer apart from API ones. The page finds new ones on Hugging Face, and
// edits what the menu shows. Python decides what fits and does all the fetching.

window.modelPage = (() => {
  const { el, button, icon } = today.ui;
  const { tabs, searchBox, filters, segments, hero, card, tag, section } = discover;
  const $ = (id) => document.getElementById(id);
  const page = () => $("view-models");
  const FITS = { fits: "Fits this computer", slow: "Bigger than your graphics memory", no_disk: "Not enough disk space" };
  const SORTS = [{ id: "downloads", words: "Most downloaded" }, { id: "likes", words: "Most liked" }, { id: "new", words: "Newest" }];
  const OPEN_LICENSES = ["mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause"];
  const KINDS = [{ id: "", words: "All" }, { id: "fits", words: "Fits this computer" }, { id: "code", words: "Code" }, { id: "vision", words: "Sees pictures" }];

  let models = {}; // what Python says is on offer
  let tab = "discover";
  let sort = "downloads";
  let kind = "";
  let words = "";
  let found = [];
  let problem = "";
  let looking = 0; // only the newest search is drawn
  let results = null;
  let jobs = []; // what's downloading
  let watching = 0;

  // -------------------------------------------------- who is answering

  function label() {
    return models.current ? models.current.name : models.own || "";
  }

  function privacy() {
    const now = models.current;
    if (!now || now.here) return "Everything stays on this computer.";
    return `What you say to Elaina goes to ${now.company}. Highlights and your document agents stay on this computer.`;
  }

  function drawNames() {
    const now = models.current;
    $("model-name").textContent = label();
    $("model").classList.toggle("cloud", Boolean(now) && !now.here);
    // Only models on this computer can show their thinking.
    $("think").hidden = Boolean(now) && now.provider !== "local";
    $("privacy").textContent = privacy();
    $("side-model").textContent = !now || now.here ? `${label()} on this computer` : `${now.name}, ${now.company}`;
    app.setModelName(label());
  }

  async function load(data) {
    models = data || (await pywebview.api.models()) || {};
    drawNames();
    today.redraw();
  }

  async function choose(provider, model) {
    today.closeMenus();
    await load(await pywebview.api.pick_model(provider, model));
  }

  // -------------------------------------------------------------- the menu

  function pickRow(name, note, here, onClick) {
    const row = button(`pick ${here ? "now" : ""}`, "", onClick);
    row.append(el("span", "pick-name", name), el("span", "pick-note", note));
    return row;
  }

  function isHere(provider, model) {
    return Boolean(models.current) && models.current.provider === provider && models.current.model === model;
  }

  function localRows() {
    const shown = (models.local || []).filter((item) => !item.hidden);
    const own = shown.find((item) => item.own);
    const rows = [pickRow(models.own, "Elaina's own", !models.current, () => choose("", ""))];
    if (own) shown.splice(shown.indexOf(own), 1);
    rows.push(...shown.map((item) => pickRow(item.name, item.detail, isHere("local", item.id), () => choose("local", item.id))));
    return rows;
  }

  // Models from a company the user chose to add a key for (optional, on the Models page).
  function keyedRows() {
    const rows = [];
    for (const company of models.providers || []) {
      const shown = company.models.filter((model) => !model.hidden);
      if (!company.has_key || !shown.length) continue;
      rows.push(el("div", "pick-label", `${company.company}, with your key`));
      rows.push(...shown.map((model) => pickRow(model.name, "", isHere(company.id, model.id), () => choose(company.id, model.id))));
      const more = button("pick pick-more", "More models", async () => {
        more.textContent = "Asking...";
        const list = await pywebview.api.more_models(company.id);
        const extra = list.map((model) => pickRow(model.name, "", false, () => choose(company.id, model.id)));
        more.replaceWith(...(extra.length ? extra : [el("div", "pick-note pick-none", "No others to show")]));
      });
      rows.push(more);
    }
    const custom = (models.custom || []).filter((item) => !item.hidden);
    if (custom.length) {
      rows.push(el("div", "pick-label", "Your own"),
                ...custom.map((item) => pickRow(item.name, "", isHere("custom", item.id), () => choose("custom", item.id))));
    }
    return rows;
  }

  // A plan the user already has, used through the company's own app: signed in once, no key.
  function planRows() {
    const rows = [];
    for (const plan of models.accounts || []) {
      rows.push(el("div", "pick-label", `Your ${plan.name} plan`));
      if (plan.signed_in) rows.push(...plan.models.map((model) => pickRow(model.name, "", isHere(plan.id, model.id), () => choose(plan.id, model.id))));
      else rows.push(pickRow(`Use ${plan.plan}`, plan.installed ? "Sign in" : `Get ${plan.app}`, false, () => open("api", `plan-${plan.id}`)));
    }
    return rows;
  }

  // One plain list: this computer, then the user's plans, then anything they added a key for.
  function drawMenu() {
    const list = el("div", "pick-list", el("div", "pick-label", "On this computer"), ...localRows(), ...planRows(), ...keyedRows());
    const foot = el("div", "pick-foot",
                    button("pick-link", "Discover", () => open("discover")),
                    button("pick-link", "Manage models", () => open("local")),
                    button("pick-link", "Use an API key", () => open("api")));
    $("model-menu").replaceChildren(list, foot);
  }

  // ------------------------------------------------- finding on Hugging Face

  function short(number) {
    if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
    return number >= 1000 ? `${Math.round(number / 1000)}K` : String(number);
  }

  function jobFor(model) {
    return jobs.find((job) => job.tag === model.tag);
  }

  function getButton(model, big) {
    if (model.have) return el("span", "added", "On this computer");
    const job = jobFor(model);
    if (job) {
      const stop = button("quiet-button", job.error ? "Dismiss" : "Stop", () => cancel(job.tag));
      return el("div", "getting", counter("getting-words", job, job.error ? "Failed" : ""), stop);
    }
    if (model.fit === "no_disk") return el("span", "added warn", "No room");
    const get = async () => {
      const reply = await pywebview.api.get_model(model.tag);
      if (reply.error) window.alert(reply.error);
      await watch();
    };
    if (big && model.fit === "fits") return button("solid-button", `Get it (${model.size_gb} GB)`, get);
    // A model can be huge, so the first click only says how big, and asks.
    const ask = button(big ? "solid-button" : "plus-button", big ? `Get it (${model.size_gb} GB)` : "", () => {
      if (ask.dataset.sure) {
        get();
        return;
      }
      ask.dataset.sure = "yes";
      ask.className = "solid-button";
      ask.textContent = `Download ${model.size_gb} GB?`;
      setTimeout(() => {
        if (ask.isConnected) ask.replaceWith(getButton(model, big));
      }, 4000);
    });
    if (!big) ask.append(icon("plus"));
    ask.title = `Get it: ${model.size_gb} GB download`;
    ask.setAttribute("aria-label", `Get ${model.name}`);
    return ask;
  }

  // Shows how far a download has got, and keeps itself up to date (see tick).
  function counter(className, job, fixed, before = "") {
    const node = el("span", className, fixed || `${before}${percent(job)}`);
    if (!fixed) {
      node.dataset.tag = job.tag;
      node.dataset.before = before;
    }
    return node;
  }

  function percent(job) {
    return `${job.total ? Math.round((job.done / job.total) * 100) : 0}%`;
  }

  function modelTags(model) {
    const fit = tag(FITS[model.fit], model.fit === "fits" ? "strong" : "warn");
    const list = [fit, tag(`${model.size_gb} GB`), tag(`${short(model.downloads)} downloads`), tag(`${short(model.likes)} likes`)];
    if (model.vision) list.push(tag("Sees pictures"));
    return list;
  }

  function about(model) {
    const job = jobFor(model);
    if (job && job.error) return job.error;
    if (OPEN_LICENSES.includes(model.license)) return "Free to use, even for work.";
    return model.license ? "Has its own license. Check it before using it for work." : "Runs on this computer through Ollama.";
  }

  function modelCard(model) {
    return card({ by: model.author, name: model.name, about: about(model), tags: modelTags(model), action: getButton(model) });
  }

  function drawResults() {
    if (!results || tab !== "discover") return;
    if (problem) {
      results.replaceChildren(el("div", "nothing", problem));
      return;
    }
    const shown = kind === "fits" ? found.filter((model) => model.fit === "fits") : found;
    if (!shown.length) {
      results.replaceChildren(el("div", "nothing", looking ? "Looking on Hugging Face..." : "Nothing found. Try other words."));
      return;
    }
    const parts = [];
    if (!words.trim()) {
      parts.push(el("h1", "disc-heading", "Discover Models"));
      parts.push(hero(shown.slice(0, 4), (model) => ({ by: model.author, name: model.name, about: about(model), tags: modelTags(model),
                                                       action: getButton(model, true) })));
    }
    const name = SORTS.find((item) => item.id === sort).words;
    parts.push(section(words.trim() ? `Found ${shown.length}` : name, "From Hugging Face, with the ones that fit this computer first.",
                       shown.slice(words.trim() ? 0 : 4).map(modelCard)));
    results.replaceChildren(...parts);
  }

  async function search() {
    const ticket = ++looking;
    problem = "";
    found = [];
    drawResults();
    const reply = (await pywebview.api.browse_models(words, sort, kind === "fits" ? "" : kind)) || {};
    if (ticket !== looking) return;
    looking = 0;
    found = reply.models || [];
    problem = reply.error || "";
    drawResults();
  }

  let typing = 0;
  function typed(value) {
    words = value;
    clearTimeout(typing);
    typing = setTimeout(search, 400);
  }

  // ------------------------------------------------------------- downloads

  async function cancel(tag_) {
    await pywebview.api.cancel_download(tag_);
    await tick();
  }

  // A big model takes minutes, so the page keeps asking how far it's got.
  async function tick() {
    const state = () => jobs.map((job) => `${job.tag} ${job.error}`).join();
    const before = jobs.length;
    const was = state();
    jobs = (await pywebview.api.downloads()) || [];
    if (jobs.length < before) {
      await load();
      const have = new Set((models.local || []).map((item) => item.id));
      for (const model of found) model.have = have.has(model.tag);
    }
    // Only the numbers change most of the time, so only they are touched.
    if (state() !== was && results) drawTab();
    for (const node of document.querySelectorAll("[data-tag]")) {
      const job = jobs.find((one) => one.tag === node.dataset.tag);
      if (job) node.textContent = `${node.dataset.before}${percent(job)}`;
    }
    if (!jobs.length) {
      clearInterval(watching);
      watching = 0;
    }
  }

  async function watch() {
    await tick();
    if (!watching && jobs.length) watching = setInterval(tick, 900);
  }

  // ------------------------------------------------------- editing the menu

  function showSwitch(provider, model, hidden, name) {
    const toggle = button(`mini-switch ${hidden ? "" : "on"}`, "", async () => {
      await load(await pywebview.api.hide_model(provider, model, !hidden));
      drawTab();
    });
    toggle.title = hidden ? "Show it in the menu" : "Hide it from the menu";
    toggle.setAttribute("aria-label", `${name}: ${hidden ? "hidden from" : "shown in"} the menu`);
    return toggle;
  }

  function addLocal() {
    const box = el("input", "cloud-key");
    box.id = "custom-first";
    box.placeholder = "A model name, or a Hugging Face link";
    box.autocomplete = "off";
    const note = el("div", "cloud-note");
    const get = button("line-button", "Get it", async () => {
      const reply = await pywebview.api.get_model(box.value);
      note.textContent = reply.error || "";
      if (!reply.error) {
        box.value = "";
        await watch();
      }
    });
    return el("div", "add-custom", el("h2", "", "Add custom model"), el("div", "cloud-row", box, get), note);
  }

  function drawLocal() {
    const rows = (models.local || []).map((item) => {
      const here = item.own ? !models.current : isHere("local", item.id);
      const use = here ? el("span", "added", "In use") : button("line-button", "Use it", async () => {
        await choose(item.own ? "" : "local", item.own ? "" : item.id);
        drawTab();
      });
      const row = el("div", "agent-line", el("span", "open still", el("span", "words", el("span", "name", item.name),
                                             el("span", "does", item.own ? `Elaina's own · ${item.detail}` : item.detail))), use);
      if (!item.own) {
        row.append(showSwitch("local", item.id, item.hidden, item.name));
        const remove = button("item-delete", "×", async () => {
          if (!remove.classList.contains("confirm")) {
            remove.classList.add("confirm");
            remove.textContent = "Delete?";
            setTimeout(() => {
              remove.classList.remove("confirm");
              remove.textContent = "×";
            }, 3000);
            return;
          }
          const reply = await pywebview.api.delete_model(item.id);
          if (!reply.error) {
            await load(reply);
            drawTab();
          }
        });
        remove.title = "Delete it from this computer";
        remove.setAttribute("aria-label", `Delete ${item.name}`);
        row.append(remove);
      }
      return row;
    });
    const waiting = jobs.map((job) => {
      return el("div", "agent-line", el("span", "open still", el("span", "words", el("span", "name", job.tag),
                                        counter("does", job, job.error, "Getting it: "))),
                button("quiet-button", job.error ? "Dismiss" : "Stop", () => cancel(job.tag)));
    });
    results.replaceChildren(el("p", "sub", "Free, and everything stays on this computer. The switch shows a model in the menu, or hides it."), ...rows, ...waiting, addLocal());
  }

  // A ChatGPT or Claude plan, used through the company's own app (accounts.py).
  function planRow(plan) {
    const row = el("div", "cloud-row", el("div", "cloud-name", `${plan.name} plan`, el("span", "cloud-company", `through ${plan.app}`)));
    row.id = `plan-${plan.id}`;
    const note = el("div", "cloud-note");
    const check = async () => {
      note.textContent = "Checking...";
      await load(await pywebview.api.check_accounts());
      drawTab();
    };
    if (plan.signed_in) {
      row.append(el("span", "cloud-saved", "Signed in"));
    } else if (plan.installed) {
      row.append(button("solid-button", "Sign in", async () => {
        const reply = await pywebview.api.sign_in_account(plan.id);
        if (reply.error) note.textContent = reply.error;
        else note.replaceChildren(`${plan.sign_in}. `, button("quiet-button", "I've signed in", check));
      }));
    } else {
      row.append(button("line-button", `Get ${plan.app}`, async () => {
        await pywebview.api.install_account(plan.id);
        note.replaceChildren(plan.id === "claude_code" ? "It's installing in the window that opened. When it's done, " : "Get it from OpenAI's page. When it's installed, ",
                             button("quiet-button", "Check again", check));
      }));
    }
    const lines = plan.signed_in ? plan.models.map((model) => el("div", "model-line", el("span", "", model.name)))
                                 : [el("div", "model-line", el("span", "", plan.installed ? plan.sign_in : `Needs ${plan.app}, ${plan.name}'s own app`))];
    return el("div", "cloud-item", row, note, el("div", "model-lines", ...lines));
  }

  function keyRow(company) {
    const row = el("div", "cloud-row", el("div", "cloud-name", company.name, el("span", "cloud-company", company.note || company.company)));
    const note = el("div", "cloud-note");
    if (company.has_key) {
      row.append(el("span", "cloud-saved", "Key saved"), button("quiet-button", "Remove", async () => {
        await load(await pywebview.api.forget_key(company.id));
        drawTab();
      }));
    } else {
      const box = el("input", "cloud-key");
      box.id = `key-${company.id}`;
      box.type = "password";
      box.placeholder = "Paste your key";
      box.autocomplete = "off";
      box.setAttribute("aria-label", `${company.name} key`);
      const save = button("line-button", "Save", async () => {
        note.textContent = "Checking...";
        const reply = await pywebview.api.save_key(company.id, box.value);
        box.value = "";
        if (reply.error) note.textContent = reply.error;
        else {
          await load(reply);
          drawTab();
        }
      });
      box.addEventListener("keydown", (event) => {
        if (event.key === "Enter") save.click();
      });
      row.append(box, save, button("quiet-button", "Get a key", () => pywebview.api.open_key_page(company.id)));
    }
    const list = company.models.map((model) => el("div", "model-line", el("span", "", model.name),
                                                  showSwitch(company.id, model.id, model.hidden, model.name)));
    return el("div", "cloud-item", row, note, el("div", "model-lines", ...list));
  }

  function addCustom() {
    const field = (words_, hint, type = "text") => {
      const box = el("input");
      box.type = type;
      box.placeholder = hint;
      box.autocomplete = "off";
      return { box, label: el("label", "", words_, box) };
    };
    const name = field("Name", "My model");
    const url = field("Address", "https://example.com/v1");
    const model = field("Model", "The name the service uses for it");
    const key = field("Key, if it needs one", "Paste your key", "password");
    url.box.id = "custom-first";
    const note = el("p", "book-error");
    note.hidden = true;
    const form = el("form", "book", name.label, url.label, model.label, key.label);
    const save = button("solid-button", "Add it", () => {});
    save.type = "submit";
    form.append(save);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const reply = await pywebview.api.add_custom_model(name.box.value, url.box.value, model.box.value, key.box.value);
      key.box.value = "";
      note.hidden = !reply.error;
      note.textContent = reply.error || "";
      if (!reply.error) {
        await load(reply);
        drawTab();
      }
    });
    return el("div", "add-custom", el("h2", "", "Add custom model"),
              el("p", "hint-line", "For any service that talks the way OpenAI's does, including programs on this computer like LM Studio."), form, note);
  }

  function drawApi() {
    const custom = (models.custom || []).map((item) => {
      const remove = button("item-delete", "×", async () => {
        await load(await pywebview.api.remove_custom_model(item.id));
        drawTab();
      });
      remove.title = "Remove it";
      remove.setAttribute("aria-label", `Remove ${item.name}`);
      return el("div", "agent-line", el("span", "open still", el("span", "words", el("span", "name", item.name),
                                        el("span", "does", `${item.model} at ${item.url}`))),
                showSwitch("custom", item.id, item.hidden, item.name), remove);
    });
    results.replaceChildren(el("p", "hint-line", "Sign in with a ChatGPT or Claude account and its models are in the menu beside the chat box: no key needed. What you say to Elaina then goes to that company."),
                            el("h2", "", "Your plans"), el("div", "cloud-list", ...(models.accounts || []).map(planRow)),
                            ...(custom.length ? [el("h2", "", "Your own"), ...custom] : []),
                            el("h2", "", "With an API key (optional)"), el("p", "sub", "Only if you already pay a company for its API. Most people never need this."), el("div", "cloud-list", ...(models.providers || []).map(keyRow)), addCustom());
  }

  // ------------------------------------------------------------------ the page

  function drawTab() {
    if (tab === "local") drawLocal();
    else if (tab === "api") drawApi();
    else drawResults();
  }

  function drawPage() {
    const counted = (models.local || []).length;
    const top = el("div", "disc-bar", tabs([{ id: "discover", words: "Discover" }, { id: "local", words: "On this computer", count: counted },
                                            { id: "api", words: "Accounts" }], tab, (id) => {
      tab = id;
      drawPage();
      if (id === "discover" && !found.length) search();
    }));
    results = el("div", "disc-results");
    if (tab !== "discover") {
      page().replaceChildren(top, results);
      drawTab();
      return;
    }
    const controls = el("div", "disc-controls",
                        segments(SORTS, sort, (id) => {
                          sort = id;
                          drawPage();
                          search();
                        }),
                        filters(KINDS, kind, (id) => {
                          const asks = kind !== id && (id === "code" || id === "vision" || kind === "code" || kind === "vision");
                          kind = id;
                          drawPage();
                          if (asks) search();
                        }));
    page().replaceChildren(top, searchBox('Try "qwen"', words, typed), controls, results);
    drawResults();
  }

  // Opens the page at a tab, and puts the cursor in a box on it if asked.
  function open(which, focus) {
    if (which) tab = which;
    today.closeMenus();
    if (document.body.dataset.view !== "models") {
      today.show("models"); // which draws the page, by coming back here
    } else {
      drawPage();
      if (tab === "discover" && !found.length) search();
    }
    if (focus && $(focus)) {
      $(focus).scrollIntoView({ block: "center" });
      $(focus).focus();
    }
    watch();
  }

  return { load, privacy, drawMenu, open, label };
})();
