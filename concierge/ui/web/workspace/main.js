// The frame around the screens: navigation, the chat dock and small messages.
// A screen is an object with render(param), which returns its page, and an
// optional refresh(), which updates it without losing what the user is typing.

(() => {
  const { el, icon, iconButton } = ws.parts;
  const $ = (id) => document.getElementById(id);
  const MAIN = [["home", "Home", "home"], ["discover", "Discover", "compass"], ["agents", "My Agents", "agents"],
                ["activity", "Activity", "activity"]];
  const ADVANCED = [["studio", "Studio", "studio"]];
  const SCREENS = {
    home: ws.home, discover: ws.discover, agents: ws.library, agent: ws.agentPage, activity: ws.activity,
    studio: ws.studio,
  };
  const TOAST_MS = 4000;

  let route = { name: "home" };
  let toastTimer = null;

  function draw() {
    const view = $("view");
    view.replaceChildren(SCREENS[route.name].render(route.param));
    // The agent page belongs to My Agents.
    const active = route.name === "agent" ? "agents" : route.name;
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.toggle("current", item.dataset.screen === active);
      if (item.dataset.screen === active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
  }

  ws.go = (name, param) => {
    route = { name, param };
    draw();
    $("view").scrollTop = 0;
    $("view").focus({ preventScroll: true });
  };

  ws.refresh = () => {
    const screen = SCREENS[route.name];
    if (screen.refresh) {
      screen.refresh();
      return;
    }
    ws.refresh.full();
  };

  // Draws the whole screen again, for changes refresh() doesn't cover.
  ws.refresh.full = () => {
    const top = $("view").scrollTop;
    draw();
    $("view").scrollTop = top;
  };

  ws.toast = (text) => {
    const toast = $("toast");
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.hidden = true), TOAST_MS);
  };

  ws.dock = {
    open() {
      document.body.classList.add("dock-is-open");
      $("messages").scrollTop = $("messages").scrollHeight;
      $("input").focus();
    },
    close() {
      document.body.classList.remove("dock-is-open");
    },
  };

  function busy() {
    ws.toast("Elaina is still working. Try again in a moment.");
  }

  // Sends words to Elaina as if the user had typed them in the chat.
  ws.ask = (text) => {
    ws.dock.open();
    if (!app.say(text)) busy();
  };

  // What buttons do to an agent. Real agents go through the engine; sample
  // ones only change this page.
  ws.actions = {
    toggle(agent) {
      if (!app.toggleAgent(agent.name)) busy();
    },
    use(agent) {
      if (agent.sample) {
        ws.store.runSample(agent);
        ws.toast(`${agent.name} started. Follow it in Activity.`);
        return;
      }
      ws.dock.open();
      app.prefill(`${agent.name}: `);
    },
    install(agent) {
      ws.addAgent.install(agent);
    },
    change(agent) {
      ws.dock.open();
      app.prefill(`Change ${agent.name} so that `);
    },
    remove(agent) {
      if (agent.sample) {
        ws.store.removeSample(agent);
        ws.toast(`Removed ${agent.name}.`);
        ws.go("agents");
        return;
      }
      ws.dock.open();
      if (!app.deleteAgent(agent.name)) busy();
    },
  };

  function navItem([id, label, glyph]) {
    const item = el("button", "nav-item", icon(glyph, 18), label);
    item.type = "button";
    item.dataset.screen = id;
    item.addEventListener("click", () => ws.go(id));
    return item;
  }

  // With the chat closed there's no box to type in, and Windows would put the
  // focus on the first button instead, drawing a ring around it.
  window.addEventListener("page-shown", () => {
    if (!document.body.classList.contains("dock-is-open")) $("view").focus({ preventScroll: true });
  });

  $("nav").append(...MAIN.map(navItem));
  $("nav-advanced").append(...ADVANCED.map(navItem));
  $("add-agent").append(icon("plus", 16), "Add agent");
  $("add-agent").addEventListener("click", () => ws.addAgent.open());
  $("dock-open").addEventListener("click", ws.dock.open);
  $("dock-tools").append(
    iconButton("history", "Past chats", () => ($("history").hidden = !$("history").hidden)),
    iconButton("close", "Hide the chat", ws.dock.close),
  );

  draw();
})();
