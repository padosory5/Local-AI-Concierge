// Adding an agent, in one sheet. Four ways in, for four kinds of people, and
// the install check every agent goes through. "Create with Elaina" is real: it
// turns the choices into plain words and hands them to Elaina, who builds the
// agent. Import, connect and build from scratch are samples for now.

ws.addAgent = (() => {
  const { el, icon, button, pill, sampleTag, compat } = ws.parts;
  const OPTIONS = [
    { id: "create", glyph: "wand", title: "Create with Elaina", text: "Describe the job and Elaina sets it up.", who: "Best for most people" },
    { id: "import", glyph: "box", title: "Import an agent", text: "Add an agent someone shared as a file.", who: "You have a package" },
    { id: "connect", glyph: "plug", title: "Connect an external agent", text: "Bring in Hermes or another framework.", who: "You already run agents" },
    { id: "scratch", glyph: "edit", title: "Build from scratch", text: "Set every detail yourself.", who: "For technical users" },
  ];
  const EXAMPLES = ["Explain hard words I highlight in simple Korean", "Fix the grammar of what I send it",
                    "Answer questions about my contracts folder"];
  // `say` is what each choice means in Elaina's words; settings_from_words in
  // recipe.py reads them, so a click means the same as typing it.
  const HOW = [
    { id: "highlight", label: "On text I highlight", note: "Works in any program while it's switched on", say: "It should work on text I highlight." },
    { id: "chat", label: "When I ask in the chat", note: "You send it text and it answers", say: "I'll ask it in the chat." },
    { id: "folder", label: "On a folder of my files", note: "It reads them and answers questions" },
    { id: "new-files", label: "When new files appear", note: "Not built yet", off: true },
    { id: "schedule", label: "On a schedule", note: "Not built yet", off: true },
  ];
  const SHOW = [
    { id: "bubble", label: "A bubble above the text", note: "Stays until you unhighlight", say: "Show the result in a bubble above the text." },
    { id: "copy", label: "Copied, ready to paste", note: "Nothing appears on screen", say: "Copy the result to the clipboard." },
    { id: "both", label: "Both", note: "Shown and copied", say: "Show the result above the text and copy it." },
  ];
  const READS = { highlight: "Read the text you highlight, while it's on", chat: "Read the text you send it", folder: "Read the folder you pick" };
  const STEPS = ["Describe", "How it works", "Model", "Permissions", "Review"];

  const box = () => document.getElementById("add-dialog");

  function close() {
    box().close();
  }

  function frame({ title, back, body, actions, step }) {
    const sheet = box();
    sheet.replaceChildren(...el("div", "",
      el("header", "sheet-head",
        back && ws.parts.iconButton("back", "Back", back),
        el("h2", "", title),
        ws.parts.iconButton("close", "Close", close)),
      step !== undefined && steps(step),
      el("div", "sheet-body", ...body),
      actions && el("footer", "sheet-foot", ...actions)).childNodes);
    if (!sheet.open) sheet.showModal();
    sheet.querySelector(".sheet-body").scrollTop = 0;
  }

  function steps(current) {
    return el("ol", "steps", ...STEPS.map((name, i) => el("li", i === current ? "current" : i < current ? "done" : "", name)));
  }

  function choices(name, options, selected, onPick) {
    return el("div", "option-list", ...options.map((option) => {
      const input = el("input");
      input.type = "radio";
      input.name = name;
      input.checked = option.id === selected;
      input.disabled = Boolean(option.off);
      input.addEventListener("change", () => onPick(option.id));
      return el("label", `option ${option.off ? "off" : ""}`, input,
        el("span", "option-text", el("span", "option-label", option.label), el("span", "option-note", option.note)));
    }));
  }

  function field(label, control, note) {
    return el("label", "field", el("span", "field-label", label), control, note && el("span", "field-note", note));
  }

  function textInput(value, placeholder, onInput, tag = "input") {
    const input = el(tag, "field-input");
    input.value = value;
    input.placeholder = placeholder;
    input.addEventListener("input", () => onInput(input.value));
    return input;
  }

  function picker(options, value, onChange) {
    const node = el("select", "picker");
    for (const text of options) {
      const option = el("option", "", text);
      option.value = text;
      node.append(option);
    }
    node.value = value;
    node.addEventListener("change", () => onChange(node.value));
    return node;
  }

  function checks(options, selected) {
    return el("div", "check-list", ...options.map((name) => {
      const input = el("input");
      input.type = "checkbox";
      input.checked = selected.has(name);
      input.addEventListener("change", () => (input.checked ? selected.add(name) : selected.delete(name)));
      return el("label", "check", input, name);
    }));
  }

  function checkRow(ok, text) {
    return el("li", ok ? "yes" : "no", icon(ok ? "tick" : "close", 15), text);
  }

  function previewNote(text) {
    return el("p", "preview-note", sampleTag(), text);
  }

  // --------------------------------------------------------------- choose

  function chooser() {
    frame({
      title: "Add an agent",
      body: [el("div", "way-grid", ...OPTIONS.map((option) => {
        const way = el("button", "way", el("span", "offer-glyph", icon(option.glyph, 20)),
          el("span", "way-title", option.title), el("span", "way-text", option.text), el("span", "way-who", option.who));
        way.type = "button";
        way.addEventListener("click", () => SCREENS[option.id]());
        return way;
      }))],
    });
  }

  // ---------------------------------------------------- create with Elaina

  function create() {
    const draft = { text: "", how: "chat", show: "bubble" };

    function guessHow() {
      if (/highlight|select/i.test(draft.text)) draft.how = "highlight";
      else if (/folder|files|documents|contracts/i.test(draft.text)) draft.how = "folder";
      else draft.how = "chat";
    }

    function words() {
      const text = draft.text.trim().replace(/[.!]+$/, "");
      if (draft.how === "folder") return `Make an agent for my documents: ${text}`;
      const how = HOW.find((h) => h.id === draft.how);
      const show = draft.how === "highlight" ? ` ${SHOW.find((s) => s.id === draft.show).say}` : "";
      // "Make a new agent" keeps this from reading as a change to a similar one.
      return `Make a new agent: ${text}. ${how.say}${show}`;
    }

    function describe() {
      const area = textInput(draft.text, "For example: sort my assignments by course and read the due dates", (value) => {
        draft.text = value;
        next.disabled = !value.trim();
      }, "textarea");
      area.rows = 4;
      const next = button("Next", () => { guessHow(); how(); }, { kind: "accent", disabled: !draft.text.trim() });
      frame({
        title: "Create with Elaina", back: chooser, step: 0,
        body: [field("What should this agent do?", area),
               el("div", "chips", ...EXAMPLES.map((example) => {
                 const chip = el("button", "chip", example);
                 chip.type = "button";
                 chip.addEventListener("click", () => {
                   draft.text = example;
                   area.value = example;
                   next.disabled = false;
                 });
                 return chip;
               }))],
        actions: [next],
      });
      area.focus();
    }

    function how() {
      const showBox = el("div", "");
      const drawShow = () => showBox.replaceChildren(...(draft.how === "highlight" ? [
        el("h3", "sheet-subhead", "How should it show the result?"),
        choices("show", SHOW, draft.show, (id) => (draft.show = id))] : []));
      drawShow();
      frame({
        title: "How should it work?", back: describe, step: 1,
        body: [choices("how", HOW, draft.how, (id) => { draft.how = id; drawShow(); }), showBox],
        actions: [button("Next", model, { kind: "accent" })],
      });
    }

    function model() {
      const system = ws.store.state.system;
      frame({
        title: "Which model should it use?", back: how, step: 2,
        body: [choices("model", [
          { id: "elaina", label: "Elaina's model (recommended)", note: `${system ? system.in_use : "Already on this computer"}. No extra memory or download.` },
          { id: "bigger", label: "A bigger model", note: "Not built yet. Elaina will tell you if a job needs one.", off: true },
        ], "elaina", () => {})],
        actions: [button("Next", permissions, { kind: "accent" })],
      });
    }

    function permissions() {
      frame({
        title: "What can it touch?", back: model, step: 3,
        body: [el("p", "sheet-text", "Agents only get what you see here."),
               el("ul", "permission-list", checkRow(true, `Can: ${READS[draft.how]}`),
                  checkRow(false, "Can't: change your files"), checkRow(false, "Can't: send anything over the internet"))],
        actions: [button("Next", review, { kind: "accent" })],
      });
    }

    function review() {
      const how = HOW.find((h) => h.id === draft.how);
      const rows = [["Job", draft.text.trim()], ["Works", how.label]];
      if (draft.how === "highlight") rows.push(["Result", SHOW.find((s) => s.id === draft.show).label]);
      rows.push(["Model", "Elaina's model"], ["Reads", READS[draft.how]]);
      const list = el("dl", "pairs");
      for (const [key, value] of rows) list.append(el("dt", "", key), el("dd", "", value));
      frame({
        title: "Ready to create", back: permissions, step: 4,
        body: [list, el("p", "sheet-text", "Elaina will set this up in the chat and show you a card to confirm.")],
        actions: [button("Create with Elaina", () => { close(); ws.ask(words()); }, { kind: "accent", glyph: "wand" })],
      });
    }

    describe();
  }

  // ------------------------------------------------------------- import

  function importAgent() {
    const input = el("input");
    input.type = "file";
    input.accept = ".zip,.json,.yaml,.yml";
    input.hidden = true;
    input.addEventListener("change", () => input.files[0] && report(input.files[0].name));
    frame({
      title: "Import an agent", back: chooser,
      body: [
        el("div", "drop-zone", icon("box", 28), el("p", "", "Choose an agent package (.zip, .json or .yaml)"),
          el("div", "action-row", button("Choose a file", () => input.click(), { kind: "accent" }),
             button("Try a sample package", () => report("study-planner.zip"))), input),
        previewNote("The check below is a sample. Files aren't read yet."),
      ],
    });

    function report(file) {
      frame({
        title: file, back: importAgent,
        body: [el("h3", "sheet-subhead", "Compatibility"),
               el("ul", "permission-list", checkRow(true, "Package format is supported"), checkRow(true, "Runs on Elaina's model"),
                  checkRow(false, "Missing: the \"Save a file\" tool. It will work without saving results.")),
               el("h3", "sheet-subhead", "It asks to"),
               el("ul", "permission-list", checkRow(true, "Can: read the folder you pick"), checkRow(false, "Can't: send anything over the internet")),
               previewNote("Added for this session only.")],
        actions: [button("Add to My Agents", () => {
          const id = `import:${Date.now()}`;
          ws.store.addExtra({ id, name: "Study Planner", type: "imported", category: "learning", runtime: "Elaina", model: "Elaina's model",
                              description: `Imported from ${file}.`, tools: ["Files in the folder you pick"],
                              permissions: [{ label: "Read the folder you pick", allowed: true }], config: [] });
          close();
          ws.go("agent", id);
        }, { kind: "accent" })],
      });
    }
  }

  // ------------------------------------------------------------ connect

  function connect() {
    frame({
      title: "Connect an external agent", back: chooser,
      body: [el("div", "stack", ...ws.mock.frameworks.map((framework) => {
        const row = el("button", "offer", el("span", "offer-glyph", icon("plug", 20)),
          el("span", "offer-text", el("span", "offer-title", framework.name), el("span", "offer-blurb", framework.blurb)),
          pill("Not connected", "plain"));
        row.type = "button";
        row.addEventListener("click", () => form(framework));
        return row;
      })), previewNote("Connections aren't made yet. This shows how they will work.")],
    });

    function form(framework) {
      let address = "";
      const result = el("div", "");
      const finish = button("Connect", () => {
        const id = `connect:${Date.now()}`;
        const offered = Object.fromEntries(framework.capabilities);
        ws.store.addExtra({ id, name: `${framework.name} agent`, type: "external", framework: framework.name, category: "custom",
                            runtime: framework.name, model: `Chosen in ${framework.name}`, description: `Connected from ${framework.name}.`,
                            compat: { level: "ok", text: "Connected" }, tools: [`Tools from ${framework.name}`],
                            unsupported: offered["Change permissions"] ? [] : ["permissions", "config"] });
        close();
        ws.go("agent", id);
      }, { kind: "accent", disabled: true });
      const check = button("Check connection", () => {
        result.replaceChildren(el("h3", "sheet-subhead", "What it can do with Elaina"),
          el("ul", "permission-list", ...framework.capabilities.map(([name, yes]) => checkRow(yes, yes ? name : `${name}: not available`))));
        finish.disabled = false;
      });
      frame({
        title: `Connect ${framework.name}`, back: connect,
        body: [field(framework.field, textInput(address, framework.placeholder, (value) => (address = value))),
               el("div", "action-row", check), result, previewNote("The check is a sample. Nothing connects yet.")],
        actions: [finish],
      });
    }
  }

  // -------------------------------------------------- build from scratch

  function scratch() {
    const draft = { name: "", description: "", instructions: "", model: "Elaina's model", runtime: "Elaina", when: "When I ask in the chat" };
    const tools = new Set();
    const servers = new Set();
    const allowed = new Set(["Read the folder I pick"]);
    const create = button("Create agent", () => {
      const id = `custom:${Date.now()}`;
      ws.store.addExtra({
        id, name: draft.name.trim(), description: draft.description.trim() || "An agent you built.", purpose: draft.instructions.trim(),
        type: "custom", category: "custom", runtime: draft.runtime, model: draft.model, tools: [...tools, ...servers],
        permissions: [...allowed].map((label) => ({ label, allowed: true })), config: [["When it runs", draft.when]],
      });
      close();
      ws.go("agent", id);
    }, { kind: "accent", disabled: true });
    const ready = () => (create.disabled = !(draft.name.trim() && draft.instructions.trim()));
    const set = (key) => (value) => {
      draft[key] = value;
      ready();
    };
    const instructions = textInput("", "What the agent should do, step by step", set("instructions"), "textarea");
    instructions.rows = 4;
    frame({
      title: "Build from scratch", back: chooser,
      body: [
        el("div", "form-two", field("Name", textInput("", "Agent name", set("name"))),
           field("Description", textInput("", "One line about it", set("description")))),
        field("Instructions (system prompt)", instructions),
        el("div", "form-two", field("Model", picker(["Elaina's model", ...ws.mock.models.map((m) => m.name)], draft.model, set("model"))),
           field("Runtime", picker(ws.mock.runtimes.map((r) => r.name).concat("Elaina"), draft.runtime, set("runtime")))),
        el("div", "form-two",
          el("div", "field", el("span", "field-label", "Tools"), checks(ws.mock.tools, tools)),
          el("div", "field", el("span", "field-label", "MCP servers"), checks(ws.mock.mcpServers, servers))),
        el("div", "field", el("span", "field-label", "Permissions"),
           checks(["Read the folder I pick", "Move files, after I confirm", "Use the internet"], allowed)),
        field("When it runs", picker(["When I ask in the chat", "While it's switched on", "On a schedule"], draft.when, set("when"))),
        el("details", "advanced", el("summary", "", "Advanced settings"),
          el("div", "form-two", field("Temperature", textInput("0.3", "", () => {})), field("Context size", textInput("8192", "", () => {})),
             field("Longest run", textInput("10 minutes", "", () => {})), field("Retries", textInput("1", "", () => {})))),
        previewNote("Added for this session only. Saving real agents from this form comes later."),
      ],
      actions: [create],
    });
  }

  // ---------------------------------------------------- install one agent

  function install(agent) {
    const external = agent.type === "external";
    const allow = (agent.permissions || []).map((p) => checkRow(p.allowed, `${p.allowed ? "Can" : "Can't"}: ${p.label}`));
    const add = () => {
      close();
      if (agent.setup) {
        ws.ask(agent.setup);
      } else if (agent.starter) {
        ws.ask(`Install ${agent.name}`);
      } else {
        ws.store.addSample(agent);
        ws.toast(`${agent.name} is in My Agents.`);
      }
    };
    frame({
      title: `${external ? "Connect" : "Add"} ${agent.name}`,
      body: [
        el("h3", "sheet-subhead", "On this computer"),
        compat(agent),
        el("p", "sheet-text", `Runs on: ${agent.runtime}. Model: ${agent.model}.`),
        allow.length > 0 && el("h3", "sheet-subhead", "What it can touch"),
        allow.length > 0 && el("ul", "permission-list", ...allow),
        agent.sample && previewNote("This agent doesn't run yet, so adding it changes nothing on your computer."),
      ],
      actions: [button("Cancel", close),
                external ? button("Connect", connect, { kind: "accent" })
                         : button(agent.setup ? "Set it up with Elaina" : "Add it", add, { kind: "accent" })],
    });
  }

  const SCREENS = { create, import: importAgent, connect, scratch };

  function open(screen) {
    (SCREENS[screen] || chooser)();
  }

  return { open, install };
})();
