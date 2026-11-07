// The Agents page: the agents people have made, to discover and add, and the
// user's own. Its search, filters, big card and rows of small cards are shared with
// the Models page (models.js). Python says what there is; this only shows it.

window.discover = (() => {
  const { el, button, icon, dots, miniSwitch, stateOf, openAgent, agentState } = today.ui;
  const $ = (id) => document.getElementById(id);
  const page = () => $("view-agents");

  let tab = "discover";
  let recipes = [];
  let categories = [];
  let grouping = "category"; // sorted by category, or by who made it
  let filter = "All";
  let words = "";
  let results = null; // the part that's redrawn, so the search box keeps its place

  // ------------------------------------------------------- parts both pages use

  function tabs(items, current, pick) {
    return el("div", "tabs", ...items.map(({ id, words: label, count }) => {
      const item = button(`tab ${id === current ? "now" : ""}`, label, () => pick(id));
      if (count) item.append(el("span", "tab-count", String(count)));
      return item;
    }));
  }

  function searchBox(hint, value, onInput) {
    const box = el("input");
    box.type = "search";
    box.placeholder = hint;
    box.value = value;
    box.setAttribute("aria-label", hint);
    box.addEventListener("input", () => onInput(box.value));
    return el("label", "disc-search", icon("search"), box);
  }

  function filters(items, current, pick) {
    return el("div", "filters", ...items.map(({ id, words: label }) =>
      button(`filter ${id === current ? "now" : ""}`, label, () => pick(id))));
  }

  function segments(items, current, pick) {
    return el("div", "segments", ...items.map(({ id, words: label }) =>
      button(`segment ${id === current ? "now" : ""}`, label, () => pick(id))));
  }

  // A picture from each thing's own name: the same print dots as the rest of the app.
  function art(name) {
    let seed = 7;
    for (const letter of name) seed = (seed * 31 + letter.charCodeAt(0)) % 9973;
    const canvas = el("canvas", "hero-art");
    canvas.width = 840;
    canvas.height = 520;
    const middleX = 310 + (seed % 90);
    const middleY = 70 + (seed % 120);
    const slant = 0.012 + (seed % 7) / 500;
    // The light runs off the card's far edge and fades towards the words.
    dots(canvas, 420, 260, 6.4, (x, y) => {
      const light = Math.max(0, 1 - Math.hypot(x - middleX, (y - middleY) * 1.15) / 330);
      const bands = 0.72 + 0.28 * Math.sin((x + y * 1.7) * slant + seed);
      return light ** 1.3 * bands * Math.min(1, x / 150);
    });
    return canvas;
  }

  // The big card at the top, one thing at a time.
  function hero(items, drawOne) {
    let at = 0;
    const holder = el("div", "hero-holder");
    function draw() {
      const { by, name, about, tags, action, open } = drawOne(items[at]);
      const words = el("div", "hero-words", el("div", "hero-by", by), el("h2", "hero-name", name),
                       el("p", "hero-about", about), el("div", "hero-foot", el("div", "disc-tags", ...tags), action));
      const body = el("div", "hero");
      body.append(words, art(name));
      body.addEventListener("click", (event) => {
        if (open && !event.target.closest("button")) open();
      });
      const step = (by) => () => {
        at = (at + by + items.length) % items.length;
        draw();
      };
      const nav = el("div", "hero-nav", button("hero-step", "", step(-1)),
                     el("div", "hero-dots", ...items.map((_, index) => el("span", index === at ? "now" : ""))),
                     button("hero-step", "", step(1)));
      nav.firstChild.append(icon("back"));
      nav.firstChild.setAttribute("aria-label", "Previous");
      nav.lastChild.append(icon("forward"));
      nav.lastChild.setAttribute("aria-label", "Next");
      holder.replaceChildren(body, nav);
    }
    if (items.length) draw();
    return holder;
  }

  function card({ by, name, about, tags, action, open }) {
    const words = button("disc-open", "", open || (() => {}));
    words.append(el("span", "disc-name", name), el("span", "disc-about", about));
    return el("div", "disc-card", el("div", "disc-top", el("span", "disc-by", by), action || ""), words,
              el("div", "disc-tags", ...tags));
  }

  const tag = (text, kind = "") => el("span", `disc-tag ${kind}`, text);

  function section(title, note, cards, seeAll) {
    const head = el("div", "disc-head", el("div", "", el("h2", "disc-title", title), el("p", "disc-note", note)));
    if (seeAll) {
      const more = button("see-all", "See all ", seeAll);
      more.append(icon("forward"));
      head.append(more);
    }
    return el("section", "disc-section", head, el("div", "cards", ...cards));
  }

  // ------------------------------------------------------------- adding agents

  function canBeSwitched(recipe) {
    return agentState().switchable.has(recipe.name);
  }

  async function add(recipe) {
    if (await app.addRecipe(recipe.id)) {
      recipe.added = true;
      drawResults();
    }
  }

  function addButton(recipe) {
    if (recipe.added) return el("span", "added", "Added");
    const plus = button("plus-button", "", (event) => {
      event.stopPropagation();
      add(recipe);
    });
    plus.append(icon("plus"));
    plus.title = "Add it";
    plus.setAttribute("aria-label", `Add ${recipe.name}`);
    return plus;
  }

  function heroAction(recipe) {
    if (!recipe.added) {
      return button("solid-button", "Add it", () => add(recipe));
    }
    if (!canBeSwitched(recipe)) return el("span", "added", "Added");
    return el("div", "hero-switch", agentState().active.has(recipe.name) ? "On" : "Off", miniSwitch(recipe.name));
  }

  function recipeTags(recipe) {
    return [tag(recipe.source === "Noir" ? "Ready-made" : "Community", "strong"), tag(recipe.category),
            tag(recipe.when.startsWith("While") ? "Works on highlights" : "Ask it in the chat")];
  }

  function recipeCard(recipe) {
    return card({ by: recipe.by, name: recipe.name, about: recipe.about, tags: recipeTags(recipe),
                  action: addButton(recipe), open: () => openRecipe(recipe) });
  }

  function matching() {
    const wanted = words.trim().toLowerCase();
    return recipes.filter((recipe) => {
      if (filter !== "All" && (grouping === "category" ? recipe.category : recipe.source) !== filter) return false;
      return !wanted || `${recipe.name} ${recipe.about} ${recipe.category}`.toLowerCase().includes(wanted);
    });
  }

  function drawResults() {
    if (!results) return;
    const found = matching();
    if (!found.length) {
      const none = filter === "Community" && !words
        ? "Nothing has been posted yet. Yours could be the first."
        : "Nothing found. Try other words.";
      results.replaceChildren(el("div", "nothing", none));
      return;
    }
    const parts = [];
    if (filter === "All" && !words.trim()) {
      parts.push(el("h1", "disc-heading", "Discover Agents"));
      parts.push(hero(found.slice(0, 4), (recipe) => ({ by: recipe.by, name: recipe.name, about: recipe.about,
                                                        tags: recipeTags(recipe), action: heroAction(recipe),
                                                        open: () => openRecipe(recipe) })));
      const groups = grouping === "category" ? categories : ["Community", "Noir"];
      for (const group of groups) {
        const inGroup = found.filter((recipe) => (grouping === "category" ? recipe.category : recipe.source) === group);
        if (inGroup.length) {
          const title = group === "Noir" ? "Ready-made" : group;
          parts.push(section(title, `${inGroup.length} agent${inGroup.length === 1 ? "" : "s"} to add.`,
                             inGroup.slice(0, 6).map(recipeCard), inGroup.length > 6 ? () => pickFilter(group) : null));
        }
      }
    } else {
      const title = words.trim() ? `Found ${found.length}` : filter === "Noir" ? "Ready-made" : filter;
      parts.push(section(title, `${found.length} agent${found.length === 1 ? "" : "s"} to add.`, found.map(recipeCard)));
    }
    results.replaceChildren(...parts);
  }

  function pickFilter(id) {
    filter = id;
    drawPage();
  }

  function openRecipe(recipe) {
    const facts = [["When it works", recipe.when], ["Made by", recipe.by], ["Category", recipe.category]];
    const back = button("quiet-button back-link", "", drawPage);
    back.append(icon("back"), "All agents");
    const head = el("div", "agent-head", art(recipe.name), el("div", "agent-titles", el("h1", "agent-name", recipe.name),
                    el("div", "agent-state", recipe.about)));
    const box = el("div", "recipe", back, head);
    box.append(el("h2", "", "What it's told to do"), el("p", "agent-does", recipe.instruction));
    box.append(el("div", "facts", ...facts.map(([label, value]) =>
      el("div", "fact", el("div", "label", label), el("div", "value", value)))));
    box.append(el("div", "actions", recipe.added ? el("span", "added", "Added") : button("solid-button", "Add it", async () => {
      await add(recipe);
      openRecipe(recipe);
    })));
    page().replaceChildren(box);
  }

  // ------------------------------------------------------------ the user's own

  async function drawYours() {
    const { agents, switchable, active } = agentState();
    const all = await Promise.all(agents.map((name) => pywebview.api.agent_details(name)));
    if (tab !== "yours") return;
    const rows = agents.map((name, index) => {
      const on = active.has(name);
      const row = el("div", `agent-line ${on ? "on" : ""}`);
      const open = button("open", "", () => openAgent(name));
      open.append(el("span", `dot ${on ? "on" : ""}`),
                  el("span", "words", el("span", "name", name),
                     el("span", "does", (all[index] && all[index].does) || "")));
      row.append(open, el("span", "state", stateOf(name)));
      if (switchable.has(name)) row.append(miniSwitch(name));
      return row;
    });
    results.replaceChildren(
      el("p", "sub", `${agents.length} made for you. ${active.size} on now.`),
      ...(rows.length ? rows : [el("div", "nothing", "No agents yet. Discover some, or make your own.")]),
      el("div", "actions", button("line-button", "Make a new agent", () => today.show("help"))),
    );
  }

  // --------------------------------------------------------------- posting

  function openPost() {
    const { agents } = agentState();
    const choice = el("select");
    choice.append(...agents.map((name) => el("option", "", name)));
    const about = el("input");
    about.maxLength = 140;
    about.placeholder = "Fixes my emails before I send them";
    const category = el("select");
    category.append(...categories.map((name) => el("option", "", name)));
    const by = el("input");
    by.maxLength = 40;
    by.placeholder = "Leave empty to stay unnamed";
    const note = el("p", "book-error");
    note.hidden = true;
    const send = async (event) => {
      event.preventDefault();
      const reply = await pywebview.api.post_agent(choice.value, about.value, category.value, by.value);
      note.hidden = false;
      note.textContent = reply.error || "Your browser opened with it filled in. Press Submit there. It appears here for everyone once it's been checked.";
      note.classList.toggle("fine", !reply.error);
    };
    const form = el("form", "book post-form",
                    el("label", "book-what", "Which agent", choice),
                    el("label", "book-what", "What it does, in one line", about),
                    el("label", "", "Category", category),
                    el("label", "", "Your name", by),
                    button("solid-button", "Post it", () => {}));
    form.lastChild.type = "submit";
    form.addEventListener("submit", send);
    const back = button("quiet-button back-link", "", drawPage);
    back.append(icon("back"), "All agents");
    const body = [back, el("h1", "disc-heading", "Post an agent"),
                  el("p", "sub", "Share an agent you made, so others can add it. Posting uses a free GitHub account. Only its name, what it does and its settings are shared, never your files or chats.")];
    body.push(...(agents.length ? [form, note] : [el("div", "nothing", "Make an agent first, then you can share it.")]));
    page().replaceChildren(...body);
  }

  // ------------------------------------------------------------------ the page

  function drawPage() {
    const { agents } = agentState();
    const top = el("div", "disc-bar",
                   tabs([{ id: "discover", words: "Discover" }, { id: "yours", words: "Your agents", count: agents.length }],
                        tab, (id) => {
                          tab = id;
                          drawPage();
                        }),
                   button("line-button", "Post an agent", openPost));
    results = el("div", "disc-results");
    if (tab === "yours") {
      page().replaceChildren(top, results);
      drawYours();
      return;
    }
    const groups = grouping === "category"
      ? categories.map((name) => ({ id: name, words: name }))
      : [{ id: "Community", words: "Community" }, { id: "Noir", words: "Ready-made" }];
    const controls = el("div", "disc-controls",
                        segments([{ id: "category", words: "Category" }, { id: "source", words: "Source" }], grouping, (id) => {
                          grouping = id;
                          filter = "All";
                          drawPage();
                        }),
                        filters([{ id: "All", words: "All" }, ...groups], filter, pickFilter));
    const search = searchBox('Try "email"', words, (value) => {
      words = value;
      drawResults();
    });
    page().replaceChildren(top, search, controls, results);
    drawResults();
  }

  async function load() {
    const data = (await pywebview.api.recipes()) || {};
    recipes = data.recipes || [];
    categories = data.categories || [];
  }

  async function open() {
    drawPage();
    await load();
    drawPage();
  }

  // An agent was added or switched somewhere: show it without losing the user's place.
  async function agentsChanged() {
    if (!results) return;
    if (tab === "yours") drawYours();
    else {
      await load();
      drawResults();
    }
  }

  return { open, agentsChanged, tabs, searchBox, filters, segments, hero, card, tag, section };
})();
