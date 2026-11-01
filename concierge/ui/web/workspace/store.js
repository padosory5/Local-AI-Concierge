// What the workspace knows. Real facts arrive from the engine as events; the
// rest comes from mock.js. Screens only read from here, so swapping a sample
// for real data changes this file and not the screens.
//
// An agent, whoever runs it, always has the same shape: id, name, description,
// purpose, category, type, runtime, model, compat, tools, permissions, config,
// installed, switchable, on, sample. `unsupported` lists what its framework
// doesn't offer, and a missing field means it isn't known yet.

window.ws = window.ws || {};

ws.store = (() => {
  const { agents: catalog, activity } = ws.mock;
  const TICK_MS = 700;

  const state = {
    system: null, // SystemInfo
    names: [], switchable: [], active: [], // AgentList: the user's real agents
    added: new Set(), // sample agents installed during this session
    extra: [], // sample agents imported, connected or built during this session
    favorites: new Set(catalog.filter((a) => a.favorite).map((a) => a.id)),
    runs: activity.map((run) => ({ ...run, started: Date.now() - run.minutes * 60000 })),
    onSince: {}, // real agent name -> when it was switched on
  };

  function has(list, name) {
    return list.some((item) => item.toLowerCase() === name.toLowerCase());
  }

  // The real agent list decides what's installed; the catalog only adds words.
  function dress(agent) {
    const real = has(state.names, agent.name);
    return {
      ...agent,
      installed: real || Boolean(agent.installed) || state.added.has(agent.id),
      switchable: real ? has(state.switchable, agent.name) : Boolean(agent.switchable),
      on: real && has(state.active, agent.name),
      favorite: state.favorites.has(agent.id),
      real,
    };
  }

  // One of the user's own agents. AgentList sends only its name for now.
  function own(name) {
    return dress({
      id: `own:${name}`, name, category: "custom", type: "custom", runtime: "Elaina",
      description: "An agent you made with Elaina.", compat: { level: "ok", text: "Works on this computer" },
    });
  }

  function agents() {
    const known = [...catalog, ...state.extra];
    const others = state.names.filter((name) => !has(known.map((a) => a.name), name));
    return [...others.map(own), ...known.map(dress)];
  }

  // Real agents first, so the ones that work are the ones seen first.
  function library() {
    return agents().filter((a) => a.installed).sort((a, b) => Number(b.real) - Number(a.real));
  }

  function find(id) {
    return agents().find((a) => a.id === id);
  }

  function changed() {
    ws.refresh && ws.refresh();
  }

  function logRun(run) {
    state.runs.unshift({ id: `run-${Date.now()}-${Math.random()}`, started: Date.now(), ...run });
  }

  // Switching a real agent on or off shows up in Activity like any other work.
  function noteSwitches(active) {
    for (const name of active.filter((n) => !has(state.active, n))) {
      state.onSince[name] = Date.now();
      ws.toast(`${name} is on. Highlight text in any program.`);
    }
    for (const name of state.active.filter((n) => !has(active, n))) {
      const since = state.onSince[name] || Date.now();
      delete state.onSince[name];
      ws.toast(`${name} is off.`);
      logRun({ agent: name, task: "Worked on highlighted text", status: "completed", started: since,
               took: ws.parts.lasted(Date.now() - since), minutes: 0 });
    }
  }

  function onEvent(event) {
    if (event.type === "SystemInfo") {
      state.system = event;
    } else if (event.type === "AgentList") {
      noteSwitches(event.active || []);
      state.names = event.agents;
      state.switchable = event.switchable || [];
      state.active = event.active || [];
    } else if (event.type === "Result") {
      logRun({ agent: event.agent, task: "Finished a job", status: "completed", took: "", output: event.text });
    } else {
      return;
    }
    changed();
  }

  window.addEventListener("engine-event", (e) => onEvent(e.detail));

  // ---------------------------------------------------------- sample work

  function runSample(agent) {
    logRun({ agent: agent.name, task: `Running ${agent.name}`, finished: `Ran ${agent.name}`, status: "running",
             progress: 4, sample: true });
    changed();
  }

  function stopRun(id) {
    const run = state.runs.find((r) => r.id === id);
    if (run && run.status === "running") {
      run.status = "stopped";
      run.took = ws.parts.lasted(Date.now() - run.started);
      changed();
    }
  }

  // Sample tasks move by themselves, so Activity shows what live work looks like.
  setInterval(() => {
    const running = state.runs.filter((r) => r.status === "running" && r.sample);
    for (const run of running) {
      run.progress = Math.min(100, run.progress + (run.pace || 4));
      if (run.progress === 100) {
        run.status = "completed";
        run.task = run.finished || run.task;
        run.took = ws.parts.lasted(Date.now() - run.started);
        run.output = "This was a sample run, so nothing on your computer changed.";
      }
    }
    if (running.length) changed();
  }, TICK_MS);

  function addSample(agent) {
    state.added.add(agent.id);
    changed();
  }

  function addExtra(agent) {
    state.extra.unshift({ compat: { level: "ok", text: "Ready" }, sample: true, installed: true, ...agent });
    changed();
  }

  function removeSample(agent) {
    state.added.delete(agent.id);
    state.extra = state.extra.filter((a) => a.id !== agent.id);
    const inCatalog = catalog.find((a) => a.id === agent.id);
    if (inCatalog) inCatalog.installed = false;
    changed();
  }

  function toggleFavorite(agent) {
    if (state.favorites.has(agent.id)) state.favorites.delete(agent.id);
    else state.favorites.add(agent.id);
    changed();
  }

  function runsOf(name) {
    return state.runs.filter((r) => r.agent.toLowerCase() === name.toLowerCase());
  }

  return {
    state, agents, library, find, runsOf, runSample, stopRun, addSample, addExtra, removeSample,
    toggleFavorite,
  };
})();
