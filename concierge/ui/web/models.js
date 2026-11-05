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
  let usage = {}; // how much each plan or key has used (usage.py)
  let tab = "discover";
  let keysOpen = false; // "Have an API key instead?" was pressed
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

  // A beginner only ever has her own model, so the pill says where she is, not what
  // she runs on. Model names stay inside the menu and the Models page.
  function label() {
    return models.current ? models.current.name : "This computer";
  }

  function privacy() {
    const now = models.current;
    if (!now || now.here) return "Everything stays on this computer.";
    if (now.auto) {
      return `Small questions stay on this computer. Harder ones go to ${now.company}. `
        + "Highlights and your document agents stay on this computer.";
    }
    return `What you say to Elaina goes to ${now.company}. Highlights and your document agents stay on this computer.`;
  }

  function drawNames() {
    const now = models.current;
    $("model-name").textContent = label();
    $("model").classList.toggle("cloud", Boolean(now) && !now.here);
    // Only models on this computer can show their thinking.
    // With Auto her own model answers small things, and it can.
    $("think").hidden = Boolean(now) && now.provider !== "local" && !now.auto;
    $("privacy").textContent = privacy();
    $("side-model").textContent = !now ? "Elaina · on this computer" : now.here ? `${now.name} on this computer`
      : now.auto ? `Auto: ${models.own} or ${now.cloud.name}` : `${now.name}, ${now.company}`;
    app.setModelName(label());
    drawUsage();
  }

  async function load(data) {
    models = data || (await pywebview.api.models()) || {};
    drawNames();
    loadUsage();
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
      const limits = plan.signed_in && usage[plan.id] ? usage[plan.id].limits : [];
      if (limits.length) rows.push(el("div", "pick-usage", ...limits.map((window) => meter(window, true))));
      if (plan.signed_in) rows.push(...plan.models.map((model) => pickRow(model.name, "", isHere(plan.id, model.id), () => choose(plan.id, model.id))));
      else rows.push(pickRow(`Use ${plan.plan}`, plan.installed ? "Sign in" : `Get ${plan.app}`, false, () => open("api", `plan-${plan.id}`)));
    }
    return rows;
  }

  // Auto (auto.py): Elaina answers small things herself and sends the rest to a plan
  // or key. Only offered once there's a plan or key to send things to.
  function autoRows() {
    const target = models.auto || {};
    if (!target.cloud) return [];
    const row = pickRow("Auto", `${models.own} or ${target.cloud}`, Boolean(models.current && models.current.auto),
                        () => choose("auto", ""));
    row.title = `Small questions stay on this computer. Code, long writing and harder questions go to ${target.cloud}, `
      + "to save your plan. Pick another plan model below, then Auto again, to change which one.";
    return [row];
  }

  // One plain list: Auto, this computer, then the user's plans, then anything they added a key for.
  function drawMenu() {
    const list = el("div", "pick-list", ...autoRows(), el("div", "pick-label", "On this computer"), ...localRows(),
                    ...planRows(), ...keyedRows());
    const foot = el("div", "pick-foot",
                    button("pick-link", "Discover", () => open("discover")),
                    button("pick-link", "Manage models", () => open("local")),
                    button("pick-link", "Use an API key", () => open("keys")));
    $("model-menu").replaceChildren(list, foot);
  }

  // ------------------------------------------------------- how much is used
  // The plan's own numbers (the same ones /usage shows in Claude Code) when its app
  // reports them, and the tokens her answers used, counted here (usage.py).

  function tokens(count) {
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 10000) return `${Math.round(count / 1000)}k`;
    return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
  }

  function whenAgain(seconds) {
    if (!seconds) return "";
    const at = new Date(seconds * 1000);
    const time = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const sameDay = at.toDateString() === new Date().toDateString();
    return sameDay ? time : `${at.toLocaleDateString([], { weekday: "short" })} ${time}`;
  }

  // The usage of whatever is answering now, or null for a model on this computer.
  function usageNow() {
    const now = models.current;
    if (!now || now.here) return null;
    const source = now.auto ? now.cloud.provider : now.provider; // Auto spends the plan it sends to
    return { source, ...(usage[source] || { limits: [] }) };
  }

  // One window of a plan: a name, a bar, and when it starts again.
  function meter(window, small) {
    const used = Math.round(window.used * 100);
    const bar = el("span", "meter-bar", el("span", "meter-fill"));
    bar.firstChild.style.width = `${Math.max(used, used ? 2 : 0)}%`;
    const again = whenAgain(window.resets_at);
    const row = el("div", `meter ${window.nearly_full ? "full" : ""} ${small ? "small" : ""}`,
                   el("span", "meter-name", window.name), bar, el("span", "meter-used", `${used}% used`));
    if (!small && again) row.append(el("span", "meter-again", `starts again ${again}`));
    row.title = `${window.name}: ${used}% of your plan used${again ? `, starts again ${again}` : ""}`;
    return row;
  }

  // Tokens her answers used, in plain words.
  function tokenLines(mine, viaApp) {
    const lines = [];
    const today = mine.today || {};
    if (today.answers) {
      lines.push(el("div", "usage-line", `Today: ${today.answers} ${today.answers === 1 ? "answer" : "answers"}, `
                    + `${tokens(today.read)} tokens read, ${tokens(today.wrote)} written`));
    }
    if (mine.week && mine.week.answers > (today.answers || 0)) {
      lines.push(el("div", "usage-line", `This week: ${tokens(mine.week.read)} read, ${tokens(mine.week.wrote)} written`));
    }
    if (mine.last) {
      // The apps send their own long instructions with every question, so most of
      // what's read is theirs: worth saying, or the numbers look wrong.
      const why = viaApp ? ` (most of that is ${viaApp}'s own instructions, sent each time)` : "";
      lines.push(el("div", "usage-line faint", `Last answer: ${tokens(mine.last.read)} read, ${tokens(mine.last.wrote)} written${why}`));
    }
    return lines;
  }

  // Tokens Auto kept off this plan or key by answering on this computer, as a blue
  // bar: how much of everything this week's questions took stayed here.
  function savedMeter(mine) {
    const week = mine.week || {};
    if (!week.saved) return null;
    const spent = (week.read || 0) + (week.wrote || 0);
    const share = Math.round((100 * week.saved) / (week.saved + spent));
    const bar = el("span", "meter-bar", el("span", "meter-fill"));
    bar.firstChild.style.width = `${Math.max(share, 2)}%`;
    const today = (mine.today || {}).saved || 0;
    const row = el("div", "meter saved", el("span", "meter-name", "Saved this week"), bar,
                   el("span", "meter-used", `${tokens(week.saved)} tokens`),
                   el("span", "meter-again", `${share}% of this week's tokens stayed on this computer`
                      + (today ? `, ${tokens(today)} of them today` : "")));
    row.title = "Answered on this computer by Auto instead of being sent here. About what those answers would "
      + "have used, counting the instructions the plan's app sends with every question.";
    return row;
  }

  // The block on the Accounts page, like /usage in Claude Code.
  function usageBlock(source, viaApp) {
    const mine = usage[source];
    if (!mine) return el("div", "usage-block", el("div", "usage-line faint", "Nothing used through Elaina yet."));
    const parts = mine.limits.map((window) => meter(window, false));
    if (viaApp && !mine.limits.length) {
      parts.push(el("div", "usage-line faint", `${viaApp} hasn't said how much of your plan is left yet.`));
    }
    const saved = savedMeter(mine);
    return el("div", "usage-block", ...parts, ...(saved ? [saved] : []), ...tokenLines(mine, viaApp));
  }

  // The small meter beside the model button: the fullest window of the plan answering
  // now, or today's tokens for an API key. Hidden for models on this computer.
  function drawUsage() {
    const pill = $("usage");
    if (!pill) return;
    const now = usageNow();
    const fullest = now && now.limits.length ? now.limits.reduce((a, b) => (b.used > a.used ? b : a)) : null;
    const today = now && now.today && now.today.answers ? now.today : null;
    pill.hidden = !fullest && !today;
    if (pill.hidden) return;
    pill.classList.toggle("full", Boolean(fullest && fullest.nearly_full));
    if (fullest) {
      const used = Math.round(fullest.used * 100);
      pill.style.setProperty("--used", `${used * 3.6}deg`);
      pill.querySelector(".usage-ring").hidden = false;
      pill.querySelector(".usage-words").textContent = `${used}%`;
      const all = now.limits.map((w) => `${w.name}: ${Math.round(w.used * 100)}% used`).join("\n");
      pill.title = `${all}\nClick for more`;
    } else {
      pill.querySelector(".usage-ring").hidden = true;
      pill.querySelector(".usage-words").textContent = `${tokens(today.read + today.wrote)} today`;
      pill.title = `Tokens used today: ${tokens(today.read)} read, ${tokens(today.wrote)} written\nClick for more`;
    }
  }

  async function loadUsage() {
    try {
      usage = (await pywebview.api.usage()) || {};
    } catch {
      usage = {};
    }
    drawUsage();
    if (document.body.dataset.view === "models" && tab === "api") drawTab();
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
    // A key has no plan limits to show, only what her answers used; what's left is
    // credit on the company's own website.
    const mine = company.has_key && usage[company.id];
    const kept = mine ? savedMeter(mine) : null;
    const used = mine ? el("div", "usage-block", ...(kept ? [kept] : []), ...tokenLines(mine, "")) : "";
    return el("div", "cloud-item", row, note, used, el("div", "model-lines", ...list));
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

  // One account on the Accounts page: a plan, used through the company's own app (accounts.py).
  function accountRow(plan) {
    const connected = plan.signed_in && !plan.hidden;
    const note = el("div", "account-note");
    const check = async () => {
      note.textContent = "Checking...";
      await load(await pywebview.api.check_accounts());
      drawTab();
    };
    const about = connected ? `Through ${plan.app}. Its models are in the menu beside the chat box.`
      : plan.signed_in ? `You're signed in to ${plan.app}. Click to use it here again.`
      : plan.installed ? `${plan.sign_in}, through ${plan.app}`
      : `Needs ${plan.app}, ${plan.name}'s own app. Click to get it, then sign in.`;
    const title = el("div", "account-title", el("b", "", `${plan.name} account`),
                     connected ? el("span", "account-badge", "✓ Connected") : "");
    let act = el("span", "account-go", "›");
    if (connected) {
      act = button("item-delete", "×", async () => {
        await load(await pywebview.api.use_account(plan.id, false));
        drawTab();
      });
      act.title = `Stop using it in Elaina. You stay signed in to ${plan.app}.`;
      act.setAttribute("aria-label", act.title);
    }
    const words = el("div", "account-words", title, el("span", "", about), note);
    if (connected) words.append(usageBlock(plan.id, plan.app));
    const row = el("div", `account-row ${connected ? "" : "clickable"}`, words, act);
    row.id = `plan-${plan.id}`;
    if (!connected) {
      row.addEventListener("click", async (event) => {
        if (event.target.closest("button")) return;
        if (plan.signed_in) {
          await load(await pywebview.api.use_account(plan.id, true));
          drawTab();
        } else if (!plan.installed) {
          await pywebview.api.install_account(plan.id);
          note.replaceChildren(plan.id === "claude_code" ? "It's installing in the window that opened. When it's done, " : "Get it from OpenAI's page. When it's installed, ",
                               button("quiet-button", "check again", check));
        } else {
          const reply = await pywebview.api.sign_in_account(plan.id);
          if (reply.error) note.textContent = reply.error;
          else note.replaceChildren("Finish signing in in your browser, then ", button("quiet-button", "I've signed in", check));
        }
      });
    }
    return row;
  }

  // Accounts, the way people already know it: connect with what they have, no keys.
  function accountsPage() {
    const plans = models.accounts || [];
    const connected = plans.filter((plan) => plan.signed_in && !plan.hidden);
    const others = plans.filter((plan) => !(plan.signed_in && !plan.hidden));
    const local = el("div", "account-row account-card clickable",
                     el("div", "account-words", el("div", "account-title", el("b", "", "Run models locally")),
                        el("span", "", "No account needed: download a model and run it on this computer")),
                     el("span", "account-go", "›"));
    local.addEventListener("click", () => open("discover"));
    results.replaceChildren(
      el("div", "accounts-head",
         el("div", "", el("h2", "", "Connect an account"),
            el("p", "sub", "Sign in with your ChatGPT or Claude account: no API key to copy. Elaina opens the sign-in for you.")),
         button("link-button", "Have an API key instead?", () => open("keys"))),
      local,
      ...(connected.length ? [el("div", "account-label", "Connected"), ...connected.map(accountRow)] : []),
      ...(others.length ? [el("div", "account-label", connected.length ? "Other accounts" : "Accounts"), ...others.map(accountRow)] : []));
  }

  // Only for people who already pay a company for its API.
  function keysPage() {
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
    results.replaceChildren(
      button("link-button back-link", "‹ Accounts", () => open("api")),
      el("h2", "", "API keys"),
      el("p", "sub", "Only if you already pay a company for its API. Paste the key, and its models join the menu beside the chat box. Keys are kept in Windows' own password store."),
      el("div", "cloud-list", ...(models.providers || []).map(keyRow)),
      ...(custom.length ? [el("h2", "", "Your own"), ...custom] : []),
      addCustom());
  }

  function drawApi() {
    if (keysOpen) keysPage();
    else accountsPage();
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
    keysOpen = which === "keys";
    if (which) tab = which === "keys" ? "api" : which;
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

  // The meter was clicked: the plan's row on Accounts, or the keys page for a key.
  function openUsage() {
    const now = models.current;
    const source = now && (now.auto ? now.cloud.provider : now.provider);
    const plan = now && (models.accounts || []).some((item) => item.id === source);
    if (plan) open("api", `plan-${source}`);
    else open("keys");
  }

  return { load, privacy, drawMenu, open, label, loadUsage, openUsage };
})();
